/* 设置：会计科目、辅助核算、车辆台账、期初余额、凭证模板、数据导入、备份、账套信息、日志 */

async function afterChange(msg) {
  if (msg) toast(msg, 'ok');
  await refreshMeta();
  reloadTab();
}

/* ================= 会计科目 ================= */
App.pages.accounts = async (page, params) => {
  const cat = params.cat || '';
  const cats = ['', '资产', '负债', '权益', '损益'];
  page.innerHTML = pageHead('会计科目', '可以新增、修改、停用、删除科目；编码规则 4-2-2-2，例如 6001 → 600101 → 60010101') + `
    <div class="tabs">${cats.map(c => `<a href="#/accounts?cat=${c}" class="${c === cat ? 'on' : ''}">${c || '全部'}</a>`).join('')}</div>
    <div class="toolbar"><input type="text" id="q" placeholder="搜索编码或名称" style="width:200px">
      <button class="btn primary" id="add1">＋ 新增一级科目</button>${printExportButtons()}</div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>科目编码</th><th>科目名称</th><th>类别</th><th class="c">方向</th><th>辅助核算</th><th class="c">现金类</th><th>报表项目</th><th class="c">状态</th><th>操作</th></tr></thead>
    <tbody id="list"></tbody></table></div>
    <p class="hint">说明：只有末级科目可以录入凭证。给已经用过的末级科目新增第一个下级科目时，原有的凭证和期初数据会自动转到这个下级科目。
      已使用的科目不能删除，可以“停用”。新增的一级科目可以指定它在资产负债表或利润表中归入哪一行；不指定的，自动归入“其他”行。</p>`;
  const rlName = key => {
    const all = App.meta.report_lines.bs.concat(App.meta.report_lines.is);
    const f = all.find(x => x.key === key); return f ? f.name : '';
  };
  const draw = () => {
    const q = $('#q', page).value.trim();
    const list = App.meta.accounts.filter(a => (!cat || a.category === cat) && (!q || a.code.startsWith(q) || a.full_name.includes(q)));
    $('#list', page).innerHTML = list.map(a => `<tr class="lvl${a.level}">
      <td class="code-txt">${a.code}</td><td class="name">${esc(a.name)}</td><td>${a.category}</td><td class="c">${a.direction}</td>
      <td>${a.aux_type ? esc(a.aux_type) + (a.aux_required ? '（必填）' : '（可选）') : ''}</td><td class="c">${a.is_cash ? '是' : ''}</td>
      <td class="small muted">${a.level === 1 ? esc(rlName(a.report_line)) : ''}</td>
      <td class="c">${a.enabled ? '' : '<span class="pill gray">停用</span>'}</td>
      <td><button class="btn link" data-add="${a.code}">新增下级</button><button class="btn link" data-edit="${a.code}">修改</button><button class="btn link danger" data-del="${a.code}">删除</button></td></tr>`).join('');
    $$('[data-add]', page).forEach(b => b.onclick = () => accountForm(null, b.dataset.add));
    $$('[data-edit]', page).forEach(b => b.onclick = () => accountForm(App.acct[b.dataset.edit]));
    $$('[data-del]', page).forEach(b => b.onclick = async () => {
      const a = App.acct[b.dataset.del];
      if (!await confirmBox(`确定删除科目 ${a.code} ${a.full_name} 吗？`, '删除', true)) return;
      try { await api('/api/account/delete', { code: a.code }); afterChange('已删除'); } catch (e) { toast(e.message, 'err'); }
    });
  };
  $('#q', page).oninput = draw;
  $('#add1', page).onclick = () => accountForm(null, '');
  bindPE(page, () => exportXlsx('会计科目表', [{ name: '科目编码' }, { name: '科目名称', width: 34 }, { name: '类别' }, { name: '方向', width: 6 }, { name: '辅助核算' }, { name: '现金类', width: 8 }, { name: '状态', width: 8 }],
    App.meta.accounts.map(a => [a.code, a.full_name, a.category, a.direction, a.aux_type, a.is_cash ? '是' : '', a.enabled ? '启用' : '停用'])));
  draw();
};

