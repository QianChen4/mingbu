/* 记账凭证：录入 / 修改 / 查询 / 审核 / 打印 / 导出 */

function cfSuggest(cashIsDebit, counterCode) {
  let best = '';
  for (const pre in App.meta.cf_suggest) if (counterCode.startsWith(pre) && pre.length > best.length) best = pre;
  const pair = App.meta.cf_suggest[best];
  return cashIsDebit ? pair[0] : pair[1];
}
function cfItems() {
  return App.meta.cf_items.map(c => ({ value: c.code, code: c.code, label: c.name, hint: c.section === '不计' ? '' : c.section + '·' + c.flow }));
}

/* ================= 凭证录入 ================= */
App.pages.voucher = async (page, params) => {
  const meta = App.meta;
  let v = null;
  if (params.id) v = await api('/api/voucher?id=' + encodeURIComponent(params.id));
  const draft = App.draft; App.draft = null;
  const curP = meta.current_period;
  let defDate = store('lastVoucherDate');
  const openP = p => p >= meta.start_period && !meta.closed.includes(p);
  if (!defDate || !openP(+defDate.slice(0, 4) * 100 + +defDate.slice(5, 7))) {
    const t = today();
    defDate = (+t.slice(0, 4) * 100 + +t.slice(5, 7)) === curP ? t : lastDay(curP);
  }
  const blank = () => ({ summary: '', account: '', aux_id: 0, cf_item: '', cf_auto: true, debit: 0, credit: 0 });
  let rows, date, attachments, readOnly = false, reason = '';
  if (v) {
    rows = v.lines.map(l => ({ summary: l.summary, account: l.account_code, aux_id: l.aux_id, cf_item: l.cf_item, cf_auto: false, debit: l.debit, credit: l.credit }));
    date = v.date; attachments = v.attachments;
    if (v.closed) { readOnly = true; reason = '该期间已结账'; }
    else if (v.audited) { readOnly = true; reason = '凭证已审核，取消审核后才能修改'; }
    else if (v.kind !== '普通') { readOnly = true; reason = `“${v.kind}”凭证由系统自动生成，不能修改；如有错误可删除后重新生成`; }
  } else if (draft) {
    rows = draft.lines.map(l => Object.assign(blank(), l, { cf_auto: !l.cf_item }));
    date = draft.date || defDate; attachments = 0;
  } else {
    rows = []; date = defDate; attachments = 0;
  }
  while (rows.length < 5) rows.push(blank());

  const vno = v ? `记-${String(v.number).padStart(4, '0')}` : '（保存后自动编号）';
  page.innerHTML = `
    <div class="page-head no-print"><div><h1>${v ? '查看 / 修改凭证' : '新增凭证'}</h1>
      <div class="sub">${v ? plabel(v.period) + ' ' + vno : '当前期间 ' + plabel(curP)}</div></div>
      <div class="grow"></div>
      <div class="toolbar" style="margin:0">
        ${v ? `<button class="btn" id="prev" ${v.prev_id ? '' : 'disabled'}>‹ 上一张</button><button class="btn" id="next" ${v.next_id ? '' : 'disabled'}>下一张 ›</button><span class="sep"></span>` : ''}
        <button class="btn" id="tpl" ${readOnly ? 'disabled' : ''}>使用模板</button>
        <button class="btn" id="save-tpl">存为模板</button>
        ${v ? `<button class="btn" id="audit">${v.audited ? '取消审核' : '审核'}</button><button class="btn" id="print">打印</button><button class="btn danger" id="del">删除</button>` : ''}
        <button class="btn" id="new">新增</button>
        <button class="btn" id="save-new" ${readOnly ? 'disabled' : ''}>保存并新增</button>
        <button class="btn primary" id="save" ${readOnly ? 'disabled' : ''}>保存</button>
      </div></div>
    ${reason ? `<div class="notice warn">${esc(reason)}</div>` : ''}
    ${draft && draft.note ? `<div class="notice info">${esc(draft.note)}</div>` : ''}
    <div class="voucher">
      <div class="v-title">记 账 凭 证</div><div class="v-title-line"></div>
      <div class="v-head">
        <label>凭证字号 <b>${vno}</b></label>
        <label>日期 <input type="date" id="v-date" value="${date}" ${readOnly ? 'disabled' : ''}></label>
        <div class="grow"></div>
        <label>附件 <input type="number" id="v-att" value="${attachments}" min="0" style="width:64px" ${readOnly ? 'disabled' : ''}> 张</label>
        ${v && v.audited ? '<span class="v-stamp">已审核</span>' : ''}${v && v.kind !== '普通' ? `<span class="v-stamp blue">${esc(v.kind)}</span>` : ''}
      </div>
      <table class="v-grid">
        <colgroup><col style="width:36px"><col style="width:21%"><col style="width:25%"><col style="width:15%"><col style="width:15%"><col><col><col style="width:34px"></colgroup>
        <thead><tr><th>#</th><th>摘要</th><th>会计科目</th><th>辅助核算</th><th>现金流量项目</th><th>借方金额</th><th>贷方金额</th><th></th></tr></thead>
        <tbody id="v-body"></tbody>
        <tfoot><tr class="v-total"><td colspan="5" id="v-upper">合计：</td><td class="num" id="v-td"></td><td class="num" id="v-tc"></td><td></td></tr></tfoot>
      </table>
      <div class="v-foot">
        <span>制单：${esc(v ? v.maker : meta.maker || '')}</span><span>审核：${esc(v ? v.auditor : '')}</span>
        <span class="grow"></span><span id="v-diff"></span>
        ${readOnly ? '' : '<button class="btn small" id="add-row">＋ 增加一行</button>'}
      </div>
      ${readOnly ? '' : `<div class="kbd-help no-print">
        <kbd>Enter</kbd> 跳到下一格　<kbd>=</kbd> 在金额格自动填入借贷差额　<kbd>空格</kbd> 把金额在借方/贷方之间切换
        <kbd>Ctrl</kbd>+<kbd>S</kbd> 保存　<kbd>Ctrl</kbd>+<kbd>Enter</kbd> 保存并新增　科目可以输入编码或名称搜索</div>`}
    </div>`;

  const body = $('#v-body', page);

  function renderRows() {
    body.innerHTML = rows.map((r, i) => {
      const a = App.acct[r.account];
      return `<tr data-i="${i}">
        <td class="idx">${i + 1}</td>
        <td><input data-f="summary" value="${esc(r.summary)}" ${readOnly ? 'disabled' : ''}></td>
        <td><input data-f="account" ${readOnly ? 'disabled' : ''} placeholder=""></td>
        <td><input data-f="aux" ${readOnly || !(a && a.aux_type) ? 'disabled' : ''} placeholder="${a && a.aux_type ? (a.aux_required ? '必选：' : '可选：') + a.aux_type : ''}"></td>
        <td><input data-f="cf" ${readOnly || !(a && a.is_cash) ? 'disabled' : ''} class="${r.cf_auto ? 'auto-cf' : ''}" placeholder="${a && a.is_cash ? '自动建议' : ''}"></td>
        <td class="num"><input data-f="debit" value="${amtInput(r.debit)}" ${readOnly ? 'disabled' : ''}></td>
        <td class="num"><input data-f="credit" value="${amtInput(r.credit)}" ${readOnly ? 'disabled' : ''}></td>
        <td class="del">${readOnly ? '' : `<button tabindex="-1" title="删除这一行" data-del="${i}">✕</button>`}</td></tr>`;
    }).join('');
    $$('tr[data-i]', body).forEach(tr => bindRow(tr, +tr.dataset.i));
    updateCf();
    updateTotals();
  }

  function bindRow(tr, i) {
    const r = rows[i];
    const acc = $('[data-f=account]', tr), aux = $('[data-f=aux]', tr), cf = $('[data-f=cf]', tr);
    setPickerValue(acc, acctItem(r.account));
    setPickerValue(aux, auxItem(r.aux_id));
    setPickerValue(cf, r.cf_item ? { value: r.cf_item, code: '', label: (App.cf[r.cf_item] || {}).name || r.cf_item } : null);
    $('[data-f=summary]', tr).addEventListener('input', e => r.summary = e.target.value);
    // 摘要为空时，自动带入上一行的摘要（全选状态，直接输入即可改写）
    $('[data-f=summary]', tr).addEventListener('focus', e => {
      if (!r.summary && i > 0 && rows[i - 1].summary) {
        e.target.value = rows[i - 1].summary;
        r.summary = e.target.value;
        setTimeout(() => e.target.select(), 0);
      }
    });
    attachPicker(acc, {
      source: () => acctItems(true),
      onPick: it => {
        const old = r.account;
        r.account = it ? it.value : '';
        if (!r.summary && i > 0) r.summary = rows[i - 1].summary;
        if (old !== r.account) { r.aux_id = 0; r.cf_item = ''; r.cf_auto = true; refreshRow(tr, i); }
      },
    });
    attachPicker(aux, {
      source: () => { const a = App.acct[r.account]; return a && a.aux_type ? auxItems(a.aux_type) : []; },
      onPick: it => r.aux_id = it ? it.value : 0,
    });
    attachPicker(cf, {
      source: cfItems,
      onPick: it => { r.cf_item = it ? it.value : ''; r.cf_auto = !it; cf.classList.toggle('auto-cf', r.cf_auto); if (!it) updateCf(); },
    });
    ['debit', 'credit'].forEach(side => {
      const inp = $(`[data-f=${side}]`, tr);
      const other = side === 'debit' ? 'credit' : 'debit';
      inp.addEventListener('input', () => {
        const val = parseAmt(inp.value);
        inp.style.color = val === null ? 'var(--red)' : '';
        r[side] = val || 0;
        if (r[side]) { r[other] = 0; $(`[data-f=${other}]`, tr).value = ''; }
        updateCf(); updateTotals();
      });
      inp.addEventListener('blur', () => { if (parseAmt(inp.value) !== null) inp.value = amtInput(r[side]); });
      inp.addEventListener('keydown', e => {
        if (e.key === '=') {
          e.preventDefault();
          r[side] = 0; r[other] = 0;
          const td = rows.reduce((s, x) => s + x.debit, 0), tc = rows.reduce((s, x) => s + x.credit, 0);
          const diff = side === 'debit' ? tc - td : td - tc;
          if (diff > 0) r[side] = diff; else if (diff < 0) r[other] = -diff;
          inp.value = amtInput(r[side]); $(`[data-f=${other}]`, tr).value = amtInput(r[other]);
          updateCf(); updateTotals();
        } else if (e.key === ' ') {
          e.preventDefault();
          const val = r[side] || r[other];
          const target = r[side] ? other : side;
          r.debit = 0; r.credit = 0; r[target] = val;
          $('[data-f=debit]', tr).value = amtInput(r.debit); $('[data-f=credit]', tr).value = amtInput(r.credit);
          $(`[data-f=${target}]`, tr).focus();
          updateCf(); updateTotals();
        }
      });
    });
    $$('input', tr).forEach(inp => inp.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        if (inp.dataset.f === 'summary' && !inp.value && inp.placeholder) { inp.value = inp.placeholder; r.summary = inp.placeholder; }
        moveNext(inp);
      }
    }));
    const del = $('[data-del]', tr);
    if (del) del.onclick = () => { rows.splice(i, 1); if (rows.length < 2) rows.push(blank()); renderRows(); };
  }

  function refreshRow(tr, i) {
    const r = rows[i], a = App.acct[r.account];
    const aux = $('[data-f=aux]', tr), cf = $('[data-f=cf]', tr);
    aux.disabled = readOnly || !(a && a.aux_type);
    aux.placeholder = a && a.aux_type ? (a.aux_required ? '必选：' : '可选：') + a.aux_type : '';
    setPickerValue(aux, auxItem(r.aux_id));
    cf.disabled = readOnly || !(a && a.is_cash);
    cf.placeholder = a && a.is_cash ? '自动建议' : '';
    setPickerValue(cf, null);
    const sum = $('[data-f=summary]', tr);
    if (!sum.value && r.summary) sum.value = r.summary;
    updateCf();
  }

  function moveNext(inp) {
    const all = $$('input:not([disabled])', body);
    const k = all.indexOf(inp);
    if (k === all.length - 1 || k === -1) {
      rows.push(blank());
      renderRows();
      const tr = body.lastElementChild;
      $('[data-f=summary]', tr).focus();
      return;
    }
    // 金额格：借方已有金额时跳过贷方
    let nxt = all[k + 1];
    if (inp.dataset.f === 'debit' && parseAmt(inp.value)) nxt = all[k + 2] || nxt;
    if (nxt) { nxt.focus(); }
  }

  function updateCf() {
    const isCash = r => App.acct[r.account] && App.acct[r.account].is_cash;
    const others = rows.filter(r => r.account && !isCash(r));
    rows.forEach((r, i) => {
      if (!isCash(r) || !r.cf_auto) return;
      let code = '';
      if (!others.length) code = rows.filter(x => x.account).length >= 2 ? 'CF99' : '';
      else {
        const debitSide = !!r.debit || !r.credit;
        let opp = others.filter(o => (!!o.credit) === debitSide);
        if (!opp.length) opp = others;
        opp = opp.slice().sort((a, b) => (Math.abs(b.debit || b.credit)) - (Math.abs(a.debit || a.credit)));
        code = cfSuggest(debitSide, opp[0].account);
      }
      r.cf_item = code;
      const tr = body.children[i];
      if (tr) {
        const cf = $('[data-f=cf]', tr);
        if (document.activeElement !== cf) setPickerValue(cf, code ? { value: code, code: '', label: App.cf[code].name } : null);
      }
    });
  }

  function updateTotals() {
    const td = rows.reduce((s, x) => s + x.debit, 0), tc = rows.reduce((s, x) => s + x.credit, 0);
    $('#v-td', page).textContent = fmtN(td);
    $('#v-tc', page).textContent = fmtN(tc);
    $('#v-upper', page).textContent = '合计：' + (td === tc ? upperAmount(td) : '');
    $('#v-diff', page).innerHTML = td !== tc ? `<span class="v-diff">借贷不平衡，相差 ${fmtN(Math.abs(td - tc))}</span>` : (td ? '<span class="green">借贷平衡</span>' : '');
  }

  async function save(andNew) {
    if (readOnly) return;
    const bad = $$('[data-f=debit],[data-f=credit]', body).find(i => parseAmt(i.value) === null);
    if (bad) { bad.focus(); return toast('金额格式不正确', 'err'); }
    const payload = {
      id: v ? v.id : undefined, date: $('#v-date', page).value, attachments: +$('#v-att', page).value || 0,
      lines: rows.filter(r => r.account || r.debit || r.credit).map(r => ({
        summary: r.summary, account: r.account, aux_id: r.aux_id, cf_item: r.cf_item, debit: r.debit, credit: r.credit,
      })),
    };
    try {
      const saved = await api('/api/voucher/save', payload);
      store('lastVoucherDate', payload.date);
      toast(`已保存：${plabel(saved.period)} 记-${String(saved.number).padStart(4, '0')}`, 'ok');
      App.meta.has_vouchers = true;
      if (andNew) go('voucher', { t: Date.now() }); else go('voucher', { id: saved.id });
    } catch (e) { toast(e.message, 'err'); }
  }

  renderRows();
  // 有改动就标记“未保存”，顶栏“全部刷新”时跳过这个标签
  page.oninput = () => { if (!readOnly) page.dataset.dirty = '1'; };
  if (!readOnly) setTimeout(() => $('[data-f=summary]', body).focus(), 50);

  const onKey = e => {
    if (!document.body.contains(body)) return document.removeEventListener('keydown', onKey);
    if (!page.classList.contains('on')) return;  // 只在当前显示的标签里响应快捷键
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save(false); }
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); save(true); }
  };
  document.addEventListener('keydown', onKey);

  $('#save', page).onclick = () => save(false);
  $('#save-new', page).onclick = () => save(true);
  $('#new', page).onclick = () => go('voucher', { t: Date.now() });
  const addRow = $('#add-row', page);
  if (addRow) addRow.onclick = () => { rows.push(blank()); renderRows(); };
  if (v) {
    $('#prev', page).onclick = () => go('voucher', { id: v.prev_id });
    $('#next', page).onclick = () => go('voucher', { id: v.next_id });
    $('#print', page).onclick = () => printVouchers([v]);
    $('#audit', page).onclick = async () => {
      try { await api('/api/voucher/audit', { ids: [v.id], flag: !v.audited }); toast(v.audited ? '已取消审核' : '已审核', 'ok'); go('voucher', { id: v.id, t: Date.now() }); }
      catch (e) { toast(e.message, 'err'); }
    };
    $('#del', page).onclick = async () => {
      if (!await confirmBox(`确定删除凭证 ${vno} 吗？`, '删除', true)) return;
      try { await api('/api/voucher/delete', { id: v.id }); toast('已删除', 'ok'); go('vouchers'); }
      catch (e) { toast(e.message, 'err'); }
    };
  }
  $('#tpl', page).onclick = () => chooseTemplate(lines => {
    rows = lines.map(l => Object.assign(blank(), l));
    while (rows.length < 3) rows.push(blank());
    renderRows();
  });
  $('#save-tpl', page).onclick = () => {
    const used = rows.filter(r => r.account);
    if (used.length < 2) return toast('请先填写至少两行分录', 'err');
    const total = used.reduce((s, r) => s + r.debit, 0);
    const m = modal({
      title: '存为凭证模板', body: `<div class="field"><span>模板名称</span><input type="text" name="name" value="${esc(used[0].summary)}"></div>
        <p class="hint">金额等于凭证合计的行，套用模板时会自动填入录入的总金额；其他行需要手工填写。</p>`,
      buttons: [{ text: '取消' }, {
        text: '保存', cls: 'primary', onClick: async el => {
          await api('/api/template/save', {
            name: $('[name=name]', el).value,
            lines: used.map(r => ({ summary: r.summary, account: r.account, aux_id: r.aux_id, dir: r.debit ? '借' : '贷', expr: (r.debit || r.credit) === total ? 'T' : '' })),
          });
          toast('模板已保存', 'ok');
        },
      }],
    });
  };
};

