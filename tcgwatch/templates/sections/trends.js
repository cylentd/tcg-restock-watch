// Is it a deal? (journey 5): per-game price index cards and a shelf-price check.
// Data: D.trends from tcgwatch/site_data/trends.py. Rules and worked examples: docs/trends.md.
const TR_INDEX_BASE = 100;       // docs/trends.md "Game index": the base date is 100
const TR_SPARK_W = 120;          // sparkline viewBox; the svg stretches to its box
const TR_SPARK_H = 56;           // viewBox height, matched to .tr-spark's css height so the stroke is not squashed
// The y-range fits the plotted values (David, 2026-10-09: "the graph seems pretty flat"). The pad is
// the share of the fitted span added above and below, so the stroke never touches the box edge.
const TR_SPARK_PAD = 0.1;
// The smallest span drawn, in index points. Real history (2026-09-06 to 10-09) wobbles about half a
// point a day, so a fit tighter than this would draw that noise as a crash.
const TR_SPARK_MIN_SPAN = 4;
const TR_LIST_MAX = 296;         // px: the open list's tallest, about five and a half 52px rows, so a cut row hints at scrolling
const TR_LIST_GAP = 8;           // px kept between the open list and the screen edge
const TR = {key: null, active: -1, hits: []};

// The verdict for a typed price: the only rule this file holds, and it is a comparison, not a formula.
// The provider (site_data/trends.py) bakes every ceiling, every shown price and which line to print;
// docs/trends.md "Deal bands" gives the order: deal_below first, then fair_below, so deal wins.
// test_section_trends_js.py runs this function against the documented examples.
const trBand = (price, b) => b.deal_below != null && price <= b.deal_below ? 'deal'
  : b.fair_below != null && price <= b.fair_below ? 'fair' : 'high';
const trDate = iso => new Date(iso + 'T00:00:00Z').toLocaleDateString('en-US', {month:'short', day:'numeric', timeZone:'UTC'});
const trPrice = s => { const v = parseFloat(String(s).replace(/[^\d.]/g, '')); return v > 0 ? v : null; };

// [low, high] of the sparkline's y axis: the values' own min and max, widened to minSpan around their
// middle when they sit closer than that, then padded by pad x span on each side.
function trSparkRange(vals, minSpan = TR_SPARK_MIN_SPAN, pad = TR_SPARK_PAD){
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < minSpan) { const mid = (lo + hi) / 2; lo = mid - minSpan / 2; hi = mid + minSpan / 2; }
  const p = (hi - lo) * pad;
  return [lo - p, hi + p];
}

// Points sit at their date, so a gap in the history reads as a gap. The dashed line is the base date
// (index 100), the same point the card's "since" number counts from: above it is up, below it is down.
function trSpark(index){
  if (index.length < 2) return '';
  const [lo, hi] = trSparkRange(index.map(p => p[1]));
  const t = index.map(p => Date.parse(p[0])), t0 = t[0], tw = (t[t.length - 1] - t0) || 1;
  const y = v => (TR_SPARK_H - (v - lo) / (hi - lo) * TR_SPARK_H).toFixed(1);
  const pts = index.map((p, i) => `${((t[i] - t0) / tw * TR_SPARK_W).toFixed(1)},${y(p[1])}`).join(' ');
  const base = y(TR_INDEX_BASE);
  return `<svg class="tr-spark" viewBox="0 0 ${TR_SPARK_W} ${TR_SPARK_H}" preserveAspectRatio="none" aria-hidden="true">`
    + `<line class="tr-base" x1="0" y1="${base}" x2="${TR_SPARK_W}" y2="${base}" vector-effect="non-scaling-stroke"/>`
    + `<polyline points="${pts}" vector-effect="non-scaling-stroke"/></svg>`;
}

