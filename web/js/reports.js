/* 财务报表：资产负债表、利润表、现金流量表、单车盈利分析 */

function reportRangePage(page, params, title, sub, defRange, hint) {
  let pf = +params.from || 0, pt = +params.to || +params.period || 0;
  if (!pf || !pt) [pf, pt] = defRange(pt || App.meta.current_period);
  if (pf > pt) pf = pt;
  page.innerHTML = pageHead(title, sub) + `
    <div class="toolbar" id="flt">${rangeControls(pf, pt)}<button class="btn primary" id="search">生成报表</button>${printExportButtons()}</div>
    <p class="hint no-print" style="margin:-4px 0 12px">${hint}</p><div id="out"></div>`;
}
const curMonth = p => [p, p];
const yearToDate = p => [Math.max(Math.floor(p / 100) * 100 + 1, App.meta.start_period), p];

/* ================= 资产负债表 ================= */
App.pages.bs = async (page, params) => {
  reportRangePage(page, params, '资产负债表', '结束月份月末的资产、负债和所有者权益，并与起始月份月初对比', yearToDate,
    '“期末余额”取结束月份的月末数；对比列取起始月份的月初数——起始月份选 1 月时就是“年初余额”。可以跨年度，例如 2026年9月 至 2027年2月。');
  let data = null, pairs = [];
  const load = async () => {
    const [a, b] = readRange(page);
    data = await api('/api/report/bs?' + qs({ from: a, to: b }));
    pairs = pairBalanceSheet(data.rows);
    const lineNo = bsLineNo(data.rows);
    const half = (r, first) => {
      const cls = first ? '' : ' class="bs-right"';
      if (!r) return `<td${cls}></td><td></td><td></td><td></td>`;
      if (r.header) return `<td${cls} colspan="4"><b>${esc(r.name)}</b></td>`;
      const name = `<td${first ? '' : ' class="bs-right"'} title="${esc(r.formula)}"><span class="${r.total ? '' : r.memo ? 'ind2 muted' : 'ind'}">${r.total ? '<b>' + esc(r.name) + '</b>' : esc(r.name)}</span></td>`;
      const m = v => `<td class="n${r.total ? ' b' : ''}${r.memo ? ' muted' : ''}${v < 0 ? ' neg' : ''}">${fmt(v)}</td>`;
      return `${name}<td class="c muted">${lineNo[r.key] || ''}</td>${m(r.end)}${m(r.begin)}`;
    };
    const c = data.checks;
    $('#out', page).innerHTML = `
      ${c.end_diff || c.begin_diff ? `<div class="notice err">资产负债表不平衡：期末差额 ${fmtN(c.end_diff)}，期初差额 ${fmtN(c.begin_diff)}。请检查期初余额是否试算平衡。</div>`
        : '<div class="notice ok no-print">资产总计 = 负债和所有者权益总计，报表平衡。鼠标停在项目上可以看到取数公式。</div>'}
      ${reportTitle('资产负债表', data.label, data.form_no)}
      <div class="tbl-wrap"><table class="tbl bs-table">
        <colgroup><col class="bs-name"><col class="bs-no"><col><col><col class="bs-name"><col class="bs-no"><col><col></colgroup>
        <thead><tr><th>资产</th><th class="c">行次</th><th class="n">期末余额</th><th class="n">${esc(data.begin_label)}</th>
          <th class="bs-right">负债和所有者权益</th><th class="c">行次</th><th class="n">期末余额</th><th class="n">${esc(data.begin_label)}</th></tr></thead>
        <tbody>${pairs.map(([l, r]) => `<tr>${half(l, true)}${half(r, false)}</tr>`).join('')}</tbody>
      </table></div>
      <p class="hint no-print">本月尚未结转的损益已包含在“未分配利润”中，所以结转前后报表都能平衡。没有对应科目的项目显示为空。${data.rows.some(r => r.memo) ? '“固定资产”按“原价 − 累计折旧 − 减值准备 ± 固定资产清理”的净额填列（“无形资产”同理扣除累计摊销），下面灰色的“其中 / 减”行列出各部分金额，只供核对，不重复计入合计，也不编行次。' : ''}</p>`;
  };
  $('#search', page).onclick = () => load().catch(e => toast(e.message, 'err'));
  bindPE(page, () => {
    if (!data) return;
    const lineNo = bsLineNo(data.rows);
    const cellsOf = r => !r ? ['', '', '', ''] : r.header ? [r.name, '', '', ''] : [r.memo ? '　　' + r.name : r.name, lineNo[r.key] || '', r.end, r.begin];
    const rows = pairs.map(([l, r]) => {
      const cells = cellsOf(l).concat(cellsOf(r));
      return (l && l.total) || (r && r.total) || (l && l.header) ? { cells, bold: true } : cells;
    });
    exportXlsx('资产负债表', [{ name: '资产', width: 26 }, { name: '行次', type: 'number', width: 6 }, { name: '期末余额', type: 'money', width: 17 },
      { name: data.begin_label, type: 'money', width: 17 }, { name: '负债和所有者权益（或股东权益）', width: 30 }, { name: '行次', type: 'number', width: 6 },
      { name: '期末余额', type: 'money', width: 17 }, { name: data.begin_label, type: 'money', width: 17 }], rows, data.label + '　' + data.form_no);
  });
  await load();
};