/** 计算模板金额 */
function tplAmount(expr, total) {
  if (!expr) return 0;
  if (expr === 'T') return total;
  const m = expr.match(/^(NET|TAX):(\d+(\.\d+)?)$/);
  if (!m) return 0;
  const rate = parseFloat(m[2]);
  const net = Math.round(total * 100 / (100 + rate));
  return m[1] === 'NET' ? net : total - net;
}

async function chooseTemplate(apply) {
  const list = await api('/api/templates');
  const box = document.createElement('div');
  box.innerHTML = `<input type="text" placeholder="搜索模板" id="tpl-q" style="width:100%;margin-bottom:10px">
    <div class="tbl-wrap" style="max-height:360px"><table class="tbl"><tbody id="tpl-list"></tbody></table></div>`;
  const draw = q => {
    $('#tpl-list', box).innerHTML = list.filter(t => !q || t.name.includes(q)).map(t =>
      `<tr class="clickable" data-id="${t.id}"><td>${esc(t.name)}</td><td class="muted small">${t.lines.map(l => (App.acct[l.account] || {}).name || l.account).join(' / ')}</td></tr>`).join('')
      || '<tr><td class="empty">没有模板</td></tr>';
    $$('tr[data-id]', box).forEach(tr => tr.onclick = () => useTpl(list.find(t => t.id == tr.dataset.id)));
  };
  const m = modal({ title: '选择凭证模板', body: box, width: 640 });
  $('#tpl-q', box).oninput = e => draw(e.target.value.trim());
  draw('');
  function useTpl(t) {
    const needTotal = t.lines.some(l => l.expr);
    const build = total => {
      apply(t.lines.map(l => {
        const amt = tplAmount(l.expr, total);
        return { summary: l.summary, account: l.account, aux_id: l.aux_id || 0, debit: l.dir === '借' ? amt : 0, credit: l.dir === '贷' ? amt : 0 };
      }));
    };
    m.close();
    if (!needTotal) return build(0);
    modal({
      title: t.name, body: `<div class="field"><span>总金额（元）${t.lines.some(l => /NET|TAX/.test(l.expr)) ? '——含税金额，系统自动拆分税额' : ''}</span><input type="text" class="num" name="total"></div>`,
      buttons: [{ text: '取消' }, {
        text: '确定', cls: 'primary', onClick: el => {
          const v = parseAmt($('[name=total]', el).value);
          if (!v) { toast('请输入金额', 'err'); return false; }
          build(v);
        },
      }],
    });
    setTimeout(() => {
      const inp = $('.modal [name=total]');
      if (inp) inp.addEventListener('keydown', e => { if (e.key === 'Enter') $('.modal .btn.primary').click(); });
    }, 50);
  }
}