function trGameCard([game, t]){
  const cls = !t.index.length ? 'none' : t.early ? 'early' : t.at_peak ? 'peak' : 'under';
  const pill = {none:'{{tr_none}}', early:'{{tr_early}}', peak:'{{tr_at_peak}}', under:'{{tr_under_peak}}'}[cls];
  let body;
  if (cls === 'none') return `<div class="tr-game ${cls}"><div class="tr-g-top">${gameTag(game)}<span class="tr-pill ${cls}">${pill}</span></div></div>`;
  if (cls === 'early') body = `<p class="tr-note">{{tr_early_note}}</p>`;
  else {
    const chg = t.latest - TR_INDEX_BASE, when = trDate(t.index[0][0]), pct = t.below_high;
    // The distance from the window high sits beside the change since the base date, so a card at its
    // peak never reads as a fall without saying how far it is from the high.
    body = `<div class="tr-num"><b class="num">${chg > 0 ? '+' : ''}${chg.toFixed(1)}%</b><span>{{tr_since}}</span>${pct > 0 ? `<span>{{tr_under_high}}</span>` : ''}</div>`;
  }
  return `<div class="tr-game ${cls}"><div class="tr-g-top">${gameTag(game)}<span class="tr-pill ${cls}">${pill}</span></div><div class="tr-g-body">${body}${trSpark(t.index)}</div></div>`;
}

const trProducts = () => live().filter(g => D.trends.products[g.key]);

// Products whose game and name together hold every typed word, in any order and any case (the shown
// name drops the game word, so "riftbound" must match the game). Nothing typed keeps them all, so the
// list doubles as a picture menu for someone who does not know the product's name.
const trFilter = (list, q) => {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  return list.filter(g => { const text = `${g.game} ${g.name}`.toLowerCase(); return words.every(w => text.includes(w)); });
};

// The active option after an arrow key in a list of n, wrapping at both ends; any other key keeps it.
function trStep(active, n, key){
  if (key === 'ArrowDown') return active + 1 >= n ? 0 : active + 1;
  if (key === 'ArrowUp') return active <= 0 ? n - 1 : active - 1;
  return active;
}

// Which option Enter picks: the highlighted one, else the first match, else none (-1).
const trEnterPick = (active, n) => active >= 0 ? active : n > 0 ? 0 : -1;

// Where the list opens: up when `want` px fits in the room above the field (the field then stays low,
// in the thumb zone), else down when it fits below, else toward the larger room. `max` never exceeds
// the room on the chosen side, so the first and last options are never cut off by the screen edge.
function trPlace(above, below, want){
  const up = above >= want || (below < want && above >= below);
  return {up, max: Math.min(want, up ? above : below)};
}

// Same picture as the product list (page.js row thumbs): g.img, already a local webp, or the
// placeholder. `pic` false leaves the box empty, for the invisible reserve (trReserve).
const trThumb = (g, pic = true) => `<span class="thumb tr-thumb">${!pic ? '' : g && g.img ? `<img src="${g.img}" alt="" loading="lazy" decoding="async">` : PLACEHOLDER}</span>`;

// Measures the room between the field and the visible screen edges (the visual viewport, so a phone
// keyboard counts as an edge) and places the list in it.
function trFit(){
  const box = $('#trMatches'), field = $('.tr-inputs').getBoundingClientRect(), vv = window.visualViewport;
  const top = vv ? vv.offsetTop : 0, bottom = top + (vv ? vv.height : innerHeight);
  box.style.maxHeight = 'none';
  const want = Math.min(box.scrollHeight, TR_LIST_MAX);
  const place = trPlace(field.top - top - TR_LIST_GAP, bottom - field.bottom - TR_LIST_GAP, want);
  box.classList.toggle('down', !place.up);
  box.style.maxHeight = `${place.max}px`;
}

function trOpen(open){
  $('#trMatches').hidden = !open;
  // The scrim dims the page under the open list; a tap on it closes the list instead of landing on
  // whatever sits under the finger (QA 2026-10-09: a tap at the heading picked a product).
  $('#trScrim').hidden = !open;
  $('#trCheck').classList.toggle('picking', open);
  $('#trQ').setAttribute('aria-expanded', String(open));
  if (open) trFit();
  else { TR.active = -1; $('#trQ').removeAttribute('aria-activedescendant'); }
}