/** 行次：附注行（如“其中：固定资产原价”“减：累计折旧”）只列示构成，不编行次 */
function bsLineNo(rows) {
  const out = {};
  let n = 0;
  rows.forEach(r => { if (!r.memo) out[r.key] = ++n; });
  return out;
}

/** 资产负债表左右两栏逐行配对：流动部分的合计行对齐，资产总计与负债和所有者权益总计对齐 */
function pairBalanceSheet(rows) {
  const g = (side, grp) => rows.filter(r => (side === 'A' ? r.side === 'A' : r.side !== 'A') && r.group === grp);
  const H = name => ({ header: true, name });
  const out = [];
  // 第一段：流动资产 ↔ 流动负债，两边的“合计”行放在同一行
  const ac = g('A', 'cur'), lc = g('L', 'cur');
  out.push([H('流动资产：'), H('流动负债：')]);
  const n1 = Math.max(ac.length, lc.length) - 1;
  for (let i = 0; i < n1; i++) out.push([i < ac.length - 1 ? ac[i] : null, i < lc.length - 1 ? lc[i] : null]);
  out.push([ac[ac.length - 1], lc[lc.length - 1]]);
  // 第二段：非流动资产 ↔ 非流动负债、负债合计、所有者权益
  const an = g('A', 'noncur');
  const right = [H('非流动负债：')].concat(g('L', 'noncur'), g('L', 'ltotal'), [H('所有者权益（或股东权益）：')], g('L', 'eq'));
  const left = [H('非流动资产：')].concat(an.slice(0, -1));
  const n2 = Math.max(left.length + 1, right.length);
  for (let i = 0; i < n2; i++) {
    const l = i < left.length ? left[i] : (i === n2 - 1 ? an[an.length - 1] : null);
    out.push([l, right[i] || null]);
  }
  // 总计行
  out.push([g('A', 'total')[0], g('L', 'total')[0]]);
  return out;
}

/* ================= 利润表 ================= */
App.pages.is = async (page, params) => {
  reportRangePage(page, params, '利润表', '所选期间的收入、成本、费用和利润', curMonth,
    '“本期金额”是所选期间的合计，可以跨年度（例如 2026年9月 至 2027年2月）；“本年累计”是结束月份所在年度 1 月至结束月份；“上年同期”是所选期间整体提前一年。选 1 月至 12 月即为年度利润表。');
  let data = null;
  const load = async () => {
    const [a, b] = readRange(page);
    data = await api('/api/report/is?' + qs({ from: a, to: b }));
    const curLabel = data.single ? '本月金额' : '本期金额';
    const ytdLabel = `本年累计金额（${Math.floor(data.to / 100)}年）`;
    let n = 0;
    $('#out', page).innerHTML = `${reportTitle('利 润 表', data.label, data.form_no)}
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>项目</th><th class="c">行次</th><th class="n">${curLabel}</th><th class="n">${ytdLabel}</th>${data.has_prev ? `<th class="n">上年同期（${esc(data.prev_label)}）</th>` : ''}</tr></thead>
      <tbody>${data.rows.map(r => `<tr class="${r.total ? 'total sum' : ''}${r.memo ? ' memo' : ''}" title="${esc(r.formula)}">
        <td class="ind${r.indent}">${esc(r.name)}</td><td class="c muted">${++n}</td>${moneyCell(r.month)}${moneyCell(r.ytd)}${data.has_prev ? moneyCell(r.prev) : ''}</tr>`).join('')}</tbody></table></div>
      <p class="hint no-print">利润表取的是损益类科目的实际发生额，不包括月末“结转损益”凭证，所以结转前后数字一致。</p>`;
  };
  $('#search', page).onclick = () => load().catch(e => toast(e.message, 'err'));
  bindPE(page, () => {
    if (!data) return;
    const cols = [{ name: '项目', width: 40 }, { name: '行次', type: 'number', width: 6 }, { name: data.single ? '本月金额' : '本期金额', type: 'money', width: 18 },
      { name: `本年累计金额（${Math.floor(data.to / 100)}年）`, type: 'money', width: 22 }];
    if (data.has_prev) cols.push({ name: `上年同期（${data.prev_label}）`, type: 'money', width: 26 });
    const rows = data.rows.map((r, i) => {
      const cells = ['　'.repeat(r.indent) + r.name, i + 1, r.month, r.ytd];
      if (data.has_prev) cells.push(r.prev);
      return r.total ? { cells, bold: true } : cells;
    });
    exportXlsx('利润表', cols, rows, data.label);
  });
  await load();
};

