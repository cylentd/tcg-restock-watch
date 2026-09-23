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
import time

import psutil

from . import NO_WINDOW

log = logging.getLogger("tcgwatch.browser")

SESSION = "tcg"
DAEMON_EXE = "agent-browser-win32-x64.exe"

# Recycle limits. Measured 2026-09-21: the agent-browser daemon reached 4.6 GB after two days
# and Best Buy pages pushed the watcher's Chrome to 9 GB; both ended in every command hanging.
RECYCLE_AFTER_S = 6 * 3600
DAEMON_CAP_MB = 1500
CHROME_CAP_MB = 3000


def _rss_mb(procs) -> int:
    return sum(p.info["memory_info"].rss for p in procs if p.info.get("memory_info")) // (1024 * 1024)


def _procs(name: str, cmd_contains: str | None = None) -> list:
    out = []
    for p in psutil.process_iter(["name", "cmdline", "memory_info"]):
        try:
            if (p.info["name"] or "").lower() != name.lower():
                continue
            if cmd_contains and cmd_contains.lower() not in " ".join(p.info["cmdline"] or []).lower():
                continue
            out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


def _kill(procs, what: str) -> int:
    n = 0
    for p in procs:
        try:
            p.kill()
            n += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if n:
        log.info("killed %d %s process(es)", n, what)
    return n


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
        self.launched = time.time()

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
            # Headed Chrome is required (Walmart/Target bot checks), but the window must not
            # keep surfacing: each Best Buy product opens in a fresh tab, and a new tab restores
            # a minimized window. Park it off-screen instead, and stop Chrome treating an
            # occluded window as hidden so pages still render and timers still run.
            "--args", ",".join([
                "--disable-blink-features=AutomationControlled",
                "--window-position=-32000,-32000",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ]),
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
                           timeout=90, creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            log.warning("agent-browser daemon start timed out; continuing")
        Browser._daemon_ready = True
        self.launched = time.time()
        # After a recycle the `open about:blank` above can return before Chrome is up (seen
        # 2026-09-21: Chrome RSS was 0 MB eight seconds later and the next command timed
        # out). Poll until the browser answers so the first real check does not eat that.
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                if "about:blank" in self.run("get", "url", check=False):
                    return
            except BrowserError:
                pass
            time.sleep(3)
        log.warning("browser did not answer within 90 s of daemon start; continuing")

    # -- memory hygiene ------------------------------------------------------------------
    def memory_mb(self) -> tuple[int, int]:
        """(daemon RSS, this profile's Chrome RSS) in MB."""
        return _rss_mb(_procs(DAEMON_EXE)), _rss_mb(_procs("chrome.exe", self.profile_dir))

    def close(self) -> None:
        """Close this session's Chrome and kill any Chrome still holding the profile.

        A daemon that dies without closing its browser leaves that Chrome running for good
        (20 such processes from a 9/15 launch were found on 2026-09-21), so the kill is not
        optional. The daemon itself is shared by every agent-browser session on the machine
        and is left alone here; see recycle().
        """
        try:
            self.run("close", check=False)
        except BrowserError as e:
            log.warning("browser close: %s", e)
        _kill(_procs("chrome.exe", self.profile_dir), "orphaned watcher Chrome")
        Browser._daemon_ready = False

    def recycle(self, reason: str) -> None:
        """Restart the browser, and the daemon too when it has grown past DAEMON_CAP_MB.

        Killing the daemon drops every other agent-browser session on the machine, so it
        is done only on memory, never on the clock, and the log says so each time.
        """
        daemon_mb, chrome_mb = self.memory_mb()
        log.info("browser recycle (%s): daemon %d MB, chrome %d MB", reason, daemon_mb, chrome_mb)
        self.close()
        if daemon_mb > DAEMON_CAP_MB:
            log.warning("agent-browser daemon at %d MB (cap %d): killing it; other agent-browser sessions are dropped too",
                        daemon_mb, DAEMON_CAP_MB)
            _kill(_procs(DAEMON_EXE), "agent-browser daemon")
            time.sleep(2)

    def due_for_recycle(self) -> str | None:
        """Why the browser should be recycled now, or None."""
        if not Browser._daemon_ready:
            return None
        if time.time() - self.launched > RECYCLE_AFTER_S:
            return "age"
        daemon_mb, chrome_mb = self.memory_mb()
        if daemon_mb > DAEMON_CAP_MB:
            return f"daemon {daemon_mb} MB"
        if chrome_mb > CHROME_CAP_MB:
            return f"chrome {chrome_mb} MB"
        return None

    def run(self, *args: str, check: bool = True) -> str:
        self._ensure_daemon()
        cmd = self._base() + list(args)
        log.debug("agent-browser %s", " ".join(args[:3]))
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
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