function trActivate(i){
  TR.active = i;
  const opts = $('#trMatches').querySelectorAll('.tr-match');
  opts.forEach((o, j) => o.setAttribute('aria-selected', String(j === i)));
  if (i < 0 || !opts[i]) { $('#trQ').removeAttribute('aria-activedescendant'); return; }
  $('#trQ').setAttribute('aria-activedescendant', opts[i].id);
  // Scroll the list only, never the page (scrollIntoView would move the page under the reader).
  const box = $('#trMatches'), o = opts[i];
  if (o.offsetTop < box.scrollTop) box.scrollTop = o.offsetTop;
  else if (o.offsetTop + o.offsetHeight > box.scrollTop + box.clientHeight) box.scrollTop = o.offsetTop + o.offsetHeight - box.clientHeight;
}

function trMatches(q){
  const picked = TR.key && D.groups.find(x => x.key === TR.key);
  // With a product picked and its name still in the box, show every product to switch to.
  TR.hits = trFilter(trProducts(), picked && q === picked.name ? '' : q);
  const box = $('#trMatches');
  box.innerHTML = TR.hits.length ? TR.hits.map((g, i) => `<div class="tr-match" role="option" id="trOpt${i}" data-key="${g.key}" aria-selected="false">${trThumb(g)}<span class="tr-match-n">${gameGlyph(g.game)}${g.name}</span></div>`).join('')
    : '<div class="tr-empty">{{tr_no_match}}</div>';
  box.scrollTop = 0;
  trOpen(true);
  // Typed words highlight the first match, the one Enter picks; a picked product highlights itself.
  trActivate(picked ? TR.hits.indexOf(picked) : q.trim() ? trEnterPick(-1, TR.hits.length) : -1);
}

function trWhy(band, b){
  if (band === 'deal') { const v = money(b.deal_shown); return `{{tr_why_deal}}`; }
  if (band === 'fair') { const v = money(b.fair_shown); return `{{tr_why_fair}}`; }
  const v = money(b.high_shown);
  return b.high_band === 'fair' ? `{{tr_why_high_fair}}` : `{{tr_why_high_deal}}`;
}

const trWait = line => `<div class="tr-verdict wait"><b>{{tr_wait_word}}</b><span>${line}</span></div>`;

function trVerdictOf(band, b){
  const word = {deal:'{{tr_deal}}', fair:'{{tr_fair}}', high:'{{tr_high}}'}[band];
  return `<div class="tr-verdict ${band}"><b>${word}</b><span>${trWhy(band, b)}</span></div>`;
}

function trVerdict(b){
  const price = trPrice($('#trPrice').value);
  return price == null ? trWait('{{tr_wait}}') : trVerdictOf(trBand(price, b), b);
}

function trWarnings(g, b){
  const out = [], gt = D.trends.games[g.game], game = g.game;
  if (gt && gt.at_peak) out.push(`{{tr_peak_warn}}`);
  if (b.drop_risk) { const r = {release: b.drop_risk.release, when: trDate(b.drop_risk.date)}; out.push(`{{tr_drop_warn}}`); }
  return out.length ? `<ul class="tr-warn">${out.map(w => `<li>${w}</li>`).join('')}</ul>` : '';
}

// One state of the check: the picked product, then the verdict, the ceilings and the warnings.
// `verdict` is the verdict box's html; trDraw passes the live one, trReserve each possible one.
function trState(g, verdict, pic = true){
  if (!g) return `<div class="tr-pick">${trThumb(null, pic)}<div><div class="tr-pick-n tr-pick-hint">{{tr_check_hint}}</div><div class="tr-pick-f"></div></div></div>${trWait('{{tr_wait}}')}`;
  const b = D.trends.products[g.key], m = g.market;
  const facts = [g.msrp ? `{{meter_msrp}} ${money(g.msrp)}` : '', m && m.price ? `{{meter_market}} ${money(m.price)}` : ''].filter(Boolean).join(' · ');
  const head = `<div class="tr-pick">${trThumb(g, pic)}<div><div class="tr-pick-n">${gameGlyph(g.game)}${g.name}</div><div class="tr-pick-f num">${facts}</div></div></div>`;
  if (b.deal_below == null && b.fair_below == null) return head + trWait('{{tr_no_bands}}') + trWarnings(g, b);
  const bands = [
    b.deal_below != null ? (v => `<span class="tr-band deal">{{tr_deal_line}}</span>`)(money(b.deal_shown)) : '',
    b.fair_line ? (v => `<span class="tr-band fair">{{tr_fair_line}}</span>`)(money(b.fair_shown)) : '',
  ].join('');
  return head + verdict(b) + `<div class="tr-bands">${bands}</div>` + trWarnings(g, b);
}