/* ================= 凭证打印 ================= */
/** 一张凭证的打印内容。slotH：这张凭证占用的高度（mm），每页多张时使用；rows：至少显示的行数 */
function voucherPrintHtml(v, slotH, rows) {
  const td = v.lines.reduce((s, l) => s + l.debit, 0);
  const minRows = Math.max(rows || 5, v.lines.length);
  const rowsHtml = [];
  for (let i = 0; i < minRows; i++) {
    const l = v.lines[i];
    const aux = l && l.aux_id ? `<span class="pv-aux">（${esc(App.aux[l.aux_id] ? App.aux[l.aux_id].type : '')}：${esc(auxText(l.aux_id))}）</span>` : '';
    rowsHtml.push(l ? `<tr><td>${esc(l.summary)}</td><td>${esc(acctText(l.account_code))}${aux}</td><td class="n">${fmt(l.debit)}</td><td class="n">${fmt(l.credit)}</td></tr>`
      : '<tr><td>&nbsp;</td><td></td><td></td><td></td></tr>');
  }
  return `<div class="pv" ${slotH ? `style="height:${slotH.toFixed(1)}mm"` : ''}><h3>记账凭证</h3><div class="pv-line"></div>
    <div class="pv-meta"><span>核算单位：${esc(App.meta.company_name)}</span><span>日期：${v.date}</span><span>记字第 ${String(v.number).padStart(4, '0')} 号</span><span>附件 ${v.attachments} 张</span></div>
    <table><colgroup><col style="width:27%"><col style="width:39%"><col><col></colgroup>
    <thead><tr><th>摘要</th><th>会计科目</th><th>借方金额</th><th>贷方金额</th></tr></thead>
    <tbody>${rowsHtml.join('')}
    <tr class="pv-total"><td colspan="2">合计：${upperAmount(td)}</td><td class="n">${fmtN(td)}</td><td class="n">${fmtN(td)}</td></tr></tbody></table>
    <div class="pv-sign"><span>记账：</span><span>审核：${esc(v.auditor || '')}</span><span>出纳：</span><span>制单：${esc(v.maker || '')}</span></div></div>`;
}
function printHtml(html) {
  $('#print-area').innerHTML = html;
  document.body.classList.add('printing');
  setTimeout(() => {
    window.print();
    setTimeout(() => { document.body.classList.remove('printing'); $('#print-area').innerHTML = ''; }, 300);
  }, 80);
}
/** 按打印设置排版凭证：每页 N 张，行数放不下的凭证单独占一页 */
async function printVouchers(list) {
  const s = await askPrintSettings('voucher');
  if (!s) return;
  const page = applyPrintPage(s);
  const scale = (s.scale || 100) / 100;
  const n = Math.max(1, s.perPage || 1);
  const HEAD = 38 * scale, ROW = 7.2 * scale; // 凭证表头、签字栏等固定高度，以及每行高度（mm）
  const cap = slot => Math.max(1, Math.floor((slot - HEAD) / ROW));
  const slotN = page.contentH / n - 1;
  const pages = [];
  let cur = [];
  const flush = () => { if (cur.length) pages.push({ items: cur, slot: slotN }); cur = []; };
  list.forEach(v => {
    if (n > 1 && v.lines.length > cap(slotN)) { flush(); pages.push({ items: [v], slot: null }); return; }
    cur.push(v);
    if (cur.length === n) flush();
  });
  flush();
  const html = pages.map(pg => `<div class="pv-page">${pg.items.map(v =>
    pg.slot ? voucherPrintHtml(v, pg.slot, Math.min(5, cap(pg.slot))) : voucherPrintHtml(v, null, Math.min(5, cap(page.contentH)))).join('')}</div>`).join('');
  printHtml(html);
}

