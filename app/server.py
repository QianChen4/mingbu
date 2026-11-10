"""
本地 Web 服务：只监听本机 127.0.0.1，界面（浏览器的应用模式窗口）通过 /api/... 读写数据。
"""
import base64
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import db, paths, desktop, applock, migrate, ledger, vouchers as V, vehicles as VH, closing as C, reports as R, io_utils as IO, updater, VERSION
from .db import AppError

WEB_DIR = os.path.join(paths.CODE_DIR, 'web')

GET_ROUTES = {}
POST_ROUTES = {}


def get(path, needs_company=True):
    def deco(fn):
        GET_ROUTES[path] = (fn, needs_company)
        return fn
    return deco


def post(path, needs_company=True):
    def deco(fn):
        POST_ROUTES[path] = (fn, needs_company)
        return fn
    return deco


class FileResponse:
    def __init__(self, data, filename, ctype):
        self.data, self.filename, self.ctype = data, filename, ctype


def P(q, name, default=None, cast=str):
    v = q.get(name, [default])[0]
    if v in (None, ''):
        return default
    try:
        return cast(v)
    except Exception:
        raise AppError('参数 %s 不正确' % name)


# ================================================================ 账套

@get('/api/companies', needs_company=False)
def api_companies(conn, q):
    return db.list_companies()


@post('/api/companies/create', needs_company=False)
def api_company_create(conn, b):
    cid = db.create_company(b.get('name'), b.get('start_year'), b.get('start_month'), b.get('copy_from') or '',
                            b.get('standard') or 'enterprise', b.get('industry') or None)
    return {'id': cid}


@get('/api/chart_options', needs_company=False)
def api_chart_options(conn, q):
    from . import charts
    return charts.options()


@post('/api/aux_type/add')
def api_aux_type_add(conn, b):
    V.add_aux_type(conn, b.get('name'))
    return {'ok': True}


@post('/api/aux_type/delete')
def api_aux_type_delete(conn, b):
    V.delete_aux_type(conn, b.get('name'))
    return {'ok': True}


@get('/api/version', needs_company=False)
def api_version(conn, q):
    return {'version': VERSION, 'root': db.ROOT, 'data_dir': db.DATA_DIR, 'started': STARTED,
            'last_page_at': watchdog.last_new}


# ================================================================ 启动密码

@get('/api/lock/status', needs_company=False)
def api_lock_status(conn, q, token=''):
    return applock.status(token)


@post('/api/lock/unlock', needs_company=False)
def api_lock_unlock(conn, b, token=''):
    return applock.unlock(b.get('password') or '')


@post('/api/lock/lock', needs_company=False)
def api_lock_lock(conn, b, token=''):
    applock.lock_all()
    return {'ok': True}


@post('/api/lock/set', needs_company=False)
def api_lock_set(conn, b, token=''):
    return applock.set_password(b.get('password') or '', b.get('old_password') or '', b.get('hint') or '',
                                b.get('idle_minutes'))


@post('/api/lock/options', needs_company=False)
def api_lock_options(conn, b, token=''):
    return applock.set_options(b.get('idle_minutes'), b.get('hint'))


@post('/api/lock/disable', needs_company=False)
def api_lock_disable(conn, b, token=''):
    return applock.disable(b.get('password') or '')


@post('/api/lock/recover', needs_company=False)
def api_lock_recover(conn, b, token=''):
    return applock.recover(b.get('code') or '', b.get('password') or '')


# 锁定时也能用的接口：版本、解锁、心跳、退出
LOCK_FREE = {'/api/version', '/api/lock/status', '/api/lock/unlock', '/api/lock/recover', '/api/heartbeat',
             '/api/shutdown'}
# 不算“有操作”的接口（不会推迟闲置自动锁定）
NOT_ACTIVITY = {'/api/heartbeat', '/api/lock/status', '/api/update/progress', '/api/update/auto'}


# ================================================================ 数据位置、找回旧账套

@get('/api/data/location', needs_company=False)
def api_data_location(conn, q):
    r = migrate.data_location()
    r.update(updater.version_info())
    return r


@post('/api/data/open_folder', needs_company=False)
def api_data_open_folder(conn, b):
    which = b.get('which')
    path = {'data': db.DATA_DIR, 'backup': db.BACKUP_DIR, 'home': db.ROOT}.get(which)
    if not path:
        raise AppError('未知的文件夹')
    return migrate.open_folder(path)