function trDraw(){
  const g = TR.key && D.groups.find(x => x.key === TR.key);
  $('#trLive').innerHTML = trState(g, trVerdict);
}

// David, 2026-10-09: "The card shouldnt also expand and shrink." Every state the check can show is
// laid out, invisible, in the same grid cell as the live one, so the browser sizes the card to the
// tallest state at the reader's own width and font; switching product, verdict or notes never moves it.
function trReserve(){
  // Pictures never load in the reserve: the thumb box has a fixed size either way.
  const states = [trState(null, null, false)];
  for (const g of trProducts())
    for (const band of ['deal', 'fair', 'high']) states.push(trState(g, b => trVerdictOf(band, b), false));
  $('#trGhost').innerHTML = states.map(s => `<div class="tr-state">${s}</div>`).join('');
}

function trPick(key){
  const g = D.groups.find(x => x.key === key);
  if (!g) return;
  TR.key = key; $('#trQ').value = g.name; trOpen(false);
  trDraw(); $('#trPrice').focus({preventScroll:true});
}

(function trSetup(){
  if (!D.trends || !trProducts().length) return;
  $('#trWrap').hidden = false;
  // Games with a trend first, then early data, then none; the provider's order (by name) breaks ties.
  const rank = ([, t]) => !t.index.length ? 2 : t.early ? 1 : 0;
  $('#trGames').innerHTML = Object.entries(D.trends.games).sort((a, b) => rank(a) - rank(b)).map(trGameCard).join('');
  trReserve(); trDraw();
  const q = $('#trQ'), price = $('#trPrice'), dock = $('#trDock'), check = $('#trCheck'), box = $('#trMatches');
  q.addEventListener('input', () => { const g = TR.key && D.groups.find(x => x.key === TR.key);
    if (g && q.value !== g.name) TR.key = null; trMatches(q.value); trDraw(); });
  q.addEventListener('focus', () => { if (TR.key) q.select(); trMatches(q.value); });
  q.addEventListener('click', () => { if (box.hidden) trMatches(q.value); });
  q.addEventListener('keydown', e => {
    if (e.key === 'Escape') { trOpen(false); return; }
    if (e.key === 'Enter') {
      const i = trEnterPick(TR.active, TR.hits.length);
      if (!box.hidden && i >= 0) { e.preventDefault(); trPick(TR.hits[i].key); }
      return;
    }
    // Arrows only: Home and End keep moving the caret inside the text box (ARIA combobox pattern).
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    if (box.hidden) trMatches(q.value);
    if (!TR.hits.length) return;
    e.preventDefault();
    trActivate(trStep(TR.active, TR.hits.length, e.key));
  });
  q.addEventListener('blur', () => setTimeout(() => { if (!box.contains(document.activeElement)) trOpen(false); }));
  // pointerdown keeps focus in the box (a tap would blur it first and close the list under the finger).
  box.addEventListener('pointerdown', e => e.preventDefault());
  box.addEventListener('click', e => { const o = e.target.closest('.tr-match'); if (o) trPick(o.dataset.key); });
  price.addEventListener('input', trDraw);
  document.addEventListener('click', e => { if (!e.target.closest('.tr-inputs')) trOpen(false); });
  $('#trScrim').addEventListener('click', () => trOpen(false));
  // The phone keyboard opening, a rotation or a scroll changes the room around the field.
  const refit = () => { if (!box.hidden) trFit(); };
  (window.visualViewport || window).addEventListener('resize', refit);
  addEventListener('scroll', refit, {passive:true});
  // Phone thumb zone: a docked button jumps to the check from anywhere on the page. It hides while
  // the check is on screen; trends.css hides it from 640px up, where the page is not one long column.
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(([e]) => { dock.hidden = e.isIntersecting; }).observe(check);
  }
  dock.onclick = () => {
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    check.scrollIntoView({block:'end', behavior: reduced ? 'auto' : 'smooth'});
    (TR.key ? price : q).focus({preventScroll:true});
  };
})();
