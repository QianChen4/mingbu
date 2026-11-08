/* 账簿：科目余额表、总账、明细账、辅助核算余额表 */

function reportTitle(title, right = '', left = '') {
  return `<div class="report-title"><h2>${esc(title)}</h2>
    <div class="meta"><span>核算单位：${esc(App.meta.company_name)}${left ? '　' + left : ''}</span><span>${right}</span><span>单位：元</span></div></div>`;
}
function pageHead(title, sub) {
  return `<div class="page-head no-print"><div><h1>${esc(title)}</h1><div class="sub">${esc(sub || '')}</div></div></div>`;
}
function printExportButtons() {
  return `<span class="sep"></span><button class="btn" data-act="print">打印</button><button class="btn" data-act="export">导出 Excel</button>`;
}
function bindPE(page, onExport) {
  $('[data-act=print]', page).onclick = () => printReport();
  $('[data-act=export]', page).onclick = () => onExport();
}
const ACCT_HISTORY_KEY = 'lastAcct';

/* ================= 科目余额表 ================= */
App.pages.balance = async (page, params) => {
  const [dpf, dpt] = defaultRange();
  const pf = +params.from || dpf, pt = +params.to || dpt;
  page.innerHTML = pageHead('科目余额表', '各科目的期初余额、本期发生额、本年累计和期末余额') + `
    <div class="toolbar" id="flt">${rangeControls(pf, pt)}
      <label>级次 <select name="level"><option value="1">一级</option><option value="2">二级</option><option value="9" selected>全部</option></select></label>
      <label class="check"><input type="checkbox" name="aux"> 显示辅助核算明细</label>
      <label class="check"><input type="checkbox" name="zero"> 显示无数据的科目</label>
      <button class="btn primary" id="search">查询</button>${printExportButtons()}</div>
    <div id="out"></div>`;
  let data = null;
  const load = async () => {
    const [a, b] = readRange(page);
    const f = formData($('#flt', page));
    data = await api('/api/balance?' + qs({ from: a, to: b, level: f.level, aux: f.aux ? 1 : 0, zero: f.zero ? 1 : 0 }));
    const t = data.totals;
    $('#out', page).innerHTML = `
      ${data.balanced ? '<div class="notice ok no-print">试算平衡：期初、本期发生额、期末余额的借贷合计都相等。</div>'
        : '<div class="notice err">试算不平衡！请检查期初余额。</div>'}
      ${reportTitle('科目余额表', `${rangeLabel(data.from, data.to)}`)}
      <div class="tbl-wrap"><table class="tbl">
      <thead><tr><th rowspan="2">科目编码</th><th rowspan="2">科目名称</th><th colspan="2" class="c">期初余额</th><th colspan="2" class="c">本期发生额</th><th colspan="2" class="c">本年累计发生额${Math.floor(data.from / 100) !== Math.floor(data.to / 100) ? '（' + Math.floor(data.to / 100) + '年）' : ''}</th><th colspan="2" class="c">期末余额</th></tr>
      <tr><th class="n">借方</th><th class="n">贷方</th><th class="n">借方</th><th class="n">贷方</th><th class="n">借方</th><th class="n">贷方</th><th class="n">借方</th><th class="n">贷方</th></tr></thead>
      <tbody>${data.rows.map(r => `<tr class="clickable lvl${r.level}${r.is_aux ? ' aux' : ''}" data-code="${r.code}" data-aux="${r.is_aux ? r.aux_id : ''}">
        <td class="code-txt">${r.is_aux ? '' : r.code}</td><td class="name">${esc(r.name)}</td>
        ${moneyCell(r.begin_d)}${moneyCell(r.begin_c)}${moneyCell(r.pd)}${moneyCell(r.pc)}${moneyCell(r.yd)}${moneyCell(r.yc)}${moneyCell(r.end_d)}${moneyCell(r.end_c)}</tr>`).join('')}
      <tr class="sum"><td></td><td>合计</td>${moneyCell(t.begin_d, false)}${moneyCell(t.begin_c, false)}${moneyCell(t.pd, false)}${moneyCell(t.pc, false)}${moneyCell(t.yd, false)}${moneyCell(t.yc, false)}${moneyCell(t.end_d, false)}${moneyCell(t.end_c, false)}</tr>
      </tbody></table></div><p class="hint no-print">点击任意一行可以查看该科目的明细账。</p>`;
    $$('tr[data-code]', page).forEach(tr => tr.onclick = () =>
      go('detail', { code: tr.dataset.code, aux: tr.dataset.aux, from: data.from, to: data.to }));
  };
  $('#search', page).onclick = () => load().catch(e => toast(e.message, 'err'));
  bindPE(page, () => {
    if (!data) return;
    const rows = data.rows.map(r => [r.is_aux ? '' : r.code, (r.is_aux ? '    ' : '  '.repeat(r.level - 1)) + r.name, r.begin_d, r.begin_c, r.pd, r.pc, r.yd, r.yc, r.end_d, r.end_c]);
    const t = data.totals;
    rows.push({ cells: ['', '合计', t.begin_d, t.begin_c, t.pd, t.pc, t.yd, t.yc, t.end_d, t.end_c], bold: true });
    const M = n => ({ name: n, type: 'money' });
    exportXlsx('科目余额表', [{ name: '科目编码', width: 12 }, { name: '科目名称', width: 30 }, M('期初借方'), M('期初贷方'), M('本期借方'), M('本期贷方'),
      M('本年累计借方'), M('本年累计贷方'), M('期末借方'), M('期末贷方')], rows, `${rangeLabel(data.from, data.to)}`);
  });
  await load();
};

