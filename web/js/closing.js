/* 期末处理：计提折旧、结转增值税、计提税金及附加、结转损益、年末结转、结账、反结账 */
App.pages.closing = async (page) => {
  const st = await api('/api/closing/status');
  const p = st.period;
  const dep = st.depreciation;
  const isDec = p % 100 === 12;
  const veh = hasFeature('vehicles');
  let n = 0;
  const step = () => ++n;
  const profitName = (App.meta.accounts.find(a => a.code === App.meta.keymap.profit) || {}).name || '本年利润';
  const profitCode = App.meta.keymap.profit || '';
  const failed = st.checks.filter(c => !c.ok && !c.warn_only);
  const vat = st.vat, sur = st.surtax;
  const vno = n => '记-' + String(n).padStart(4, '0');
  const vatCard = () => !vat.enabled ? '' : `<div class="card"><h2>第 ${step()} 步　结转增值税</h2>
      <p class="hint">把“应交税费—应交增值税”各明细（销项税额、进项税额、进项税额转出、已交税金等）的合计余额结清：贷方余额是本月应交未交的增值税，生成“借：应交税费—应交增值税（转出未交增值税），贷：应交税费—未交增值税”的凭证，下月申报缴纳时再“借：未交增值税，贷：银行存款”。借方余额是留抵税额，留到下月继续抵扣，不需要结转。请在本月销售、采购凭证都录完后执行；结转后又补录了凭证，再执行一次即可。</p>
      ${vat.pending ? `<div class="notice info">应交增值税贷方余额 <b>${fmtN(vat.pending)}</b> 元，即本月应交未交增值税。${vat.transferred ? `本月此前已结转 ${fmtN(vat.transferred)} 元。` : ''}</div>${vat.can_transfer ? '<button class="btn primary" id="do-vat">结转增值税</button>' : '<div class="notice err">找不到“转出未交增值税”或“未交增值税”科目，请在“设置 → 会计科目”中检查。</div>'}`
        : vat.retained ? `<div class="notice ok">应交增值税为借方余额 <b>${fmtN(vat.retained)}</b> 元（留抵税额），留到下月继续抵扣，不需要结转。${vat.transferred ? `本月已结转未交增值税 ${fmtN(vat.transferred)} 元。` : ''}</div>`
          : vat.transferred ? `<div class="notice ok">本月已结转未交增值税 <b>${fmtN(vat.transferred)}</b> 元。</div>`
            : '<div class="notice ok">本月应交增值税没有余额，不需要结转。</div>'}
      ${vat.simple ? `<p class="hint">另有简易计税应纳增值税 ${fmtN(vat.simple)} 元（记在“应交税费—简易计税”，不参与上面的结转，但计入附加税的计税依据）。</p>` : ''}
    </div>`;
  const rateInput = it => `<input type="text" class="num" data-rate="${it.key}" value="${esc(it.rate)}" style="width:64px" ${sur.done ? 'disabled' : ''}> %`;
  const surCard = () => !sur.enabled ? '' : `<div class="card"><h2>第 ${step()} 步　计提税金及附加</h2>
      <p class="hint">以本月应缴增值税（转出未交增值税 + 简易计税）为计税依据，计提城市维护建设税（市区 7%、县城和镇 5%、其他地区 1%）、教育费附加（3%）和地方教育附加（2%）。享受减半政策或免征时可以直接改税率（例如减半填 3.5、1.5、1；免征填 0），改过的税率会记住。生成“借：税金及附加，贷：应交税费”的凭证；“税金及附加”在下一步“结转损益”时一并转入本年利润。</p>
      ${sur.done ? '<div class="notice ok">本月已计提税金及附加。如需重新计提，请在凭证查询中删除本月的“计提附加税”凭证。</div>' : ''}
      <div class="tbl-wrap" style="max-width:640px;margin-bottom:10px"><table class="tbl"><thead><tr><th>项目</th><th class="n">计税依据</th><th class="n">税率</th><th class="n">金额</th></tr></thead>
        <tbody>${sur.items.map(it => `<tr><td>${esc(it.name)}</td><td class="n">${fmtN(sur.base)}</td><td class="n">${rateInput(it)}</td><td class="n" data-amt="${it.key}">${fmtN(it.amount)}</td></tr>`).join('')}
        <tr class="sum"><td>合计</td><td></td><td></td><td class="n" id="sur-total">${fmtN(sur.total)}</td></tr></tbody></table></div>
      ${sur.done ? '' : sur.vat_pending ? '<div class="notice info">请先完成上一步“结转增值税”，再计提税金及附加。</div>'
        : sur.base > 0 ? '<button class="btn primary" id="do-sur">计提税金及附加</button>' : '<div class="notice ok">本月没有应缴增值税，不需要计提。</div>'}
    </div>`;
  page.innerHTML = pageHead('期末处理与结账', `当前会计期间：${plabel(p)}。按顺序完成下面的步骤后结账。`) + `
    ${veh ? `<div class="card"><h2>第 ${step()} 步　计提车辆折旧</h2>
      <p class="hint">按车辆台账自动计算：当月购入的车辆下月开始计提，当月处置的车辆当月照提。生成一张“借：主营业务成本—车辆折旧，贷：累计折旧”的凭证。</p>
      ${dep.done ? '<div class="notice ok">本月已计提折旧。如需重新计提，请在凭证查询中删除本月的“折旧”凭证。</div>'
        : dep.count ? `<div class="notice info">本月应计提 <b>${dep.count}</b> 辆车，折旧合计 <b>${fmtN(dep.amount)}</b> 元。</div><button class="btn primary" id="do-dep">计提折旧</button>`
          : '<div class="notice info">本月没有需要计提折旧的车辆。</div>'}
    </div>` : ''}
    ${vatCard()}
    ${surCard()}
    <div class="card"><h2>第 ${step()} 步　结转损益</h2>
      <p class="hint">${veh ? '' : '固定资产折旧、费用摊销等请先用凭证录入（可用“凭证模板”）。'}每个收入、成本、费用科目单独生成一张凭证，把余额转入“${profitCode} ${esc(profitName)}”。请在本月所有业务凭证（包括工资、税费等）录完之后再执行。如果结转后又补录了凭证，再执行一次即可，系统只结转剩余的金额。</p>
      ${st.carry_preview.length ? `<div class="notice info">将生成 <b>${st.carry_preview.length}</b> 张结转凭证，每个损益科目一张（含该科目的全部明细）：${st.carry_preview.map(x => esc(x.code + ' ' + x.name)).join('、')}。</div><button class="btn primary" id="do-carry">结转损益</button>`
        : '<div class="notice ok">损益类科目已全部结转（或没有余额）。</div>'}
    </div>
    ${isDec ? `<div class="card"><h2>第 ${step()} 步　年末结转（仅 12 月）</h2>
      <p class="hint">把“本年利润”和“利润分配”各明细科目的余额转入“利润分配—未分配利润”。如需提取盈余公积，请先手工录入“借：利润分配—提取盈余公积，贷：盈余公积”。</p>
      ${st.year_end_needed ? '<button class="btn primary" id="do-ye">年末结转</button>' : '<div class="notice ok">不需要年末结转，或已完成。</div>'}</div>` : ''}
    <div class="card"><h2>第 ${step()} 步　结账检查</h2>
      <ul class="check-list">${st.checks.map(c => `<li><span class="ic ${c.ok ? 'green' : c.warn_only ? '' : 'red'}">${c.ok ? '✓' : c.warn_only ? '!' : '✕'}</span><b style="min-width:150px;display:inline-block">${esc(c.name)}</b><span class="${c.ok ? 'muted' : c.warn_only ? '' : 'red'}">${esc(c.msg)}</span></li>`).join('')}</ul>
      <div class="toolbar" style="margin-top:14px">
        <button class="btn primary" id="do-close" ${failed.length ? 'disabled' : ''}>结账（${plabel(p)}）</button>
        ${st.last_closed ? `<button class="btn danger" id="do-reopen">反结账（${plabel(st.last_closed)}）</button>` : ''}
        <a class="btn" href="#/balance">查看科目余额表</a><a class="btn" href="#/bs">查看报表</a>
      </div>
      <p class="hint">结账后本月凭证不能再修改；发现错误时可以“反结账”，每次只能退回最近结账的一个月。</p>
    </div>`;
  const run = async (url, okMsg) => {
    try { const r = await api(url, { period: p }); toast(okMsg(r), 'ok'); await refreshMeta(); reloadTab(); }
    catch (e) { toast(e.message, 'err'); }
  };
  const b = id => $('#' + id, page);
  if (b('do-dep')) b('do-dep').onclick = () => run('/api/closing/depreciation', r => `已生成折旧凭证 记-${String(r.number).padStart(4, '0')}，${r.count} 辆，${fmtN(r.amount)} 元`);
  if (b('do-vat')) b('do-vat').onclick = () => run('/api/closing/vat', r => `已生成结转增值税凭证 ${vno(r.number)}，转出未交增值税 ${fmtN(r.amount)} 元`);
  const rates = () => { const o = {}; $$('[data-rate]', page).forEach(i => o[i.dataset.rate] = i.value.trim()); return o; };
  $$('[data-rate]', page).forEach(inp => inp.oninput = () => {
    let total = 0;
    $$('[data-rate]', page).forEach(i => {
      const r = parseFloat(i.value);
      const amt = isFinite(r) && r >= 0 ? Math.round(sur.base * r / 100) : 0;
      total += amt;
      $(`[data-amt="${i.dataset.rate}"]`, page).textContent = fmtN(amt);
    });
    $('#sur-total', page).textContent = fmtN(total);
  });
  if (b('do-sur')) b('do-sur').onclick = async () => {
    try { const r = await api('/api/closing/surtax', { period: p, rates: rates() }); toast(`已生成计提税金及附加凭证 ${vno(r.number)}，合计 ${fmtN(r.amount)} 元`, 'ok'); await refreshMeta(); reloadTab(); }
    catch (e) { toast(e.message, 'err'); }
  };
  if (b('do-carry')) b('do-carry').onclick = () => run('/api/closing/carry', r => `已生成 ${r.count} 张结转凭证（记-${String(r.first).padStart(4, '0')} 至 记-${String(r.last).padStart(4, '0')}），本次结转利润 ${fmtN(r.profit)} 元`);
  if (b('do-ye')) b('do-ye').onclick = () => run('/api/closing/yearend', r => `已生成年末结转凭证 记-${String(r.number).padStart(4, '0')}`);
  b('do-close').onclick = async () => {
    if (!await confirmBox(`确定结账 ${plabel(p)} 吗？结账后该月凭证将被锁定。`, '结账')) return;
    run('/api/closing/close', r => `${plabel(r.closed)} 已结账，当前期间进入 ${plabel(r.current_period)}`);
  };
  if (b('do-reopen')) b('do-reopen').onclick = async () => {
    if (!await confirmBox(`确定反结账 ${plabel(st.last_closed)} 吗？反结账后可以修改该月凭证，修改完需要重新结账。`, '反结账', true)) return;
    run('/api/closing/reopen', r => `${plabel(r.reopened)} 已反结账`);
  };
};
