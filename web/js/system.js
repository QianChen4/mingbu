/* 系统：软件更新、启动密码、数据位置（没选账套时也能打开） */

function sysHead(title, sub) {
  return `<div class="page-head no-print"><div><h1>${esc(title)}</h1><div class="sub">${esc(sub || '')}</div></div></div>`;
}
const fmtBytes = n => n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';

/** 立即重启：关掉后台程序再用启动程序打开（会用新版本），页面等新后台起来后自动刷新 */
async function restartApp(box) {
  const dirty = App.tabs.filter(isDirty).map(tabTitle);
  if (dirty.length && !await confirmBox(`“${dirty.join('、')}”还有没保存的内容，重启后就没有了。确定现在重启吗？`, '重启', true)) return;
  let before = App.started;
  try { before = (await api('/api/version')).started; } catch (e) { /* 忽略 */ }
  try { await api('/api/restart', {}); } catch (e) { return toast(e.message, 'err'); }
  App.quitting = true;
  if (box) box.innerHTML = '<h2>正在重启…</h2><div class="upd-msg">正在用新版本重新打开，页面会自动刷新，请稍等。</div><div class="pbar busy"><i></i></div>';
  const t0 = Date.now();
  const wait = async () => {
    try {
      const v = await fetch('/api/version').then(r => r.json());
      if (v.started && v.started !== before) { location.reload(); return; }
    } catch (e) { /* 还没起来 */ }
    if (Date.now() - t0 > 60000) {
      if (box) box.innerHTML = `<div class="notice warn">等了一分钟软件还没重新打开。请关掉这个窗口，再双击“${APP_NAME}”图标打开。</div>`;
      return;
    }
    setTimeout(wait, 800);
  };
  setTimeout(wait, 1200);
}