@post('/api/data/scan', needs_company=False)
def api_data_scan(conn, b):
    return migrate.scan()


@post('/api/data/inspect', needs_company=False)
def api_data_inspect(conn, b):
    folder = (b.get('folder') or '').strip().strip('"')
    if not folder:
        raise AppError('请填写文件夹位置')
    r = migrate.inspect_folder(folder)
    if not r:
        raise AppError('这个文件夹里没有找到账套。请选择旧版软件的文件夹（里面有 data 文件夹），或 data 文件夹本身')
    return r


@post('/api/data/import_folder', needs_company=False)
def api_data_import_folder(conn, b):
    return migrate.import_from(b.get('folder') or '', b.get('files') or None, b.get('mode') or 'new')


@get('/api/companies/export_all', needs_company=False)
def api_companies_export_all(conn, q):
    fn, data = db.export_all_zip()
    db.mark_exported()
    return FileResponse(data, fn, 'application/zip')


@post('/api/companies/import', needs_company=False)
def api_companies_import(conn, b):
    raw = base64.b64decode(b.get('data') or '')
    if not raw:
        raise AppError('请选择要导入的文件')
    return db.import_companies(raw, b.get('filename') or '', b.get('mode') or 'replace', bool(b.get('force')))


@post('/api/update/start', needs_company=False)
def api_update_start(conn, b):
    """离线更新（后台进行，用 /api/update/progress 看进度）。"""
    raw = base64.b64decode(b.get('data') or '')
    if not raw:
        raise AppError('请选择新版本的压缩包')
    return updater.start_job('file', raw)


@post('/api/update/online/start', needs_company=False)
def api_update_online_start(conn, b):
    """在线更新（后台进行，用 /api/update/progress 看进度）。"""
    return updater.start_job('online', b.get('url') or updater.get_update_url())


@get('/api/update/progress', needs_company=False)
def api_update_progress(conn, q):
    return updater.job_status()


@post('/api/update/rollback', needs_company=False)
def api_update_rollback(conn, b):
    """退回上一个版本（重启后生效）。"""
    return updater.start_job('rollback', None)


@post('/api/restart', needs_company=False)
def api_restart(conn, b):
    """立即重启：关掉现在的后台程序，用启动程序重新打开（会用 versions/current.txt 里的版本）。
    页面不会关闭，它会等新的后台程序起来后自动刷新。"""
    if updater.busy():
        raise AppError('正在更新，请等更新完成后再重启')
    _state['restart'] = True
    threading.Timer(0.3, _stop_server).start()
    return {'ok': True}


@get('/api/update/settings', needs_company=False)
def api_update_settings(conn, q):
    r = {'url': updater.get_update_url(), 'default_url': updater.UPDATE_URL, 'version': VERSION,
         'auto_check': updater.get_auto_check()}
    r.update(updater.version_info())
    return r


@post('/api/update/settings', needs_company=False)
def api_update_settings_save(conn, b):
    if 'url' in b:
        updater.set_update_url(b.get('url') or '')
    if 'auto_check' in b:
        updater.set_auto_check(b.get('auto_check'))
    return {'ok': True}


@get('/api/update/auto', needs_company=False)
def api_update_auto(conn, q):
    """打开软件时的自动检查（每次启动只联网一次，失败不报错）。"""
    return updater.auto_check()


@post('/api/update/check', needs_company=False)
def api_update_check(conn, b):
    return updater.check_online(b.get('url') or updater.get_update_url())


@get('/api/company/export')
def api_company_export(conn, q, cid=None):
    fn, data = db.export_company_file(cid)
    db.mark_exported()
    return FileResponse(data, fn, 'application/octet-stream')


@post('/api/company/update')
def api_company_update(conn, b):
    if 'name' in b:
        name = (b.get('name') or '').strip()
        if not name:
            raise AppError('公司名称不能为空')
        db.set_meta(conn, 'company_name', name)
    if 'maker' in b:
        db.set_meta(conn, 'maker', (b.get('maker') or '').strip())
    if 'start_period' in b:
        sp = int(b['start_period'])
        if sp != ledger.start_period(conn):
            if conn.execute('SELECT COUNT(*) FROM vouchers').fetchone()[0] or ledger.closed_periods(conn):
                raise AppError('已经有凭证，不能修改启用期间')
            if not (200001 <= sp <= 210012 and 1 <= sp % 100 <= 12):
                raise AppError('启用期间不正确')
            db.set_meta(conn, 'start_period', sp)
    return {'ok': True}