/* ================= 总账 ================= */
App.pages.gl = async (page, params) => {
  const [dpf, dpt] = defaultRange();
  const pf = +params.from || dpf, pt = +params.to || dpt;
  const code = params.code || '1002';
  page.innerHTML = pageHead('总账', '按月列示科目的本月合计、本年累计和余额') + `
    <div class="toolbar" id="flt"><label>科目 <input type="text" name="acct" style="width:240px"></label>${rangeControls(pf, pt)}
      <label class="check"><input type="checkbox" name="all1"> 全部一级科目</label>
      <button class="btn primary" id="search">查询</button>${printExportButtons()}</div><div id="out"></div>`;
  const acc = $('[name=acct]', page);
  attachPicker(acc, { source: () => acctItems(false) });
  setPickerValue(acc, acctItem(code));
  let results = [];
  const load = async () => {
    const [a, b] = readRange(page);
    const all1 = $('[name=all1]', page).checked;
    const codes = all1 ? App.meta.accounts.filter(x => x.level === 1).map(x => x.code) : [acc.dataset.value];
    if (!codes[0]) return toast('请选择科目', 'err');
    results = [];
    for (const c of codes) {
      const d = await api('/api/gl?' + qs({ code: c, from: a, to: b }));
      if (all1 && d.rows.every(r => !r.debit && !r.credit && !r.balance)) continue;
      results.push(d);
    }
    $('#out', page).innerHTML = results.map(d => `
      ${reportTitle('总 账', rangeLabel(d.from, d.to), `科目：${d.account.code} ${esc(d.account.full_name)}`)}
      <div class="tbl-wrap" style="margin-bottom:20px"><table class="tbl"><thead><tr><th>期间</th><th>摘要</th><th class="n">借方</th><th class="n">贷方</th><th class="c">方向</th><th class="n">余额</th></tr></thead>
      <tbody>${d.rows.map(r => `<tr class="${r.type === 'ytd' ? 'ytd' : r.type === 'month' ? 'clickable' : ''}" data-p="${r.type === 'month' ? r.period : ''}" data-code="${d.account.code}">
        <td>${r.type === 'begin' ? '' : plabel(r.period)}</td><td>${r.summary}</td>${moneyCell(r.debit)}${moneyCell(r.credit)}<td class="c">${r.dir}</td>${moneyCell(r.balance, false)}</tr>`).join('')}
      </tbody></table></div>`).join('') || '<div class="empty">没有数据</div>';
    $$('tr[data-p]', page).forEach(tr => { if (tr.dataset.p) tr.onclick = () => go('detail', { code: tr.dataset.code, from: tr.dataset.p, to: tr.dataset.p }); });
  };
  $('#search', page).onclick = () => load().catch(e => toast(e.message, 'err'));
  bindPE(page, () => {
    if (!results.length) return;
    const rows = [];
    results.forEach(d => {
      rows.push({ cells: [`${d.account.code} ${d.account.full_name}`], bold: true });
      d.rows.forEach(r => rows.push([r.type === 'begin' ? '' : plabel(r.period), r.summary, r.debit, r.credit, r.dir, r.balance]));
    });
    exportXlsx('总账', [{ name: '期间', width: 14 }, { name: '摘要', width: 18 }, { name: '借方', type: 'money' }, { name: '贷方', type: 'money' },
      { name: '方向', width: 6 }, { name: '余额', type: 'money' }], rows, rangeLabel(results[0].from, results[0].to));
  });
  await load();
};