/* ================= 软件更新 ================= */
App.pages.update = async (page) => {
  const us = await api('/api/update/settings');
  const isWin = us.platform === 'windows';
  page.innerHTML = sysHead('软件更新', '更新只换程序，账套数据不受影响；更新前会自动备份所有账套') + `
    <div class="card" style="max-width:820px">
      <h2>当前版本：v${esc(us.version)}</h2>
      <div class="toolbar"><button class="btn primary" id="check">检查更新</button>
        <span class="hint" id="chk-hint">有新版本时会自动下载并安装，网络不好时会自动换下载地址、断了也能接着下载。</span></div>
      <div id="upd-box"></div>
      ${us.pending_restart ? `<div class="notice info">新版本 ${esc(us.current)} 已经装好，重启后生效。
        <button class="btn primary small" id="restart-pending" style="margin-left:8px">立即重启</button></div>` : ''}
    </div>
    <div class="card" style="max-width:820px">
      <h2>离线更新（不需要联网）</h2>
      <p class="hint">拿到新版本的完整安装包（例如 ${isWin ? 'caiwu-jizhang-windows.zip' : 'caiwu-jizhang-mac.zip'}）后，不用解压，直接在这里选择它。
        ${isWin ? '这个安装包和新装软件用的是同一个文件：更新后把整个软件文件夹拷到别的电脑上，打开的也是新版本。' : ''}</p>
      <div class="toolbar"><input type="file" id="upd-file" accept=".zip"><button class="btn" id="upd-btn">用这个安装包更新</button></div>
    </div>
    ${us.layout === 'versioned' ? `<div class="card" style="max-width:820px">
      <h2>退回上一个版本</h2>
      <p class="hint">新版本用着有问题时，可以退回上一个版本（账套数据不变）。软件里保留了这些版本：
        ${(us.installed || []).map(v => `<b>${esc(v)}</b>${v === us.current ? '（正在用）' : ''}`).join('、') || '—'}</p>
      <button class="btn" id="rollback" ${us.can_rollback ? '' : 'disabled'}>退回上一个版本</button></div>` : ''}
    <details class="card" style="max-width:820px"><summary><b>更新设置</b></summary>
      <div class="toolbar" style="margin-top:10px"><label><input type="checkbox" id="auto-check" ${us.auto_check !== false ? 'checked' : ''}>
        打开软件时自动检查新版本（有新版本时在右下角提示；连不上网时不提示）</label></div>
      <p class="hint">更新地址（latest.json）。一般不用改；以后换了发布的地方（例如阿里云 OSS），在这里填新地址。</p>
      <div class="toolbar"><input type="text" id="upd-url" value="${esc(us.url || '')}" placeholder="${esc(us.default_url || 'https://…/latest.json')}" style="width:520px">
        <button class="btn" id="url-save">保存地址</button><button class="btn link" id="url-reset">恢复默认</button></div>
      <p class="hint">软件文件夹：${esc(us.home || '')}</p>
    </details>`;
  const box = $('#upd-box', page);
  const lockBtns = on => ['#check', '#upd-btn', '#rollback'].forEach(id => { const b = $(id, page); if (b) b.disabled = on || (id === '#rollback' && !us.can_rollback); });
  const draw = st => {
    if (!st || st.state === 'idle') { box.innerHTML = ''; return; }
    const idx = st.stages.findIndex(x => x.key === st.stage);
    const steps = st.stages.map((x, i) => {
      let cls = i < idx ? 'done' : i === idx ? 'cur' : '';
      if (st.state === 'error' && i === idx) cls = 'fail';
      if (st.state === 'done') cls = i < st.stages.length - 1 ? 'done' : 'cur';
      const mark = cls === 'done' ? '✓' : cls === 'fail' ? '✕' : String(i + 1);
      return `<li class="${cls}"><span class="dot">${mark}</span>${esc(x.name)}</li>`;
    }).join('');
    let pct = null, detail = '';
    if (st.state === 'running' && st.total > 0) {
      pct = Math.min(100, Math.floor(st.done * 100 / st.total));
      if (st.stage === 'download') detail = `已下载 ${fmtBytes(st.done)} / ${fmtBytes(st.total)}${st.speed ? ' · ' + fmtBytes(st.speed) + '/秒' : ''}`;
      else detail = `${st.done} / ${st.total}`;
    } else if (st.state === 'running' && st.stage === 'download') detail = st.done ? `已下载 ${fmtBytes(st.done)}` : '正在连接…';
    const bar = st.state === 'running' ? (pct === null ? '<div class="pbar busy"><i></i></div>' : `<div class="pbar"><i style="width:${pct}%"></i></div>`) : '';
    let foot = '';
    if (st.state === 'done') {
      const r = st.result || {};
      foot = `<div class="notice ok">${r.rollback ? `已切换到 v${esc(r.new_version)}。` : `新版本 v${esc(r.new_version)} 已经装好（原来是 v${esc(r.old_version)}）。`}
          点“立即重启”就会用新版本打开，打开的标签会自动刷新。</div>
        <button class="btn primary" id="restart-now">立即重启</button>`;
    } else if (st.state === 'error') foot = `<div class="notice err"><b>更新没有完成：</b>${esc(st.error)}</div>`;
    box.innerHTML = `<ol class="upd-steps">${steps}</ol>
      ${st.state === 'running' ? `<div class="upd-msg">${esc(st.message || '')}</div>${bar}
        <div class="hint">${esc(detail)}${st.source ? `${detail ? ' · ' : ''}下载地址：<b>${esc(st.source)}</b>` : ''} · 已用时 ${st.elapsed} 秒</div>` : ''}
      ${foot}
      ${st.log && st.log.length ? `<details ${st.state === 'error' ? 'open' : ''} style="margin-top:8px"><summary class="hint">详细过程（${st.log.length} 条）</summary>
        <pre class="upd-log">${esc(st.log.join('\n'))}</pre></details>` : ''}`;
    const rb = $('#restart-now', box);
    if (rb) rb.onclick = () => restartApp(box);
  };
  let timer = null;
  const poll = async () => {
    let st;
    try { st = await api('/api/update/progress'); }
    catch (e) { if (page.isConnected) timer = setTimeout(poll, 1500); return; }
    if (!page.isConnected) return;
    draw(st);
    lockBtns(st.state === 'running');
    if (st.state === 'running') timer = setTimeout(poll, 500);
  };
  const start = async (path, body) => {
    clearTimeout(timer);
    lockBtns(true);
    try { draw(await api(path, body)); poll(); }
    catch (e) { lockBtns(false); box.innerHTML = `<div class="notice err">${esc(e.message)}</div>`; }
  };
  // 打开这个页面时如果有更新正在进行或刚完成，接着显示
  api('/api/update/progress').then(st => { if (st.state !== 'idle') { draw(st); if (st.state === 'running') poll(); } }).catch(() => {});

  $('#check', page).onclick = async () => {
    lockBtns(true);
    box.innerHTML = '<div class="upd-msg">正在检查新版本…（GitHub 连不上时会自动改用国内加速地址，可能要等十几秒）</div><div class="pbar busy"><i></i></div>';
    let r;
    try { r = await api('/api/update/check', {}); }
    catch (e) { lockBtns(false); box.innerHTML = `<div class="notice err">${esc(e.message)}</div>`; return; }
    if (!r.has_update) { lockBtns(false); box.innerHTML = `<div class="notice ok">已经是最新版本（v${esc(r.current)}）。</div>`; return; }
    box.innerHTML = `<div class="notice info">发现新版本 <b>v${esc(r.latest)}</b>，开始下载…
      ${r.notes ? `<div style="white-space:pre-wrap;margin-top:6px">${esc(r.notes)}</div>` : ''}</div>`;
    start('/api/update/online/start', {});
  };
  $('#upd-btn', page).onclick = async () => {
    const file = $('#upd-file', page).files[0];
    if (!file) return toast('请先选择安装包', 'err');
    box.innerHTML = '<div class="upd-msg">正在读取安装包…</div><div class="pbar busy"><i></i></div>';
    let data;
    try { data = await fileToB64(file); } catch (e) { box.innerHTML = `<div class="notice err">读取文件失败：${esc(e.message)}</div>`; return; }
    start('/api/update/start', { data });
  };
  const rb = $('#rollback', page);
  if (rb) rb.onclick = async () => {
    if (!await confirmBox('退回上一个版本吗？账套数据不变，重启后生效。', '退回')) return;
    start('/api/update/rollback', {});
  };
  const rp = $('#restart-pending', page);
  if (rp) rp.onclick = () => restartApp(box);
  $('#auto-check', page).onchange = async e => {
    try { await api('/api/update/settings', { auto_check: e.target.checked }); toast(e.target.checked ? '已打开自动检查' : '已关闭自动检查', 'ok'); }
    catch (err) { toast(err.message, 'err'); }
  };
  $('#url-save', page).onclick = async () => {
    try { await api('/api/update/settings', { url: $('#upd-url', page).value.trim() }); toast('已保存', 'ok'); } catch (e) { toast(e.message, 'err'); }
  };
  $('#url-reset', page).onclick = async () => {
    try { await api('/api/update/settings', { url: '' }); $('#upd-url', page).value = us.default_url || ''; toast('已恢复默认地址', 'ok'); } catch (e) { toast(e.message, 'err'); }
  };
};