@post('/api/company/delete')
def api_company_delete(conn, b, cid=None):
    meta = db.get_meta(conn)
    if (b.get('confirm_name') or '').strip() != meta.get('company_name'):
        raise AppError('输入的公司名称不一致')
    return {'delete': True}


@get('/api/meta')
def api_meta(conn, q):
    meta = db.get_meta(conn)
    prof = db.company_profile(conn)
    accts = ledger.load_accounts(conn)
    aux = [dict(r) for r in conn.execute('SELECT * FROM aux_items ORDER BY type, code')]
    cf = [dict(r) for r in conn.execute('SELECT * FROM cf_items ORDER BY sort')]
    closed = sorted(ledger.closed_periods(conn))
    years = [r[0] // 100 for r in conn.execute('SELECT DISTINCT period FROM vouchers')]
    sp = ledger.start_period(conn)
    cur = ledger.current_period(conn)
    years = sorted(set(years + [sp // 100, cur // 100]))
    return {
        'company_name': meta.get('company_name'), 'maker': meta.get('maker', ''),
        'start_period': sp, 'current_period': cur, 'closed': closed, 'years': years,
        'accounts': accts, 'aux_items': aux, 'aux_types': prof['aux_types'], 'cf_items': cf,
        'cf_suggest': prof['cf_suggest'], 'report_lines': R.report_line_options(prof['standard']),
        'standard': prof['standard'], 'standard_name': prof['standard_name'], 'industry': prof['industry'],
        'industry_name': prof['industry_name'], 'features': prof['features'], 'keymap': prof['keymap'],
        'vehicle_label': prof['vehicle_label'], 'vat_mode': prof['vat_mode'],
        'has_vouchers': conn.execute('SELECT COUNT(*) FROM vouchers').fetchone()[0] > 0,
    }


@get('/api/home')
def api_home(conn, q):
    cur = ledger.current_period(conn)
    cnt = conn.execute('SELECT COUNT(*), COALESCE(SUM(audited = 0), 0) FROM vouchers WHERE period = ?', (cur,)).fetchone()
    recent = V.list_vouchers(conn, cur, cur)[-8:]
    status = C.closing_status(conn, cur)
    veh = conn.execute("SELECT COUNT(*), COALESCE(SUM(status = '在用'), 0) FROM vehicles").fetchone()
    return {'current_period': cur, 'voucher_count': cnt[0], 'unaudited': cnt[1], 'recent': recent,
            'export_reminder': db.export_reminder(conn), 'status': status, 'vehicle_count': veh[0], 'vehicle_in_use': veh[1]}


@get('/api/logs')
def api_logs(conn, q):
    return [dict(r) for r in conn.execute('SELECT * FROM logs ORDER BY id DESC LIMIT 300')]


# ================================================================ 凭证

@get('/api/vouchers')
def api_vouchers(conn, q):
    return V.list_vouchers(conn, P(q, 'from'), P(q, 'to'), P(q, 'q', ''),
                           P(q, 'account', ''), P(q, 'status', ''),
                           P(q, 'no_from', None, int), P(q, 'no_to', None, int),
                           P(q, 'amt_from', None, int), P(q, 'amt_to', None, int))


@get('/api/voucher')
def api_voucher(conn, q):
    return V.get_voucher(conn, P(q, 'id', cast=int))


@post('/api/voucher/print')
def api_voucher_print(conn, b):
    return V.vouchers_with_lines(conn, b.get('ids') or [])


@post('/api/voucher/save')
def api_voucher_save(conn, b):
    vid = V.save_voucher(conn, b)
    return V.get_voucher(conn, vid)


@post('/api/voucher/delete')
def api_voucher_delete(conn, b):
    for vid in b.get('ids') or [b.get('id')]:
        V.delete_voucher(conn, int(vid))
    return {'ok': True}


@post('/api/voucher/audit')
def api_voucher_audit(conn, b):
    maker = db.get_meta(conn).get('maker', '')
    return {'count': V.audit_vouchers(conn, b.get('ids') or [], b.get('flag', True), b.get('auditor') or maker)}


@post('/api/voucher/renumber')
def api_voucher_renumber(conn, b):
    return {'count': V.renumber(conn, int(b.get('period')))}


@get('/api/templates')
def api_templates(conn, q):
    return V.list_templates(conn)


@post('/api/template/save')
def api_template_save(conn, b):
    V.save_template(conn, b)
    return {'ok': True}


@post('/api/template/delete')
def api_template_delete(conn, b):
    V.delete_template(conn, int(b.get('id')))
    return {'ok': True}


# ================================================================ 科目、辅助核算、期初

@post('/api/account/save')
def api_account_save(conn, b):
    V.save_account(conn, b, bool(b.get('is_new')))
    return {'ok': True}


@post('/api/account/delete')
def api_account_delete(conn, b):
    V.delete_account(conn, b.get('code'))
    return {'ok': True}


@post('/api/aux/save')
def api_aux_save(conn, b):
    return {'id': V.save_aux(conn, b)}


@post('/api/aux/delete')
def api_aux_delete(conn, b):
    V.delete_aux(conn, int(b.get('id')))
    return {'ok': True}


@get('/api/opening')
def api_opening(conn, q):
    return {'rows': V.get_opening(conn), 'check': V.opening_check(conn),
            'locked': bool(ledger.closed_periods(conn))}


@post('/api/opening/save')
def api_opening_save(conn, b):
    V.save_opening(conn, b.get('rows') or [])
    return V.opening_check(conn)


# ================================================================ 车辆

@get('/api/vehicles')
def api_vehicles(conn, q):
    return VH.list_vehicles(conn)


@post('/api/vehicle/save')
def api_vehicle_save(conn, b):
    return {'id': VH.save_vehicle(conn, b)}


@post('/api/vehicle/delete')
def api_vehicle_delete(conn, b):
    VH.delete_vehicle(conn, int(b.get('id')))
    return {'ok': True}


@post('/api/vehicle/purchase_draft')
def api_vehicle_purchase(conn, b):
    return VH.purchase_draft(conn, int(b.get('id')), float(b.get('tax_rate', 13)), b.get('mode') or '')


@post('/api/vehicle/dispose')
def api_vehicle_dispose(conn, b):
    return VH.dispose(conn, b)


@post('/api/vehicle/undo_dispose')
def api_vehicle_undo(conn, b):
    VH.undo_dispose(conn, int(b.get('id')))
    return {'ok': True}


@get('/api/vehicle/reconcile')
def api_vehicle_reconcile(conn, q):
    return VH.reconcile(conn, P(q, 'period', None, int))


@get('/api/vehicle/profit')
def api_vehicle_profit(conn, q):
    return VH.vehicle_profit(conn, P(q, 'from'), P(q, 'to'))


@get('/api/opening/vehicles')
def api_opening_vehicles(conn, q):
    """把车辆台账（启用前已有的车辆）带入期初余额。"""
    sp = ledger.start_period(conn)
    fa, depr = db.acct_key(conn, 'vehicle_fa'), db.acct_key(conn, 'vehicle_depr')
    rows = []
    accum = 0
    for r in conn.execute('SELECT * FROM vehicles'):
        if ledger.period_of_date(r['purchase_date']) < sp:
            rows.append({'account_code': fa, 'aux_id': r['aux_id'], 'year_begin': r['original']})
            accum += r['opening_accum']
    return {'rows': rows, 'accum': accum, 'fa_code': fa, 'depr_code': depr}


# ================================================================ 账簿与报表

def _audited_only(q):
    """查询条件“包含未审核凭证”没勾（unaudited=0）时，只统计已审核的凭证。不传时和以前一样统计全部。"""
    return ledger.audited_only(P(q, 'unaudited', '1') == '0')


@get('/api/balance')
def api_balance(conn, q):
    with _audited_only(q):
        return ledger.balance_table(conn, P(q, 'from'), P(q, 'to'), P(q, 'level', 9, int),
                                    P(q, 'aux', '0') == '1', P(q, 'zero', '0') == '1',
                                    P(q, 'code_from', ''), P(q, 'code_to', ''), P(q, 'level_from', 1, int))


@get('/api/gl')
def api_gl(conn, q):
    with _audited_only(q):
        return ledger.general_ledger(conn, P(q, 'code'), P(q, 'from'), P(q, 'to'))


@get('/api/detail')
def api_detail(conn, q):
    with _audited_only(q):
        return ledger.detail_ledger(conn, P(q, 'code'), P(q, 'from'), P(q, 'to'), P(q, 'aux'))


@get('/api/auxbal')
def api_auxbal(conn, q):
    with _audited_only(q):
        return ledger.aux_balance(conn, P(q, 'code'), P(q, 'from'), P(q, 'to'), P(q, 'zero', '0') == '1')


def _report_range(q):
    """报表日期：from/to 为起止日期（YYYY-MM-DD，可跨年度）；也兼容期间整数 YYYYMM 和只传 period 的旧写法。"""
    p = P(q, 'period')
    d1, d2 = P(q, 'from', p), P(q, 'to', p)
    if not d1 or not d2:
        raise AppError('请选择报表日期')
    return d1, d2


@get('/api/report/bs')
def api_bs(conn, q):
    return R.balance_sheet(conn, *_report_range(q))


@get('/api/report/is')
def api_is(conn, q):
    return R.income_statement(conn, *_report_range(q))


@get('/api/report/cf')
def api_cf(conn, q):
    return R.cash_flow(conn, *_report_range(q))


# ================================================================ 期末处理

@get('/api/closing/status')
def api_closing_status(conn, q):
    return C.closing_status(conn, P(q, 'period', None, int))


@post('/api/closing/depreciation')
def api_closing_depr(conn, b):
    return C.run_depreciation(conn, b.get('period'))


@post('/api/closing/vat')
def api_closing_vat(conn, b):
    return C.transfer_vat(conn, b.get('period'))


@post('/api/closing/surtax')
def api_closing_surtax(conn, b):
    return C.run_surtax(conn, b.get('period'), b.get('rates'))


@post('/api/closing/surtax_rates')
def api_closing_surtax_rates(conn, b):
    return C.save_surtax_rates(conn, b.get('rates'))


@post('/api/closing/carry')
def api_closing_carry(conn, b):
    return C.carry_forward(conn, b.get('period'))


@post('/api/closing/yearend')
def api_closing_yearend(conn, b, cid=None):
    _backup_before(cid, '年末结转前')
    return C.year_end(conn, b.get('period'))


@post('/api/closing/close')
def api_closing_close(conn, b, cid=None):
    _backup_before(cid, '结账前')
    return C.close_period(conn, b.get('period'))


@post('/api/closing/reopen')
def api_closing_reopen(conn, b, cid=None):
    _backup_before(cid, '反结账前')
    return C.reopen_period(conn)


def _backup_before(cid, label):
    """结账、反结账、年末结转、导入这些大动作之前，先自动备份一次账套。"""
    try:
        db.backup_company(cid, label)
    except (AppError, OSError) as e:
        raise AppError('操作前自动备份账套失败，已停止，账套没有改动：%s' % e)


# ================================================================ 导入导出与备份

@post('/api/import')
def api_import(conn, b, cid=None):
    raw = base64.b64decode(b.get('data') or '')
    kind = b.get('kind')
    if kind in ('vouchers', 'vehicles', 'aux'):
        _backup_before(cid, '导入前')
    if kind == 'vouchers':
        return IO.import_vouchers(conn, raw)
    if kind == 'vehicles':
        return IO.import_vehicles(conn, raw)
    if kind == 'aux':
        return IO.import_aux(conn, raw)
    raise AppError('未知的导入类型')


@get('/api/import/template', needs_company=False)
def api_import_template(conn, q):
    kind = P(q, 'kind')
    names = {'vouchers': '凭证导入模板.csv', 'vehicles': '车辆导入模板.csv', 'aux': '辅助核算导入模板.csv'}
    if kind not in names:
        raise AppError('未知模板')
    return FileResponse(IO.template_csv(kind), names[kind], 'text/csv; charset=utf-8')


@post('/api/export/xlsx', needs_company=False)
def api_export(conn, b):
    data = IO.build_xlsx(b.get('title') or '导出', b.get('columns') or [], b.get('rows') or [], b.get('subtitle') or '')
    return FileResponse(data, (b.get('filename') or b.get('title') or '导出') + '.xlsx',
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@get('/api/backups')
def api_backups(conn, q, cid=None):
    return db.list_backups(cid)


@post('/api/backup/now')
def api_backup_now(conn, b, cid=None):
    return {'name': db.backup_company(cid, '手动')}


@post('/api/backup/restore')
def api_backup_restore(conn, b, cid=None):
    return {'restore': b.get('name')}


@get('/api/backup/download')
def api_backup_download(conn, q, cid=None):
    name = P(q, 'name')
    meta = db.get_meta(conn)
    db.mark_exported()
    if name:
        path = db.backup_file_path(cid, name)
        with open(path, 'rb') as f:
            return FileResponse(f.read(), '%s-%s' % (meta.get('company_name'), name), 'application/octet-stream')
    fn = db.backup_company(cid, '下载')
    with open(db.backup_file_path(cid, fn), 'rb') as f:
        return FileResponse(f.read(), '%s-%s' % (meta.get('company_name'), fn), 'application/octet-stream')


NEEDS_CID = {api_company_export, api_backups, api_backup_now, api_backup_restore, api_backup_download, api_company_delete,
             api_closing_yearend, api_closing_close, api_closing_reopen, api_import}
NEEDS_TOKEN = {api_lock_status, api_lock_unlock, api_lock_lock, api_lock_set, api_lock_options, api_lock_disable,
               api_lock_recover}


# ================================================================ HTTP 处理

class Handler(BaseHTTPRequestHandler):
    server_version = 'RentalAccounting/1.0'

    def log_message(self, fmt, *args):
        pass  # 不在控制台刷屏

    def _send(self, code, body, ctype='application/json; charset=utf-8', filename=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        if filename:
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + urllib.parse.quote(filename))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # 浏览器已经离开了这个页面，不用处理

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    # ---------------------------------------------------- 只接受本软件自己页面的请求
    # 服务虽然只监听 127.0.0.1，但用户在同一台电脑上用浏览器打开的任何网页都能向它发请求。
    # 下面三项检查用来挡住别的网页跨站调用接口（写数据、关软件、上传更新包）以及 DNS 重绑定。

    def _local_origins(self):
        port = self.server.server_address[1]
        hosts = ('127.0.0.1:%d' % port, 'localhost:%d' % port)
        return hosts, tuple('http://' + h for h in hosts)

    def _forbidden_reason(self, is_api, is_post):
        """请求可以放行时返回 None，否则返回拒绝原因。"""
        hosts, origins = self._local_origins()
        # 1. Host 必须是本机地址，防止 DNS 重绑定（别的域名解析到 127.0.0.1 后读写数据）
        host = (self.headers.get('Host') or '').strip().lower()
        if host not in hosts:
            return 'Host 不正确'
        if not is_api:
            return None
        # 2. 带了 Origin（浏览器跨站请求和所有 POST 都会带）就必须是本软件自己的页面
        origin = self.headers.get('Origin')
        if origin is not None and origin.strip().lower().rstrip('/') not in origins:
            return '来源不正确'
        # 3. 浏览器标明是从别的网站发来的请求一律拒绝（较新的浏览器才有这个头，没有就跳过）
        site = (self.headers.get('Sec-Fetch-Site') or '').strip().lower()
        if site in ('cross-site', 'same-site'):
            return '来源不正确'
        # 4. POST 必须是 JSON。网页跨站发 JSON 时浏览器会先做预检，本服务不放行，请求就发不出来
        if is_post:
            ctype = (self.headers.get('Content-Type') or '').split(';')[0].strip().lower()
            if ctype != 'application/json':
                return '请求格式不正确'
        return None

    def _reject(self, reason):
        self._json(403, {'error': '拒绝访问：%s。请从软件自己打开的页面操作。' % reason})

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        is_api = url.path.startswith('/api/')
        reason = self._forbidden_reason(is_api, False)
        if reason:
            return self._reject(reason)
        if is_api:
            return self._api(GET_ROUTES, url.path, urllib.parse.parse_qs(url.query))
        self._static(url.path)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        reason = self._forbidden_reason(True, True)
        if reason:
            self.close_connection = True  # 不读请求体，直接断开
            return self._reject(reason)
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b'{}'
        try:
            body = json.loads(raw.decode('utf-8') or '{}')
        except Exception:
            return self._json(400, {'error': '请求格式不正确'})
        self._api(POST_ROUTES, url.path, body, is_post=True)

    def _api(self, routes, path, arg, is_post=False):
        route = routes.get(path)
        if not route:
            return self._json(404, {'error': '接口不存在：' + path})
        fn, needs_company = route
        cid = self.headers.get('X-Company') or (arg.get('company', [''])[0] if not is_post else '')
        token = self.headers.get('X-Unlock') or (arg.get('unlock', [''])[0] if not is_post else '')
        if path not in LOCK_FREE and not applock.token_valid(token):
            return self._json(401, {'error': '软件已锁定，请输入启动密码', 'locked': True})
        if path not in NOT_ACTIVITY:
            applock.touch(token)
        conn = None
        try:
            if needs_company:
                conn = db.connect(cid)
            if fn in NEEDS_CID:
                result = fn(conn, arg, cid=cid)
            elif fn in NEEDS_TOKEN:
                result = fn(conn, arg, token=token)
            else:
                result = fn(conn, arg)
            if conn is not None:
                conn.commit()
                conn.close()
                conn = None
            # 需要在关闭数据库连接之后才能做的文件操作
            if isinstance(result, dict) and result.get('restore') and fn is api_backup_restore:
                db.restore_backup(cid, result['restore'])
                result = {'ok': True}
            if isinstance(result, dict) and result.get('delete') and fn is api_company_delete:
                db.delete_company(cid)
                result = {'ok': True}
            if isinstance(result, FileResponse):
                return self._send(200, result.data, result.ctype, result.filename)
            self._json(200, result)
        except AppError as e:
            if conn is not None:
                conn.rollback()
            self._json(400, {'error': str(e)})
        except Exception as e:
            if conn is not None:
                conn.rollback()
            traceback.print_exc()
            self._json(500, {'error': '程序出错：%s' % e})
        finally:
            if conn is not None:
                conn.close()

    def _static(self, path):
        if path in ('', '/'):
            path = '/index.html'
        full = os.path.normpath(os.path.join(WEB_DIR, path.lstrip('/')))
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            return self._send(404, 'Not found', 'text/plain; charset=utf-8')
        ext = os.path.splitext(full)[1].lower()
        ctype = {'.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
                 '.png': 'image/png', '.ico': 'image/x-icon'}.get(ext) or mimetypes.guess_type(full)[0] or 'application/octet-stream'
        if ctype.startswith('text/') or ctype in ('application/javascript',):
            ctype += '; charset=utf-8'
        with open(full, 'rb') as f:
            self._send(200, f.read(), ctype)


INSTANCE_FILE = os.path.join(db.DATA_DIR, '.instance.json')
_httpd = None


def _existing_instance():
    """如果软件已经在运行，返回 (网址, 它的版本号)；否则返回 (None, None)。"""
    import urllib.request
    try:
        with open(INSTANCE_FILE, encoding='utf-8') as f:
            info = json.load(f)
        url = 'http://127.0.0.1:%d/' % int(info['port'])
        with urllib.request.urlopen(url + 'api/version', timeout=1.5) as r:
            v = json.loads(r.read().decode('utf-8'))
        if os.path.normcase(v.get('root', '')) == os.path.normcase(db.ROOT):
            return url, str(v.get('version') or '')
    except Exception:
        pass
    return None, None


def _page_since(url, t0):
    """已经在运行的那份后台：t0 之后有没有新页面连上。"""
    import urllib.request
    try:
        with urllib.request.urlopen(url + 'api/version', timeout=1.5) as r:
            return float(json.loads(r.read().decode('utf-8')).get('last_page_at') or 0) >= t0
    except Exception:
        return False


def _stop_other(url):
    """在后台运行的是别的版本（例如更新前的老版本没退出）：请它退出，最多等 8 秒。"""
    import urllib.request
    try:
        req = urllib.request.Request(url + 'api/shutdown', data=b'{}', headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass
    for _ in range(40):
        time.sleep(0.2)
        try:
            urllib.request.urlopen(url + 'api/version', timeout=0.5).read()
        except Exception:
            return True
    return False


def _stop_server():
    try:
        os.remove(INSTANCE_FILE)
    except OSError:
        pass
    if _httpd:
        _httpd.shutdown()


@post('/api/shutdown', needs_company=False)
def api_shutdown(conn, b):
    threading.Timer(0.3, _stop_server).start()
    return {'ok': True}


@post('/api/heartbeat', needs_company=False)
def api_heartbeat(conn, b):
    """页面每隔几秒报一次“我还开着”；关闭页面时报 bye。所有页面都关掉后，后台程序自动退出。"""
    watchdog.beat(str(b.get('id') or ''), bool(b.get('bye')))
    return {'ok': True, 'version': VERSION, 'started': STARTED}


class Watchdog:
    """所有界面窗口都关掉后，自动关闭后台程序（以前关掉浏览器后，后台的 Python 会一直留着）。

    - 页面每 5 秒发一次心跳；关闭/刷新页面时发 bye。
    - 没有任何页面后再等 GRACE 秒（刷新页面、在页面之间跳转时会马上有新的心跳），还没有就退出。
    - 页面在后台（最小化）时浏览器会把定时器放慢到最多 1 分钟一次，所以心跳超过 STALE 秒没来才算页面没了。
    - 打开软件后 FIRST_WAIT 秒内一直没有页面连上（例如浏览器没打开），也退出；再双击图标就会重新打开。
    - 正在更新时不退出。
    """
    STALE = 150
    GRACE = 10
    FIRST_WAIT = 300

    def __init__(self):
        self.pages = {}
        self.lock = threading.Lock()
        self.enabled = False
        self.ever = False
        self.last_new = 0  # 最近一次有新页面连上的时间
        self.last_alive = time.time()

    def beat(self, pid, bye=False):
        with self.lock:
            now = time.time()
            if bye:
                self.pages.pop(pid, None)
            else:
                if pid not in self.pages:
                    self.last_new = now
                self.pages[pid] = now
                self.ever = True
            self.last_alive = now

    def should_exit(self):
        with self.lock:
            now = time.time()
            for k, t in list(self.pages.items()):
                if now - t > self.STALE:
                    del self.pages[k]
            if self.pages:
                self.last_alive = now
                return False
            if not self.enabled or updater.busy():
                return False
            if self.ever:
                return now - self.last_alive > self.GRACE
            return now - self.last_alive > self.FIRST_WAIT

    def start(self):
        self.enabled = True
        self.last_alive = time.time()

        def loop():
            while _httpd is not None:
                time.sleep(2)
                if self.should_exit():
                    print('所有窗口都已关闭，后台程序自动退出')
                    _stop_server()
                    return
        threading.Thread(target=loop, daemon=True).start()


watchdog = Watchdog()
STARTED = time.time()
_state = {'restart': False}


def _spawn_new_instance():
    """重启：用启动程序重新打开软件（不再打开新窗口，原来的页面会自动连上）。"""
    env = dict(os.environ)
    env['MINGBU_NO_BROWSER'] = '1'
    exe = paths.launcher()
    if exe and exe.endswith('.exe'):
        cmd = [exe]
    elif exe:
        cmd = ['/bin/bash', exe]
    else:
        cmd = [sys.executable, os.path.join(paths.CODE_DIR, 'start.py')]
    kw = {'close_fds': True, 'cwd': paths.HOME, 'env': env}
    if os.name == 'nt':
        kw['creationflags'] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw['start_new_session'] = True
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    except OSError as e:
        print('重启失败：', e)


def run(port=8765, open_browser=True):
    global _httpd
    existing, ver = _existing_instance()
    if existing and ver == VERSION:
        # 同一个版本已经在运行：只打开窗口，不再启动第二份
        print('软件已经在运行：%s' % existing)
        if open_browser:
            t0 = time.time()
            desktop.open_ui(existing, lambda: _page_since(existing, t0))
        return
    if existing:
        print('后台还在运行 v%s，先让它退出，再启动 v%s' % (ver, VERSION))
        _stop_other(existing)
    db.auto_backup_all()
    httpd = None
    for p in range(port, port + 30):
        try:
            httpd = ThreadingHTTPServer(('127.0.0.1', p), Handler)
            port = p
            break
        except OSError:
            continue
    if not httpd:
        raise SystemExit('找不到可用端口')
    _httpd = httpd
    url = 'http://127.0.0.1:%d/' % port
    try:
        with open(INSTANCE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'port': port, 'pid': os.getpid()}, f)
    except OSError:
        pass
    print('=' * 56)
    print('  明簿已启动 v%s' % VERSION)
    print('  界面地址：%s' % url)
    print('  关掉软件窗口，或点左下角“退出软件”即可关闭。')
    print('=' * 56)
    if open_browser:
        t0 = time.time()
        threading.Timer(0.3, lambda: desktop.open_ui(url, lambda: watchdog.last_new >= t0)).start()
        watchdog.start()  # 只启动后台服务（--no-browser，开发调试用）时不自动退出
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            httpd.server_close()
        except Exception:
            pass
        try:
            if os.path.exists(INSTANCE_FILE):
                with open(INSTANCE_FILE, encoding='utf-8') as f:
                    if json.load(f).get('pid') == os.getpid():
                        os.remove(INSTANCE_FILE)
        except Exception:
            pass
        if _state['restart']:
            _spawn_new_instance()
