"""Thin wrapper around the agent-browser CLI.

All browser work (Walmart and Pokemon Center checks, add-to-cart) runs in one
headed real-Chrome session with a persistent profile, so the user logs in once
and bot protection sees an ordinary browser.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess

log = logging.getLogger("tcgwatch.browser")

SESSION = "tcg"


def js_str(s: str) -> str:
    """A JS string literal that survives the agent-browser .cmd shim on Windows.

    The shim re-expands its arguments through cmd.exe, which splits at every '&' and
    expands %..% pairs, so a URL with a query string arrives mangled (verified 2026-09-07:
    'store_id' is not recognized as an internal or external command). Escaping those
    characters as \\uXXXX inside the literal keeps cmd out of it; JS decodes them back.
    """
    out = json.dumps(s)
    for ch in "&%!":
        out = out.replace(ch, "\\u%04x" % ord(ch))
    return out


def _host(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0].lower()


def _site(url: str) -> str:
    """Registrable domain, roughly: last two labels (redsky.target.com -> target.com)."""
    return ".".join(_host(url).split(".")[-2:])


class BrowserError(RuntimeError):
    pass


class Browser:
    def __init__(self, chrome_path: str, profile_dir: str, timeout: int = 30):
        self.chrome_path = chrome_path
        self.profile_dir = profile_dir
        self.timeout = timeout
        self.exe = shutil.which("agent-browser")
        if not self.exe:
            raise BrowserError("agent-browser not found on PATH (npm install -g agent-browser)")

    def _base(self) -> list[str]:
        return [
            self.exe,
            "--session", SESSION,
            "--headed",
            "--executable-path", self.chrome_path,
            "--profile", self.profile_dir,
            # Playwright-driven Chrome reports navigator.webdriver=true; PerimeterX (Walmart)
            # reads it and serves the "Robot or human?" page on the second load. This flag
            # flips it to false. Verified 2026-09-07.
            "--args", "--disable-blink-features=AutomationControlled",
        ]

    _daemon_ready = False

    def _ensure_daemon(self) -> None:
        """Start the session daemon with no pipes attached.

        The first agent-browser command spawns a long-lived daemon that inherits the
        caller's stdout/stderr. With pipes attached, Python then waits for EOF that never
        comes and the watcher hangs forever. So the daemon is started here with output
        discarded, and every later command can safely capture its own output.
        """
        if Browser._daemon_ready:
            return
        cmd = self._base() + ["open", "about:blank"]
        try:
            subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=90)
        except subprocess.TimeoutExpired:
            log.warning("agent-browser daemon start timed out; continuing")
        Browser._daemon_ready = True

    def run(self, *args: str, check: bool = True) -> str:
        self._ensure_daemon()
        cmd = self._base() + list(args)
        log.debug("agent-browser %s", " ".join(args[:3]))
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        try:
            stdout, stderr = proc.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired as e:
            proc.kill()
            # Do not communicate() again: if a daemon inherited the pipe it never closes.
            raise BrowserError(f"agent-browser timed out: {' '.join(args[:2])}") from e
        out = "\n".join(
            line for line in (stdout or "").splitlines() if "daemon already running" not in line
        ).strip()
        if check and proc.returncode != 0:
            err = "\n".join(l for l in (stderr or "").splitlines() if "daemon already running" not in l).strip()
            msg = (out or err).encode("ascii", "ignore").decode().strip()
            raise BrowserError(f"agent-browser failed ({' '.join(args[:2])}): {msg[:300]}")
        return out

    def open(self, url: str) -> str:
        """Navigate and return the page title line agent-browser prints. URLs with a query string
        must go through goto(): `open` hands the raw URL to the .cmd shim, which splits at '&'."""
        return self.run("open", url)

    def goto(self, url: str) -> None:
        """Navigate from inside the page, so the URL never touches the command line."""
        self.run("eval", "location.assign(" + js_str(url) + ")", check=False)

    def fetch_json(self, url: str, tries: int = 4, wait_ms: int = 1500) -> tuple[int, object, str]:
        """GET a JSON API as the browser. Returns (status, parsed body or None, note).

        Fetches from the current tab when it is already on the API's site (cookies and CORS
        line up). Otherwise, or when that fetch is refused, navigates the tab to the URL
        itself: a top-level load runs the site's bot challenge and then renders the JSON as
        the document body. Verified 2026-09-07 on redsky.target.com, where a plain client had
        been captcha-blocked for most of a day: the navigation returned JSON on the first try
        and page-context fetches returned 200 afterwards.
        """
        if _site(self.url() or "") == _site(url):
            js = (
                "(async()=>{try{const r=await fetch(" + js_str(url) + ",{credentials:'include'});"
                "const t=await r.text();return JSON.stringify({s:r.status,t:t})}"
                "catch(e){return JSON.stringify({s:0,t:String(e)})}})()"
            )
            res = self.eval_json(js)
            if isinstance(res, dict) and res.get("s") == 200:
                try:
                    return 200, json.loads(res["t"]), "fetch"
                except (json.JSONDecodeError, TypeError):
                    pass
        self.goto(url)
        text = ""
        for _ in range(tries):
            self.wait(wait_ms)
            text = self.eval_json("JSON.stringify(document.body?document.body.innerText:'')") or ""
            if isinstance(text, str) and text[:1] in "{[":
                try:
                    return 200, json.loads(text), "navigate"
                except json.JSONDecodeError:
                    break
        head = (text if isinstance(text, str) else str(text))[:120].replace("\n", " ")
        status = 403 if ("captcha" in head.lower() or not head.strip()) else 0
        return status, None, f"navigate: {head or 'empty body'}"

    def wait(self, ms: int) -> None:
        self.run("wait", str(ms))

    def title(self) -> str:
        return self.run("get", "title", check=False)

    def url(self) -> str:
        return self.run("get", "url", check=False)

    def eval_json(self, js: str):
        """Run JS that returns a JSON string; parse it."""
        out = self.run("eval", js)
        # agent-browser prints the JSON-encoded return value; unwrap once or twice.
        for _ in range(2):
            try:
                out = json.loads(out)
            except (json.JSONDecodeError, TypeError):
                break
            if not isinstance(out, str):
                break
        return out

    def click_button(self, name: str) -> bool:
        out = self.run("find", "role", "button", "click", "--name", name, check=False)
        ok = "✗" not in out and "not found" not in out.lower()
        if not ok:
            log.warning("click '%s' failed: %s", name, out[:200])
        return ok

    def click_selector(self, selector: str) -> bool:
        out = self.run("click", selector, check=False)
        ok = "✗" not in out and "not found" not in out.lower()
        if not ok:
            log.warning("click '%s' failed: %s", selector, out[:200])
        return ok

    def button_enabled(self, name: str) -> bool | None:
        """True/False if a button with this accessible name exists, None if absent."""
        js = (
            "(()=>{const bs=[...document.querySelectorAll('button')];"
            f"const b=bs.find(x=>(x.getAttribute('aria-label')||x.innerText||'').toLowerCase().includes({json.dumps(name.lower())}));"
            "return b?JSON.stringify({enabled:!b.disabled}):'null'})()"
        )
        res = self.eval_json(js)
        if not res or res == "null":
            return None
        return bool(res.get("enabled"))

    def body_text(self, limit: int = 4000) -> str:
        return self.eval_json(f"JSON.stringify(document.body.innerText.slice(0,{limit}))") or ""

    def next_data(self):
        """Parse the Next.js __NEXT_DATA__ blob, or None if absent."""
        js = (
            "(()=>{const el=document.getElementById('__NEXT_DATA__');"
            "return el?el.innerText:'null'})()"
        )
        res = self.eval_json(js)
        if not res or res == "null":
            return None
        if isinstance(res, str):
            try:
                return json.loads(res)
            except json.JSONDecodeError:
                return None
        return res

    def close(self) -> None:
        self.run("close", check=False)