/* ================= 现金流量表 ================= */
App.pages.cf = async (page, params) => {
  reportRangePage(page, params, '现金流量表', '所选期间现金及现金等价物的流入和流出（直接法）', curMonth,
    '“本期金额”是所选期间的合计，可以跨年度；“本年累计”是结束月份所在年度 1 月至结束月份。选 1 月至 12 月即为年度现金流量表。');
  let data = null;
  const load = async () => {
    const [a, b] = readRange(page);
    data = await api('/api/report/cf?' + qs({ from: a, to: b }));
    const c = data.checks;
    const curLabel = data.single ? '本月金额' : '本期金额';
    const ytdLabel = `本年累计金额（${Math.floor(data.to / 100)}年）`;
    const notes = [];
    if (c.unassigned_month || c.unassigned_ytd) notes.push(`有现金类分录没有指定现金流量项目：本期 ${fmtN(c.unassigned_month)}，本年 ${fmtN(c.unassigned_ytd)}。可在凭证查询中按现金科目筛选后补充。`);
    if (c.internal_month || c.internal_ytd) notes.push(`“现金内部划转”项目借贷不相抵：本期 ${fmtN(c.internal_month)}，本年 ${fmtN(c.internal_ytd)}。`);
    const ok = !c.month_diff && !c.ytd_diff;
    $('#out', page).innerHTML = `
      ${ok ? `<div class="notice ok no-print">核对通过：期末现金余额 ${fmtN(c.book_end)} 与账面货币资金余额一致。</div>`
        : `<div class="notice err">期末现金余额与账面不一致（本期差额 ${fmtN(c.month_diff)}，本年差额 ${fmtN(c.ytd_diff)}）。</div>`}
      ${notes.map(t => `<div class="notice warn">${esc(t)}</div>`).join('')}
      ${reportTitle('现金流量表', data.label, data.form_no)}
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>项目</th><th class="n">${curLabel}</th><th class="n">${ytdLabel}</th></tr></thead>
      <tbody>${data.rows.map(r => r.header ? `<tr class="head"><td colspan="3">${esc(r.name)}</td></tr>`
        : `<tr class="${r.total ? 'total sum' : ''}${r.subtotal ? ' total' : ''}"><td class="${r.indent ? 'ind' + r.indent : ''}">${esc(r.name)}</td>${moneyCell(r.month)}${moneyCell(r.ytd)}</tr>`).join('')}</tbody></table></div>
      <p class="hint no-print">现金流量项目在录入凭证时指定（系统会根据对方科目自动建议）。现金、银行、微信、支付宝之间的互相划转不计入现金流量。</p>`;
  };
  $('#search', page).onclick = () => load().catch(e => toast(e.message, 'err'));
  bindPE(page, () => {
    if (!data) return;
    const rows = data.rows.map(r => r.header ? { cells: [r.name], bold: true }
      : (r.total ? { cells: [r.name, r.month, r.ytd], bold: true } : ['　'.repeat(r.indent || 0) + r.name, r.month, r.ytd]));
    exportXlsx('现金流量表', [{ name: '项目', width: 50 }, { name: data.single ? '本月金额' : '本期金额', type: 'money', width: 18 },
      { name: `本年累计金额（${Math.floor(data.to / 100)}年）`, type: 'money', width: 22 }], rows, data.label);
  });
  await load();
};

