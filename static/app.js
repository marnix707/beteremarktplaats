const $ = id => document.getElementById(id);
const LS = {
  get(k, d){ try{ const v = JSON.parse(localStorage.getItem(k)); return v ?? d }catch(e){ return d } },
  set(k, v){ try{ localStorage.setItem(k, JSON.stringify(v)) }catch(e){} },
};
const esc = t => String(t ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const safe = u => /^https?:\/\//i.test(u) ? u : '#';
const api = async (path, opts) => {
  const r = await fetch('/api/' + path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || 'Onbekende fout');
  return j;
};

const FIELDS = ['q','min','max','pc','km','city','days','sort','wheel','frameMin','frameMax'];
const CHECKS = ['useMp','useFb','noAds','smart','inTitle','private','needSize'];
const SOURCES = {marktplaats: ['useMp', 'Marktplaats'], facebook: ['useFb', 'Facebook']};
let exclude = LS.get('bm.exclude', ['gezocht']);
let require = LS.get('bm.require', []);
let data = {marktplaats: [], facebook: []};
let state = {marktplaats: '', facebook: ''};
let showHidden = false, searchId = 0, info = {channels: {}, suggest: []};

// ---------------------------------------------------------------- search

function params(){
  const p = new URLSearchParams();
  FIELDS.forEach(f => { if ($(f).value) p.set(f, $(f).value); });
  ['noAds','smart','inTitle','private','needSize'].forEach(c => p.set(c, $(c).checked ? '1' : '0'));
  p.set('exclude', exclude.join(','));
  p.set('require', require.join(','));
  return p;
}
const formState = () => Object.fromEntries([...FIELDS.map(f => [f, $(f).value]), ...CHECKS.map(c => [c, $(c).checked])]);

async function fetchSource(key, id, fresh){
  const qs = params(); if (fresh) qs.set('fresh', '1');
  if (fresh) { state[key] = 'busy'; data[key] = []; render(); }
  try{
    const j = await api('search/' + key + '?' + qs);
    if (id !== searchId) return;
    data[key] = j.items; state[key] = 'ok';
  }catch(err){
    if (id !== searchId) return;
    state[key] = {error: err.message === 'Failed to fetch' ? 'geen verbinding met de server' : err.message};
    if (/niet ingelogd/.test(err.message)) refreshStatus();
  }
  render();
}
function search(fresh = true){
  if (!$('q').value.trim()) return;
  const id = ++searchId;
  LS.set('bm.form2', formState());
  if (fresh) showHidden = false;
  for (const [key, [box]] of Object.entries(SOURCES)){
    if ($(box).checked) fetchSource(key, id, fresh);
    else { data[key] = []; state[key] = ''; }
  }
  render();
}

function merged(){
  const src = Object.entries(SOURCES).filter(([, [box]]) => $(box).checked).flatMap(([key]) => data[key]);
  const s = $('sort').value;
  const byPrice = (a, b, d) => (a.price == null) - (b.price == null) || d * ((a.price ?? 0) - (b.price ?? 0));
  if (s === 'price_asc') return src.sort((a, b) => byPrice(a, b, 1));
  if (s === 'price_desc') return src.sort((a, b) => byPrice(a, b, -1));
  if (s === 'distance') return src.sort((a, b) => (a.distanceKm == null) - (b.distanceKm == null) || (a.distanceKm ?? 0) - (b.distanceKm ?? 0) || a.rank - b.rank);
  return src.sort((a, b) => a.rank - b.rank || (a.source < b.source ? -1 : 1)); // alternate, in each site's own order
}

const specLine = it => [(it.specs?.wheel || []).map(w => String(w).replace('.', ',') + '\u2033').join('/'),
  (it.specs?.frame || []).length ? 'frame ' + it.specs.frame.join('/') + ' cm' : ''].filter(Boolean).join(' · ');

function render(){
  const list = merged();
  const visible = list.filter(it => !it.why.length);
  const hidden = list.length - visible.length;
  const shown = showHidden ? list : visible;

  const st = [];
  for (const [key, [box, name]] of Object.entries(SOURCES)){
    if (!$(box).checked) continue;
    const v = state[key];
    if (v === 'busy') st.push(`<span class="st">${name}: bezig…</span>`);
    else if (v && v.error) st.push(`<span class="st err">${name}: ${esc(v.error.replace(/^(Facebook|Marktplaats):\s*/, ''))}</span>`);
    else if (v === 'ok') st.push(`<span class="st">${name}: <b>${data[key].length}</b></span>`);
  }
  if (list.length) st.push(`<span class="st"><b>${visible.length}</b> getoond · <b>${hidden}</b> weggefilterd</span>`);
  if (hidden) st.push(`<button class="linkbtn" id="toggleHidden">${showHidden ? 'Verberg weggefilterde' : 'Toon weggefilterde'}</button>`);
  $('status').innerHTML = st.join('');
  const th = $('toggleHidden'); if (th) th.onclick = () => { showHidden = !showHidden; render(); };

  if (!shown.length){
    const busy = Object.values(state).includes('busy');
    $('results').innerHTML = `<div class="empty">${busy ? 'Even zoeken…' : list.length ? 'Alles is weggefilterd. Kies "Toon weggefilterde" om te zien waarom.' : 'Niets gevonden.'}</div>`;
    return;
  }
  $('results').innerHTML = shown.map(it => {
    const cls = it.source === 'marktplaats' ? 'mp' : 'fb';
    const meta = [it.city, it.distanceKm != null ? it.distanceKm + ' km' : '', it.posted].filter(Boolean).join(' · ');
    const isHidden = it.why.includes('door jou verborgen');
    return `<a class="card ${cls}${it.why.length ? ' faded' : ''}" href="${esc(safe(it.url))}" target="_blank" rel="noopener noreferrer">
      <div class="ph">${it.image ? `<img src="${esc(safe(it.image))}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : ''}<span class="src">${cls === 'mp' ? 'Marktplaats' : 'Facebook'}</span></div>
      <div class="body">
        <div class="price">${esc(it.priceLabel)}</div>
        ${it.bid ? `<div class="bid" data-url="${esc(safe(it.url))}">Biedingen laden…</div>` : ''}
        <div class="title">${esc(it.title)}</div>
        ${specLine(it) ? `<div class="specs">${esc(specLine(it))}</div>` : ''}
        ${meta ? `<div class="meta">${esc(meta)}</div>` : ''}
        ${it.why.length ? `<span class="why">${esc(it.why.join(', '))}</span>` : ''}
      </div>
      <button class="nope" data-id="${esc(it.id)}" data-hidden="${isHidden ? 1 : 0}" title="Niet meer tonen">${isHidden ? 'Terugzetten' : 'Verberg'}</button>
    </a>`;
  }).join('');
  watchBids();
}

// Highest bid: not in the search results, so fetched per card, a few at a time
const bidSeen = new Map(), bidQueue = [];
let bidBusy = 0;
const euro = n => '€ ' + n.toLocaleString('nl-NL', {maximumFractionDigits: 0});
function showBid(el, b){
  if (!b) el.textContent = '';
  else if (!b.count) el.innerHTML = '<span class="nobid">Nog geen biedingen</span>';
  else el.innerHTML = `Hoogste bod <b>${euro(b.highest)}</b> <span class="nobid">(${b.count} ${b.count === 1 ? 'bod' : 'biedingen'})</span>`;
}
function pumpBids(){
  while (bidBusy < 3 && bidQueue.length){
    const el = bidQueue.shift(), url = el.dataset.url;
    bidBusy++;
    api('bids?url=' + encodeURIComponent(url)).then(b => bidSeen.set(url, b)).catch(() => bidSeen.set(url, null))
      .finally(() => { bidBusy--; showBid(el, bidSeen.get(url)); pumpBids(); });
  }
}
const bidObserver = new IntersectionObserver(entries => entries.forEach(en => {
  if (!en.isIntersecting) return;
  bidObserver.unobserve(en.target);
  if (bidSeen.has(en.target.dataset.url)) showBid(en.target, bidSeen.get(en.target.dataset.url));
  else { bidQueue.push(en.target); pumpBids(); }
}), {rootMargin: '300px'});
function watchBids(){
  bidQueue.length = 0;
  document.querySelectorAll('.bid').forEach(el => {
    if (bidSeen.has(el.dataset.url)) showBid(el, bidSeen.get(el.dataset.url));
    else bidObserver.observe(el);
  });
}

$('results').addEventListener('click', async e => {
  const b = e.target.closest('.nope'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  await api('hide/' + encodeURIComponent(b.dataset.id), {method: b.dataset.hidden === '1' ? 'DELETE' : 'PUT'});
  search(false);
});

$('form').addEventListener('submit', e => { e.preventDefault(); search(true); });
['noAds','smart','inTitle','private','needSize','wheel','frameMin','frameMax'].forEach(id => $(id).addEventListener('change', () => search(false)));
['useMp','useFb'].forEach(id => $(id).addEventListener('change', () => { LS.set('bm.form2', formState()); search(false); }));
$('sort').addEventListener('change', () => { LS.set('bm.form2', formState()); render(); });

// ---------------------------------------------------------------- words to hide

function renderEx(){
  $('exList').innerHTML = exclude.map(w => `<span class="chip">${esc(w)}<button type="button" data-w="${esc(w)}" aria-label="Verwijder ${esc(w)}">×</button></span>`).join('');
  $('exSug').innerHTML = info.suggest.filter(w => !exclude.includes(w)).slice(0, 8).map(w => `<button type="button" class="chip sug" data-add="${esc(w)}">+ ${esc(w)}</button>`).join('');
}
function renderReq(){
  $('reqList').innerHTML = require.map(w => `<span class="chip req">${esc(w)}<button type="button" data-rw="${esc(w)}" aria-label="Verwijder ${esc(w)}">×</button></span>`).join('');
}
function setReq(list){ require = list; LS.set('bm.require', require); renderReq(); search(false); }
$('rq').addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  const w = e.target.value.trim().toLowerCase(); e.target.value = '';
  if (w && !require.includes(w)) setReq([...require, w]);
});
$('reqWrap').addEventListener('click', e => {
  const d = e.target.closest('[data-rw]');
  if (d) setReq(require.filter(w => w !== d.dataset.rw));
});
function setEx(list){ exclude = list; LS.set('bm.exclude', exclude); renderEx(); search(false); }
$('ex').addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  const w = e.target.value.trim().toLowerCase(); e.target.value = '';
  if (w && !exclude.includes(w)) setEx([...exclude, w]);
});
$('exWrap').addEventListener('click', e => {
  const d = e.target.closest('[data-w]'), a = e.target.closest('[data-add]');
  if (d) setEx(exclude.filter(w => w !== d.dataset.w));
  if (a) setEx([...exclude, a.dataset.add]);
});

// ---------------------------------------------------------------- tabs

function showTab(name){
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.dataset.tab === name));
  $('search').hidden = name !== 'search';
  $('alarms').hidden = name !== 'alarms';
  if (name === 'alarms') loadAlarms();
}
document.querySelectorAll('.tab').forEach(t => t.onclick = () => showTab(t.dataset.tab));

// ---------------------------------------------------------------- alarms

const CH_NAMES = {browser: 'browser', ntfy: 'telefoon', email: 'e-mail'};
const ago = ts => {
  if (!ts) return 'nog niet gecontroleerd';
  const m = Math.round((Date.now() / 1000 - ts) / 60);
  return m < 1 ? 'zojuist gecontroleerd' : m < 60 ? m + ' min geleden gecontroleerd' : Math.round(m / 60) + ' uur geleden gecontroleerd';
};
function describe(p){
  const bits = [];
  if (p.max) bits.push('tot €' + p.max);
  if (p.min) bits.push('vanaf €' + p.min);
  if (p.pc && p.km) bits.push(p.km + ' km rond ' + p.pc);
  if (p.wheel) bits.push(String(p.wheel).replace('.', ',') + ' inch');
  if (p.frameMin || p.frameMax) bits.push('frame ' + (p.frameMin || '') + '–' + (p.frameMax || '') + ' cm');
  if ((p.require || []).length) bits.push('moet: ' + p.require.join(', '));
  bits.push((p.sources || []).map(s => s === 'marktplaats' ? 'Marktplaats' : 'Facebook').join(' + '));
  return bits.join(' · ');
}
async function loadAlarms(){
  let list = [];
  try{ list = await api('alarms'); }catch(e){}
  $('alarmCount').hidden = !list.length;
  $('alarmCount').textContent = list.length;
  if ($('alarms').hidden) return;
  $('alarmList').innerHTML = list.length ? list.map(a => `
    <div class="alarm${a.enabled ? '' : ' off'}" data-id="${a.id}">
      <div class="info"><b>${esc(a.name)}</b>
        <span class="muted">${esc(describe(a.params))}</span>
        <span class="muted">elke ${a.interval_min} min · via ${a.channels.map(c => CH_NAMES[c]).join(', ')} · ${ago(a.last_run)}${a.last_status ? ' · ' + esc(a.last_status) : ''}</span></div>
      <div class="btns">
        <button data-act="run">Nu controleren</button>
        <button data-act="test">Test</button>
        <button data-act="toggle">${a.enabled ? 'Pauzeer' : 'Hervat'}</button>
        <button data-act="delete">Verwijder</button>
      </div>
    </div>`).join('') : '<div class="empty">Nog geen alarmen. Zoek iets en kies "Maak hiervan een alarm".</div>';
  $('alarmList').dataset.enabled = JSON.stringify(Object.fromEntries(list.map(a => [a.id, a.enabled])));
}
$('alarmList').addEventListener('click', async e => {
  const b = e.target.closest('[data-act]'); if (!b) return;
  const row = b.closest('.alarm'), id = row.dataset.id, act = b.dataset.act;
  const enabled = JSON.parse($('alarmList').dataset.enabled)[id];
  b.disabled = true;
  try{
    if (act === 'delete' && confirm('Dit alarm verwijderen?')) await api('alarms/' + id, {method: 'DELETE'});
    if (act === 'toggle') await api(`alarms/${id}?enabled=${!enabled}`, {method: 'PATCH'});
    if (act === 'test'){
      const r = await api(`alarms/${id}/test`, {method: 'POST'});
      Object.entries(r).forEach(([c, err]) => toast(err ? `${CH_NAMES[c]}: ${err}` : `${CH_NAMES[c]}: verstuurd`));
    }
    if (act === 'run'){ b.textContent = 'Bezig…'; toast((await api(`alarms/${id}/run`, {method: 'POST'})).status); }
  }catch(err){ toast(err.message); }
  loadAlarms();
});

$('alarmBtn').onclick = () => {
  if (!$('q').value.trim()) return $('q').focus();
  const p = formState();
  $('alarmSummary').textContent = `"${p.q}" · ${describe({...p, sources: [p.useMp && 'marktplaats', p.useFb && 'facebook'].filter(Boolean)})}`;
  document.querySelectorAll('[name=ch]').forEach(c => {
    const off = info.channels[c.value] === false;
    c.disabled = off; if (off) c.checked = false;
    const note = document.querySelector(`[data-off=${c.value}]`);
    if (note) note.textContent = off ? '(niet ingesteld in .env)' : '';
  });
  $('alarmDlg').showModal();
};
$('alarmForm').addEventListener('submit', async e => {
  if (e.submitter?.value !== 'ok') return;
  const p = formState();
  const body = {
    params: {...p, exclude, require, sources: [p.useMp && 'marktplaats', p.useFb && 'facebook'].filter(Boolean)},
    channels: [...document.querySelectorAll('[name=ch]:checked')].map(c => c.value),
    interval_min: +$('interval').value,
  };
  try{
    await api('alarms', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    toast('Alarm gemaakt. Ik meld alleen wat nieuw is.');
    loadAlarms();
    if (body.channels.includes('browser')) enableNotifications();
  }catch(err){ toast(err.message); }
});

// ---------------------------------------------------------------- notifications in this browser

let lastNote = null, audio = null;
function beep(){
  try{
    audio = audio || new AudioContext();
    [0, .18].forEach((t, i) => {
      const o = audio.createOscillator(), g = audio.createGain();
      o.frequency.value = i ? 1175 : 880; o.connect(g); g.connect(audio.destination);
      g.gain.setValueAtTime(.2, audio.currentTime + t); g.gain.exponentialRampToValueAtTime(.001, audio.currentTime + t + .16);
      o.start(audio.currentTime + t); o.stop(audio.currentTime + t + .17);
    });
  }catch(e){}
}
function toast(text, n){
  const el = document.createElement(n ? 'a' : 'div');
  el.className = 'toast';
  if (n){ el.href = safe(n.url); el.target = '_blank'; el.rel = 'noopener noreferrer'; }
  el.innerHTML = `${n && n.image ? `<img src="${esc(safe(n.image))}" alt="" referrerpolicy="no-referrer">` : ''}<div>${esc(text)}${n ? `<small>${esc(n.body)}</small>` : ''}</div>`;
  $('toasts').append(el);
  setTimeout(() => el.remove(), n ? 15000 : 5000);
}
async function pollNotifications(){
  try{
    const j = await api('notifications' + (lastNote === null ? '' : '?after=' + lastNote));
    const first = lastNote === null;
    lastNote = j.last;
    if (!first && j.items.length) beep();
    j.items.forEach(n => {
      toast(n.title, n);
      if ('Notification' in window && Notification.permission === 'granted'){
        const x = new Notification(n.title, {body: n.body, icon: n.image || undefined});
        x.onclick = () => { window.open(safe(n.url), '_blank', 'noopener'); x.close(); };
      }
    });
    if (j.items.length) loadAlarms();
  }catch(e){}
}
async function enableNotifications(){
  audio = audio || new AudioContext();
  if ('Notification' in window && Notification.permission === 'default') await Notification.requestPermission();
  updateNotifyBtn();
}
function updateNotifyBtn(){
  $('notifyBtn').hidden = !('Notification' in window) || Notification.permission !== 'default';
}
$('notifyBtn').onclick = enableNotifications;
document.addEventListener('click', () => { try{ audio = audio || new AudioContext(); audio.resume(); }catch(e){} }, {once: true});

// ---------------------------------------------------------------- Facebook login

function renderBanner(){
  const b = $('fbBanner');
  if (info.loginRunning){
    b.hidden = false; b.className = 'banner info';
    b.innerHTML = 'Log in bij Facebook in het nieuwe tabblad en klik hier daarna op <button class="linkbtn" id="fbDone">Klaar</button>';
    $('fbDone').onclick = async () => { b.textContent = 'Controleren…'; await api('facebook/login', {method: 'DELETE'}); await refreshStatus(true); };
  }else if (info.facebook === false){
    b.hidden = false; b.className = 'banner';
    b.innerHTML = 'Facebook: niet ingelogd, alleen Marktplaats werkt. <button class="linkbtn" id="fbLogin">Inloggen bij Facebook</button>';
    $('fbLogin').onclick = async () => {
      const w = window.open('', '_blank');  // opened right away so the popup blocker allows it
      try{
        await api('facebook/login', {method: 'POST'});
        w.location = `http://${location.hostname}:6080/vnc.html?autoconnect=1&resize=scale`;
      }catch(err){ w.close(); toast(err.message); }
      refreshStatus();
    };
  }else b.hidden = true;
}
async function refreshStatus(check){
  try{
    info = await api('status');
    if (check || info.facebook === null) info.facebook = (await api('facebook/check', {method: 'POST'})).facebook;
  }catch(e){}
  renderBanner(); renderEx();
}