/* ================= 凭证查询 ================= */
App.pages.vouchers = async (page, params) => {
  const [dpf, dpt] = defaultRange();
  const pf = +params.from || dpf, pt = +params.to || dpt;
  page.innerHTML = `
    <div class="page-head"><div><h1>凭证查询</h1><div class="sub">查询、审核、打印和导出凭证</div></div></div>
    <div class="toolbar" id="flt">
      ${rangeControls(pf, pt)}
      <input type="text" name="q" placeholder="摘要关键字" value="${esc(params.q || '')}" style="width:140px">
      <input type="text" name="account" placeholder="科目（编码或名称）" style="width:180px">
      <select name="status"><option value="">全部状态</option><option value="unaudited" ${params.status === 'unaudited' ? 'selected' : ''}>未审核</option><option value="audited" ${params.status === 'audited' ? 'selected' : ''}>已审核</option></select>
      <button class="btn primary" id="search">查询</button>
    </div>
    <div class="toolbar">
      <label class="check"><input type="checkbox" id="all"> 全选</label><span class="sep"></span>
      <button class="btn" id="b-audit">审核</button><button class="btn" id="b-unaudit">取消审核</button>
      <button class="btn" id="b-print">打印</button><button class="btn" id="b-export">导出 Excel</button>
      <button class="btn danger" id="b-del">删除</button><span class="sep"></span>
      <button class="btn" id="b-renum" title="按日期顺序重新连续编号">整理凭证号</button>
      <span class="grow"></span><span class="muted" id="count"></span>
    </div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th style="width:32px"></th><th>期间</th><th>日期</th><th>凭证号</th><th>摘要</th><th class="n">金额</th><th class="c">分录</th><th>类型</th><th>状态</th><th>制单</th></tr></thead>
    <tbody id="list"></tbody></table></div>`;
  const acc = $('[name=account]', page);
  attachPicker(acc, { source: () => acctItems(false) });
  if (params.account) setPickerValue(acc, acctItem(params.account));
  let data = [];
  const load = async () => {
    const [a, b] = readRange(page);
    data = await api('/api/vouchers?' + qs({ from: a, to: b, q: $('[name=q]', page).value.trim(), account: acc.dataset.value || '', status: $('[name=status]', page).value }));
    $('#list', page).innerHTML = data.map(v => `<tr data-id="${v.id}" class="clickable">
      <td><input type="checkbox" class="sel" value="${v.id}"></td><td>${plabel(v.period)}</td><td>${v.date}</td>
      <td>记-${String(v.number).padStart(4, '0')}</td><td>${esc(v.first_summary)}${v.line_count > 1 ? '' : ''}</td>${moneyCell(v.total)}
      <td class="c">${v.line_count}</td><td>${v.kind === '普通' ? '' : `<span class="pill">${esc(v.kind)}</span>`}</td>
      <td>${v.audited ? '<span class="pill green">已审核</span>' : '<span class="pill amber">未审核</span>'}</td><td>${esc(v.maker)}</td></tr>`).join('')
      || '<tr><td colspan="10" class="empty">没有符合条件的凭证</td></tr>';
    const total = data.reduce((s, v) => s + v.total, 0);
    $('#count', page).textContent = `共 ${data.length} 张，金额合计 ${fmtN(total)}`;
    $$('tr[data-id]', page).forEach(tr => tr.addEventListener('click', e => {
      if (e.target.classList.contains('sel')) return;
      go('voucher', { id: tr.dataset.id });
    }));
    $('#all', page).checked = false;
  };
  const selected = () => $$('.sel:checked', page).map(c => +c.value);
  const need = () => { const s = selected(); if (!s.length) toast('请先勾选凭证', 'err'); return s; };
  $('#all', page).onchange = e => $$('.sel', page).forEach(c => c.checked = e.target.checked);
  $('#search', page).onclick = () => load().catch(e => toast(e.message, 'err'));
  $('#flt', page).addEventListener('keydown', e => { if (e.key === 'Enter') load().catch(er => toast(er.message, 'err')); });
  const doAudit = async flag => {
    const ids = need(); if (!ids.length) return;
    try { const r = await api('/api/voucher/audit', { ids, flag }); toast(`已${flag ? '审核' : '取消审核'} ${r.count} 张`, 'ok'); load(); }
    catch (e) { toast(e.message, 'err'); }
  };
  $('#b-audit', page).onclick = () => doAudit(true);
  $('#b-unaudit', page).onclick = () => doAudit(false);
  $('#b-del', page).onclick = async () => {
    const ids = need(); if (!ids.length) return;
    if (!await confirmBox(`确定删除选中的 ${ids.length} 张凭证吗？`, '删除', true)) return;
    try { await api('/api/voucher/delete', { ids }); toast('已删除', 'ok'); load(); } catch (e) { toast(e.message, 'err'); load(); }
  };
  $('#b-print', page).onclick = async () => {
    let ids = selected();
    if (!ids.length) {
      if (!data.length) return toast('没有可打印的凭证', 'err');
      if (!await confirmBox(`没有勾选凭证。要打印当前查询结果中的全部 ${data.length} 张凭证吗？`, '打印')) return;
      ids = data.map(v => v.id);
    }
    try { printVouchers(await api('/api/voucher/print', { ids })); } catch (e) { toast(e.message, 'err'); }
  };
  $('#b-export', page).onclick = async () => {
    let ids = selected();
    if (!ids.length) ids = data.map(v => v.id);
    if (!ids.length) return toast('没有可导出的凭证', 'err');
    const list = await api('/api/voucher/print', { ids });
    const rows = [];
    list.forEach(v => v.lines.forEach(l => rows.push([plabel(v.period), v.date, '记-' + String(v.number).padStart(4, '0'), l.summary,
      l.account_code, (App.acct[l.account_code] || {}).full_name || '', auxText(l.aux_id), (App.cf[l.cf_item] || {}).name || '',
      l.debit, l.credit, v.audited ? '已审核' : '未审核', v.maker])));
    const [a, b] = readRange(page);
    exportXlsx('凭证明细', [{ name: '期间' }, { name: '日期', width: 12 }, { name: '凭证号' }, { name: '摘要', width: 26 }, { name: '科目编码' },
      { name: '科目名称', width: 28 }, { name: '辅助核算', width: 18 }, { name: '现金流量项目', width: 28 }, { name: '借方金额', type: 'money' },
      { name: '贷方金额', type: 'money' }, { name: '状态' }, { name: '制单' }], rows, `${plabel(a)} 至 ${plabel(b)}`);
  };
  $('#b-renum', page).onclick = async () => {
    const [a, b] = readRange(page);
    if (a !== b) return toast('请把起止月份设为同一个月，再整理该月的凭证号', 'err');
    if (!await confirmBox(`把 ${plabel(a)} 的凭证按日期重新从 1 号开始连续编号？`, '整理')) return;
    try { const r = await api('/api/voucher/renumber', { period: a }); toast(`已整理 ${r.count} 张`, 'ok'); load(); } catch (e) { toast(e.message, 'err'); }
  };
  await load();
};