/* ================= 启动密码 ================= */
function showRecoveryCode(code, then) {
  modal({
    title: '请记下恢复码', width: 460,
    body: `<p>忘记启动密码时，用这个恢复码可以重设密码。<b>它只显示这一次</b>，请抄在纸上或拍照，放在安全的地方：</p>
      <div class="recovery-code" style="text-align:center">${esc(code)}</div>
      <p class="hint">恢复码也丢了：退出软件，删除数据文件夹里的 security.json，启动密码就取消了（账套数据不受影响）。</p>`,
    buttons: [{ text: '我已记下', cls: 'primary', onClick: () => { if (then) setTimeout(then, 0); } }],
  });
}
App.pages.security = async (page) => {
  const st = await api('/api/lock/status');
  App.lock = st;
  const idleSel = v => [0, 5, 10, 15, 30, 60].map(n => `<option value="${n}" ${n === v ? 'selected' : ''}>${n ? n + ' 分钟没有操作' : '不自动锁定'}</option>`).join('');
  page.innerHTML = sysHead('启动密码', '打开软件时要输入密码；一台电脑一个密码，对所有账套都有效') + (st.enabled ? `
    <div class="notice ok" style="max-width:640px">已经设置了启动密码。</div>
    <div class="card" style="max-width:640px"><h2>自动锁定</h2>
      <div class="toolbar"><select id="idle">${idleSel(st.idle_minutes)}</select><span class="hint">后自动锁定，要重新输入密码</span></div>
      <div class="field"><span>密码提示（可不填，锁屏时显示，别直接写密码）</span><input type="text" id="hint" value="${esc(st.hint || '')}" maxlength="40"></div>
      <button class="btn primary" id="save-opt">保存</button> <button class="btn" id="lock-now">现在锁定</button></div>
    <div class="card" style="max-width:640px"><h2>修改密码</h2>
      <div class="field"><span>原密码</span><input type="password" id="old" autocomplete="current-password"></div>
      <div class="field-row"><div class="field"><span>新密码（至少 4 位）</span><input type="password" id="new1" autocomplete="new-password"></div>
        <div class="field"><span>再输一次</span><input type="password" id="new2" autocomplete="new-password"></div></div>
      <p class="hint">改密码后会生成新的恢复码，旧的作废。</p>
      <button class="btn primary" id="change">修改密码</button></div>
    <div class="card" style="max-width:640px"><h2>取消启动密码</h2>
      <div class="toolbar"><input type="password" id="dis-pw" placeholder="输入现在的密码"><button class="btn danger" id="disable">取消启动密码</button></div></div>` : `
    <div class="card" style="max-width:640px"><h2>设置启动密码</h2>
      <p class="hint">设置后，每次打开软件、或离开电脑一段时间后，要输入密码才能看账。设置时会给你一个恢复码，忘记密码时用它重设。</p>
      <div class="field-row"><div class="field"><span>密码（至少 4 位）</span><input type="password" id="new1" autocomplete="new-password"></div>
        <div class="field"><span>再输一次</span><input type="password" id="new2" autocomplete="new-password"></div></div>
      <div class="field"><span>密码提示（可不填，锁屏时显示，别直接写密码）</span><input type="text" id="hint" maxlength="40"></div>
      <div class="toolbar"><select id="idle">${idleSel(10)}</select><span class="hint">后自动锁定</span></div>
      <button class="btn primary" id="set">设置启动密码</button></div>`) +
    `<p class="hint" style="max-width:640px">密码和恢复码都忘了：退出软件，删除数据文件夹（${esc(App.dataDir || 'data')}）里的 security.json，启动密码就取消了，账套数据不受影响。</p>`;
  const after = () => { renderChrome(); reloadTab(); };
  const pw2 = () => {
    const a = $('#new1', page).value, b = $('#new2', page).value;
    if (a !== b) throw new Error('两次输入的新密码不一样');
    return a;
  };
  const q = id => $(id, page);
  if (q('#set')) q('#set').onclick = async () => {
    try {
      const r = await api('/api/lock/set', { password: pw2(), hint: q('#hint').value, idle_minutes: +q('#idle').value });
      setLockToken(r.token);
      App.lock = await api('/api/lock/status');
      showRecoveryCode(r.recovery_code, after);
    } catch (e) { toast(e.message, 'err'); }
  };
  if (q('#change')) q('#change').onclick = async () => {
    try {
      const r = await api('/api/lock/set', { password: pw2(), old_password: q('#old').value, hint: q('#hint').value });
      setLockToken(r.token);
      showRecoveryCode(r.recovery_code, after);
    } catch (e) { toast(e.message, 'err'); }
  };
  if (q('#save-opt')) q('#save-opt').onclick = async () => {
    try { await api('/api/lock/options', { idle_minutes: +q('#idle').value, hint: q('#hint').value }); toast('已保存', 'ok'); App.lock = await api('/api/lock/status'); }
    catch (e) { toast(e.message, 'err'); }
  };
  if (q('#lock-now')) q('#lock-now').onclick = lockNow;
  if (q('#disable')) q('#disable').onclick = async () => {
    try { await api('/api/lock/disable', { password: q('#dis-pw').value }); setLockToken(''); App.lock = { enabled: false }; toast('已取消启动密码', 'ok'); after(); }
    catch (e) { toast(e.message, 'err'); }
  };
};