// ---------------------------------------------------------------- start

// ---------------------------------------------------------------- default search + postcode

let defaultSearch = null;
function applyForm(s){
  FIELDS.forEach(f => { $(f).value = s[f] ?? ''; });
  CHECKS.forEach(c => { if (s[c] != null) $(c).checked = s[c]; });
  if (s.exclude) setExQuiet(s.exclude);
  require = s.require || []; LS.set('bm.require', require); renderReq();
  $('city').dataset.auto = '0';
}
function setExQuiet(list){ exclude = list; LS.set('bm.exclude', exclude); renderEx(); }
function renderDefault(){
  const b = $('defaultLoad');
  b.hidden = !defaultSearch;
  if (defaultSearch) b.textContent = `↺ Standaard: ${defaultSearch.q}`;
}
$('defaultSave').onclick = async () => {
  if (!$('q').value.trim()) return $('q').focus();
  const s = {...formState(), exclude, require};
  try{
    await api('default', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(s)});
    defaultSearch = s; renderDefault(); toast('Opgeslagen als standaard zoekopdracht.');
  }catch(err){ toast(err.message); }
};
$('defaultLoad').onclick = () => { applyForm(defaultSearch); search(true); };

// Postcode fills in the Facebook city, unless you typed a city yourself
async function fillCity(){
  const pc = $('pc').value.replace(/\s/g, '');
  if (!/^\d{4}([A-Za-z]{2})?$/.test(pc)) return;
  const city = $('city');
  if (city.value && city.dataset.auto !== '1') return;
  try{
    const j = await api('postcode/' + pc);
    if (j.slug && $('pc').value.replace(/\s/g, '') === pc){ city.value = j.slug; city.dataset.auto = '1'; LS.set('bm.form2', formState()); }
  }catch(e){}
}
$('pc').addEventListener('input', fillCity);
$('city').addEventListener('input', () => { $('city').dataset.auto = '0'; });

const saved = LS.get('bm.form2', {});
FIELDS.forEach(f => { if (saved[f] != null) $(f).value = saved[f]; });
CHECKS.forEach(c => { if (saved[c] != null) $(c).checked = saved[c]; });
try{ $('filters').open = LS.get('bm.filters', false); }catch(e){}
$('filters').addEventListener('toggle', () => LS.set('bm.filters', $('filters').open));
renderEx(); renderReq(); updateNotifyBtn();
refreshStatus();
// The default search wins when the page opens; "↺ Standaard" gets back to it later
api('default').then(d => {
  defaultSearch = d; renderDefault();
  if (d) applyForm(d);
}).catch(() => {}).finally(() => { if ($('q').value) search(true); });
loadAlarms(); pollNotifications();
setInterval(pollNotifications, 30000);
setInterval(loadAlarms, 60000);
