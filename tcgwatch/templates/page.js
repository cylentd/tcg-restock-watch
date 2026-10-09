const D = JSON.parse(document.getElementById('data').textContent);
// Tuning numbers, named 2026-10-09 with their values unchanged. Unless a line says otherwise they
// came over from the single-file site.py template, tuned by eye with David on 2026-09-07.
const FULL_TURN = 360;             // degrees in a circle
const SWIRL_ARMS = 5;              // Riftbound's swirl glyph: five arms, 72 degrees apart
const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_DAY = 86400;
const AGO_SECONDS_UNDER = 90;      // "45s" until 90 s, then minutes
const AGO_MINUTES_UNDER = 5400;    // minutes until 90 min, then hours
const AGO_HOURS_UNDER = 172800;    // hours until 48 h, then days
const AT_MSRP_MAX = 1.15;          // market up to 1.15x MSRP still reads "at MSRP"
const MARKET_EVEN_BAND = 0.03;     // a listing within 3% of market is "about market"
const REEL_MAX = 10;               // hot reel shows the 10 hottest products
const REEL_MIN = 3;                // fewer than 3 is not worth a moving strip
const REEL_VEL_STOP = 0.05;        // px/frame below which a fling has stopped
const REEL_FRICTION = 0.955;       // fling velocity kept per frame
const REEL_IDLE_MS = 700;          // pause after a drag before the drift resumes
const REEL_DRIFT = 0.4;            // idle drift, px/frame
const REEL_DRIFT_HOVER = 0.16;     // slower drift under the mouse
const REEL_VEL_MAX = 150;          // fling speed cap, px/frame
const TAP_SLOP_PX = 6;             // a pointer that moved this far or less was a tap, not a drag
const SPARK_W = 100;               // sparkline viewBox; it stretches to its box
const SPARK_H = 28;
const TOAST_SHOW_MS = 1400;
const TOAST_FADE_MS = 250;         // matches the .toast opacity transition in page.css
const CAL_SOON_DAYS = 7;           // "soon" colour on the release calendar
const CAL_NEAR_DAYS = 30;          // "near" colour
const CAL_DAYS_MAX = 60;           // "in N days" up to 60, then "in N weeks"
const WHEEL_DONE_PX = 0.5;         // wheel ease stops this close to its target
const WHEEL_EASE = 0.18;           // share of the remaining distance covered per frame (David, 2026-09-07)
const RET = {target:{l:'Target',c:'var(--target)'}, bestbuy:{l:'Best Buy',c:'var(--bestbuy)'}, walmart:{l:'Walmart',c:'var(--walmart)'}, gamestop:{l:'GameStop',c:'var(--gamestop)'}};
const ST = {
  in:{l:'{{st_in}}', i:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 5 5L20 7"/></svg>'},
  out:{l:'{{st_out}}', i:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M5 12h14"/></svg>'},
  unknown:{l:'{{st_unknown}}', i:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><circle cx="12" cy="12" r="8"/><path d="M12 8v4l2.5 2.5"/></svg>'}
};
const PLACEHOLDER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h3"/></svg>';
// One glyph per game: filled pokeball, stroked anchor (David kept it over a Straw Hat skull, more
// distinctive at 11px), Riftbound's orange swirl. Hue reserved per game, used on the glyph only.
const GAME = {
  'Pokemon':   {c:'#ffcf4a', i:'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 0 1 9.8 8.2h-6.1a3.8 3.8 0 0 0-7.4 0H2.2A10 10 0 0 1 12 2z"/><path d="M2.2 13.8h6.1a3.8 3.8 0 0 0 7.4 0h6.1A10 10 0 0 1 2.2 13.8z"/><circle cx="12" cy="12" r="2"/></svg>'},
  'One Piece': {c:'#3ddbc4', i:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="2.4"/><path d="M12 7.4V21M5 13a7 7 0 0 0 14 0M8.5 13H5M19 13h-3.5"/></svg>'},
  'Riftbound': {c:'#ff8a1f', i:'<svg viewBox="0 0 24 24" fill="currentColor">' + Array.from({length: SWIRL_ARMS}, (_, k) => k * FULL_TURN / SWIRL_ARMS).map(a => `<path d="M11 12C10 5 16 1 23 4 17 4.5 15 8 15 12 15 14 12 14.5 11 12z" transform="rotate(${a} 12 12)"/>`).join('') + '</svg>'},
};
const gameTag = name => { const g = GAME[name]; return `<span class="tag" style="--gc:${g ? g.c : 'currentColor'}">${g ? g.i : ''}${name}</span>`; };
// Icon-only glyph (no text chip) for tight spaces; title carries the game name for a11y/hover.
const gameGlyph = name => { const g = GAME[name]; if (!g) return ''; return `<span class="gi" style="--gc:${g.c}" title="${name}">${g.i}</span>`; };
const F = {q:'', game:'', kind:'', ret:new Set(Object.keys(RET)), status:'', sort:'hot'};
const FLAME = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2c1 4 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-5 1-9z"/></svg>';
const $ = s => document.querySelector(s);
const money = v => v == null ? null : '$' + Number(v).toFixed(2);
const ago = ts => { if(!ts) return ''; const d = Math.max(0, Math.round(D.generated - ts)); return d<AGO_SECONDS_UNDER? d+'s' : d<AGO_MINUTES_UNDER? Math.round(d/SECONDS_PER_MINUTE)+'m' : d<AGO_HOURS_UNDER? Math.round(d/SECONDS_PER_HOUR)+'h' : Math.round(d/SECONDS_PER_DAY)+'d'; };

function stats(){
  const listings = D.groups.reduce((n,g)=>n+g.listings.length,0);
  const inStock = D.groups.filter(g=>g.in_stock).length;
  const prems = D.groups.map(g=>g.premium).filter(Boolean).sort((a,b)=>a-b);
  const med = prems.length ? prems[Math.floor(prems.length/2)] : null;
  $('#stats').innerHTML = [
    [D.groups.length, '{{stat_products}}', ''],
    [listings, '{{stat_listings}}', ''],
    [inStock, '{{stat_in_stock}}', inStock ? '<span class="dot"></span>' : ''],
    [med ? med.toFixed(1)+'×' : '—', prems.length ? '{{stat_median_pre}}'+prems.length+'{{stat_median_post}}' : '{{stat_median_none}}', ''],
  ].map(([v,l,x])=>`<div class="stat"><div class="v">${x}${v}</div><div class="l">${l}</div></div>`).join('');
}

// Single source of truth for the premium verdict; the meter headline is the only place it renders.
// Color still grades severity (green/amber/red); the word doesn't need to try too — "2.5x
// scalped" said the same thing twice, awkwardly (David, 2026-09-07).
const premiumVerdict = p => p == null ? null : p <= AT_MSRP_MAX ? {cls:'ok', t:'{{verdict_at}}'} : {cls: p <= 2 ? 'hi' : 'wild', t:'{{verdict_over}}'};
// The ratio + verdict word alone: the signal ("3.0x scalped"). Used on the row, where the actual
// MSRP/Market breakdown is a click away, not a second thing to scan past for every product.
function meterHead(g){
  const m = g.market, p = g.premium, v = premiumVerdict(p);
  return p ? `<div class="cmp-head ${v.cls}"><b>${p.toFixed(1)}×</b><span>${v.t}</span></div>`
           : `<div class="cmp-head muted"><span>${m? '{{meter_no_msrp}}' : '{{meter_no_market}}'}</span></div>`;
}
// showHead: the sheet wants the exact "3.0x over MSRP" readout; the row doesn't need to say the
// same thing three ways (number, word, and bar length) — the bar alone carries it once the
// Market bar's own color grades severity (green/amber/red), not just a decorative gradient
// (David, 2026-09-07).
function meter(g, showHead){
  const m = g.market, v = premiumVerdict(g.premium);
  const max = Math.max(g.msrp||0, m? m.price:0) || 1;
  // The link icon sits on the label, not the number — appended after the number broke the
  // right-aligned edge between the MSRP and MARKET value columns (David, 2026-09-07).
  const bar = (cls, label, val, href) => `<div class="cmp-row"><span class="cmp-l">${href ? `<a class="cmp-link" href="${href}" target="_blank" rel="noopener" title="{{tcgplayer_link_title}}">${label}${ICO.go}</a>` : label}</span><span class="cmp-t"><span class="cmp-b ${cls}" style="width:${val? Math.max(3, val/max*100):0}%"></span></span><span class="cmp-v num">${val? money(val) : '—'}</span></div>`;
  return `<div class="meter">${showHead? meterHead(g) : ''}${bar('msrp','{{meter_msrp}}',g.msrp)}${bar(`mkt ${v?v.cls:''}`,'{{meter_market}}',m? m.price:null, m? m.url:null)}</div>`;
}

// This retailer's asking price vs the true open-market price (not MSRP): is buying it right
// now actually a deal, or is TCGplayer itself cheaper? Only meaningful while it's orderable.
function dealBadge(l, m){
  if (l.status !== 'in' || !l.price || !m || !m.price) return '';
  const diff = l.price - m.price;
  if (Math.abs(diff) / m.price < MARKET_EVEN_BAND) return `<span class="deal even">{{deal_even}}</span>`;
  return diff < 0 ? `<span class="deal buy">{{deal_buy_pre}}${money(-diff)}{{deal_buy_post}}</span>` : `<span class="deal pass">{{deal_pass_pre}}${money(diff)}{{deal_pass_post}}</span>`;
}

function shop(l, m){
  const r = RET[l.retailer] || {l:l.retailer, c:'var(--ink-3)'};
  const s = ST[l.status];
  return `<a class="shop" href="${l.url}" target="_blank" rel="noopener" style="--c:${r.c}" title="${l.checked ? '{{checked_prefix}}' + ago(l.checked) + '{{checked_suffix}}' : '{{not_checked}}'}">
    <div class="shop-top"><span class="id"></span><span class="r">${r.l}</span><span class="st ${l.status}">${s.i}${s.l}</span></div>
    <div class="shop-bot">${l.price? `<span class="num">${money(l.price)}</span>`:'<span class="num muted">—</span>'}${dealBadge(l, m)}</div>
  </a>`;
}
// A single retailer stretched into the same two-line card as a multi-retailer row left a card
// that's visibly short of full width — a box that should be bigger but isn't. One listing gets a
// compact single-line pill instead, sized to its content, so a natural gap after it reads as a
// small tag, not a box that looks broken (David: "u love gaps dont u", 2026-09-07).
function shopSolo(l, m){
  const r = RET[l.retailer] || {l:l.retailer, c:'var(--ink-3)'};
  const s = ST[l.status];
  return `<a class="shop solo" href="${l.url}" target="_blank" rel="noopener" style="--c:${r.c}" title="${l.checked ? '{{checked_prefix}}' + ago(l.checked) + '{{checked_suffix}}' : '{{not_checked}}'}">
    <span class="id"></span><span class="r">${r.l}</span>${l.price? `<span class="num">${money(l.price)}</span>`:''}${dealBadge(l, m)}<span class="st ${l.status}">${s.i}${s.l}</span>
  </a>`;
}

// Rows the same height needs the two things that actually varied — name length and listing
// count — normalized, not just the bars (David wants those back) hidden or shown. Name clamps to
// 2 lines with that height always reserved; more than 2 listings collapses to a "+N more" tag
// that opens the sheet, since 84 of 86 products have 1-2 listings anyway (2026-09-07).
const SHOP_CAP = 2;
function row(g){
  const over = g.listings.length - SHOP_CAP;
  const visible = over > 0 ? g.listings.slice(0, SHOP_CAP) : g.listings;
  let shops = g.listings.length === 1 ? shopSolo(g.listings[0], g.market) : visible.map(l => shop(l, g.market)).join('');
  if (over > 0) shops += `<button class="shop more" data-key="${g.key}">+${over} {{more}}</button>`;
  return `<div class="row ${g.in_stock?'in':''}" data-key="${g.key}">
    <div class="thumb">${g.img? `<img src="${g.img}" alt="" loading="lazy" decoding="async">` : PLACEHOLDER}</div>
    <div class="head"><div class="name">${gameGlyph(g.game)}${g.name}</div><div class="meta">${g.buzz? `<span class="hot" title="{{buzz_title}}">${FLAME}${g.buzz} {{buzz_suffix}}</span>`:''}${g.retired? `<span class="micro">${g.retired}</span>`:''}</div></div>
    ${meter(g, false)}
    <div class="shops">${shops}</div>
  </div>`;
}

function apply(){
  const q = F.q.trim().toLowerCase();
  const retired = D.groups.filter(g => g.retired);
  $('#retired').hidden = !retired.length;
  $('#retiredCount').textContent = retired.length;
  $('#retiredList').innerHTML = retired.map(row).join('');
  let rows = D.groups.filter(g => !g.retired).filter(g =>
    (!F.game || g.game===F.game) &&
    (!F.kind || g.kind===F.kind) &&
    (!q || g.name.toLowerCase().includes(q) || (g.market && g.market.name.toLowerCase().includes(q))) &&
    g.listings.some(l => F.ret.has(l.retailer) && (!F.status || l.status===F.status))
  ).map(g => ({...g, listings: g.listings.filter(l => F.ret.has(l.retailer) && (!F.status || l.status===F.status))}));
  const s = F.sort;
  rows.sort((a,b)=> s==='hot' ? (b.hot - a.hot) || a.name.localeCompare(b.name)
              : s==='premium' ? (b.premium||0)-(a.premium||0) : s==='name' ? a.name.localeCompare(b.name) : s==='msrp' ? (b.msrp||0)-(a.msrp||0)
              : (b.in_stock - a.in_stock) || a.game.localeCompare(b.game) || a.name.localeCompare(b.name));
  $('#list').innerHTML = rows.length ? rows.map(row).join('') : '<div class="empty">{{empty}}</div>';
  $('#count').textContent = rows.length + '{{count_of}}' + (D.groups.length - retired.length) + '{{count_tail}}' + D.generated_label;
}

$('#retailers').innerHTML = Object.entries(RET).map(([k,r])=>`<button class="chip on" data-r="${k}" style="--c:${r.c}"><span class="sw"></span>${r.l}</button>`).join('');
document.querySelectorAll('.chip').forEach(b=>b.onclick=()=>{ const k=b.dataset.r; F.ret.has(k)? F.ret.delete(k): F.ret.add(k); b.classList.toggle('on'); apply(); });
document.querySelectorAll('#game button').forEach(b=>b.onclick=()=>{ F.game=b.dataset.v; b.parentElement.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b)); apply(); drawCal(); });
$('#inStockToggle').onclick = () => { F.status = F.status ? '' : 'in'; $('#inStockToggle').classList.toggle('on', !!F.status); apply(); };
$('#kind').onchange = e => { F.kind = e.target.value; $('#kindWrap').classList.toggle('active', !!F.kind); apply(); };
$('#q').oninput = e => { F.q = e.target.value; apply(); };
$('#sort').onchange = e => { F.sort = e.target.value; apply(); };
// Hot reel: top products by hot score, doubled into one looping track.
(function reel(){
  const hot = D.groups.filter(g => !g.retired && (g.img || g.premium)).sort((a,b)=>b.hot-a.hot).slice(0,REEL_MAX);
  if (hot.length < REEL_MIN) return;
  const wrap = $('#reelWrap'), reelEl = $('#reel'), track = $('#track');
  wrap.hidden = false;
  const tile = g => `<a class="tile${g.in_stock ? ' in' : ''}" href="#${encodeURIComponent(g.key)}" data-key="${g.key}"><div class="art">${g.img? `<img src="${g.img}" alt="" loading="lazy" decoding="async">` : PLACEHOLDER}</div><div class="t">${g.name}</div><div class="x">${g.in_stock? '<span class="in">{{tile_in_stock}}</span>' : ''}${g.premium? `<b>${g.premium.toFixed(1)}×</b>`:''}</div></a>`;
  track.innerHTML = hot.map(tile).join('') + hot.map(tile).join('');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let pos = 0, vel = 0, drag = null, moved = 0, hover = false, idleAt = 0, setW = 0, tapTile = null;
  const measure = () => { setW = track.scrollWidth / 2; };
  measure(); addEventListener('resize', measure);
  function frame(){
    const now = performance.now();
    if (drag) { /* position follows pointer */ }
    else if (Math.abs(vel) > REEL_VEL_STOP) { pos += vel; vel *= REEL_FRICTION; }
    else if (!reduced && now - idleAt > REEL_IDLE_MS) { pos += hover ? REEL_DRIFT_HOVER : REEL_DRIFT; }
    if (setW > 0) { pos = ((pos % setW) + setW) % setW; }
    track.style.transform = `translateX(${-pos}px)`;
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  reelEl.addEventListener('mouseenter', ()=>hover=true); reelEl.addEventListener('mouseleave', ()=>hover=false);
  // setPointerCapture retargets the follow-up click to the reel itself, so a click listener on the
  // track never fires. Decide tap-vs-drag on pointerup instead and open the sheet from there.
  reelEl.addEventListener('pointerdown', e => { tapTile = e.target.closest('.tile'); drag = {x:e.clientX, pos, last:e.clientX, t:performance.now()}; moved = 0; vel = 0; reelEl.classList.add('drag'); reelEl.setPointerCapture(e.pointerId); });
  reelEl.addEventListener('pointermove', e => { if(!drag) return; const dx = e.clientX - drag.x; moved = Math.max(moved, Math.abs(dx)); pos = drag.pos - dx; const now = performance.now(); vel = -(e.clientX - drag.last) * 2; vel = Math.max(-REEL_VEL_MAX, Math.min(REEL_VEL_MAX, vel)); drag.last = e.clientX; drag.t = now; });
  const end = e => { if(!drag) return; drag = null; idleAt = performance.now(); reelEl.classList.remove('drag');
    if (e.type === 'pointerup' && moved <= TAP_SLOP_PX && tapTile) { vel = 0; openKey(tapTile.dataset.key); } tapTile = null; };
  reelEl.addEventListener('pointerup', end); reelEl.addEventListener('pointercancel', end);
  reelEl.addEventListener('click', e => { if (e.target.closest('.tile')) e.preventDefault(); });
})();
// Product sheet: one product's full picture. Opened by row tap, hot tile tap, or a #key deep link.
const SHEET = $('#sheet');
const ICO = {
  go:'<svg class="go" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17 17 7M9 7h8v8"/></svg>',
};
const live = () => D.groups.filter(x => !x.retired);
const VERDICT_ICON = {
  buy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 5 5L20 7"/></svg>',
  pass: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  even: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"><path d="M5 12h14"/></svg>',
};
// The one thing the sheet says that the row doesn't: a plain-language recommendation synthesized
// across every listing, instead of the same MSRP/Market numbers shown a second time.
function bestDeal(g){
  const m = g.market;
  const inStock = g.listings.filter(l => l.status === 'in' && l.price);
  // Nothing in stock is already unambiguous from every "SOLD OUT" pill in the retailer list right
  // below — a whole callout box just to restate that read as dead weight (David, 2026-09-07).
  if (!inStock.length || !m || !m.price) return null;
  const best = inStock.reduce((a, b) => a.price < b.price ? a : b);
  const r = RET[best.retailer] || {l: best.retailer};
  const diff = best.price - m.price;
  if (diff <= -m.price * MARKET_EVEN_BAND) return { cls:'buy', text: `{{best_buy}}` };
  if (diff >= m.price * MARKET_EVEN_BAND) return { cls:'pass', text: `{{best_pass}}` };
  return { cls:'even', text: `{{best_even}}` };
}
// EV per set link-out was dropped 2026-09-07: no existing EV calculator site was found to link
// to. Built our own instead (item 7, tcgwatch/ev.py) -- chase-card EV only (base cards ignored,
// see docs/ev-calculator-spec.md), a long-run mean across many box openings, not a per-box
// guarantee. `g.ev` is set server-side only for the handful of sets with pull-rate data.
function evBlock(g){
  const e = g.ev;
  if (!e || e.ev == null) return '';
  const cls = e.verdict > 0 ? 'buy' : 'pass';
  const rows = e.tiers.map(t => t.price == null
    ? `<tr><td>${t.name}</td><td class="est">{{ev_price_unknown}}</td></tr>`
    : `<tr><td>${t.name} <span class="est">{{ev_per_box}}</span></td><td${t.price_source && t.price_source.includes('community') ? ' class="est"' : ''}>${money(t.contribution)}</td></tr>`
  ).join('');
  return `<div class="ev-box">
    <div class="ev-head ${cls}"><span>{{ev_head}}</span><span>${e.verdict >= 0 ? '+' : '-'}${money(Math.abs(e.verdict))} {{ev_vs_box}}</span></div>
    <div class="ev-note">{{ev_note}}</div>
    <table class="ev-tiers">${rows}</table>
  </div>`;
}
// 90-day price trend: a small inline sparkline (no library) + 30/90-day % change, only for
// products with at least two days of recorded price -- see g.history in collect() (site.py).
function sparkSvg(pts){
  if (!pts || pts.length < 2) return '';
  const min = Math.min(...pts), max = Math.max(...pts), span = (max - min) || 1;
  const w = SPARK_W, h = SPARK_H;
  const step = w / (pts.length - 1);
  const coords = pts.map((p, i) => `${(i * step).toFixed(1)},${(h - (p - min) / span * h).toFixed(1)}`).join(' ');
  const up = pts[pts.length - 1] >= pts[0];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${coords}" fill="none" stroke="${up ? '#5fd65f' : '#ff8a80'}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>`;
}
function changeChip(pct, label){
  if (pct == null) return `<span class="chg muted">${label} {{chg_none}}</span>`;
  const cls = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat';
  return `<span class="chg ${cls}">${label} ${pct > 0 ? '+' : ''}${pct}%</span>`;
}
function historyBlock(g){
  const h = g.history;
  if (!h) return '';
  return `<div class="hist-box"><div class="hist-top">${sparkSvg(h.spark)}<div class="hist-chg">${changeChip(h.pct30, '30d')}${changeChip(h.pct90, '90d')}</div></div></div>`;
}
function openSheet(g){
  const p = g.premium, m = g.market, rank = live().findIndex(x => x.key === g.key) + 1;
  $('#sheetArt').innerHTML = g.img ? `<img src="${g.img}" alt="">` : PLACEHOLDER;
  const deal = bestDeal(g);
  const stores = g.listings.map(l => { const r = RET[l.retailer] || {l:l.retailer, c:'var(--ink-3)'}, s = ST[l.status];
    return `<a class="store" href="${l.url}" target="_blank" rel="noopener" style="--c:${r.c}"><span class="id"></span><span class="r">${r.l}<small>${l.checked ? '{{checked_prefix}}' + ago(l.checked) + '{{checked_suffix}}' : '{{not_checked}}'}</small></span><span class="num-wrap"><span class="num">${l.price ? money(l.price) : '—'}</span>${dealBadge(l, m)}</span><span class="st ${l.status}">${s.i}${s.l}</span>${ICO.go}</a>`; }).join('');
  const sig = [
    rank ? `<span>${FLAME}<b>#${rank}</b> {{sig_hottest_of}} ${live().length}</span>` : '',
    g.buzz ? `<span>${FLAME}<b>${g.buzz}</b> {{sig_mentions}}</span>` : '',
    g.last_in_stock ? `<span>${ST.unknown.i}{{sig_last_pre}} <b>${ago(g.last_in_stock)}</b> {{sig_last_post}}</span>` : `<span>${ST.unknown.i}{{sig_never}}</span>`,
  ].join('');
  $('#sheetBody').innerHTML = `<div class="meta">${gameTag(g.game)}${g.in_stock ? `<span class="tag" style="--gc:#5fd65f">${ST.in.i}{{sheet_in_stock}}</span>` : ''}${g.retired ? `<span class="micro">${g.retired}</span>` : ''}</div>
    <h2 class="sheet-title" id="sheetTitle">${g.name}</h2>
    ${m && m.name && m.name !== g.name ? `<div class="matched">{{sheet_match}} <a href="${m.url}" target="_blank" rel="noopener">${m.name}</a></div>` : ''}
    ${meter(g, true)}
    ${historyBlock(g)}
    ${deal ? `<div class="verdict ${deal.cls}">${VERDICT_ICON[deal.cls]}<span>${deal.text}</span></div>` : ''}
    ${evBlock(g)}
    <div class="micro sheet-sec">{{sheet_where}}</div>
    <div class="stores">${stores}</div>
    <div class="signals">${sig}</div>`;
  if (!SHEET.open) SHEET.showModal();
  $('#sheetCard').scrollTop = 0;
  history.replaceState(null, '', '#' + encodeURIComponent(g.key));
}
function openKey(k){ const g = D.groups.find(x => x.key === k); if (g) openSheet(g); }
const closeSheet = () => { if (SHEET.open) SHEET.close(); };
SHEET.addEventListener('close', () => { if (location.hash) history.replaceState(null, '', location.pathname + location.search); });
SHEET.addEventListener('click', e => { if (e.target === SHEET) closeSheet(); });
$('#sheetX').onclick = closeSheet;
// Selecting/copying the product name kept getting swallowed as a row-open click. The name now
// copies to the clipboard instead of opening the sheet; the rest of the row still opens it
// (David, 2026-09-07).
let toastTimer;
function showToast(msg){
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  requestAnimationFrame(() => t.classList.add('show'));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.classList.remove('show'); setTimeout(() => { t.hidden = true; }, TOAST_FADE_MS); }, TOAST_SHOW_MS);
}
['#list', '#retiredList'].forEach(s => $(s).addEventListener('click', e => {
  if (e.target.closest('a')) return;
  const nameEl = e.target.closest('.name');
  if (nameEl) {
    const text = nameEl.textContent.trim();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => showToast('{{toast_copied}}')).catch(() => showToast('{{toast_failed}}'));
    } else showToast('{{toast_failed}}');
    return;
  }
  const r = e.target.closest('.row'); if (r) openKey(r.dataset.key);
}));
const fromHash = () => { if (location.hash.length > 1) openKey(decodeURIComponent(location.hash.slice(1))); };
addEventListener('hashchange', fromHash);
$('#gen').textContent = D.generated_label;
if (D.discord_invite) { const j = $('#join'); j.href = D.discord_invite; j.hidden = false; }
$('#poll').textContent = D.last_poll ? '{{poll_pre}}' + ago(D.last_poll) + '{{poll_post}}' : '{{poll_none}}';
$('#feeds').textContent = D.feeds.join(', ');
// Coming up: release calendar from config `releases:`. The game filter (Pokemon/One Piece/
// Riftbound) applies here too — "only show me Riftbound" should mean the calendar as well as the
// list. Retailer/type/in-stock filters don't: those describe live listings, and an unreleased
// product doesn't have a retailer or type yet, so they'd have nothing to filter against.
const ALL_RELEASES = D.releases || [];
function calCollapsed(){ try { return localStorage.getItem('tcgwatch:calCollapsed') === '1'; } catch(e) { return false; } }
function setCalCollapsed(v){
  $('#calWrap').classList.toggle('collapsed', v);
  try { localStorage.setItem('tcgwatch:calCollapsed', v ? '1' : '0'); } catch(e) {}
}
function drawCal(){
  if (!ALL_RELEASES.length) return;
  $('#calWrap').hidden = false;
  $('#calWrap').classList.toggle('collapsed', calCollapsed());
  const R = ALL_RELEASES.filter(r => !F.game || r.game === F.game);
  const item = r => { const d = r.days, cls = d < 0 ? 'now' : d <= CAL_SOON_DAYS ? 'soon' : d <= CAL_NEAR_DAYS ? 'near' : '';
    const when = d < 0 ? '{{cal_out_now}}' : d === 0 ? '{{cal_today}}' : d === 1 ? '{{cal_tomorrow}}' : d <= CAL_DAYS_MAX ? `{{cal_in_days}}` : `{{cal_in_weeks}}`;
    const tag = r.source ? 'a' : 'div', href = r.source ? ` href="${r.source}" target="_blank" rel="noopener"` : '';
    const g = GAME[r.game] || {c:'currentColor', i:''};
    return `<${tag} class="rel ${cls}" style="--gc:${g.c}"${href} title="${r.game} — ${(r.note || '').replace(/"/g, '&quot;')}"><div class="rel-top"><div><div class="date-mon">${r.mon}</div><div class="date-day">${r.day}</div></div><div class="rel-icon">${g.i}</div></div><div class="rel-n">${r.name}</div><div class="rel-when">${when}</div></${tag}>`; };
  const cal = $('#cal');
  cal.scrollLeft = 0;
  cal.innerHTML = R.length ? R.map(item).join('') : `<div class="cal-empty">{{cal_empty}}</div>`;
}
$('#calToggle').onclick = () => setCalCollapsed(!$('#calWrap').classList.contains('collapsed'));
(function calSetup(){
  const cal = $('#cal');
  // Mouse users: vertical wheel scrolls the strip sideways. Each tick nudges a target rather than
  // jumping scrollLeft directly, then a per-frame lerp glides toward it — fast at first, easing
  // out as it approaches (David: wheel scroll "too fast", wanted accel/decel, 2026-09-07).
  // CSS scroll-snap fights small per-frame scrollLeft writes (each one can get pulled back
  // toward the nearest snap point), which stalled the ease well short of its target — the same
  // reason the drag path below already turns snap off for its duration; the wheel-ease needs the
  // same treatment (David: wheel scroll "too fast", wanted accel/decel, 2026-09-07).
  let wheelTarget = null;
  (function easeWheel(){
    if (wheelTarget !== null) {
      const d = wheelTarget - cal.scrollLeft;
      if (Math.abs(d) < WHEEL_DONE_PX) { cal.scrollLeft = wheelTarget; wheelTarget = null; cal.classList.remove('drag'); }
      else cal.scrollLeft += d * WHEEL_EASE;
    }
    requestAnimationFrame(easeWheel);
  })();
  cal.addEventListener('wheel', e => {
    if (Math.abs(e.deltaY) <= Math.abs(e.deltaX) || cal.scrollWidth <= cal.clientWidth) return;
    e.preventDefault();
    const max = cal.scrollWidth - cal.clientWidth;
    cal.classList.add('drag');
    wheelTarget = Math.max(0, Math.min(max, (wheelTarget ?? cal.scrollLeft) + e.deltaY));
  }, {passive:false});
  let drag = null, moved = 0, tapCard = null;
  // setPointerCapture (needed so a mouse can click-drag this like the reel; touch already scrolls
  // natively) retargets the click to #cal, so the card's own <a> never navigates. Open the tapped
  // card from the click handler itself: window.open from pointerup counted as a weaker user
  // activation and popup blockers ate it, which read as "clicking does nothing" (2026-09-07).
  cal.addEventListener('pointerdown', e => { if (e.pointerType !== 'mouse') return; tapCard = e.target.closest('.rel'); wheelTarget = null;
    drag = {x:e.clientX, left:cal.scrollLeft}; moved = 0; cal.setPointerCapture(e.pointerId); cal.classList.add('drag'); });
  cal.addEventListener('pointermove', e => { if (!drag) return; const dx = e.clientX - drag.x; moved = Math.max(moved, Math.abs(dx)); cal.scrollLeft = drag.left - dx; });
  const end = () => { if (!drag) return; drag = null; cal.classList.remove('drag'); };
  cal.addEventListener('pointerup', end); cal.addEventListener('pointercancel', end);
  cal.addEventListener('click', e => {
    const card = tapCard, dragged = moved > TAP_SLOP_PX; tapCard = null; moved = 0;
    if (dragged) { e.preventDefault(); e.stopPropagation(); return; }
    if (card && card.tagName === 'A' && !card.contains(e.target)) { e.preventDefault(); window.open(card.href, '_blank', 'noopener'); }
  }, true);
})();
drawCal();
// Game filter buttons get the same glyphs as the tags.
document.querySelectorAll('#game button[data-v]').forEach(b => { const g = GAME[b.dataset.v]; if (g) { b.style.setProperty('--gc', g.c); b.insertAdjacentHTML('afterbegin', g.i); } });
stats(); apply(); fromHash();