function accountForm(acc, parentCode) {
  const isNew = !acc;
  const parent = parentCode ? App.acct[parentCode] : null;
  let code = acc ? acc.code : '';
  if (isNew && parent) {
    const kids = App.meta.accounts.filter(a => a.parent === parent.code).map(a => +a.code.slice(-2));
    const next = Math.min(99, (kids.length ? Math.max(...kids) : 0) + 1);
    code = parent.code + String(next).padStart(2, '0');
  }
  const level1 = isNew ? !parent : acc.level === 1;
  const category = acc ? acc.category : parent ? parent.category : '资产';
  const dir = acc ? acc.direction : parent ? parent.direction : '借';
  const auxType = acc ? acc.aux_type : parent && parent.is_leaf ? parent.aux_type : '';
  const rlOptions = cat => {
    if (cat === '损益') return App.meta.report_lines.is;
    const side = { 资产: 'A', 负债: 'L', 权益: 'E' }[cat];
    return App.meta.report_lines.bs.filter(x => x.side === side);
  };
  const body = document.createElement('div');
  body.innerHTML = `
    ${parent ? `<p class="hint">上级科目：${parent.code} ${esc(parent.full_name)}</p>` : ''}
    <div class="field-row"><div class="field"><span>科目编码</span><input type="text" name="code" value="${code}" ${isNew ? '' : 'disabled'}></div>
      <div class="field"><span>科目名称</span><input type="text" name="name" value="${esc(acc ? acc.name : '')}"></div></div>
    <div class="field-row">
      <div class="field"><span>类别</span><select name="category" ${isNew && level1 ? '' : 'disabled'}>${['资产', '负债', '权益', '损益'].map(c => `<option ${c === category ? 'selected' : ''}>${c}</option>`).join('')}</select></div>
      <div class="field"><span>余额方向</span><select name="direction">${['借', '贷'].map(c => `<option ${c === dir ? 'selected' : ''}>${c}</option>`).join('')}</select></div></div>
    <div class="field-row">
      <div class="field"><span>辅助核算</span><select name="aux_type"><option value="">无</option>${App.meta.aux_types.map(t => `<option ${t === auxType ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
      <div class="field"><span>&nbsp;</span><label class="check"><input type="checkbox" name="aux_required" ${acc ? (acc.aux_required ? 'checked' : '') : ''}> 录凭证时必须选择辅助项</label></div></div>
    ${level1 ? `<div class="field-row">
      <div class="field"><span>报表项目（只对新增的一级科目起作用）</span><select name="report_line"><option value="">自动（归入“其他”行）</option></select></div>
      <div class="field"><span>&nbsp;</span><label class="check"><input type="checkbox" name="is_cash" ${acc && acc.is_cash ? 'checked' : ''}> 现金类科目（计入现金流量表）</label></div></div>` : ''}
    ${acc ? `<label class="check"><input type="checkbox" name="enabled" ${acc.enabled ? 'checked' : ''}> 启用</label>` : ''}
    <p class="hint">辅助核算：例如“应收账款”按客户核算，“租赁车辆”按车辆核算。设了辅助核算后，就不需要为每个客户、每辆车单独建科目。</p>`;
  const fillRl = () => {
    const sel = $('[name=report_line]', body);
    if (!sel) return;
    const c = $('[name=category]', body).value;
    sel.innerHTML = '<option value="">自动（归入“其他”行）</option>' + rlOptions(c).map(o =>
      `<option value="${o.key}" ${acc && acc.report_line === o.key ? 'selected' : ''}>${esc(o.name)}</option>`).join('');
  };
  fillRl();
  $('[name=category]', body).onchange = fillRl;
  modal({
    title: isNew ? (parent ? '新增下级科目' : '新增一级科目') : '修改科目', body, width: 560,
    buttons: [{ text: '取消' }, {
      text: '保存', cls: 'primary', onClick: async el => {
        const d = formData(el);
        d.code = isNew ? d.code.trim() : acc.code;
        d.is_new = isNew;
        if (!level1) { delete d.is_cash; delete d.report_line; }
        if (!isNew && !('enabled' in d)) d.enabled = true;
        await api('/api/account/save', d);
        afterChange('科目已保存');
      },
    }],
  });
}

/* ================= 辅助核算项目 ================= */
App.pages.aux = async (page, params) => {
  const type = params.type || '客户';
  page.innerHTML = pageHead('辅助核算项目', '客户、供应商、员工、银行账户等；车辆在“车辆台账”中维护。可以自己增加类型，如“部门”“项目”“门店”。') + `
    <div class="tabs">${App.meta.aux_types.map(t => `<a href="#/aux?type=${encodeURIComponent(t)}" class="${t === type ? 'on' : ''}">${esc(t)}</a>`).join('')}
      <a href="javascript:void 0" id="add-type" title="新增辅助核算类型">＋ 新增类型</a></div>
    ${type === '车辆' ? '<div class="notice info">车辆在“设置 → 车辆台账”中新增和修改，这里只能查看。<a href="#/vehicles">前往车辆台账</a></div>' : ''}
    <div class="toolbar"><input type="text" id="q" placeholder="搜索编码或名称" style="width:200px">
      ${type === '车辆' ? '' : `<button class="btn primary" id="add">＋ 新增${esc(type)}</button><a class="btn" href="#/import">从 Excel 导入</a>`}${printExportButtons()}
      ${['客户', '供应商', '员工', '银行账户', '车辆'].includes(type) ? '' : `<span class="sep"></span><button class="btn danger" id="del-type">删除“${esc(type)}”类型</button>`}</div>
    <p class="hint">新增类型后，在“会计科目”里把需要按它核算的科目的“辅助核算”设为这个类型即可。</p>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>编码</th><th>名称</th><th class="c">状态</th><th>操作</th></tr></thead><tbody id="list"></tbody></table></div>`;
  $('#add-type', page).onclick = () => modal({
    title: '新增辅助核算类型', body: '<div class="field"><span>类型名称（如：部门、项目、门店、线路）</span><input type="text" name="name"></div>',
    buttons: [{ text: '取消' }, {
      text: '新增', cls: 'primary', onClick: async el => {
        const name = $('[name=name]', el).value.trim();
        await api('/api/aux_type/add', { name });
        await refreshMeta(); go('aux', { type: name });
      },
    }],
  });
  if ($('#del-type', page)) $('#del-type', page).onclick = async () => {
    if (!await confirmBox(`删除辅助核算类型“${type}”吗？`, '删除', true)) return;
    try { await api('/api/aux_type/delete', { name: type }); await refreshMeta(); go('aux', { type: '客户' }); } catch (e) { toast(e.message, 'err'); }
  };
  const items = () => App.meta.aux_items.filter(a => a.type === type);
  const draw = () => {
    const q = $('#q', page).value.trim();
    const list = items().filter(a => !q || a.code.includes(q) || a.name.includes(q));
    $('#list', page).innerHTML = list.map(a => `<tr><td class="code-txt">${esc(a.code)}</td><td>${esc(a.name)}</td><td class="c">${a.enabled ? '' : '<span class="pill gray">停用</span>'}</td>
      <td>${type === '车辆' ? '' : `<button class="btn link" data-edit="${a.id}">修改</button><button class="btn link danger" data-del="${a.id}">删除</button>`}
      <a class="btn link" href="#/auxbal?code=${encodeURIComponent((App.meta.accounts.find(x => x.aux_type === type) || {}).code || '')}">查余额</a></td></tr>`).join('')
      || '<tr><td colspan="4" class="empty">还没有项目</td></tr>';
    $$('[data-edit]', page).forEach(b => b.onclick = () => auxForm(type, App.aux[b.dataset.edit]));
    $$('[data-del]', page).forEach(b => b.onclick = async () => {
      if (!await confirmBox('确定删除这个项目吗？', '删除', true)) return;
      try { await api('/api/aux/delete', { id: +b.dataset.del }); afterChange('已删除'); } catch (e) { toast(e.message, 'err'); }
    });
  };
  $('#q', page).oninput = draw;
  if ($('#add', page)) $('#add', page).onclick = () => auxForm(type, null);
  bindPE(page, () => exportXlsx(type + '列表', [{ name: '编码' }, { name: '名称', width: 30 }, { name: '状态' }], items().map(a => [a.code, a.name, a.enabled ? '启用' : '停用'])));
  draw();
};
function auxForm(type, item) {
  const n = App.meta.aux_items.filter(a => a.type === type).length + 1;
  const prefix = { 客户: 'C', 供应商: 'S', 员工: 'E', 银行账户: '' }[type] || '';
  modal({
    title: (item ? '修改' : '新增') + type,
    body: `<div class="field-row"><div class="field"><span>编码</span><input type="text" name="code" value="${esc(item ? item.code : prefix + String(n).padStart(type === '银行账户' ? 2 : 3, '0'))}"></div>
      <div class="field" style="flex:2"><span>名称</span><input type="text" name="name" value="${esc(item ? item.name : '')}" placeholder="${type === '银行账户' ? '例如：工商银行 基本户 尾号1234' : ''}"></div></div>
      ${item ? `<label class="check"><input type="checkbox" name="enabled" ${item.enabled ? 'checked' : ''}> 启用</label>` : ''}`,
    buttons: [{ text: '取消' }, {
      text: '保存', cls: 'primary', onClick: async el => {
        const d = formData(el);
        d.type = type; d.id = item ? item.id : null;
        if (!item) d.enabled = true;
        await api('/api/aux/save', d);
        afterChange('已保存');
      },
    }],
  });
}

/* ================= 车辆台账 ================= */
App.pages.vehicles = async (page) => {
  if (!hasFeature('vehicles')) {
    page.innerHTML = pageHead('车辆台账', '') + '<div class="notice info">本账套所选行业没有车辆台账功能。汽车租赁、旅客运输、道路货物运输行业的账套才有车辆台账、自动折旧和单车盈利分析。</div>';
    return;
  }
  const [data, rc] = await Promise.all([api('/api/vehicles'), api('/api/vehicle/reconcile')]);
  const vs = data.vehicles;
  const inUse = vs.filter(v => v.status === '在用');
  const sum = (list, k) => list.reduce((s, v) => s + v[k], 0);
  const rcOk = rc.card_original === rc.book_original && rc.card_accum === rc.book_accum;
  page.innerHTML = pageHead('车辆台账', '每辆车一张卡片，系统据此每月自动计提折旧') + `
    <div class="stat-row">
      <div class="stat"><div class="k">在用车辆</div><div class="v">${inUse.length} 辆</div></div>
      <div class="stat"><div class="k">在用车辆原值</div><div class="v">${fmtN(sum(inUse, 'original'))}</div></div>
      <div class="stat"><div class="k">累计折旧</div><div class="v">${fmtN(sum(inUse, 'accum'))}</div></div>
      <div class="stat"><div class="k">月折旧额（参考）</div><div class="v">${fmtN(inUse.filter(v => !v.fully).reduce((s, v) => s + v.monthly, 0))}</div></div>
    </div>
    ${rcOk ? `<div class="notice ok no-print">截至 ${plabel(rc.period)} 末，车辆台账与账面一致（原值 ${fmtN(rc.book_original)}，累计折旧 ${fmtN(rc.book_accum)}）。</div>`
      : `<div class="notice warn no-print">截至当前会计期间 ${plabel(rc.period)} 末，台账与账面不一致：台账原值 ${fmtN(rc.card_original)} / 账面 ${fmtN(rc.book_original)}；台账累计折旧 ${fmtN(rc.card_accum)} / 账面 ${fmtN(rc.book_accum)}。
        ${rc.mismatches.length ? `<br>原值不一致的车辆：${rc.mismatches.slice(0, 12).map(m => esc(m.plate) + (m.reason ? `（${esc(m.reason)}）` : '')).join('；')}${rc.mismatches.length > 12 ? ' 等 ' + rc.mismatches.length + ' 辆' : ''}` : ''}
        <br>常见原因：新买的车还没录购车凭证、期初余额没有带入、本月折旧还没计提、处置凭证还没保存。</div>`}
    <div class="toolbar"><input type="text" id="q" placeholder="车牌号 / 车型" style="width:160px">
      <select id="st"><option value="在用">在用</option><option value="已处置">已处置</option><option value="">全部</option></select>
      <button class="btn primary" id="add">＋ 新增车辆</button><a class="btn" href="#/import">从 Excel 导入</a>${printExportButtons()}
      <span class="muted" id="cnt"></span></div>
    <div class="tbl-wrap" style="max-height:60vh"><table class="tbl"><thead><tr><th>车牌号</th><th>车型</th><th>购置日期</th><th class="n">原值</th><th class="n">残值率</th><th class="n">折旧月数</th>
      <th class="n">月折旧额</th><th class="n">累计折旧</th><th class="n">净值</th><th>状态</th><th>操作</th></tr></thead><tbody id="list"></tbody></table></div>
    <p class="hint">原值填不含税的购置成本（发票金额 − 进项税额，加上购置税等）。启用账套前已有的车辆，请填写“启用时已提累计折旧”，然后在“期初余额”中点“从车辆台账带入”。</p>`;
  let shown = [];
  const draw = () => {
    const q = $('#q', page).value.trim().toUpperCase(), st = $('#st', page).value;
    shown = vs.filter(v => (!st || v.status === st) && (!q || v.plate.includes(q) || v.model.toUpperCase().includes(q)));
    $('#cnt', page).textContent = `${shown.length} 辆`;
    $('#list', page).innerHTML = shown.slice(0, 2000).map(v => `<tr>
      <td>${esc(v.plate)}</td><td>${esc(v.model)}</td><td>${v.purchase_date}</td>${moneyCell(v.original)}<td class="n">${(v.salvage_bp / 100).toFixed(1)}%</td><td class="n">${v.life_months}</td>
      ${moneyCell(v.monthly)}${moneyCell(v.accum)}${moneyCell(v.net, false)}
      <td>${v.status === '在用' ? (v.fully ? '<span class="pill gray">已提足</span>' : '<span class="pill green">在用</span>') : `<span class="pill amber">已处置 ${plabel(v.dispose_period)}</span>`}</td>
      <td><button class="btn link" data-edit="${v.id}">修改</button><button class="btn link" data-buy="${v.id}">购车凭证</button>
        ${v.status === '在用' ? `<button class="btn link" data-dis="${v.id}">处置</button>` : `<button class="btn link" data-undo="${v.id}">撤销处置</button>`}
        <button class="btn link danger" data-del="${v.id}">删除</button></td></tr>`).join('') || '<tr><td colspan="11" class="empty">没有车辆</td></tr>';
    const byId = id => vs.find(v => v.id == id);
    $$('[data-edit]', page).forEach(b => b.onclick = () => vehicleForm(byId(b.dataset.edit)));
    $$('[data-buy]', page).forEach(b => b.onclick = async () => {
      try { App.draft = await api('/api/vehicle/purchase_draft', { id: +b.dataset.buy }); go('voucher'); }
      catch (e) { toast(e.message, 'err'); }
    });
    $$('[data-dis]', page).forEach(b => b.onclick = () => disposeForm(byId(b.dataset.dis)));
    $$('[data-undo]', page).forEach(b => b.onclick = async () => {
      if (!await confirmBox('撤销处置后车辆恢复为“在用”。如果已经保存了处置凭证，请记得一并删除。', '撤销处置')) return;
      try { await api('/api/vehicle/undo_dispose', { id: +b.dataset.undo }); toast('已撤销', 'ok'); reloadTab(); } catch (e) { toast(e.message, 'err'); }
    });
    $$('[data-del]', page).forEach(b => b.onclick = async () => {
      if (!await confirmBox('确定删除这辆车的卡片吗？', '删除', true)) return;
      try { await api('/api/vehicle/delete', { id: +b.dataset.del }); afterChange('已删除'); } catch (e) { toast(e.message, 'err'); }
    });
  };
  $('#q', page).oninput = draw;
  $('#st', page).onchange = draw;
  $('#add', page).onclick = () => vehicleForm(null);
  bindPE(page, () => exportXlsx('车辆台账', [{ name: '车牌号' }, { name: '车型' }, { name: '购置日期', width: 12 }, { name: '原值', type: 'money' }, { name: '残值率%', type: 'number', width: 8 },
    { name: '折旧月数', type: 'number', width: 8 }, { name: '月折旧额', type: 'money' }, { name: '累计折旧', type: 'money' }, { name: '净值', type: 'money' }, { name: '状态' }, { name: '处置期间' }],
    shown.map(v => [v.plate, v.model, v.purchase_date, v.original, v.salvage_bp / 100, v.life_months, v.monthly, v.accum, v.net, v.status, v.dispose_period ? plabel(v.dispose_period) : ''])));
  draw();
};

function vehicleForm(v) {
  const sp = App.meta.start_period;
  modal({
    title: v ? '修改车辆' : '新增车辆', width: 560,
    body: `<div class="field-row"><div class="field"><span>车牌号</span><input type="text" name="plate" value="${esc(v ? v.plate : '')}"></div>
      <div class="field"><span>车型</span><input type="text" name="model" value="${esc(v ? v.model : '')}"></div></div>
      <div class="field-row"><div class="field"><span>购置日期</span><input type="date" name="purchase_date" value="${v ? v.purchase_date : today()}"></div>
      <div class="field"><span>原值（不含税，元）</span><input type="text" class="num" name="original" value="${v ? amtInput(v.original) : ''}"></div></div>
      <div class="field-row"><div class="field"><span>残值率（%）</span><input type="number" name="salvage_rate" value="${v ? v.salvage_bp / 100 : 5}" step="0.1"></div>
      <div class="field"><span>折旧月数</span><input type="number" name="life_months" value="${v ? v.life_months : 48}"></div></div>
      <div class="field"><span>启用账套时已提累计折旧（元）——只有 ${plabel(sp)} 之前购入的车辆才需要填</span><input type="text" class="num" name="opening_accum" value="${v ? amtInput(v.opening_accum) : ''}"></div>
      <div class="field"><span>备注</span><input type="text" name="note" value="${esc(v ? v.note : '')}"></div>
      <p class="hint">税法规定汽车最低折旧年限为 4 年（48 个月）。月折旧额 = 原值 ×（1 − 残值率）÷ 折旧月数。</p>`,
    buttons: [{ text: '取消' }, {
      text: '保存', cls: 'primary', onClick: async el => {
        const d = formData(el);
        d.id = v ? v.id : null;
        d.original = parseAmt(d.original); d.opening_accum = parseAmt(d.opening_accum);
        if (d.original === null || d.opening_accum === null) { toast('金额格式不正确', 'err'); return false; }
        await api('/api/vehicle/save', d);
        afterChange('车辆已保存');
      },
    }],
  });
}

function disposeForm(v) {
  const cashAccts = App.meta.accounts.filter(a => a.is_cash && a.is_leaf);
  const body = document.createElement('div');
  body.innerHTML = `<p class="hint">车辆：${esc(v.plate)} ${esc(v.model)}，原值 ${fmtN(v.original)}，累计折旧 ${fmtN(v.accum)}</p>
    <div class="field-row"><div class="field"><span>处置日期</span><input type="date" name="date" value="${lastDay(App.meta.current_period)}"></div>
    <div class="field"><span>售价（含税，元；报废无收入填 0）</span><input type="text" class="num" name="price"></div></div>
    <div class="field-row"><div class="field"><span>收款科目</span><select name="cash_account">${cashAccts.map(a => `<option value="${a.code}" ${a.code === '1002' ? 'selected' : ''}>${a.code} ${esc(a.full_name)}</option>`).join('')}</select></div>
    <div class="field"><span>收款银行账户</span><select name="cash_aux">${auxItems('银行账户').map(a => `<option value="${a.value}">${esc(a.code + ' ' + a.label)}</option>`).join('')}<option value="0">（不是银行存款时不用选）</option></select></div></div>
    <div class="field"><span>增值税处理</span><select name="vat_mode"><option>简易3%减按2%</option><option>13%</option><option>不计税</option></select></div>
    <p class="hint">处置当月照提折旧。确定后车辆标记为“已处置”，并打开一张处置凭证草稿：收款、冲销原值和累计折旧、计算增值税，差额记入“资产处置损益”。请核对后保存凭证。增值税处理方式请以税务顾问意见为准。</p>`;
  modal({
    title: '处置车辆（出售 / 报废）', body, width: 600,
    buttons: [{ text: '取消' }, {
      text: '确定并生成凭证', cls: 'primary', onClick: async el => {
        const d = formData(el);
        d.id = v.id; d.price = parseAmt(d.price);
        if (d.price === null) { toast('售价格式不正确', 'err'); return false; }
        App.draft = await api('/api/vehicle/dispose', d);
        go('voucher');
      },
    }],
  });
}

/* ================= 期初余额 ================= */
App.pages.opening = async (page) => {
  const data = await api('/api/opening');
  const sp = App.meta.start_period;
  const midYear = sp % 100 !== 1;
  const locked = data.locked;
  // entries: code -> [{aux, yb(带符号), yd, yc}]
  const entries = {};
  data.rows.forEach(r => (entries[r.account_code] = entries[r.account_code] || []).push({ aux: r.aux_id, yb: r.year_begin, yd: r.ytd_debit, yc: r.ytd_credit }));
  const accts = App.meta.accounts.filter(a => midYear || a.category !== '损益');
  const expanded = new Set();
  page.innerHTML = pageHead('期初余额', `录入账套启用时（${plabel(sp)} 初）各科目的余额`) + `
    ${locked ? '<div class="notice warn">已经有结账的期间，期初余额不能再修改。</div>' : ''}
    <div class="notice info">金额按科目的余额方向填写正数：资产类填借方余额，负债和权益类填贷方余额；累计折旧填正数。与方向相反的余额填负数。
      ${midYear ? '<br>账套从年中启用：还需要填写“启用前本年累计借方/贷方发生额”，损益类科目填写启用前本年实际累计发生额，这样利润表的本年累计才完整。' : ''}</div>
    <div class="toolbar"><button class="btn primary" id="save" ${locked ? 'disabled' : ''}>保存</button>
      ${hasFeature('vehicles') ? `<button class="btn" id="from-veh" ${locked ? 'disabled' : ''}>从车辆台账带入车辆原值和累计折旧</button>` : ''}
      <span class="sep"></span><span id="chk"></span>${printExportButtons()}</div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>科目编码</th><th>科目名称</th><th class="c">方向</th><th class="n">年初余额</th>
      ${midYear ? '<th class="n">启用前本年累计借方</th><th class="n">启用前本年累计贷方</th>' : ''}<th class="n">启用时期初余额</th><th></th></tr></thead><tbody id="list"></tbody></table></div>`;

  const sign = a => a.direction === '借' ? 1 : -1;
  const isPL = a => a.category === '损益';
  const leafAt = (a, e) => isPL(a) ? 0 : e.yb + e.yd - e.yc;
  const totals = code => {
    let yb = 0, yd = 0, yc = 0, st = 0;
    for (const c in entries) if (c.startsWith(code)) entries[c].forEach(e => { const a = App.acct[c]; yb += e.yb; yd += e.yd; yc += e.yc; st += a ? leafAt(a, e) : 0; });
    return { yb, yd, yc, st };
  };
  const nat = (a, v) => v * sign(a);
  const inputCell = (val, attrs) => `<td class="n" style="padding:2px 4px"><input type="text" class="num" style="width:130px" value="${val ? (val / 100).toFixed(2) : ''}" ${attrs} ${locked ? 'disabled' : ''}></td>`;

  const draw = () => {
    const html = [];
    accts.forEach(a => {
      const t = totals(a.code);
      const pl = isPL(a);
      if (!a.is_leaf) {
        html.push(`<tr class="lvl${a.level}" style="background:#fafbfc"><td class="code-txt">${a.code}</td><td class="name"><b>${esc(a.name)}</b></td><td class="c">${a.direction}</td>
          ${moneyCell(nat(a, t.yb))}${midYear ? moneyCell(t.yd) + moneyCell(t.yc) : ''}${moneyCell(nat(a, t.st))}<td></td></tr>`);
        return;
      }
      if (a.aux_type) {
        const list = entries[a.code] || [];
        const open = expanded.has(a.code);
        html.push(`<tr class="lvl${a.level}"><td class="code-txt">${a.code}</td><td class="name">${esc(a.name)} <span class="pill gray">${esc(a.aux_type)} ${list.length} 项</span></td><td class="c">${a.direction}</td>
          ${moneyCell(nat(a, t.yb))}${midYear ? moneyCell(t.yd) + moneyCell(t.yc) : ''}${moneyCell(nat(a, t.st))}
          <td><button class="btn link" data-tg="${a.code}">${open ? '收起' : '展开明细'}</button>${locked ? '' : `<button class="btn link" data-addaux="${a.code}">＋ 添加</button>`}</td></tr>`);
        if (open) list.forEach((e, i) => html.push(`<tr class="aux"><td></td><td class="name">${esc(auxText(e.aux) || '（未指定）')}</td><td></td>
          ${inputCell(nat(a, e.yb), `data-c="${a.code}" data-i="${i}" data-k="yb"`)}
          ${midYear ? inputCell(e.yd, `data-c="${a.code}" data-i="${i}" data-k="yd"`) + inputCell(e.yc, `data-c="${a.code}" data-i="${i}" data-k="yc"`) : ''}
          ${moneyCell(nat(a, leafAt(a, e)))}<td>${locked ? '' : `<button class="btn link danger" data-rm="${a.code}" data-i="${i}">删除</button>`}</td></tr>`));
        return;
      }
      const e = (entries[a.code] || [])[0] || { aux: 0, yb: 0, yd: 0, yc: 0 };
      if (pl) {
        // 损益类：只填启用前本年累计实际发生额
        const v = a.direction === '借' ? e.yd : e.yc;
        html.push(`<tr class="lvl${a.level}"><td class="code-txt">${a.code}</td><td class="name">${esc(a.name)}</td><td class="c">${a.direction}</td><td class="n muted small">—</td>
          ${a.direction === '借' ? inputCell(v, `data-c="${a.code}" data-i="0" data-k="yd"`) + '<td></td>' : '<td></td>' + inputCell(v, `data-c="${a.code}" data-i="0" data-k="yc"`)}
          <td class="n muted small">—</td><td></td></tr>`);
        return;
      }
      html.push(`<tr class="lvl${a.level}"><td class="code-txt">${a.code}</td><td class="name">${esc(a.name)}</td><td class="c">${a.direction}</td>
        ${inputCell(nat(a, e.yb), `data-c="${a.code}" data-i="0" data-k="yb"`)}
        ${midYear ? inputCell(e.yd, `data-c="${a.code}" data-i="0" data-k="yd"`) + inputCell(e.yc, `data-c="${a.code}" data-i="0" data-k="yc"`) : ''}
        ${moneyCell(nat(a, leafAt(a, e)))}<td></td></tr>`);
    });
    $('#list', page).innerHTML = html.join('');
    $$('input[data-c]', page).forEach(inp => inp.addEventListener('change', () => {
      const code = inp.dataset.c, i = +inp.dataset.i, k = inp.dataset.k, a = App.acct[code];
      const v = parseAmt(inp.value);
      if (v === null) { toast('金额格式不正确', 'err'); inp.focus(); return; }
      entries[code] = entries[code] || [];
      if (!entries[code][i]) entries[code][i] = { aux: 0, yb: 0, yd: 0, yc: 0 };
      entries[code][i][k] = k === 'yb' ? v * sign(a) : v;
      draw(); check();
    }));
    $$('[data-tg]', page).forEach(b => b.onclick = () => { const c = b.dataset.tg; expanded.has(c) ? expanded.delete(c) : expanded.add(c); draw(); });
    $$('[data-rm]', page).forEach(b => b.onclick = () => { entries[b.dataset.rm].splice(+b.dataset.i, 1); draw(); check(); });
    $$('[data-addaux]', page).forEach(b => b.onclick = () => addAux(b.dataset.addaux));
  };
  const addAux = code => {
    const a = App.acct[code];
    const body = document.createElement('div');
    body.innerHTML = `<div class="field"><span>${esc(a.aux_type)}</span><input type="text" name="aux"></div>
      <div class="field"><span>年初余额（${a.direction}方，元）</span><input type="text" class="num" name="yb"></div>`;
    attachPicker($('[name=aux]', body), { source: () => auxItems(a.aux_type) });
    modal({
      title: `添加 ${a.code} ${a.name} 的期初明细`, body,
      buttons: [{ text: '取消' }, {
        text: '添加', cls: 'primary', onClick: el => {
          const aux = +$('[name=aux]', el).dataset.value || 0;
          const v = parseAmt($('[name=yb]', el).value);
          if (!aux && a.aux_required) { toast('请选择' + a.aux_type, 'err'); return false; }
          if (v === null) { toast('金额格式不正确', 'err'); return false; }
          entries[code] = entries[code] || [];
          const ex = entries[code].find(e => e.aux === aux);
          if (ex) ex.yb = v * sign(a); else entries[code].push({ aux, yb: v * sign(a), yd: 0, yc: 0 });
          expanded.add(code); draw(); check();
        },
      }],
    });
  };
  const check = () => {
    let st = 0, yb = 0;
    for (const c in entries) entries[c].forEach(e => { const a = App.acct[c]; if (!a) return; yb += e.yb; st += leafAt(a, e); });
    const dr = Object.entries(entries).reduce((s, [c, l]) => s + l.reduce((x, e) => x + Math.max(0, App.acct[c] ? leafAt(App.acct[c], e) : 0), 0), 0);
    const cr = Object.entries(entries).reduce((s, [c, l]) => s + l.reduce((x, e) => x + Math.max(0, App.acct[c] ? -leafAt(App.acct[c], e) : 0), 0), 0);
    $('#chk', page).innerHTML = st === 0 && yb === 0
      ? `<span class="pill green">试算平衡　借方 ${fmtN(dr)} = 贷方 ${fmtN(cr)}</span>`
      : `<span class="pill red">不平衡：借方 ${fmtN(dr)}，贷方 ${fmtN(cr)}，差额 ${fmtN(st)}${yb !== st ? '；年初差额 ' + fmtN(yb) : ''}</span>`;
  };
  $('#save', page).onclick = async () => {
    const rows = [];
    for (const c in entries) entries[c].forEach(e => rows.push({ account_code: c, aux_id: e.aux, year_begin: e.yb, ytd_debit: e.yd, ytd_credit: e.yc }));
    try {
      const r = await api('/api/opening/save', { rows });
      toast(r.balanced ? '期初余额已保存，试算平衡' : '已保存，但借贷不平衡，请检查', r.balanced ? 'ok' : 'err');
    } catch (e) { toast(e.message, 'err'); }
  };
  if ($('#from-veh', page)) $('#from-veh', page).onclick = async () => {
    const r = await api('/api/opening/vehicles');
    if (!r.rows.length) return toast(`车辆台账中没有 ${plabel(sp)} 之前购入的车辆`, 'err');
    if (!await confirmBox(`将带入 ${r.rows.length} 辆车：原值合计 ${fmtN(r.rows.reduce((s, x) => s + x.year_begin, 0))}，累计折旧 ${fmtN(r.accum)}。\n这会覆盖“${acctText(r.fa_code)}”和“${acctText(r.depr_code)}”现有的期初数。`, '带入')) return;
    entries[r.fa_code] = r.rows.map(x => ({ aux: x.aux_id, yb: x.year_begin, yd: 0, yc: 0 }));
    entries[r.depr_code] = [{ aux: 0, yb: -r.accum, yd: 0, yc: 0 }];
    draw(); check();
    toast('已带入，请检查后点“保存”', 'ok');
  };
  bindPE(page, () => {
    const rows = [];
    accts.forEach(a => {
      const t = totals(a.code);
      const cells = [a.code, '  '.repeat(a.level - 1) + a.name, a.direction, nat(a, t.yb)];
      if (midYear) cells.push(t.yd, t.yc);
      cells.push(nat(a, t.st));
      rows.push(a.is_leaf ? cells : { cells, bold: true });
    });
    const cols = [{ name: '科目编码' }, { name: '科目名称', width: 30 }, { name: '方向', width: 6 }, { name: '年初余额', type: 'money' }];
    if (midYear) cols.push({ name: '启用前累计借方', type: 'money' }, { name: '启用前累计贷方', type: 'money' });
    cols.push({ name: '启用时期初余额', type: 'money' });
    exportXlsx('期初余额', cols, rows, plabel(sp) + ' 初');
  });
  draw(); check();
};

/* ================= 凭证模板 ================= */
App.pages.templates = async (page) => {
  const list = await api('/api/templates');
  const exprName = e => ({ '': '手工填写', T: '总金额' }[e] || (e.startsWith('NET:') ? `不含税金额（${e.slice(4)}%）` : e.startsWith('TAX:') ? `税额（${e.slice(4)}%）` : e));
  page.innerHTML = pageHead('凭证模板', '常用业务做成模板，录凭证时只需输入总金额') + `
    <div class="toolbar"><button class="btn primary" id="add">＋ 新增模板</button><span class="muted">也可以在凭证录入界面点“存为模板”。</span></div>
    ${list.map(t => `<div class="card"><div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><b>${esc(t.name)}</b><span class="grow" style="flex:1"></span>
      <button class="btn small" data-edit="${t.id}">修改</button><button class="btn small danger" data-del="${t.id}">删除</button></div>
      <table class="tbl"><tbody>${t.lines.map(l => `<tr><td style="width:60px">${l.dir}</td><td>${esc(acctText(l.account))}</td><td>${esc(l.summary)}</td><td class="muted">${exprName(l.expr)}</td></tr>`).join('')}</tbody></table></div>`).join('')
      || '<div class="empty">还没有模板</div>'}`;
  $('#add', page).onclick = () => templateForm(null);
  $$('[data-edit]', page).forEach(b => b.onclick = () => templateForm(list.find(t => t.id == b.dataset.edit)));
  $$('[data-del]', page).forEach(b => b.onclick = async () => {
    if (!await confirmBox('确定删除这个模板吗？', '删除', true)) return;
    await api('/api/template/delete', { id: +b.dataset.del }); toast('已删除', 'ok'); reloadTab();
  });
};
function templateForm(t) {
  const lines = t ? t.lines.map(l => Object.assign({}, l)) : [{ summary: '', account: '', dir: '借', expr: 'T' }, { summary: '', account: '', dir: '贷', expr: 'T' }];
  const exprOpts = ['', 'T', 'NET:13', 'TAX:13', 'NET:9', 'TAX:9', 'NET:6', 'TAX:6', 'NET:3', 'TAX:3'];
  const exprName = e => ({ '': '手工填写', T: '总金额' }[e] || (e.startsWith('NET:') ? `不含税（${e.slice(4)}%）` : `税额（${e.slice(4)}%）`));
  const body = document.createElement('div');
  const draw = () => {
    body.innerHTML = `<div class="field"><span>模板名称</span><input type="text" id="tname" value="${esc(t ? t.name : '')}"></div>
      <table class="tbl"><thead><tr><th>摘要</th><th>科目</th><th>方向</th><th>金额规则</th><th></th></tr></thead><tbody>
      ${lines.map((l, i) => `<tr data-i="${i}"><td><input type="text" data-k="summary" value="${esc(l.summary)}" style="width:150px"></td>
        <td><input type="text" data-k="account" style="width:230px"></td>
        <td><select data-k="dir"><option ${l.dir === '借' ? 'selected' : ''}>借</option><option ${l.dir === '贷' ? 'selected' : ''}>贷</option></select></td>
        <td><select data-k="expr">${exprOpts.map(e => `<option value="${e}" ${e === (l.expr || '') ? 'selected' : ''}>${exprName(e)}</option>`).join('')}</select></td>
        <td><button class="btn link danger" data-rm="${i}">删除</button></td></tr>`).join('')}</tbody></table>
      <button class="btn small" id="addl" style="margin-top:8px">＋ 增加一行</button>
      <p class="hint">“不含税 / 税额”会把录入的含税总金额自动拆成两部分，例如租金收入和销项税额。</p>`;
    $$('tr[data-i]', body).forEach(tr => {
      const l = lines[+tr.dataset.i];
      const acc = $('[data-k=account]', tr);
      attachPicker(acc, { source: () => acctItems(true), onPick: it => l.account = it ? it.value : '' });
      setPickerValue(acc, acctItem(l.account));
      $('[data-k=summary]', tr).oninput = e => l.summary = e.target.value;
      $('[data-k=dir]', tr).onchange = e => l.dir = e.target.value;
      $('[data-k=expr]', tr).onchange = e => l.expr = e.target.value;
    });
    $$('[data-rm]', body).forEach(b => b.onclick = () => { lines.splice(+b.dataset.rm, 1); keepName(); draw(); });
    $('#addl', body).onclick = () => { keepName(); lines.push({ summary: lines.length ? lines[lines.length - 1].summary : '', account: '', dir: '贷', expr: '' }); draw(); };
  };
  const keepName = () => { t = Object.assign({}, t || {}, { name: $('#tname', body).value }); };
  draw();
  modal({
    title: t && t.id ? '修改模板' : '新增模板', body, width: 820,
    buttons: [{ text: '取消' }, {
      text: '保存', cls: 'primary', onClick: async () => {
        await api('/api/template/save', { id: t && t.id, name: $('#tname', body).value, lines });
        toast('模板已保存', 'ok'); reloadTab();
      },
    }],
  });
}

/* ================= 数据导入 ================= */
App.pages.import = async (page) => {
  const card = (kind, title, desc, cols) => `<div class="card"><h2>${title}</h2><p class="hint">${desc}</p>
    <pre class="fmt">${cols}</pre>
    <div class="toolbar"><a class="btn" href="/api/import/template?kind=${kind}">下载导入模板</a>
      <input type="file" accept=".csv,text/csv" data-kind="${kind}"><button class="btn primary" data-imp="${kind}">导入</button></div>
    <div data-res="${kind}"></div></div>`;
  page.innerHTML = pageHead('数据导入', '从 Excel 批量导入。先在 Excel 中按模板整理好，然后“另存为 → CSV UTF-8（逗号分隔）”，再在这里导入。') + `
    <div class="notice info">导入是“全部成功才保存”：只要有一行出错，整个文件都不会导入，并会列出出错的行，修改后重新导入即可。</div>
    ${card('vehicles', '导入车辆台账', '一次导入全部车辆。车牌号已存在的会更新卡片信息。', '车牌号, 车型, 购置日期, 原值, 残值率%, 折旧月数, 期初累计折旧, 备注')}
    ${card('aux', '导入客户 / 供应商 / 员工 / 银行账户', '“类型”填 客户、供应商、员工 或 银行账户。编码已存在的会更新名称。', '类型, 编码, 名称')}
    ${card('vouchers', '导入记账凭证', '同一天、同一“凭证号”的行合成一张凭证（这里的凭证号只用来分组，系统会重新编号）。辅助核算编码填客户编码、车牌号、银行账户编码等。现金流量项目可以不填，系统会根据对方科目自动判断。', '日期, 凭证号, 摘要, 科目编码, 辅助核算编码, 借方金额, 贷方金额, 现金流量项目编码, 附件数')}
    <div class="card"><h2>现金流量项目编码</h2><table class="tbl"><tbody>${App.meta.cf_items.map(c => `<tr><td class="code-txt">${c.code}</td><td>${esc(c.name)}</td><td class="muted">${c.section}</td></tr>`).join('')}</tbody></table></div>`;
  $$('[data-imp]', page).forEach(b => b.onclick = async () => {
    const kind = b.dataset.imp;
    const file = $(`input[data-kind=${kind}]`, page).files[0];
    const res = $(`[data-res=${kind}]`, page);
    if (!file) return toast('请先选择文件', 'err');
    const buf = await file.arrayBuffer();
    let bin = '';
    const bytes = new Uint8Array(buf);
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    b.disabled = true; res.innerHTML = '<div class="notice info">正在导入…</div>';
    try {
      const r = await api('/api/import', { kind, data: btoa(bin) });
      res.innerHTML = `<div class="notice ok">导入成功：${r.count} 条。</div>`;
      await refreshMeta();
    } catch (e) { res.innerHTML = `<div class="notice err" style="white-space:pre-wrap">${esc(e.message)}</div>`; }
    finally { b.disabled = false; }
  });
};

/* ================= 备份与恢复 ================= */
App.pages.backup = async (page) => {
  const list = await api('/api/backups');
  page.innerHTML = pageHead('备份与恢复', '每天第一次打开软件时自动备份；也可以随时手动备份，并下载到 U 盘或网盘保存') + `
    <div class="toolbar"><button class="btn primary" id="now">立即备份</button>
      <a class="btn" href="/api/backup/download?company=${App.cid}">下载当前账套数据文件</a>
      <a class="btn" href="/api/company/export?company=${App.cid}">导出账套（拿到别的电脑导入）</a></div>
    <div class="notice info">要在另一台电脑上继续记账：在这里导出账套，然后在另一台电脑的“切换账套”页面里导入。</div>
    <div class="notice warn">数据只保存在这台电脑上。请定期把备份文件下载到 U 盘或网盘，防止电脑损坏导致数据丢失。系统保留最近 60 个备份。</div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>备份文件</th><th class="n">大小</th><th>操作</th></tr></thead><tbody>
    ${list.map(b => `<tr><td>${esc(b.name)}</td><td class="n">${(b.size / 1024).toFixed(0)} KB</td>
      <td><a class="btn link" href="/api/backup/download?company=${App.cid}&name=${encodeURIComponent(b.name)}">下载</a>
      <button class="btn link danger" data-restore="${esc(b.name)}">恢复到这个备份</button></td></tr>`).join('') || '<tr><td colspan="3" class="empty">还没有备份</td></tr>'}
    </tbody></table></div>`;
  $('#now', page).onclick = async () => { try { const r = await api('/api/backup/now', {}); toast('已备份：' + r.name, 'ok'); reloadTab(); } catch (e) { toast(e.message, 'err'); } };
  $$('[data-restore]', page).forEach(b => b.onclick = async () => {
    if (!await confirmBox(`确定把账套恢复到备份“${b.dataset.restore}”吗？\n当前数据会先自动备份一份，然后被替换。`, '恢复', true)) return;
    try { await api('/api/backup/restore', { name: b.dataset.restore }); toast('已恢复', 'ok'); App.meta = null; closeAllTabs(); go('home'); } catch (e) { toast(e.message, 'err'); }
  });
};

/* ================= 账套信息 ================= */
App.pages.company = async (page) => {
  const m = App.meta;
  page.innerHTML = pageHead('账套信息', '') + `
    <div class="card" style="max-width:560px"><h2>基本信息</h2>
      <div class="field-row"><div class="field"><span>会计准则</span><input type="text" value="${esc(m.standard_name)}" disabled></div>
        <div class="field"><span>行业</span><input type="text" value="${esc(m.industry_name)}" disabled></div></div>
      <div class="field"><span>公司名称</span><input type="text" name="name" value="${esc(m.company_name)}"></div>
      <div class="field"><span>制单人（录凭证、审核时默认使用）</span><input type="text" name="maker" value="${esc(m.maker)}"></div>
      <div class="field-row"><div class="field"><span>启用年度</span><input type="number" name="sy" value="${Math.floor(m.start_period / 100)}" ${m.has_vouchers ? 'disabled' : ''}></div>
        <div class="field"><span>启用月份</span><select name="sm" ${m.has_vouchers ? 'disabled' : ''}>${monthOptions(m.start_period % 100)}</select></div></div>
      ${m.has_vouchers ? '<p class="hint">已有凭证，启用期间不能再修改。</p>' : ''}
      <button class="btn primary" id="save">保存</button></div>
    <div class="card" style="max-width:560px"><h2>删除账套</h2>
      <p class="hint">删除前会自动备份，文件会移到 backups/已删除的账套 文件夹，不会彻底消失。请输入公司全称确认。</p>
      <div class="toolbar"><input type="text" id="confirm-name" placeholder="输入公司名称" style="width:260px"><button class="btn danger" id="del">删除账套</button></div></div>`;
  $('#save', page).onclick = async () => {
    const d = formData($('.card', page));
    const body = { name: d.name, maker: d.maker };
    if (!m.has_vouchers) body.start_period = +d.sy * 100 + +d.sm;
    try { await api('/api/company/update', body); afterChange('已保存'); } catch (e) { toast(e.message, 'err'); }
  };
  $('#del', page).onclick = async () => {
    const name = $('#confirm-name', page).value.trim();
    if (!await confirmBox(`确定删除账套“${name}”吗？`, '删除', true)) return;
    try { await api('/api/company/delete', { confirm_name: name }); toast('已删除', 'ok'); App.cid = null; store('cid', ''); App.meta = null; closeAllTabs(); go('companies'); }
    catch (e) { toast(e.message, 'err'); }
  };
};

/* ================= 操作日志 ================= */
App.pages.logs = async (page) => {
  const list = await api('/api/logs');
  page.innerHTML = pageHead('操作日志', '最近 300 条操作记录') + `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>时间</th><th>操作</th><th>内容</th></tr></thead><tbody>
    ${list.map(l => `<tr><td>${l.at}</td><td>${esc(l.action)}</td><td>${esc(l.detail)}</td></tr>`).join('')}</tbody></table></div>`;
};

/* ================= 软件更新 ================= */
App.pages.update = async (page) => {
  const [v, us, ds] = await Promise.all([api('/api/version'), api('/api/update/settings'), api('/api/desktop/status')]);
  const modeNow = ds.mode === 'window' ? '现在是<b>独立窗口</b>。'
    : `现在是<b>浏览器</b>${ds.reason ? '（' + esc(ds.reason) + '）' : ''}。`;
  page.innerHTML = pageHead('软件更新', '更新只替换程序文件，账套数据不受影响') + `
    <div class="card" style="max-width:820px">
      <h2>当前版本：v${esc(v.version)}</h2>
      <p class="hint">两种更新方法任选一种。更新前会自动备份所有账套，并把旧版程序保存到 backups/旧版本程序 文件夹；
        <b>data 文件夹里的账套数据不会被改动</b>。更新完成后，点右上角“退出软件”，再重新打开软件即可。</p>
    </div>
    <div class="card" id="upd-progress" style="max-width:820px;display:none"></div>
    <div class="card" style="max-width:820px">
      <h2>方法一：选择更新包（不需要联网）</h2>
      <p class="hint">拿到新版本的“更新包”（例如“明簿-更新包-v1.6.3.zip”，几百 KB，Windows 和 Mac 通用）后，不用解压，直接在这里选择它。
        也可以选择完整安装包，效果一样。</p>
      <div class="toolbar"><input type="file" id="upd-file" accept=".zip"><button class="btn primary" id="upd-btn">开始更新</button></div>
    </div>
    <div class="card" style="max-width:820px">
      <h2>方法二：在线检查更新</h2>
      <p class="hint">如果你把新版本发布在网上（例如 GitHub、Gitee 或自己的网站），在这里填写 latest.json 的地址，以后点“检查更新”就能自动下载安装。发布方法见“开发说明.md”。<br>国内网络连不上 GitHub 时，软件会自动改用国内加速地址下载，并核对多个来源的更新信息和 sha256 校验值。</p>
      <div class="toolbar"><input type="text" id="upd-url" value="${esc(us.url || '')}" placeholder="https://…/latest.json" style="width:460px">
        <button class="btn" id="url-save">保存地址</button><button class="btn primary" id="check">检查更新</button></div>
      <div id="chk-res"></div>
      <div class="toolbar" style="margin-top:8px"><label><input type="checkbox" id="auto-check" ${us.auto_check !== false ? 'checked' : ''}>
        打开软件时自动检查新版本（有新版本时在右下角提示；连不上网时不提示）</label></div>
    </div>
    <div class="card" style="max-width:820px">
      <h2>打开方式</h2>
      <p class="hint">${modeNow}独立窗口像普通软件一样单独显示，关掉窗口就退出软件；打不开时会自动改用浏览器。
        如果独立窗口用起来有问题，可以改回浏览器。改了以后，退出软件再重新打开才生效。</p>
      <div class="toolbar"><label><input type="radio" name="ui-prefer" value="window" ${ds.prefer !== 'browser' ? 'checked' : ''}> 独立窗口（推荐）</label>
        <label><input type="radio" name="ui-prefer" value="browser" ${ds.prefer === 'browser' ? 'checked' : ''}> 浏览器</label></div>
    </div>
    <p class="hint">软件文件夹：${esc(v.root)}<br>数据文件夹：${esc(v.data_dir)}</p>`;
  // 两种方法共用的进度显示：后台每一步的进度由 /api/update/progress 提供
  const box = $('#upd-progress', page);
  const fmtB = n => n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
  const lock = on => { ['#upd-btn', '#check', '#do-online'].forEach(id => { const b = $(id, page); if (b) b.disabled = on; }); };
  const render = st => {
    if (!st || st.state === 'idle') { box.style.display = 'none'; return; }
    box.style.display = '';
    const idx = st.stages.findIndex(x => x.key === st.stage);
    const steps = st.stages.map((x, i) => {
      let cls = i < idx ? 'done' : i === idx ? 'cur' : '';
      if (st.state === 'error' && i === idx) cls = 'fail';
      if (st.state === 'done') cls = i < idx ? 'done' : 'cur';
      const mark = cls === 'done' ? '✓' : cls === 'fail' ? '✕' : String(i + 1);
      return `<li class="${cls}"><span class="dot">${mark}</span>${esc(x.name)}</li>`;
    }).join('');
    // 进度条：下载/安装等有数量的步骤按实际进度，其余步骤按“第几步”
    let pct, detail = '';
    if (st.total > 0 && st.state === 'running') {
      pct = Math.min(100, Math.floor(st.done * 100 / st.total));
      if (st.stage === 'download') {
        detail = `已下载 ${fmtB(st.done)} / ${fmtB(st.total)}${st.speed ? ' · ' + fmtB(st.speed) + '/秒' : ''}`;
      } else if (st.stage === 'install') detail = `已替换 ${st.done} / ${st.total} 个文件`;
    } else if (st.stage === 'download' && st.state === 'running') {
      pct = null; detail = st.done ? `已下载 ${fmtB(st.done)}（服务器没有告知文件大小）` : '正在连接…';
    } else pct = st.state === 'done' ? 100 : null;
    const overall = st.state === 'done' ? 100 : Math.round((Math.max(idx, 0) + (pct || 0) / 100) * 100 / (st.stages.length - 1));
    const bar = pct === null && st.state === 'running'
      ? `<div class="pbar busy"><i></i></div>` : `<div class="pbar${st.state === 'error' ? ' fail' : ''}"><i style="width:${pct === null ? 0 : pct}%"></i></div>`;
    let head;
    if (st.state === 'done') {
      const r = st.result || {};
      head = `<div class="notice ok">已从 v${esc(r.old_version)} 更新到 v${esc(r.new_version)}，共替换 ${r.files} 个文件。<br>
        <b>请点右上角“退出软件”，然后重新打开软件</b>，新版本才会生效。旧版程序已备份到 ${esc(r.code_backup)}。</div>`;
    } else if (st.state === 'error') {
      head = `<div class="notice err"><b>更新没有完成：</b>${esc(st.error)}</div>`;
    } else head = '';
    box.innerHTML = `<h2>${st.state === 'running' ? '正在更新…' : st.state === 'done' ? '更新完成' : '更新失败'}
        <span class="hint" style="font-weight:normal;margin-left:8px">总进度 ${st.state === 'error' ? '—' : overall + '%'} · 已用时 ${st.elapsed} 秒</span></h2>
      <ol class="upd-steps">${steps}</ol>${head}
      ${st.state === 'running' ? `<div class="upd-msg">${esc(st.message || '')}</div>${bar}
        <div class="hint">${esc(detail)}${st.source ? `${detail ? ' · ' : ''}下载地址：<b>${esc(st.source)}</b>` : ''}</div>` : ''}
      ${st.log.length ? `<details ${st.state === 'error' ? 'open' : ''} style="margin-top:8px"><summary class="hint">详细过程（${st.log.length} 条）</summary>
        <pre class="upd-log">${esc(st.log.join('\n'))}</pre></details>` : ''}`;
  };
  let timer = null;
  const poll = async () => {
    let st;
    try { st = await api('/api/update/progress'); }
    catch (e) { if (!page.isConnected) return; timer = setTimeout(poll, 1500); return; }
    if (!page.isConnected) return; // 已经离开这个页面
    render(st);
    lock(st.state === 'running');
    if (st.state === 'running') timer = setTimeout(poll, 400);
    else if (st.state === 'done') toast('更新完成，请退出软件后重新打开', 'ok');
  };
  const start = async (path, body) => {
    clearTimeout(timer);
    lock(true);
    try { render(await api(path, body)); box.scrollIntoView({ block: 'nearest' }); poll(); }
    catch (e) { lock(false); render({ state: 'error', stage: '', stages: [], error: e.message, log: [], elapsed: 0 }); }
  };
  // 打开这个页面时如果有更新正在进行（例如切换了标签页），接着显示进度
  api('/api/update/progress').then(st => { if (st.state === 'running') poll(); }).catch(() => {});

  $('#upd-btn', page).onclick = async () => {
    const file = $('#upd-file', page).files[0];
    if (!file) return toast('请先选择更新包', 'err');
    if (!await confirmBox('开始更新吗？', '开始更新')) return;
    box.style.display = '';
    box.innerHTML = '<h2>正在更新…</h2><div class="upd-msg">正在读取更新包…</div><div class="pbar busy"><i></i></div>';
    let data;
    try { data = await fileToB64(file); } catch (e) { box.innerHTML = `<div class="notice err">读取文件失败：${esc(e.message)}</div>`; return; }
    start('/api/update/start', { data });
  };
  page.querySelectorAll('[name="ui-prefer"]').forEach(r => r.onchange = async () => {
    try { await api('/api/desktop/settings', { prefer: r.value }); toast('已保存，下次打开软件时生效', 'ok'); }
    catch (e) { toast(e.message, 'err'); }
  });
  $('#auto-check', page).onchange = async e => {
    try { await api('/api/update/settings', { auto_check: e.target.checked }); toast(e.target.checked ? '已打开自动检查，下次打开软件时生效' : '已关闭自动检查', 'ok'); }
    catch (err) { toast(err.message, 'err'); }
  };
  $('#url-save', page).onclick = async () => {
    try { await api('/api/update/settings', { url: $('#upd-url', page).value }); toast('已保存', 'ok'); } catch (e) { toast(e.message, 'err'); }
  };
  $('#check', page).onclick = async () => {
    const res = $('#chk-res', page);
    const url = $('#upd-url', page).value.trim();
    res.innerHTML = '<div class="notice info">正在检查…（GitHub 连不上时会自动改用国内加速地址，可能要等十几秒）</div>';
    try {
      const r = await api('/api/update/check', { url });
      const via = r.source && r.source !== '直连' ? `<div class="hint">（GitHub 直连失败，已通过加速地址 ${esc(r.source)} 获取）</div>` : '';
      if (!r.has_update) { res.innerHTML = `<div class="notice ok">已经是最新版本（v${esc(r.current)}）。${via}</div>`; return; }
      res.innerHTML = `<div class="notice info">发现新版本 <b>v${esc(r.latest)}</b>（当前 v${esc(r.current)}）。
        ${r.notes ? `<div style="white-space:pre-wrap;margin-top:6px">${esc(r.notes)}</div>` : ''}${via}</div>
        <button class="btn primary" id="do-online">下载并更新</button>`;
      $('#do-online', res).onclick = () => start('/api/update/online/start', { url });
    } catch (e) { res.innerHTML = `<div class="notice err">${esc(e.message)}</div>`; }
  };
};
