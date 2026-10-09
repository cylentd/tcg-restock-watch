// Is it a deal? (journey 5): per-game price index cards and a shelf-price check.
// Data: D.trends from tcgwatch/site_data/trends.py. Rules and worked examples: docs/trends.md.
const TR_INDEX_BASE = 100;       // docs/trends.md "Game index": the base date is 100
const TR_MATCH_MAX = 6;          // search results shown at once; fits above the inputs on a 390px phone
const TR_SPARK_W = 120;          // sparkline viewBox; the svg stretches to its box
const TR_SPARK_H = 36;
const TR_SPARK_PAD = 3;          // keeps the 2.4px stroke inside the box at the max and min
const TR = {key: null};

// The verdict for a typed price: the only rule this file holds, and it is a comparison, not a formula.
// The provider (site_data/trends.py) bakes every ceiling, every shown price and which line to print;
// docs/trends.md "Deal bands" gives the order: deal_below first, then fair_below, so deal wins.
// test_section_trends_js.py runs this function against the documented examples.
const trBand = (price, b) => b.deal_below != null && price <= b.deal_below ? 'deal'
  : b.fair_below != null && price <= b.fair_below ? 'fair' : 'high';
const trDate = iso => new Date(iso + 'T00:00:00Z').toLocaleDateString('en-US', {month:'short', day:'numeric', timeZone:'UTC'});
const trPrice = s => { const v = parseFloat(String(s).replace(/[^\d.]/g, '')); return v > 0 ? v : null; };

function trSpark(index){
  if (index.length < 2) return '';
  const vals = index.map(p => p[1]), min = Math.min(...vals), span = (Math.max(...vals) - min) || 1;
  const step = TR_SPARK_W / (vals.length - 1), h = TR_SPARK_H - TR_SPARK_PAD * 2;
  const pts = vals.map((v, i) => `${(i * step).toFixed(1)},${(TR_SPARK_PAD + h - (v - min) / span * h).toFixed(1)}`).join(' ');
  return `<svg class="tr-spark" viewBox="0 0 ${TR_SPARK_W} ${TR_SPARK_H}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" vector-effect="non-scaling-stroke"/></svg>`;
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

function trMatches(q){
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const box = $('#trMatches');
  if (!words.length || TR.key) { box.hidden = true; return; }
  const hits = trProducts().filter(g => words.every(w => g.name.toLowerCase().includes(w))).slice(0, TR_MATCH_MAX);
  box.innerHTML = hits.length ? hits.map(g => `<button class="tr-match" role="option" data-key="${g.key}">${gameGlyph(g.game)}<span>${g.name}</span></button>`).join('')
    : '<div class="tr-empty">{{tr_no_match}}</div>';
  box.hidden = false;
}

function trWhy(band, b){
  if (band === 'deal') { const v = money(b.deal_shown); return `{{tr_why_deal}}`; }
  if (band === 'fair') { const v = money(b.fair_shown); return `{{tr_why_fair}}`; }
  const v = money(b.high_shown);
  return b.high_band === 'fair' ? `{{tr_why_high_fair}}` : `{{tr_why_high_deal}}`;
}

function trVerdict(b){
  const price = trPrice($('#trPrice').value);
  // The wait state holds the verdict's two lines, so typing a price never moves the inputs below it.
  if (price == null) return `<div class="tr-verdict wait"><b>{{tr_wait_word}}</b><span>{{tr_wait}}</span></div>`;
  const band = trBand(price, b);
  const word = {deal:'{{tr_deal}}', fair:'{{tr_fair}}', high:'{{tr_high}}'}[band];
  return `<div class="tr-verdict ${band}"><b>${word}</b><span>${trWhy(band, b)}</span></div>`;
}

function trWarnings(g, b){
  const out = [], gt = D.trends.games[g.game], game = g.game;
  if (gt && gt.at_peak) out.push(`{{tr_peak_warn}}`);
  if (b.drop_risk) { const r = {release: b.drop_risk.release, when: trDate(b.drop_risk.date)}; out.push(`{{tr_drop_warn}}`); }
  return out.length ? `<ul class="tr-warn">${out.map(w => `<li>${w}</li>`).join('')}</ul>` : '';
}

function trDraw(){
  const g = TR.key && D.groups.find(x => x.key === TR.key);
  if (!g) { $('#trOut').innerHTML = '<p class="tr-hint">{{tr_check_hint}}</p>'; return; }
  const b = D.trends.products[g.key], m = g.market;
  const facts = [g.msrp ? `{{meter_msrp}} ${money(g.msrp)}` : '', m && m.price ? `{{meter_market}} ${money(m.price)}` : ''].filter(Boolean).join(' · ');
  const head = `<div class="tr-pick"><div class="tr-pick-n">${gameGlyph(g.game)}${g.name}</div>${facts ? `<div class="tr-pick-f num">${facts}</div>` : ''}</div>`;
  if (b.deal_below == null && b.fair_below == null) { $('#trOut').innerHTML = head + '<p class="tr-hint">{{tr_no_bands}}</p>' + trWarnings(g, b); return; }
  const bands = [
    b.deal_below != null ? (v => `<span class="tr-band deal">{{tr_deal_line}}</span>`)(money(b.deal_shown)) : '',
    b.fair_line ? (v => `<span class="tr-band fair">{{tr_fair_line}}</span>`)(money(b.fair_shown)) : '',
  ].join('');
  $('#trOut').innerHTML = head + trVerdict(b) + `<div class="tr-bands">${bands}</div>` + trWarnings(g, b);
}

function trPick(key){
  const g = D.groups.find(x => x.key === key);
  if (!g) return;
  TR.key = key; $('#trQ').value = g.name; $('#trMatches').hidden = true;
  trDraw(); $('#trPrice').focus({preventScroll:true});
}

(function trSetup(){
  if (!D.trends || !trProducts().length) return;
  $('#trWrap').hidden = false;
  // Games with a trend first, then early data, then none; the provider's order (by name) breaks ties.
  const rank = ([, t]) => !t.index.length ? 2 : t.early ? 1 : 0;
  $('#trGames').innerHTML = Object.entries(D.trends.games).sort((a, b) => rank(a) - rank(b)).map(trGameCard).join('');
  const q = $('#trQ'), price = $('#trPrice'), dock = $('#trDock'), check = $('#trCheck');
  q.addEventListener('input', () => { const g = TR.key && D.groups.find(x => x.key === TR.key);
    if (g && q.value !== g.name) TR.key = null; trMatches(q.value); trDraw(); });
  q.addEventListener('focus', () => trMatches(q.value));
  q.addEventListener('keydown', e => { if (e.key === 'Escape') $('#trMatches').hidden = true; });
  $('#trMatches').addEventListener('click', e => { const b = e.target.closest('.tr-match'); if (b) trPick(b.dataset.key); });
  price.addEventListener('input', trDraw);
  document.addEventListener('click', e => { if (!e.target.closest('.tr-inputs, .tr-matches')) $('#trMatches').hidden = true; });
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
