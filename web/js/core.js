/* 公共部分：接口调用、格式化、弹窗、下拉选择、路由与页面框架 */
const App = window.App = {
  cid: null,
  meta: null,
  pages: {},
};

/* ================= 工具函数 ================= */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function store(key, val) {
  try {
    if (val === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, val);
  } catch (e) { return null; }
}

/** 分 → "1,234.56"；zero 为 true 时 0 显示为空 */
function fmt(c, blankZero = true) {
  if (c === null || c === undefined || c === '') return '';
  c = Number(c);
  if (blankZero && c === 0) return '';
  const neg = c < 0;
  const abs = Math.abs(c);
  const yuan = Math.floor(abs / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const fen = String(abs % 100).padStart(2, '0');
  return (neg ? '-' : '') + yuan + '.' + fen;
}
function fmtN(c) { return fmt(c, false); }
function moneyCell(c, blankZero = true) {
  return `<td class="n${c < 0 ? ' neg' : ''}">${fmt(c, blankZero)}</td>`;
}

/** 输入的金额文字 → 分；空返回 0；格式错误返回 null */
function parseAmt(s) {
  s = String(s ?? '').replace(/[,，\s¥]/g, '');
  if (s === '') return 0;
  if (!/^-?\d+(\.\d{0,2})?$/.test(s)) {
    if (/^-?\d*\.\d+$/.test(s) && s.split('.')[1].length <= 2) s = s.replace(/^(-?)\./, '$10.');
    else return null;
  }
  const neg = s.startsWith('-');
  if (neg) s = s.slice(1);
  const [a, b = ''] = s.split('.');
  const v = parseInt(a || '0', 10) * 100 + parseInt((b + '00').slice(0, 2), 10);
  return neg ? -v : v;
}
function amtInput(c) { return c ? (c / 100).toFixed(2) : ''; }

function plabel(p) { return `${Math.floor(p / 100)}年${p % 100}月`; }
function nextP(p) { return p % 100 === 12 ? (Math.floor(p / 100) + 1) * 100 + 1 : p + 1; }
function prevP(p) { return p % 100 === 1 ? (Math.floor(p / 100) - 1) * 100 + 12 : p - 1; }
function lastDay(p) {
  const y = Math.floor(p / 100), m = p % 100;
  const d = new Date(y, m, 0).getDate();
  return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}
function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** 金额大写 */
function upperAmount(c) {
  if (!c) return '零元整';
  const neg = c < 0;
  c = Math.abs(c);
  const digits = '零壹贰叁肆伍陆柒捌玖';
  const units = ['', '拾', '佰', '仟'];
  const big = ['', '万', '亿', '兆'];
  let yuan = Math.floor(c / 100);
  const jiao = Math.floor(c / 10) % 10, fen = c % 10;
  let s = '';
  if (yuan > 0) {
    let groupIdx = 0, needZero = false;
    while (yuan > 0) {
      const g = yuan % 10000;
      let gs = '';
      let zero = false;
      for (let i = 0; i < 4; i++) {
        const d = Math.floor(g / Math.pow(10, i)) % 10;
        if (d === 0) { if (gs) zero = true; }
        else { gs = digits[d] + units[i] + (zero ? '零' : '') + gs; zero = false; }
      }
      if (gs) s = gs + big[groupIdx] + (needZero ? '零' : '') + s;
      needZero = g > 0 && g < 1000;
      if (g === 0 && s) needZero = true;
      yuan = Math.floor(yuan / 10000);
      groupIdx++;
    }
    s = s.replace(/零+/g, '零').replace(/零$/, '') + '元';
  }
  if (jiao === 0 && fen === 0) s += '整';
  else {
    if (jiao) s += digits[jiao] + '角'; else if (s) s += '零';
    if (fen) s += digits[fen] + '分';
  }
  return (neg ? '负' : '') + s;
}

/* ================= 接口 ================= */
async function fileToB64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}
// 这些 POST 只是查询或下载，不算“改了数据”
const READ_ONLY_POSTS = new Set(['/api/export/xlsx', '/api/update/check', '/api/data/scan', '/api/data/inspect', '/api/heartbeat',
  '/api/lock/lock', '/api/lock/unlock', '/api/voucher/print', '/api/vehicle/purchase_draft', '/api/data/open_folder',
  '/api/update/start', '/api/update/online/start', '/api/update/rollback', '/api/update/settings', '/api/restart', '/api/backup/now', '/api/lock/set', '/api/lock/options',
  '/api/lock/disable', '/api/lock/recover', '/api/shutdown']);