/* ================= 明细账 ================= */
App.pages.detail = async (page, params) => {
  const [dpf, dpt] = defaultRange();
  const pf = +params.from || dpf, pt = +params.to || dpt;
  const code = params.code || store(ACCT_HISTORY_KEY) || '1002';
  page.innerHTML = pageHead('明细账', '科目的逐笔发生额与滚动余额，点击凭证号可打开原凭证') + `
    <div class="toolbar" id="flt"><label>科目 <input type="text" name="acct" style="width:240px"></label>
      <label>辅助项 <input type="text" name="aux" style="width:170px" placeholder="全部"></label>
      ${rangeControls(pf, pt)}
      <button class="btn" id="prev-acct" title="上一个有数据的科目">‹</button><button class="btn" id="next-acct" title="下一个科目">›</button>
      <button class="btn primary" id="search">查询</button>${printExportButtons()}</div><div id="out"></div>`;
  const acc = $('[name=acct]', page), aux = $('[name=aux]', page);
  const auxType = () => { const a = App.acct[acc.dataset.value]; return a ? a.aux_type : ''; };
  attachPicker(acc, { source: () => acctItems(false), onPick: () => { setPickerValue(aux, null); aux.disabled = !auxType(); } });
  attachPicker(aux, { source: () => auxType() ? auxItems(auxType()) : [] });
  setPickerValue(acc, acctItem(code));
  aux.disabled = !auxType();
  if (params.aux) setPickerValue(aux, auxItem(+params.aux));
  let data = null;
  const load = async () => {
    const [a, b] = readRange(page);
    if (!acc.dataset.value) return toast('请选择科目', 'err');
    store(ACCT_HISTORY_KEY, acc.dataset.value);
    data = await api('/api/detail?' + qs({ code: acc.dataset.value, from: a, to: b, aux: aux.dataset.value || '' }));
    const ac = data.account;
    const showAcct = !ac.is_leaf, showAux = !!ac.aux_type && !aux.dataset.value;
    $('#out', page).innerHTML = `${reportTitle('明 细 账', `${rangeLabel(data.from, data.to)}`,
      `科目：${ac.code} ${esc(ac.full_name)}${aux.dataset.value ? '　' + esc(ac.aux_type) + '：' + esc(auxText(+aux.dataset.value)) : ''}`)}
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>日期</th><th>凭证号</th><th>摘要</th>${showAcct ? '<th>科目</th>' : ''}${showAux ? '<th>' + esc(ac.aux_type) + '</th>' : ''}
        <th class="n">借方</th><th class="n">贷方</th><th class="c">方向</th><th class="n">余额</th></tr></thead>
      <tbody>${data.rows.map(r => `<tr class="${r.type === 'month' ? 'sum' : r.type === 'ytd' ? 'ytd' : ''}">
        <td>${r.date || ''}</td><td>${r.voucher_id ? `<a href="#/voucher?id=${r.voucher_id}">${r.voucher}</a>` : ''}</td>
        <td class="wrap">${esc(r.summary)}</td>${showAcct ? `<td class="small">${esc(r.account || '')}</td>` : ''}${showAux ? `<td class="small">${esc(r.aux || '')}</td>` : ''}
        ${moneyCell(r.debit)}${moneyCell(r.credit)}<td class="c">${r.dir}</td>${moneyCell(r.balance, false)}</tr>`).join('')}</tbody></table></div>`;
  };
  const step = dir => {
    const list = App.meta.accounts;
    let i = list.findIndex(x => x.code === acc.dataset.value);
    i = Math.min(list.length - 1, Math.max(0, i + dir));
    setPickerValue(acc, acctItem(list[i].code));
    setPickerValue(aux, null); aux.disabled = !auxType();
    load().catch(e => toast(e.message, 'err'));
  };
  $('#prev-acct', page).onclick = () => step(-1);
  $('#next-acct', page).onclick = () => step(1);
  $('#search', page).onclick = () => load().catch(e => toast(e.message, 'err'));
  bindPE(page, () => {
    if (!data) return;
    const rows = data.rows.map(r => {
      const cells = [r.date || '', r.voucher || '', r.summary, r.account || '', r.aux || '', r.debit, r.credit, r.dir, r.balance];
      return r.type === 'month' ? { cells, bold: true } : cells;
    });
    exportXlsx('明细账-' + data.account.code + data.account.name, [{ name: '日期', width: 12 }, { name: '凭证号' }, { name: '摘要', width: 28 }, { name: '科目', width: 26 },
      { name: '辅助核算', width: 18 }, { name: '借方', type: 'money' }, { name: '贷方', type: 'money' }, { name: '方向', width: 6 }, { name: '余额', type: 'money' }],
      rows, `${data.account.code} ${data.account.full_name}　${rangeLabel(data.from, data.to)}`);
  });
  await load();
};