/* ================= 数据位置、找回旧账套 ================= */
function oldDataHtml(found) {
  if (!found.length) return '<div class="notice info">没有找到别的地方的账套。</div>';
  return found.map((f, i) => `<div class="card old-data" data-i="${i}" style="margin:10px 0">
    <div><b>${esc(f.folder)}</b></div>
    <table class="tbl" style="margin:8px 0"><thead><tr><th style="width:30px"></th><th>公司</th><th class="n">凭证</th><th>最后修改</th><th>文件</th></tr></thead><tbody>
    ${f.companies.map(c => `<tr><td><input type="checkbox" checked data-file="${esc(c.file)}"></td><td>${esc(c.name)}</td><td class="n">${c.vouchers}</td><td>${esc(c.modified || '—')}</td><td class="muted">${esc(c.file)}</td></tr>`).join('')}
    </tbody></table>
    <div class="toolbar"><label class="check"><input type="radio" name="mode${i}" value="new" checked> 作为新账套导入（不会覆盖现有的）</label>
      <label class="check"><input type="radio" name="mode${i}" value="replace"> 有同名账套时覆盖</label>
      <button class="btn primary" data-import="${i}">导入选中的账套</button></div></div>`).join('');
}
function bindOldData(root, found, onDone) {
  $$('[data-import]', root).forEach(b => b.onclick = async () => {
    const i = +b.dataset.import, card = $(`.old-data[data-i="${i}"]`, root);
    const files = $$('input[data-file]:checked', card).map(x => x.dataset.file);
    if (!files.length) return toast('请勾选要导入的账套', 'err');
    const mode = $(`[name=mode${i}]:checked`, card).value;
    try {
      const r = await api('/api/data/import_folder', { folder: found[i].folder, files, mode });
      toast('导入完成', 'ok');
      card.innerHTML = `<div class="notice ok">${r.results.map(esc).join('<br>')}</div>`;
      if (onDone) onDone();
    } catch (e) { toast(e.message, 'err'); }
  });
}
App.pages.datadir = async (page) => {
  const loc = await api('/api/data/location');
  page.innerHTML = sysHead('数据位置', '账套数据存在哪里，以及把别处的旧账套找回来') + `
    <div class="card" style="max-width:820px"><h2>账套数据存在这里</h2>
      <p><b>${esc(loc.data_dir)}</b> <button class="btn small" data-open="data">打开文件夹</button></p>
      <p class="hint">每个账套是一个 c数字.db 文件（现在有 ${loc.files.length} 个：${esc(loc.files.join('、') || '无')}）。软件更新时这个文件夹不会被改动。</p>
      <p>自动备份在：<b>${esc(loc.backup_dir)}</b> <button class="btn small" data-open="backup">打开文件夹</button></p></div>
    <div class="card" style="max-width:820px"><h2>找回别处的旧账套</h2>
      <p class="hint">以前在别的文件夹里用过这个软件（例如解压过好几份），账套可能存在那边。点“自动查找”会在桌面、文档、下载和各个磁盘里找，大约十几秒；
        也可以直接填文件夹位置（旧软件的文件夹，或者它里面的 data 文件夹）。</p>
      <div class="toolbar"><button class="btn primary" id="scan">自动查找</button>
        <input type="text" id="folder" placeholder="例如 D:\\财务记账软件" style="width:340px"><button class="btn" id="inspect">查看这个文件夹</button></div>
      <div id="found"></div></div>`;
  $$('[data-open]', page).forEach(b => b.onclick = () => api('/api/data/open_folder', { which: b.dataset.open }).catch(e => toast(e.message, 'err')));
  const out = $('#found', page);
  const show = found => { out.innerHTML = oldDataHtml(found); bindOldData(out, found); };
  $('#scan', page).onclick = async () => {
    out.innerHTML = '<div class="upd-msg">正在查找…</div><div class="pbar busy"><i></i></div>';
    try { const r = await api('/api/data/scan', {}); show(r.found); if (!r.complete) toast('查找时间到了，可能没有找全；可以直接填文件夹位置', 'warn'); }
    catch (e) { out.innerHTML = `<div class="notice err">${esc(e.message)}</div>`; }
  };
  $('#inspect', page).onclick = async () => {
    try { show([await api('/api/data/inspect', { folder: $('#folder', page).value })]); }
    catch (e) { out.innerHTML = `<div class="notice err">${esc(e.message)}</div>`; }
  };
};