async function api(path, body, retried) {
  const opt = { method: body === undefined ? 'GET' : 'POST', headers: {} };
  if (App.cid) opt.headers['X-Company'] = App.cid;
  const tok = lockToken();
  if (tok) opt.headers['X-Unlock'] = tok;
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  let res;
  try { res = await fetch(path, opt); }
  catch (e) { throw new Error('无法连接到软件后台。请确认启动窗口没有被关闭。'); }
  const ct = res.headers.get('Content-Type') || '';
  if (!ct.includes('application/json')) {
    if (!res.ok) throw new Error('请求失败：' + res.status);
    return res;
  }
  const data = await res.json();
  if (res.status === 401 && data.locked) {
    if (!App.lock) App.lock = { enabled: true };
    App.lock.enabled = true;
    if (!retried) { await showLockScreen(); return api(path, body, true); }
    const err = new Error(data.error); err.locked = true; throw err;
  }
  if (!res.ok) throw new Error(data.error || '请求失败');
  if (body !== undefined && !READ_ONLY_POSTS.has(path.split('?')[0])) App.dataVer++;
  return data;
}
function qs(obj) {
  return Object.entries(obj).filter(([k, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&');
}
/* 页面上的下载链接（如“下载账套数据文件”）：设了启动密码时要带上通行证 */
document.addEventListener('click', e => {
  const a = e.target.closest && e.target.closest('a[href^="/api/"]');
  if (!a || a.dataset.signed) return;
  const tok = lockToken();
  if (!tok) return;
  e.preventDefault();
  const href = a.getAttribute('href');
  const b = document.createElement('a');
  b.href = href + (href.includes('?') ? '&' : '?') + 'unlock=' + encodeURIComponent(tok);
  b.dataset.signed = '1';
  b.download = '';
  document.body.appendChild(b); b.click(); setTimeout(() => b.remove(), 1000);
});

async function apiFile(path, body, fallbackName) {
  const res = await api(path, body);
  const blob = await res.blob();
  let name = fallbackName || '下载';
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename\*=UTF-8''([^;]+)/);
  if (m) name = decodeURIComponent(m[1]);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
/** 导出 Excel：columns [{name, type:'text'|'money', width}]，rows 二维数组 */
async function exportXlsx(title, columns, rows, subtitle = '') {
  try {
    await apiFile('/api/export/xlsx', { title, subtitle, columns, rows, filename: `${App.meta?.company_name || ''}-${title}` });
  } catch (e) { toast(e.message, 'err'); }
}
async function refreshMeta() {
  App.meta = await api('/api/meta');
  App.acct = {};
  App.meta.accounts.forEach(a => App.acct[a.code] = a);
  App.aux = {};
  App.meta.aux_items.forEach(a => App.aux[a.id] = a);
  App.cf = {};
  App.meta.cf_items.forEach(c => App.cf[c.code] = c);
  renderChrome();
}

/* ================= 提示与弹窗 ================= */
function toast(msg, type = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  $('#toast-box').appendChild(el);
  setTimeout(() => el.remove(), type === 'err' || type === 'warn' ? 6000 : 2600);
}
function modal({ title, body, buttons = [], width }) {
  const mask = document.createElement('div');
  mask.className = 'modal-mask';
  mask.innerHTML = `<div class="modal" style="${width ? 'width:' + width + 'px' : ''}">
    <div class="modal-head"><span>${esc(title)}</span><button class="x" title="关闭">✕</button></div>
    <div class="modal-body"></div><div class="modal-foot"></div></div>`;
  const bodyEl = $('.modal-body', mask);
  if (typeof body === 'string') bodyEl.innerHTML = body; else if (body) bodyEl.appendChild(body);
  const close = () => { mask.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = e => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  $('.x', mask).onclick = close;
  const foot = $('.modal-foot', mask);
  buttons.forEach(b => {
    const btn = document.createElement('button');
    btn.className = 'btn ' + (b.cls || '');
    btn.textContent = b.text;
    btn.onclick = async () => {
      if (!b.onClick) return close();
      btn.disabled = true;
      try {
        const r = await b.onClick(bodyEl);
        if (r !== false) close();
      } catch (e) { toast(e.message, 'err'); }
      finally { btn.disabled = false; }
    };
    foot.appendChild(btn);
  });
  if (!buttons.length) foot.remove();
  document.body.appendChild(mask);
  const first = $('input, select, textarea', bodyEl);
  if (first) setTimeout(() => first.focus(), 30);
  return { el: bodyEl, close };
}
function confirmBox(msg, okText = '确定', danger = false) {
  return new Promise(resolve => {
    let done = false;
    const m = modal({
      title: '请确认', body: `<div style="line-height:1.8;white-space:pre-wrap">${esc(msg)}</div>`,
      buttons: [
        { text: '取消', onClick: () => { done = true; resolve(false); } },
        { text: okText, cls: danger ? 'danger' : 'primary', onClick: () => { done = true; resolve(true); } },
      ],
    });
    const obs = new MutationObserver(() => { if (!document.body.contains(m.el)) { obs.disconnect(); if (!done) resolve(false); } });
    obs.observe(document.body, { childList: true });
  });
}
function formData(root) {
  const o = {};
  $$('[name]', root).forEach(el => {
    if (el.type === 'checkbox') o[el.name] = el.checked;
    else o[el.name] = el.value;
  });
  return o;
}

/* ================= 下拉选择（可输入编码或名称搜索） ================= */
let pickerList = null;
let pointerInPicker = false;
function closePicker() {
  if (pickerList) { pickerList.remove(); pickerList = null; }
  pointerInPicker = false;
}
// 页面滚动时关闭下拉框（下拉框是固定定位，不跟随页面滚动）；但下拉框自己滚动时不要关闭
document.addEventListener('scroll', e => {
  if (pickerList && (e.target === pickerList || pickerList.contains(e.target))) return;
  closePicker();
}, true);
window.addEventListener('resize', closePicker);
const PICKER_MAX = 3000;

/**
 * input: 文本框；opts.source(): [{value, code, label, hint}]
 * opts.onPick(item|null)；选中值保存在 input.dataset.value
 */
function attachPicker(input, opts) {
  let items = [], idx = 0, navigated = false, total = 0;
  const isOpen = () => pickerList && pickerList.__owner === input;
  const scrollToOn = () => {
    if (!pickerList) return;
    const on = $('.on', pickerList);
    if (!on) return;
    const top = on.offsetTop, bottom = top + on.offsetHeight;
    if (top < pickerList.scrollTop) pickerList.scrollTop = top;
    else if (bottom > pickerList.scrollTop + pickerList.clientHeight) pickerList.scrollTop = bottom - pickerList.clientHeight;
  };
  const show = () => {
    navigated = false;
    const q = input.value.trim().toLowerCase();
    const all = opts.source();
    let list;
    if (!q || (input.dataset.label && input.value === input.dataset.label)) list = all;
    else {
      const exact = all.filter(i => (i.code || '').toLowerCase().startsWith(q));
      const fuzzy = all.filter(i => !exact.includes(i) && (i.label + ' ' + (i.hint || '') + ' ' + (i.code || '')).toLowerCase().includes(q));
      list = exact.concat(fuzzy);
    }
    total = list.length;
    items = list.slice(0, PICKER_MAX);
    idx = Math.max(0, items.findIndex(i => String(i.value) === input.dataset.value));
    closePicker();
    pickerList = document.createElement('div');
    pickerList.__owner = input;
    pickerList.className = 'picker-list';
    pickerList.innerHTML = (items.length ? items.map((it, i) =>
      `<div data-i="${i}" class="${i === idx ? 'on' : ''}"><span class="code">${esc(it.code || '')}</span><span>${esc(it.label)}</span>${it.hint ? `<span class="hint">${esc(it.hint)}</span>` : ''}</div>`).join('')
      : '<div class="none">没有匹配的项目</div>')
      + (total > items.length ? `<div class="none">还有 ${total - items.length} 项未显示，请输入编码或名称缩小范围</div>` : '');
    const r = input.getBoundingClientRect();
    pickerList.style.left = Math.min(r.left, window.innerWidth - 300) + 'px';
    pickerList.style.minWidth = Math.max(r.width, 280) + 'px';
    const below = window.innerHeight - r.bottom;
    if (below < 260 && r.top > below) {
      pickerList.style.bottom = (window.innerHeight - r.top + 2) + 'px';
      pickerList.style.maxHeight = Math.min(320, r.top - 10) + 'px';
    } else {
      pickerList.style.top = (r.bottom + 2) + 'px';
      pickerList.style.maxHeight = Math.min(320, below - 10) + 'px';
    }
    // 按下鼠标时阻止文本框失去焦点；松开时才选中，这样拖动滚动条、滚轮都不会误关闭或误选
    pickerList.addEventListener('mousedown', e => e.preventDefault());
    pickerList.addEventListener('click', e => {
      const d = e.target.closest('[data-i]');
      if (d) pick(items[+d.dataset.i]);
    });
    pickerList.addEventListener('mouseenter', () => pointerInPicker = true);
    pickerList.addEventListener('mouseleave', () => pointerInPicker = false);
    document.body.appendChild(pickerList);
    scrollToOn();
  };
  const highlight = () => {
    if (!pickerList) return;
    $$('[data-i]', pickerList).forEach((d, i) => d.classList.toggle('on', i === idx));
    scrollToOn();
  };
  const pick = it => {
    setPickerValue(input, it);
    closePicker();
    opts.onPick && opts.onPick(it);
  };
  input.setAttribute('autocomplete', 'off');
  input.addEventListener('focus', () => { if (!isOpen()) { input.select(); show(); } });
  // 已经有焦点时再点一下文本框，也要能重新打开下拉框
  input.addEventListener('mousedown', () => { if (document.activeElement === input && !isOpen()) setTimeout(show, 0); });
  input.addEventListener('input', () => { input.dataset.value = ''; show(); });
  input.addEventListener('blur', () => {
    // 某些系统点击滚动条会让文本框失去焦点：鼠标还在下拉框上时，把焦点还给文本框，不关闭
    if (isOpen() && pointerInPicker) { setTimeout(() => input.focus({ preventScroll: true }), 0); return; }
    if (isOpen()) closePicker();
    // 离开时：文字被清空就清除；文字没变就保留；否则尝试按编码精确匹配
    if (!input.value.trim()) { if (input.dataset.value) pick(null); return; }
    if (input.dataset.value && input.value === input.dataset.label) return;
    const all = opts.source();
    const q = input.value.trim().toLowerCase();
    const hit = all.find(i => (i.code || '').toLowerCase() === q) || (items.length === 1 ? items[0] : null);
    if (hit) pick(hit); else { setPickerValue(input, null); opts.onPick && opts.onPick(null); }
  });
  input.addEventListener('keydown', e => {
    if (!isOpen()) { if (e.key === 'ArrowDown') { show(); e.preventDefault(); } return; }
    if (e.key === 'ArrowDown') { idx = Math.min(items.length - 1, idx + 1); navigated = true; highlight(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { idx = Math.max(0, idx - 1); navigated = true; highlight(); e.preventDefault(); }
    else if (e.key === 'PageDown') { idx = Math.min(items.length - 1, idx + 10); navigated = true; highlight(); e.preventDefault(); }
    else if (e.key === 'PageUp') { idx = Math.max(0, idx - 10); navigated = true; highlight(); e.preventDefault(); }
    else if (e.key === 'Enter' || e.key === 'Tab') {
      const typed = input.value.trim() && !(input.dataset.value && input.value === input.dataset.label);
      if (items[idx] && (typed || navigated)) { pick(items[idx]); }
      else closePicker();
    } else if (e.key === 'Escape') closePicker();
  });
}
function setPickerValue(input, it) {
  input.dataset.value = it ? it.value : '';
  input.dataset.label = it ? ((it.code ? it.code + ' ' : '') + it.label) : '';
  input.value = input.dataset.label;
}

/* 科目与辅助项的数据源 */
function acctItems(leafOnly = true) {
  return App.meta.accounts.filter(a => (!leafOnly || a.is_leaf) && a.enabled)
    .map(a => ({ value: a.code, code: a.code, label: a.full_name, hint: a.aux_type ? '辅助：' + a.aux_type : '' }));
}
function acctItem(code) {
  const a = App.acct[code];
  return a ? { value: a.code, code: a.code, label: a.full_name } : null;
}
function auxItems(type) {
  return App.meta.aux_items.filter(a => a.type === type && a.enabled)
    .map(a => ({ value: a.id, code: a.code, label: a.name }));
}
function auxItem(id) {
  const a = App.aux[id];
  return a ? { value: a.id, code: a.code, label: a.name } : null;
}
function auxText(id) { const a = App.aux[id]; return a ? `${a.code} ${a.name}` : ''; }
function acctText(code) { const a = App.acct[code]; return a ? `${a.code} ${a.full_name}` : code; }

/* ================= 期间选择控件 ================= */
function yearList() {
  const ys = (App.meta.years || []).slice();
  ys.push(Math.floor(App.meta.start_period / 100), Math.floor(App.meta.current_period / 100));
  const lo = Math.min(...ys), hi = Math.max(...ys);
  const out = [];
  for (let y = lo; y <= hi; y++) out.push(y);
  return out;
}
function yearOptions(sel) {
  return yearList().map(y => `<option value="${y}" ${y === sel ? 'selected' : ''}>${y}年</option>`).join('');
}
function monthOptions(sel) {
  return Array.from({ length: 12 }, (_, i) => i + 1).map(m => `<option value="${m}" ${m === sel ? 'selected' : ''}>${m}月</option>`).join('');
}
/* 账簿、报表都按日期查询：起始日期 至 结束日期（可以是某一天，也可以跨年度） */
function isDate(s) { return /^\d{4}-\d{2}-\d{2}$/.test(String(s || '')); }
function rangeLabel(d1, d2) { return d1 === d2 ? d1 : `${d1} 至 ${d2}`; }
function startDate() { const sp = App.meta.start_period; return `${Math.floor(sp / 100)}-${String(sp % 100).padStart(2, '0')}-01`; }
function rangeControls(d1, d2) {
  return `<span class="range"><label>日期 <input type="date" name="d1" value="${esc(d1)}"></label>
    <label>至 <input type="date" name="d2" value="${esc(d2)}"></label></span>`;
}
function setRange(root, d1, d2) {
  const r = $('.range', root) || root;
  $('[name=d1]', r).value = d1; $('[name=d2]', r).value = d2;
}
function readRange(root) {
  const r = $('.range', root) || root;
  let a = $('[name=d1]', r).value, b = $('[name=d2]', r).value;
  if (!a && !b) throw new Error('请选择查询日期');
  a = a || b; b = b || a;
  if (a > b) throw new Error('起始日期不能晚于结束日期');
  return [a, b];
}
// 起止日期保持正序：改了起始日期导致晚于结束日期时，把结束日期调成一样；反之亦然
document.addEventListener('change', e => {
  const r = e.target.closest && e.target.closest('.range');
  if (!r || !['d1', 'd2'].includes(e.target.name)) return;
  const a = $('[name=d1]', r), b = $('[name=d2]', r);
  if (!a.value || !b.value || a.value <= b.value) return;
  if (e.target.name === 'd1') b.value = a.value; else a.value = b.value;
  toast('起始日期不能晚于结束日期，已自动调整');
});
/** 默认查询区间：当前会计期间所在年度 1 月 1 日（启用年度从启用日）到当前会计期间的最后一天 */
function defaultRange() {
  const cur = App.meta.current_period;
  const y1 = `${Math.floor(cur / 100)}-01-01`;
  return [y1 > startDate() ? y1 : startDate(), lastDay(cur)];
}
/** 期间参数兼容：YYYYMM 转成该月第一天 / 最后一天，日期原样返回 */
function asDate(v, end) {
  if (isDate(v)) return v;
  const p = +v;
  if (p > 190000 && p % 100 >= 1 && p % 100 <= 12) return end ? lastDay(p) : `${Math.floor(p / 100)}-${String(p % 100).padStart(2, '0')}-01`;
  return '';
}

/* ================= 路由、标签页与页面框架 ================= */
const APP_NAME = '明簿';
const NAV = [
  ['日常', [['home', '工作台'], ['voucher', '凭证录入'], ['vouchers', '凭证查询']]],
  ['账簿', [['balance', '科目余额表'], ['gl', '总账'], ['detail', '明细账'], ['auxbal', '辅助核算余额表']]],
  ['报表', [['bs', '资产负债表'], ['is', '利润表'], ['cf', '现金流量表'], ['vprofit', '单车盈利分析', 'vehicles']]],
  ['期末', [['closing', '期末处理与结账']]],
  ['设置', [['accounts', '会计科目'], ['aux', '辅助核算项目'], ['vehicles', '车辆台账', 'vehicles'], ['opening', '期初余额'],
    ['templates', '凭证模板'], ['import', '数据导入'], ['backup', '备份与恢复'], ['company', '账套信息'], ['logs', '操作日志'],
    ['security', '启动密码'], ['datadir', '数据位置'], ['update', '软件更新']]],
];
const PAGE_TITLES = {};
NAV.forEach(([g, items]) => items.forEach(([k, t]) => PAGE_TITLES[k] = t));
// 工作台和“设置”里的页面不进标签栏：同一时间只显示一个，点开就是最新的内容
const SOLO_PAGES = new Set(['home']);
NAV.find(g => g[0] === '设置')[1].forEach(([k]) => SOLO_PAGES.add(k));
// 没有选账套时也能打开的页面
const NO_COMPANY_PAGES = new Set(['update', 'security', 'datadir']);
function hasFeature(f) { return !!(App.meta && (App.meta.features || []).includes(f)); }

function parseHash(h) {
  h = (h === undefined ? location.hash : h).replace(/^#\/?/, '');
  const [name, query = ''] = h.split('?');
  const params = {};
  new URLSearchParams(query).forEach((v, k) => params[k] = v);
  return { name: name || 'home', params };
}
function setHash(name, params) {
  const q = qs(params || {});
  // 只改地址栏，不产生浏览历史（浏览器的“后退”不会把页面弄乱；返回用左上角的“← 返回”）
  try { history.replaceState(null, '', '#/' + name + (q ? '?' + q : '')); } catch (e) { /* 忽略 */ }
}
/**
 * 页面里的跳转（保存凭证后打开它、上一张/下一张、从余额表点进明细账等）。
 * 和当前标签是同一个功能时，就在当前标签里换内容；否则新开一个标签。
 */
function go(name, params = {}) { navigate(name, params, 'auto'); }
App.go = go;

/*
 * 标签页：
 * - 点左侧菜单：新开一个空白的标签（默认查询条件）；同一个功能可以开好几个，比如两个明细账查不同科目；
 * - 点上面的标签：回到之前查过的那一页，查询条件和结果都还在；
 * - 其他标签里改了数据（录了凭证、结了账等），切回来时自动按原来的条件重新查询；正在录入还没保存的凭证不动；
 * - 标签上的 ● 表示有没保存的内容，关闭时会先确认；↻ 刷新这个标签；× 关闭；
 * - 工作台和“设置”里的页面不进标签栏。
 */
App.tabs = [];
App.activeTab = null;   // 当前显示的页面：某个标签，或者 App.solo（工作台 / 设置页）
App.solo = null;
App.hist = [];          // “← 返回”用：之前看过的页面
App.dataVer = 0;        // 每改一次数据加 1；标签记下自己加载时的版本，落后了就重新查询
const MAX_TABS = 15;
let tabSeq = 0;

function frameEls() {
  const page = $('#page');
  if (!$('#tabbar', page)) page.innerHTML = '<div id="tabbar"></div><div id="panes"></div>';
  return { bar: $('#tabbar', page), panes: $('#panes', page) };
}
function closeAllTabs() {
  App.tabs = []; App.activeTab = null; App.solo = null; App.hist = [];
  $('#page').innerHTML = '';
}
function isDirty(t) { return !!(t && t.pane && t.pane.dataset.dirty === '1'); }
function tabTitle(t) {
  const p = t.params || {};
  if (t.name === 'voucher' && p.id) return t.label || '凭证';
  if (t.name === 'detail' && p.code) return '明细账 ' + p.code;
  return PAGE_TITLES[t.name] || t.name;
}
function renderTabbar() {
  const { bar } = frameEls();
  bar.innerHTML = App.tabs.map(t => `<div class="tab ${t === App.activeTab ? 'on' : ''}" data-id="${t.id}" title="${esc(tabTitle(t))}">
      ${isDirty(t) ? '<span class="tab-dirty" title="有没保存的内容">●</span>' : ''}<span class="tab-title">${esc(tabTitle(t))}</span>
      ${t === App.activeTab ? '<button class="tab-btn" data-act="reload" title="刷新这个标签（重新读取最新数据）">↻</button>' : ''}
      <button class="tab-btn" data-act="close" title="关闭">×</button></div>`).join('');
  layoutTabs(bar);
  const on = $('.tab.on', bar);
  if (on) {  // 当前标签不在可见范围时，把标签栏滚动过去
    const l = on.offsetLeft, r = l + on.offsetWidth;
    if (l < bar.scrollLeft) bar.scrollLeft = l - 12;
    else if (r > bar.scrollLeft + bar.clientWidth) bar.scrollLeft = r - bar.clientWidth + 12;
  }
  $$('.tab', bar).forEach(el => {
    const t = App.tabs.find(x => String(x.id) === el.dataset.id);
    el.addEventListener('mousedown', e => { if (e.button === 1) { e.preventDefault(); closeTab(t); } });
    el.onclick = e => {
      const act = e.target.dataset && e.target.dataset.act;
      if (act === 'close') {
        // 像浏览器一样：连续点 × 关标签时，标签宽度先不变，下一个标签的 × 正好移到鼠标下面
        App.tabFreeze = App.tabWidth || null;
        return closeTab(t);
      }
      if (act === 'reload') return reloadTab(t);
      showView(t);
    };
  });
  if (!bar.dataset.leaveBound) {
    bar.dataset.leaveBound = '1';
    // 鼠标离开标签栏后，再按剩下的标签重新分配宽度
    bar.addEventListener('mouseleave', () => { if (App.tabFreeze) { App.tabFreeze = null; layoutTabs(bar); } });
  }
  renderBack();
}
/* 标签宽度：所有标签一样宽。空间够时按最长的标签文字定宽度（最宽 200），标签多了就平均分，最窄 96，再多就左右滚动。
 * 刚点过 × 、鼠标还在标签栏上时，宽度保持不变。 */
const TAB_MIN = 96, TAB_MAX = 200, TAB_GAP = 3;
let tabMeasure = null;
function tabTextWidth(text, bold) {
  tabMeasure = tabMeasure || document.createElement('canvas').getContext('2d');
  const font = getComputedStyle(document.body).fontFamily;
  tabMeasure.font = `${bold ? 600 : 400} 13px ${font}`;
  return tabMeasure.measureText(text).width;
}
function layoutTabs(bar) {
  bar = bar || $('#tabbar');
  if (!bar || !App.tabs.length) return;
  let w = App.tabFreeze;
  if (!w) {
    // 文字 + 左右留白 + ●/↻/× 按钮的位置
    const need = Math.max(...App.tabs.map(t => tabTextWidth(tabTitle(t), true))) + 12 + 6 + 20 + 20 + 14 + 8;
    const avail = (bar.clientWidth - 24) / App.tabs.length - TAB_GAP;
    w = Math.floor(Math.max(TAB_MIN, Math.min(TAB_MAX, need, avail)));
  }
  App.tabWidth = w;
  $$('.tab', bar).forEach(el => { el.style.width = w + 'px'; });
}
window.addEventListener('resize', () => { if (!App.tabFreeze) layoutTabs(); });
// 有没保存的内容时，标签上显示 ●
setInterval(() => {
  const sig = App.tabs.map(t => t.id + (isDirty(t) ? '*' : '')).join(',');
  if (sig !== App.dirtySig) { App.dirtySig = sig; if ($('#tabbar')) renderTabbar(); }
}, 800);
window.addEventListener('beforeunload', e => {
  if (App.tabs.some(isDirty) && !App.quitting) { e.preventDefault(); e.returnValue = ''; }
});

/** 显示某个标签（或 App.solo）。pushHist=false 时不记入“返回”历史 */
function showView(t, pushHist = true) {
  closePicker();
  if (pushHist && App.activeTab && App.activeTab !== t) {
    App.hist.push(App.activeTab.solo ? { solo: App.activeTab.name, params: App.activeTab.params } : { tab: App.activeTab });
    if (App.hist.length > 50) App.hist.shift();
  }
  App.activeTab = t;
  App.tabs.forEach(x => x.pane.classList.toggle('on', x === t));
  if (App.solo) App.solo.pane.classList.toggle('on', App.solo === t);
  renderTabbar();
  highlightNav(t.name);
  setHash(t.name, t.params);
  scheduleFit();
  // 别的地方改过数据：按原来的条件重新查询（没保存的凭证除外）
  if (!t.solo && t.ver < App.dataVer && !isDirty(t) && !t.loading) loadIntoTab(t, t.params || {});
}
function renderBack() {
  const b = $('#go-back');
  if (b) b.style.visibility = App.hist.some(h => h.solo || App.tabs.includes(h.tab)) ? '' : 'hidden';
}
function goBack() {
  while (App.hist.length) {
    const h = App.hist.pop();
    if (h.tab && App.tabs.includes(h.tab)) return showView(h.tab, false);
    if (h.solo) return openSolo(h.solo, h.params || {}, false);
  }
  renderBack();
}
async function closeTab(t) {
  const i = App.tabs.indexOf(t);
  if (i < 0) return;
  if (isDirty(t)) {
    if (App.activeTab !== t) showView(t);
    if (!await confirmBox(`“${tabTitle(t)}”里有没保存的内容，关闭后这些内容就没有了。确定关闭吗？`, '关闭', true)) return;
  }
  closePicker();
  t.pane.remove();
  App.tabs.splice(i, 1);
  if (App.activeTab === t) {
    App.activeTab = null;
    // 优先回到打开它之前的页面
    let back = null;
    while (App.hist.length && !back) {
      const h = App.hist.pop();
      if (h.tab && App.tabs.includes(h.tab)) back = h.tab;
      else if (h.solo) back = h;
    }
    if (back && back.solo) openSolo(back.solo, back.params || {}, false);
    else if (back) showView(back, false);
    else if (App.tabs.length) showView(App.tabs[Math.min(i, App.tabs.length - 1)], false);
    else openSolo('home', {}, false);
  } else renderTabbar();
}
async function loadIntoTab(t, params) {
  const fn = App.pages[t.name];
  t.params = params;
  t.ver = App.dataVer;
  t.loading = true;
  delete t.pane.dataset.dirty;
  t.pane.innerHTML = '<div class="empty">加载中…</div>';
  t.pane.scrollTop = 0;
  try { await fn(t.pane, params); }
  catch (e) { if (!e.locked) t.pane.innerHTML = `<div class="notice err">${esc(e.message)}</div>`; console.error(e); }
  finally { t.loading = false; }
  if (App.tabs.includes(t)) renderTabbar();
  if (App.activeTab === t) setHash(t.name, t.params);
}
/** 重新加载某个标签（默认当前页面），保留它现在的查询条件 */
async function reloadTab(t) {
  t = t || App.activeTab;
  if (!t) return navigate(parseHash().name, parseHash().params, 'auto');
  await loadIntoTab(t, t.params || {});
}
App.reloadTab = reloadTab;
/** 页面查询时调用：记下这个标签现在的查询条件，以后自动重新查询、刷新时都用它 */
function remember(page, params) {
  const t = App.tabs.find(x => x.pane === page) || (App.solo && App.solo.pane === page ? App.solo : null);
  if (!t) return;
  t.params = Object.assign({}, params);
  t.ver = App.dataVer;
  if (App.activeTab === t) setHash(t.name, t.params);
  if (App.tabs.includes(t)) renderTabbar();
}
/** 一键刷新：重新读取账套信息，再把所有打开的标签按各自的条件重新加载。
 *  正在录入、还没保存的凭证不刷新，免得辛苦录的内容丢掉。 */
let reloadingAll = false;
async function reloadAllTabs() {
  if (reloadingAll) return;
  reloadingAll = true;
  const btn = $('#reload-all');
  if (btn) btn.disabled = true;
  try {
    await refreshMeta();
    const skipped = [];
    let n = 0;
    for (const t of App.tabs.slice()) {
      if (!App.tabs.includes(t)) continue;
      if (isDirty(t)) { skipped.push(tabTitle(t)); continue; }
      await loadIntoTab(t, t.params || {});
      n++;
    }
    if (App.activeTab && App.activeTab.solo) await loadIntoTab(App.activeTab, App.activeTab.params || {});
    renderTabbar();
    if (skipped.length) toast(`已刷新 ${n} 个标签；“${skipped.join('、')}”有未保存的修改，没有刷新（保存后再点一次即可）`, 'warn');
    else toast(`已刷新全部 ${n} 个标签`, 'ok');
  } catch (e) { toast(e.message, 'err'); }
  finally { reloadingAll = false; const b = $('#reload-all'); if (b) b.disabled = false; }
}
App.reloadAllTabs = reloadAllTabs;
function highlightNav(name) {
  $$('#sidebar .nav-group a').forEach(a => a.classList.toggle('active', a.dataset.page === name));
}

function renderChrome() {
  const side = $('#sidebar'), top = $('#topbar');
  if (!App.cid || !App.meta) {
    side.classList.add('hidden');
    const name = parseHash().name;
    top.innerHTML = `<span class="topbar-company">${APP_NAME}</span>
      ${NO_COMPANY_PAGES.has(name) ? '<a href="#/companies" class="btn small">← 返回账套列表</a>' : ''}<span class="topbar-spacer"></span>
      ${App.lock && App.lock.enabled ? '<button class="btn small" data-lock title="锁定软件，要输入启动密码才能继续用">锁定</button>' : ''}
      <button class="btn small" data-quit>退出软件</button>`;
    $('[data-quit]', top).onclick = quitApp;
    const lk = $('[data-lock]', top); if (lk) lk.onclick = lockNow;
    return;
  }
  side.classList.remove('hidden');
  const cur = App.activeTab ? App.activeTab.name : '';
  side.innerHTML = `<div class="side-scroll"><div class="brand">${APP_NAME}<small>${esc(App.meta.industry_name || '')} · ${esc(App.meta.standard_name || '')}${App.version ? '<br>v' + esc(App.version) : ''}</small></div>` + NAV.map(([g, items]) =>
    `<div class="nav-group"><div>${g}</div>${items.filter(([k, t, f]) => !f || hasFeature(f)).map(([k, t]) =>
      `<a href="#/${k}" data-page="${k}" class="${k === cur ? 'active' : ''}">${t}</a>`).join('')}</div>`).join('') +
    `</div><div class="side-foot">
      ${App.lock && App.lock.enabled ? '<button class="side-btn" data-lock title="锁定软件，要输入启动密码才能继续用">🔒 锁定</button>' : ''}
      <button class="side-btn" data-quit title="关闭软件（后台程序也会一起退出）">⏻ 退出软件</button></div>`;
  $$('.nav-group a', side).forEach(a => a.onclick = e => { e.preventDefault(); navigate(a.dataset.page, {}, 'new'); });
  $('[data-quit]', side).onclick = quitApp;
  const lk = $('[data-lock]', side); if (lk) lk.onclick = lockNow;
  const m = App.meta;
  top.innerHTML = `<button class="btn small" id="go-back" title="回到上一个看过的页面">← 返回</button>
    <span class="topbar-company">${esc(m.company_name)}</span>
    <span class="topbar-period">当前会计期间：<b>${plabel(m.current_period)}</b></span>
    ${m.closed.length ? `<span class="pill gray">已结账至 ${plabel(m.closed[m.closed.length - 1])}</span>` : ''}
    <span class="topbar-spacer"></span>
    <button class="btn small" id="reload-all" title="重新读取最新数据，把所有打开的标签都刷新一遍（快捷键 F9）">⟳ 全部刷新</button>
    <a href="#/voucher?new=1" class="btn primary small">＋ 新增凭证</a>
    <button class="btn small" id="switch-company">切换账套</button>`;
  $('#go-back').onclick = goBack;
  $('#switch-company').onclick = async () => {
    if (App.tabs.some(isDirty) && !await confirmBox('有凭证还没保存，切换账套后这些内容就没有了。确定切换吗？', '切换', true)) return;
    App.cid = null; store('cid', ''); App.meta = null; closeAllTabs(); navigate('companies', {}, 'new');
  };
  $('#reload-all').onclick = reloadAllTabs;
  renderBack();
}

async function quitApp() {
  const dirty = App.tabs.filter(isDirty).map(tabTitle);
  const msg = (dirty.length ? `“${dirty.join('、')}”还有没保存的内容，退出后就没有了。\n\n` : '') +
    '退出软件吗？退出后要再次使用，请重新双击软件图标。';
  if (!await confirmBox(msg, '退出', !!dirty.length)) return;
  App.quitting = true;
  try { await api('/api/shutdown', {}); } catch (e) { /* 已经退出 */ }
  stopHeartbeat();
  document.body.innerHTML = `<div style="max-width:520px;margin:18vh auto;text-align:center;font-family:var(--font);color:#1c2430">
    <h2>软件已退出</h2><p style="color:#4a5565;line-height:1.8">现在可以关闭这个窗口。<br>下次使用时，双击“${APP_NAME}”图标即可。</p></div>`;
  setTimeout(() => { try { window.close(); } catch (e) { /* 浏览器不让关就留着提示 */ } }, 600);
}

/** 打开工作台或设置里的页面（不进标签栏） */
async function openSolo(name, params, pushHist = true) {
  const { panes } = frameEls();
  if (!App.solo) {
    const pane = document.createElement('div');
    pane.className = 'pane';
    panes.appendChild(pane);
    App.solo = { solo: true, name, pane, params: {} };
  }
  const s = App.solo;
  s.name = name;
  showView(s, pushHist);
  await loadIntoTab(s, params);
}

/** 打开一个功能。mode：'new' 新开标签（左侧菜单、页面里的链接）；'auto' 同一个功能时在当前标签里换内容 */
async function navigate(name, params = {}, mode = 'new') {
  closePicker();
  if (!App.cid && NO_COMPANY_PAGES.has(name)) { // 还没选账套时（例如从右下角新版本提示过来），也能打开“软件更新”等
    closeAllTabs();
    setHash(name, params);
    renderChrome();
    $('#page').innerHTML = '<div class="pane on solo"></div>';
    try { await App.pages[name]($('#page .solo'), params); } catch (e) { if (!e.locked) toast(e.message, 'err'); }
    return;
  }
  if (!App.cid || name === 'companies') {
    App.cid = null;
    closeAllTabs();
    setHash('companies', {});
    renderChrome();
    $('#page').innerHTML = '<div class="pane on solo"></div>';
    try { await App.pages.companies($('#page .solo'), params); } catch (e) { if (!e.locked) toast(e.message, 'err'); }
    return;
  }
  if (!App.meta) {
    try { await refreshMeta(); }
    catch (e) { if (e.locked) return; App.cid = null; store('cid', ''); toast(e.message, 'err'); return navigate('companies'); }
  }
  if (!App.pages[name]) { toast('页面不存在', 'err'); return; }
  if (!$('#sidebar').innerHTML || $('#sidebar').classList.contains('hidden')) renderChrome();
  if (SOLO_PAGES.has(name)) return openSolo(name, params);
  const cur = App.activeTab;
  // 页面里的跳转，和当前标签是同一个功能：在当前标签里换内容
  if (mode === 'auto' && cur && !cur.solo && cur.name === name) {
    if (isDirty(cur) && !await confirmBox('这个标签里有没保存的内容，离开后这些内容就没有了。确定离开吗？', '离开', true)) return;
    return loadIntoTab(cur, params);
  }
  // 已经开着一模一样的标签（例如同一张凭证），直接切过去
  const key = qs(params);
  const same = key && !params.new && !params.t && App.tabs.find(x => x.name === name && qs(x.params || {}) === key && !isDirty(x));
  if (same) return showView(same);
  const { panes } = frameEls();
  if (App.tabs.length >= MAX_TABS) {
    const old = App.tabs.find(x => x !== cur && !isDirty(x));
    if (!old) return toast(`最多同时开 ${MAX_TABS} 个标签，请先关掉一些`, 'warn');
    old.pane.remove(); App.tabs.splice(App.tabs.indexOf(old), 1);
  }
  const pane = document.createElement('div');
  pane.className = 'pane';
  panes.appendChild(pane);
  const t = { id: ++tabSeq, name, pane, params: {}, ver: App.dataVer };
  // 新标签放在当前标签后面
  const at = cur && !cur.solo ? App.tabs.indexOf(cur) + 1 : App.tabs.length;
  App.tabs.splice(at, 0, t);
  showView(t);
  await loadIntoTab(t, params);
}
App.navigate = navigate;

// 页面里的 #/ 链接：新开标签（不经过浏览器的地址历史）
document.addEventListener('click', e => {
  const a = e.target.closest && e.target.closest('a[href^="#/"]');
  if (!a || e.defaultPrevented || e.ctrlKey || e.metaKey || e.shiftKey) return;
  e.preventDefault();
  const { name, params } = parseHash(a.getAttribute('href'));
  navigate(name, params, 'new');
});

App.start = async () => {
  App.cid = store('cid') || null;
  try {
    const v = await api('/api/version');
    App.version = v.version; App.root = v.root; App.dataDir = v.data_dir; App.started = v.started;
  } catch (e) { /* 后台还没起来，下面的请求会提示 */ }
  try { App.lock = await api('/api/lock/status'); } catch (e) { App.lock = null; }
  startHeartbeat();
  window.addEventListener('hashchange', () => { const { name, params } = parseHash(); navigate(name, params, 'new'); });
  document.addEventListener('keydown', e => {
    if (e.key === 'F9' && App.cid && App.meta && !document.querySelector('.modal-mask')) { e.preventDefault(); reloadAllTabs(); }
  });
  if (App.lock && App.lock.enabled && !App.lock.unlocked) await showLockScreen();
  const { name, params } = parseHash();
  await navigate(name, params, 'new');
  setTimeout(autoCheckUpdate, 3000); // 等界面先打开，再在后台查新版本
};

/* ================= 表格高度跟着窗口走 =================
 * 表格框（.tbl-wrap）自己有滚动条、表头固定。它的高度要正好到窗口底部：以前用固定的“窗口高度 - 180”，
 * 表格上面的内容多时（标题、查询条件、提示），表格框就超出窗口，看起来像表格跑出了边框，还出现两层滚动条。 */
function fitTables() {
  const pane = $('.pane.on');
  if (!pane) return;
  const pr = pane.getBoundingClientRect();
  $$('.tbl-wrap', pane).forEach(w => {
    if (w.closest('.modal-mask')) return;
    const top = w.getBoundingClientRect().top - pr.top + pane.scrollTop;
    const avail = Math.floor(pane.clientHeight - top - 28);
    w.style.maxHeight = Math.max(260, avail) + 'px';
  });
}
let fitPending = false;
function scheduleFit() {
  if (fitPending) return;
  fitPending = true;
  requestAnimationFrame(() => { fitPending = false; fitTables(); });
}
window.addEventListener('resize', scheduleFit);
new MutationObserver(scheduleFit).observe(document.getElementById('page') || document.body, { childList: true, subtree: true });

/* ================= 心跳：所有窗口都关掉后，后台程序自动退出 ================= */
const PAGE_ID = Math.random().toString(36).slice(2) + Date.now().toString(36);
let hbTimer = null;
function startHeartbeat() {
  const beat = async () => {
    try {
      const res = await fetch('/api/heartbeat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: PAGE_ID }) });
      const r = await res.json();
      // 后台程序重启过（例如更新后点了“立即重启”）：刷新页面，用新版本
      if (App.started && r.started && r.started !== App.started && !App.quitting) {
        App.quitting = true;
        location.reload();
        return;
      }
    } catch (e) { /* 后台暂时连不上 */ }
    // 闲置自动锁定：后台判断通行证过期后，这里马上盖上锁屏
    if (App.lock && App.lock.enabled && !$('#lock-screen')) {
      try {
        const st = await fetch('/api/lock/status', { headers: { 'X-Unlock': lockToken() } }).then(r => r.json());
        if (st.enabled && !st.unlocked) showLockScreen();
      } catch (e) { /* 忽略 */ }
    }
  };
  beat();
  hbTimer = setInterval(beat, 5000);
  window.addEventListener('pagehide', () => {
    try { navigator.sendBeacon('/api/heartbeat', new Blob([JSON.stringify({ id: PAGE_ID, bye: true })], { type: 'application/json' })); } catch (e) { /* 忽略 */ }
  });
}
function stopHeartbeat() { clearInterval(hbTimer); }

/* ================= 启动密码：锁屏 ================= */
function lockToken() { try { return sessionStorage.getItem('unlock') || ''; } catch (e) { return ''; } }
function setLockToken(t) { try { sessionStorage.setItem('unlock', t || ''); } catch (e) { /* 忽略 */ } }
async function lockNow() {
  try { await api('/api/lock/lock', {}); } catch (e) { /* 忽略 */ }
  setLockToken('');
  showLockScreen();
}
let lockWaiters = null;
/** 盖上锁屏，输对密码后 resolve。已经盖着时返回同一个等待。 */
function showLockScreen() {
  if (lockWaiters) return lockWaiters.promise;
  let resolve;
  const promise = new Promise(r => resolve = r);
  lockWaiters = { promise, resolve };
  closePicker();
  $$('.modal-mask').forEach(m => m.style.visibility = 'hidden');
  const box = document.createElement('div');
  box.id = 'lock-screen';
  const hint = App.lock && App.lock.hint ? `<div class="hint">密码提示：${esc(App.lock.hint)}</div>` : '';
  const drawLogin = () => {
    box.innerHTML = `<div class="lock-card"><img src="app.png" alt="" class="lock-logo"><h2>${APP_NAME} 已锁定</h2>
      <p class="hint">请输入启动密码</p>
      <input type="password" id="lk-pw" autocomplete="current-password" placeholder="启动密码">${hint}
      <div class="lock-err" id="lk-err"></div>
      <button class="btn primary" id="lk-ok">解锁</button>
      <div class="lock-links"><a href="javascript:void 0" id="lk-forgot">忘记密码？</a> · <a href="javascript:void 0" id="lk-quit">退出软件</a></div></div>`;
    const pw = $('#lk-pw', box), err = $('#lk-err', box);
    const ok = async () => {
      err.textContent = '';
      try {
        const r = await fetch('/api/lock/unlock', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: pw.value }) });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || '解锁失败');
        done(d.token);
      } catch (e) { err.textContent = e.message; pw.select(); }
    };
    $('#lk-ok', box).onclick = ok;
    pw.onkeydown = e => { if (e.key === 'Enter') ok(); };
    $('#lk-forgot', box).onclick = drawRecover;
    $('#lk-quit', box).onclick = async () => {
      App.quitting = true;
      try { await fetch('/api/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); } catch (e) { /* 忽略 */ }
      stopHeartbeat();
      box.innerHTML = `<div class="lock-card"><h2>软件已退出</h2><p class="hint">现在可以关闭这个窗口。</p></div>`;
      setTimeout(() => { try { window.close(); } catch (e) { /* 忽略 */ } }, 600);
    };
    setTimeout(() => pw.focus(), 50);
  };
  const drawRecover = () => {
    box.innerHTML = `<div class="lock-card" style="width:420px"><h2>用恢复码重设密码</h2>
      <p class="hint">恢复码是设置启动密码时显示的那串字母和数字（例如 ABCD-EFGH-JKLM-NPQR）。</p>
      <input type="text" id="lk-code" placeholder="恢复码" style="text-transform:uppercase">
      <input type="password" id="lk-new" placeholder="新密码（至少 4 位）" autocomplete="new-password">
      <input type="password" id="lk-new2" placeholder="再输一次新密码" autocomplete="new-password">
      <div class="lock-err" id="lk-err"></div>
      <button class="btn primary" id="lk-ok">重设密码并解锁</button>
      <p class="hint" style="text-align:left;margin-top:14px">恢复码也找不到了？先退出软件，再打开数据文件夹<br><b>${esc(App.dataDir || 'data')}</b><br>
        删除里面的 <b>security.json</b> 文件，启动密码就取消了，账套数据不受影响。</p>
      <div class="lock-links"><a href="javascript:void 0" id="lk-back">← 返回输入密码</a></div></div>`;
    const err = $('#lk-err', box);
    $('#lk-back', box).onclick = drawLogin;
    $('#lk-ok', box).onclick = async () => {
      err.textContent = '';
      const a = $('#lk-new', box).value, b = $('#lk-new2', box).value;
      if (a !== b) { err.textContent = '两次输入的新密码不一样'; return; }
      try {
        const r = await fetch('/api/lock/recover', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: $('#lk-code', box).value, password: a }) });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || '重设失败');
        box.innerHTML = `<div class="lock-card" style="width:420px"><h2>密码已重设</h2>
          <p>新的恢复码（旧的已经作废），请抄下来或拍照，放在安全的地方：</p>
          <div class="recovery-code">${esc(d.recovery_code)}</div>
          <button class="btn primary" id="lk-go">我已记下，进入软件</button></div>`;
        $('#lk-go', box).onclick = () => done(d.token);
      } catch (e) { err.textContent = e.message; }
    };
  };
  const done = token => {
    setLockToken(token);
    box.remove();
    $$('.modal-mask').forEach(m => m.style.visibility = '');
    const w = lockWaiters; lockWaiters = null;
    w.resolve();
  };
  drawLogin();
  document.body.appendChild(box);
  return promise;
}

/* 打开软件时自动查一次新版本，有就在右下角提示；连不上不提示（设置 → 软件更新 里可以关掉） */
async function autoCheckUpdate() {
  let r;
  try { r = await api('/api/update/auto'); } catch (e) { return; }
  if (!r || !r.has_update || document.getElementById('update-notice')) return;
  const box = document.createElement('div');
  box.id = 'update-notice';
  box.innerHTML = `<button class="x" title="关闭">✕</button>
    <div class="un-title">发现新版本 v${esc(r.latest)}</div>
    <div class="hint">当前是 v${esc(r.current)}${r.notes ? `<br><span class="un-notes">${esc(String(r.notes).split('\n')[0])}</span>` : ''}</div>
    <div class="un-foot"><button class="btn small" data-later>以后再说</button><button class="btn primary small" data-go>去更新</button></div>`;
  const close = () => box.remove();
  $('.x', box).onclick = close;
  $('[data-later]', box).onclick = close;
  $('[data-go]', box).onclick = () => { close(); navigate('update', {}, 'new'); };
  document.body.appendChild(box);
}

/* ================= 账套选择页 ================= */
App.pages.companies = async (page) => {
  const [list, opts] = await Promise.all([api('/api/companies'), api('/api/chart_options')]);
  const y = new Date().getFullYear();
  page.innerHTML = `<div class="welcome">
    <h1>选择账套</h1>
    <p class="hint">每家公司是一个独立的账套，数据互不影响。点击公司名称进入。</p>
    <div class="company-grid" id="clist">
      ${list.map(c => `<div class="company" data-id="${c.id}">
        <div class="name">${esc(c.name)}</div>
        <div class="info">${c.broken ? '文件无法打开' : `${esc(c.industry_name || '')} · ${esc(c.standard_name || '')}<br>启用期间：${plabel(c.start_period)}<br>当前期间：${plabel(c.current_period)}<br>凭证：${c.voucher_count} 张<br>最后修改：${esc(c.modified || '—')}`}</div>
        ${c.broken ? '' : `<a class="btn small" style="margin-top:10px" href="/api/company/export?company=${c.id}" data-stop>导出这个账套</a>`}
      </div>`).join('')}
    </div>
    ${list.length ? '' : `<div class="notice info">这里还没有账套。正在电脑上找以前用过的账套，找到了可以直接导入；没有的话请在下面新建一个。</div>
      <div id="old-found"></div>`}
    <div class="card" style="margin-top:22px;max-width:560px">
      <h2>新建账套</h2>
      <div class="field"><span>公司名称</span><input type="text" name="name" placeholder="例如：某某有限公司"></div>
      <div class="field-row">
        <div class="field"><span>启用年度</span><input type="number" name="start_year" value="${y}"></div>
        <div class="field"><span>启用月份</span><select name="start_month">${monthOptions(1)}</select></div>
      </div>
      <div class="field-row">
        <div class="field"><span>执行的会计准则</span><select name="standard">${opts.standards.map(o => `<option value="${o.code}">${esc(o.name)}</option>`).join('')}</select></div>
        <div class="field"><span>行业</span><select name="industry">${opts.industries.map(o => `<option value="${o.code}" ${o.code === opts.default_industry ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</select></div>
      </div>
      <p class="hint" id="ind-desc"></p>
      <div class="field"><span>会计科目从哪里来</span><select name="copy_from">
        <option value="">按上面选择的准则和行业预置</option>
        ${list.filter(c => !c.broken).map(c => `<option value="${c.id}">复制“${esc(c.name)}”的科目、模板和设置（准则、行业跟随它）</option>`).join('')}
      </select></div>
      <p class="hint">《小企业会计准则》适用于符合小型企业标准、且不对外筹资的企业；规模较大或有上市、融资需要的执行《企业会计准则》。准则和行业建账后不能更改，不确定请先咨询公司会计。</p>
      <p class="hint">建议从 1 月启用，这样全年的利润表和现金流量表都完整。启用期间建账后、录凭证前可以修改。</p>
      <button class="btn primary" id="create">新建账套</button>
    </div>
    <div class="card" style="max-width:760px" id="transfer">
      <h2>在多台电脑之间转移数据</h2>
      <p class="hint">在一台电脑上“导出”，用 U 盘、网盘或微信把文件传到另一台电脑，再在那台电脑上“导入”。
        导出的文件里包含账套的全部数据（科目、凭证、车辆、期初等）。<b>请约定同一时间只在一台电脑上记账</b>，换电脑前先导出、到另一台后先导入，否则两边的数据会不一致。</p>
      <div class="toolbar"><a class="btn" href="/api/companies/export_all">导出全部账套（.zip）</a>
        <span class="muted small">也可以点上面每个账套里的“导出这个账套”，只导出一家公司（.db）。</span></div>
      <div class="toolbar">
        <input type="file" id="imp-file" accept=".db,.zip">
        <label class="check"><input type="radio" name="imp-mode" value="replace" checked> 有同名账套时覆盖</label>
        <label class="check"><input type="radio" name="imp-mode" value="new"> 作为新账套导入</label>
        <button class="btn primary" id="imp-btn">导入</button>
      </div>
      <p class="hint">覆盖前会自动备份本机原来的账套；如果本机的数据比导入的文件更新，会先提醒你确认。</p>
      <div id="imp-res"></div>
    </div>
    <p class="hint">软件版本 v${esc(App.version || '')}　数据文件夹：${esc(App.dataDir || '')}</p>
    <div class="toolbar"><a class="btn small" href="#/datadir">数据位置 / 找回旧账套</a><a class="btn small" href="#/security">启动密码</a><a class="btn small" href="#/update">软件更新</a></div></div>`;
  if (!list.length) {
    const box = $('#old-found', page);
    box.innerHTML = '<div class="hint">正在查找…</div>';
    api('/api/data/scan', {}).then(r => {
      if (!box.isConnected) return;
      if (!r.found.length) { box.innerHTML = '<div class="hint">没有找到以前的账套。</div>'; return; }
      box.innerHTML = '<h2>找到了以前的账套</h2>' + oldDataHtml(r.found);
      bindOldData(box, r.found, () => setTimeout(() => navigate('companies'), 1200));
    }).catch(() => { if (box.isConnected) box.innerHTML = ''; });
  }
  $$('[data-stop]', page).forEach(a => a.addEventListener('click', e => e.stopPropagation()));
  const showDesc = () => {
    const ind = opts.industries.find(o => o.code === $('[name=industry]', page).value);
    const copy = $('[name=copy_from]', page).value;
    $('[name=standard]', page).disabled = $('[name=industry]', page).disabled = !!copy;
    $('#ind-desc', page).textContent = copy ? '将复制所选账套的全部科目和设置。' : (ind ? ind.desc : '');
  };
  $('[name=industry]', page).onchange = showDesc;
  $('[name=copy_from]', page).onchange = showDesc;
  showDesc();
  $$('.company', page).forEach(el => el.onclick = () => {
    App.cid = el.dataset.id; store('cid', App.cid); App.meta = null; closeAllTabs(); go('home');
  });
  $('#imp-btn', page).onclick = async () => {
    const file = $('#imp-file', page).files[0];
    const res = $('#imp-res', page);
    if (!file) return toast('请先选择要导入的文件（.db 或 .zip）', 'err');
    const body = { data: await fileToB64(file), filename: file.name, mode: $('[name=imp-mode]:checked', page).value };
    try {
      let r = await api('/api/companies/import', body);
      if (r.need_confirm) {
        const ok = await confirmBox('注意：下面的账套本机数据比导入的文件更新，覆盖后本机较新的数据会被替换（覆盖前会自动备份）：\n\n' + r.warnings.join('\n') + '\n\n确定要覆盖吗？', '仍然覆盖', true);
        if (!ok) return;
        r = await api('/api/companies/import', Object.assign(body, { force: true }));
      }
      toast('导入完成', 'ok');
      App.pages.companies(page);
      setTimeout(() => { const el = $('#imp-res'); if (el) el.innerHTML = `<div class="notice ok">${r.results.map(esc).join('<br>')}</div>`; }, 200);
    } catch (e) { res.innerHTML = `<div class="notice err">${esc(e.message)}</div>`; }
  };
  $('#create', page).onclick = async () => {
    try {
      const d = formData($('.card', page));
      const r = await api('/api/companies/create', d);
      App.cid = r.id; store('cid', r.id); App.meta = null; closeAllTabs();
      toast('账套已建立', 'ok');
      go('opening');
    } catch (e) { toast(e.message, 'err'); }
  };
};

/* ================= 工作台 ================= */
App.pages.home = async (page) => {
  const h = await api('/api/home');
  const st = h.status;
  const m = App.meta;
  const stepOk = name => (st.checks.find(c => c.name === name) || {}).ok;
  page.innerHTML = `
    <div class="page-head"><div><h1>工作台</h1><div class="sub">${plabel(h.current_period)} 的工作进度</div></div></div>
    <div class="stat-row">
      <div class="stat"><div class="k">本月凭证</div><div class="v">${h.voucher_count} 张</div></div>
      <div class="stat"><div class="k">未审核凭证</div><div class="v ${h.unaudited ? 'red' : ''}">${h.unaudited} 张</div></div>
      ${hasFeature('vehicles') ? `<div class="stat"><div class="k">在用车辆</div><div class="v">${h.vehicle_in_use} 辆</div></div>
      <div class="stat"><div class="k">本月应提折旧</div><div class="v">${fmtN(st.depreciation.amount)}</div></div>` : ''}
    </div>
    <div class="card"><h2>本月操作流程</h2>
      <ol class="steps">
        <li class="${h.voucher_count ? 'ok' : ''}"><span class="t">录入凭证</span><span class="d">日常业务按天汇总录入，常用业务可以用凭证模板。</span><a class="btn small" href="#/voucher">新增凭证</a></li>
        <li class="${h.voucher_count && !h.unaudited ? 'ok' : ''}"><span class="t">审核凭证</span><span class="d">逐张核对后审核；审核后的凭证不能修改。</span><a class="btn small" href="#/vouchers?status=unaudited">去审核</a></li>
        ${hasFeature('vehicles') ? `<li class="${stepOk('计提车辆折旧') ? 'ok' : ''}"><span class="t">计提折旧</span><span class="d">系统按车辆台账自动计算，生成一张折旧凭证。</span><a class="btn small" href="#/closing">期末处理</a></li>` : ''}
        <li class="${stepOk('结转损益') && h.voucher_count ? 'ok' : ''}"><span class="t">结转损益</span><span class="d">把收入和费用转入“本年利润”，自动生成凭证。</span><a class="btn small" href="#/closing">期末处理</a></li>
        <li><span class="t">查看账表</span><span class="d">科目余额表 → 资产负债表、利润表、现金流量表。</span><a class="btn small" href="#/balance">余额表</a><a class="btn small" href="#/bs">报表</a></li>
        <li><span class="t">结账</span><span class="d">检查全部通过后结账，进入下个月。</span><a class="btn small" href="#/closing">去结账</a></li>
      </ol>
    </div>
    <div class="card"><h2>本月最近的凭证</h2>
      ${h.recent.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>日期</th><th>凭证号</th><th>摘要</th><th class="n">金额</th><th>状态</th></tr></thead><tbody>
      ${h.recent.map(v => `<tr class="clickable" data-id="${v.id}"><td>${v.date}</td><td>记-${String(v.number).padStart(4, '0')}</td><td>${esc(v.first_summary)}</td>${moneyCell(v.total)}<td>${v.audited ? '<span class="pill green">已审核</span>' : '<span class="pill amber">未审核</span>'}</td></tr>`).join('')}
      </tbody></table></div>` : '<div class="empty">本月还没有凭证</div>'}
    </div>
    ${m.has_vouchers ? '' : `<div class="card"><h2>第一次使用？</h2><ol class="hint" style="margin:0;padding-left:20px">
      <li>在“设置 → 会计科目”里检查科目，按公司实际情况增减；</li>
      <li>在“设置 → 辅助核算项目”里添加银行账户、客户、供应商；</li>
      ${hasFeature('vehicles') ? '<li>在“设置 → 车辆台账”里录入或从 Excel 导入全部车辆；</li>' : ''}
      <li>在“设置 → 期初余额”里录入启用时各科目的余额，并试算平衡；</li>
      <li>开始录入凭证。</li></ol></div>`}`;
  $$('tr[data-id]', page).forEach(tr => tr.onclick = () => go('voucher', { id: tr.dataset.id }));
};

/* ================= 打印设置（纸张、方向、缩放、每页凭证张数） ================= */
const PAPERS = {
  A4: { name: 'A4（210×297mm）', w: 210, h: 297 },
  A5: { name: 'A5（148×210mm）', w: 148, h: 210 },
  B5: { name: 'B5（176×250mm）', w: 176, h: 250 },
  VOUCHER: { name: '凭证纸（240×140mm）', w: 240, h: 140, fixed: true },
};
const PRINT_MARGIN = 10; // 页边距 mm
const PRINT_DEFAULTS = {
  voucher: { paper: 'A4', orient: 'portrait', perPage: 2, scale: 100 },
  report: { paper: 'A4', orient: 'portrait', scale: 100 },
};
function loadPrintSettings(kind) {
  let saved = null;
  try { saved = JSON.parse(store('print_' + kind) || 'null'); } catch (e) { saved = null; }
  return Object.assign({}, PRINT_DEFAULTS[kind], saved || {});
}
/** 根据设置得到页面尺寸（mm），并写入 @page 样式 */
function applyPrintPage(s) {
  const p = PAPERS[s.paper] || PAPERS.A4;
  let w = p.w, h = p.h;
  if (!p.fixed) {
    const a = Math.min(w, h), b = Math.max(w, h);
    [w, h] = s.orient === 'landscape' ? [b, a] : [a, b];
  }
  let el = document.getElementById('print-page-style');
  if (!el) { el = document.createElement('style'); el.id = 'print-page-style'; document.head.appendChild(el); }
  el.textContent = `@page { size: ${w}mm ${h}mm; margin: ${PRINT_MARGIN}mm; } :root { --pscale: ${(s.scale || 100) / 100}; }`;
  return { w, h, contentW: w - 2 * PRINT_MARGIN, contentH: h - 2 * PRINT_MARGIN };
}
/** 弹出打印设置；确定后返回设置，取消返回 null */
function askPrintSettings(kind) {
  const s = loadPrintSettings(kind);
  return new Promise(resolve => {
    let done = false;
    const body = document.createElement('div');
    body.innerHTML = `
      <div class="field-row">
        <div class="field"><span>纸张</span><select name="paper">${Object.entries(PAPERS).map(([k, p]) => `<option value="${k}" ${k === s.paper ? 'selected' : ''}>${p.name}</option>`).join('')}</select></div>
        <div class="field"><span>方向</span><select name="orient"><option value="portrait" ${s.orient === 'portrait' ? 'selected' : ''}>纵向</option><option value="landscape" ${s.orient === 'landscape' ? 'selected' : ''}>横向</option></select></div>
      </div>
      <div class="field-row">
        ${kind === 'voucher' ? `<div class="field"><span>每页打印凭证</span><select name="perPage">${[1, 2, 3].map(n => `<option value="${n}" ${n === +s.perPage ? 'selected' : ''}>${n} 张</option>`).join('')}</select></div>` : ''}
        <div class="field"><span>缩放</span><select name="scale">${[120, 110, 100, 90, 80, 70, 60].map(n => `<option value="${n}" ${n === +s.scale ? 'selected' : ''}>${n}%</option>`).join('')}</select></div>
      </div>
      <p class="hint">设置会被记住，下次打印时自动使用。${kind === 'voucher' ? 'A4 纵向每页 2 张最常用；分录行数较多的凭证会自动单独占一页。' : '表格列数多（如科目余额表）时，纵向放不下可以把缩放调小，或改为横向。'}
      <br>“凭证纸”是固定尺寸（宽 240mm × 高 140mm），方向选项对它不起作用，请在打印机设置里也选择同样的纸张。</p>`;
    const sync = () => {
      const fixed = PAPERS[$('[name=paper]', body).value].fixed;
      $('[name=orient]', body).disabled = fixed;
    };
    $('[name=paper]', body).onchange = sync;
    sync();
    const m = modal({
      title: kind === 'voucher' ? '打印凭证' : '打印', body, width: 520,
      buttons: [
        { text: '取消', onClick: () => { done = true; resolve(null); } },
        {
          text: '打印', cls: 'primary', onClick: el => {
            const d = formData(el);
            const out = { paper: d.paper, orient: d.orient || s.orient, scale: +d.scale, perPage: +(d.perPage || 1) };
            store('print_' + kind, JSON.stringify(out));
            done = true; resolve(out);
          },
        },
      ],
    });
    const obs = new MutationObserver(() => { if (!document.body.contains(m.el)) { obs.disconnect(); if (!done) resolve(null); } });
    obs.observe(document.body, { childList: true });
  });
}
/** 打印当前页面上的报表 / 账簿 */
async function printReport() {
  const s = await askPrintSettings('report');
  if (!s) return;
  applyPrintPage(s);
  setTimeout(() => window.print(), 80);
}