/* ================= 辅助核算余额表 ================= */
App.pages.auxbal = async (page, params) => {
  const [dpf, dpt] = defaultRange();
  const pf = +params.from || dpf, pt = +params.to || dpt;
  const auxAccts = () => App.meta.accounts.filter(a => a.aux_type).map(a => ({ value: a.code, code: a.code, label: a.full_name, hint: a.aux_type }));
  page.innerHTML = pageHead('辅助核算余额表', '按客户、供应商、车辆、银行账户等列示余额，例如每位客户的押金、每家供应商的欠款') + `
    <div class="toolbar" id="flt"><label>科目 <input type="text" name="acct" style="width:240px"></label>${rangeControls(pf, pt)}
      <label class="check"><input type="checkbox" name="zero"> 显示余额为零的项目</label>
      <button class="btn primary" id="search">查询</button>${printExportButtons()}</div><div id="out"></div>`;
  const acc = $('[name=acct]', page);
  attachPicker(acc, { source: auxAccts });
  setPickerValue(acc, acctItem(params.code || (App.meta.accounts.find(a => a.aux_type === '客户' && a.is_leaf) || App.meta.accounts.find(a => a.aux_type) || {}).code));
  let data = null;
  const load = async () => {
    const [a, b] = readRange(page);
    if (!acc.dataset.value) return toast('请选择设置了辅助核算的科目', 'err');
    data = await api('/api/auxbal?' + qs({ code: acc.dataset.value, from: a, to: b, zero: $('[name=zero]', page).checked ? 1 : 0 }));
    const sum = k => data.rows.reduce((s, r) => s + r[k], 0);
    $('#out', page).innerHTML = `${reportTitle('辅助核算余额表', `${rangeLabel(data.from, data.to)}`, `科目：${data.account.code} ${esc(data.account.full_name)}`)}
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th rowspan="2">编码</th><th rowspan="2">${esc(data.account.aux_type)}</th><th colspan="2" class="c">期初余额</th><th colspan="2" class="c">本期发生额</th><th colspan="2" class="c">期末余额</th></tr>
      <tr><th class="n">借方</th><th class="n">贷方</th><th class="n">借方</th><th class="n">贷方</th><th class="n">借方</th><th class="n">贷方</th></tr></thead>
      <tbody>${data.rows.map(r => `<tr class="clickable" data-aux="${r.aux_id}"><td class="code-txt">${esc(r.aux_code)}</td><td>${esc(r.aux_name)}</td>
        ${moneyCell(r.begin_d)}${moneyCell(r.begin_c)}${moneyCell(r.pd)}${moneyCell(r.pc)}${moneyCell(r.end_d)}${moneyCell(r.end_c)}</tr>`).join('')
      || '<tr><td colspan="8" class="empty">没有数据</td></tr>'}
      <tr class="sum"><td></td><td>合计（${data.rows.length} 项）</td>${['begin_d', 'begin_c', 'pd', 'pc', 'end_d', 'end_c'].map(k => moneyCell(sum(k), false)).join('')}</tr>
      </tbody></table></div>`;
    $$('tr[data-aux]', page).forEach(tr => tr.onclick = () => go('detail', { code: data.account.code, aux: tr.dataset.aux, from: data.from, to: data.to }));
  };
  $('#search', page).onclick = () => load().catch(e => toast(e.message, 'err'));
  bindPE(page, () => {
    if (!data) return;
    const M = n => ({ name: n, type: 'money' });
    exportXlsx('辅助核算余额表-' + data.account.name, [{ name: '编码' }, { name: data.account.aux_type, width: 24 }, M('期初借方'), M('期初贷方'), M('本期借方'), M('本期贷方'), M('期末借方'), M('期末贷方')],
      data.rows.map(r => [r.aux_code, r.aux_name, r.begin_d, r.begin_c, r.pd, r.pc, r.end_d, r.end_c]),
      `${data.account.code} ${data.account.full_name}　${rangeLabel(data.from, data.to)}`);
  });
  await load();
};