/* ================= 单车盈利分析 ================= */
App.pages.vprofit = async (page, params) => {
  if (!hasFeature('vehicles')) {
    page.innerHTML = pageHead('单车盈利分析', '') + '<div class="notice info">本账套所选行业没有车辆功能。</div>';
    return;
  }
  let [dpf, dpt] = defaultRange();
  if (+params.from && +params.to && +params.from <= +params.to) [dpf, dpt] = [+params.from, +params.to];
  page.innerHTML = pageHead('单车盈利分析', '按车辆汇总租金收入、折旧、保险、维修等直接成本') + `
    <div class="toolbar" id="flt">${rangeControls(dpf, dpt)}<input type="text" name="q" placeholder="车牌号筛选" style="width:130px">
      <button class="btn primary" id="search">查询</button>${printExportButtons()}</div><div id="out"></div>`;
  let data = null;
  const load = async () => {
    const [a, b] = readRange(page);
    data = await api('/api/vehicle/profit?' + qs({ from: a, to: b }));
    const q = $('[name=q]', page).value.trim().toUpperCase();
    const rows = data.rows.filter(r => !q || r.plate.includes(q));
    const t = data.total;
    const lossCount = data.rows.filter(r => r.aux_id && r.profit < 0).length;
    $('#out', page).innerHTML = `
      <div class="stat-row">
        <div class="stat"><div class="k">收入合计</div><div class="v">${fmtN(t.revenue)}</div></div>
        <div class="stat"><div class="k">直接成本合计</div><div class="v">${fmtN(t.cost)}</div></div>
        <div class="stat"><div class="k">毛利</div><div class="v ${t.profit < 0 ? 'red' : ''}">${fmtN(t.profit)}</div></div>
        <div class="stat"><div class="k">亏损车辆</div><div class="v ${lossCount ? 'red' : ''}">${lossCount} 辆</div></div>
      </div>
      ${reportTitle('单车盈利分析', rangeLabel(data.from, data.to))}
      <div class="tbl-wrap" style="max-height:62vh"><table class="tbl"><thead><tr><th>车牌号</th><th>车型</th><th>状态</th><th class="n">收入</th><th class="n">折旧</th><th class="n">保险</th><th class="n">维修保养</th><th class="n">其他成本</th><th class="n">毛利</th><th class="n">毛利率</th></tr></thead>
      <tbody>${rows.map(r => `<tr><td>${esc(r.plate)}</td><td>${esc(r.model)}</td><td>${esc(r.status)}</td>${moneyCell(r.revenue)}${moneyCell(r.depr)}${moneyCell(r.insurance)}${moneyCell(r.repair)}${moneyCell(r.other)}${moneyCell(r.profit, false)}
        <td class="n">${r.revenue ? (r.profit / r.revenue * 100).toFixed(1) + '%' : ''}</td></tr>`).join('') || '<tr><td colspan="10" class="empty">没有数据</td></tr>'}</tbody></table></div>
      <p class="hint">收入和费用要在凭证的“辅助核算”里选择车辆，才能归属到具体车辆；按天汇总录入、没有选车辆的金额显示在“未归属到具体车辆”一行。折旧按车辆台账自动分摊到每辆车。</p>`;
  };
  $('#search', page).onclick = () => load().catch(e => toast(e.message, 'err'));
  bindPE(page, () => {
    if (!data) return;
    const M = n => ({ name: n, type: 'money' });
    const rows = data.rows.map(r => [r.plate, r.model, r.status, r.revenue, r.depr, r.insurance, r.repair, r.other, r.profit]);
    const t = data.total;
    rows.push({ cells: ['合计', '', '', t.revenue, t.depr, t.insurance, t.repair, t.other, t.profit], bold: true });
    exportXlsx('单车盈利分析', [{ name: '车牌号', width: 22 }, { name: '车型' }, { name: '状态' }, M('收入'), M('折旧'), M('保险'), M('维修保养'), M('其他成本'), M('毛利')],
      rows, `${plabel(data.from)} 至 ${plabel(data.to)}`);
  });
  await load();
};
