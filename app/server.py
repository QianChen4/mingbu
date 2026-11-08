"""
本地 Web 服务：只监听本机 127.0.0.1，界面（独立窗口或浏览器）通过 /api/... 读写数据。
"""
import base64
import json
import mimetypes
import os
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import db, desktop, ledger, vouchers as V, vehicles as VH, closing as C, reports as R, io_utils as IO, updater, VERSION
from .db import AppError

WEB_DIR = os.path.join(db.ROOT, 'web')

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
                            b.get('standard') or 'enterprise', b.get('industry') or 'general')
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
    return {'version': VERSION, 'root': db.ROOT, 'data_dir': db.DATA_DIR}


@get('/api/companies/export_all', needs_company=False)
def api_companies_export_all(conn, q):
    fn, data = db.export_all_zip()
    return FileResponse(data, fn, 'application/zip')


@post('/api/companies/import', needs_company=False)
def api_companies_import(conn, b):
    raw = base64.b64decode(b.get('data') or '')
    if not raw:
        raise AppError('请选择要导入的文件')
    return db.import_companies(raw, b.get('filename') or '', b.get('mode') or 'replace', bool(b.get('force')))


@post('/api/update', needs_company=False)
def api_update(conn, b):
    raw = base64.b64decode(b.get('data') or '')
    if not raw:
        raise AppError('请选择新版本的压缩包')
    return updater.apply_update(raw)


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


@get('/api/update/settings', needs_company=False)
def api_update_settings(conn, q):
    return {'url': updater.get_update_url(), 'version': VERSION, 'auto_check': updater.get_auto_check()}


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


@post('/api/update/online', needs_company=False)
def api_update_online(conn, b):
    return updater.update_online(b.get('url') or updater.get_update_url())


@get('/api/company/export')
def api_company_export(conn, q, cid=None):
    fn, data = db.export_company_file(cid)
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
        'vehicle_label': prof['vehicle_label'],
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
            'status': status, 'vehicle_count': veh[0], 'vehicle_in_use': veh[1]}


@get('/api/logs')
def api_logs(conn, q):
    return [dict(r) for r in conn.execute('SELECT * FROM logs ORDER BY id DESC LIMIT 300')]


# ================================================================ 凭证

@get('/api/vouchers')
def api_vouchers(conn, q):
    return V.list_vouchers(conn, P(q, 'from', cast=int), P(q, 'to', cast=int), P(q, 'q', ''),
                           P(q, 'account', ''), P(q, 'status', ''))


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
    return VH.purchase_draft(conn, int(b.get('id')), float(b.get('tax_rate', 13)))


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
    pf, pt = ledger.normalize_range(conn, P(q, 'from', cast=int), P(q, 'to', cast=int))
    return VH.vehicle_profit(conn, pf, pt)


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

@get('/api/balance')
def api_balance(conn, q):
    return ledger.balance_table(conn, P(q, 'from', cast=int), P(q, 'to', cast=int), P(q, 'level', 9, int),
                                P(q, 'aux', '0') == '1', P(q, 'zero', '0') == '1')


@get('/api/gl')
def api_gl(conn, q):
    return ledger.general_ledger(conn, P(q, 'code'), P(q, 'from', cast=int), P(q, 'to', cast=int))


@get('/api/detail')
def api_detail(conn, q):
    return ledger.detail_ledger(conn, P(q, 'code'), P(q, 'from', cast=int), P(q, 'to', cast=int), P(q, 'aux'))


@get('/api/auxbal')
def api_auxbal(conn, q):
    return ledger.aux_balance(conn, P(q, 'code'), P(q, 'from', cast=int), P(q, 'to', cast=int), P(q, 'zero', '0') == '1')


def _report_range(q):
    """报表期间：from/to（可跨年度）；兼容只传 period 的旧写法。"""
    p = P(q, 'period', None, int)
    pf, pt = P(q, 'from', p, int), P(q, 'to', p, int)
    if not pf or not pt:
        raise AppError('请选择报表期间')
    return pf, pt


@get('/api/report/bs')
def api_bs(conn, q):
    pf, pt = _report_range(q)
    if P(q, 'from') is None:
        pf = (pt // 100) * 100 + 1
    return R.balance_sheet(conn, pf, pt)


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
def api_closing_yearend(conn, b):
    return C.year_end(conn, b.get('period'))


@post('/api/closing/close')
def api_closing_close(conn, b):
    return C.close_period(conn, b.get('period'))


@post('/api/closing/reopen')
def api_closing_reopen(conn, b):
    return C.reopen_period(conn)


# ================================================================ 导入导出与备份

@post('/api/import')
def api_import(conn, b):
    raw = base64.b64decode(b.get('data') or '')
    kind = b.get('kind')
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
    if name:
        path = db.backup_file_path(cid, name)
        with open(path, 'rb') as f:
            return FileResponse(f.read(), '%s-%s' % (meta.get('company_name'), name), 'application/octet-stream')
    fn = db.backup_company(cid, '下载')
    with open(db.backup_file_path(cid, fn), 'rb') as f:
        return FileResponse(f.read(), '%s-%s' % (meta.get('company_name'), fn), 'application/octet-stream')


NEEDS_CID = {api_company_export, api_backups, api_backup_now, api_backup_restore, api_backup_download, api_company_delete}


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
        conn = None
        try:
            if needs_company:
                conn = db.connect(cid)
            if fn in NEEDS_CID:
                result = fn(conn, arg, cid=cid)
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
    """如果软件已经在运行，返回它的网址；否则返回 None。"""
    import urllib.request
    try:
        with open(INSTANCE_FILE, encoding='utf-8') as f:
            info = json.load(f)
        url = 'http://127.0.0.1:%d/' % int(info['port'])
        with urllib.request.urlopen(url + 'api/version', timeout=1.5) as r:
            v = json.loads(r.read().decode('utf-8'))
        if os.path.normcase(v.get('root', '')) == os.path.normcase(db.ROOT):
            return url
    except Exception:
        pass
    return None


def _stop_server():
    try:
        os.remove(INSTANCE_FILE)
    except OSError:
        pass
    if _httpd:
        _httpd.shutdown()


@post('/api/shutdown', needs_company=False)
def api_shutdown(conn, b):
    import threading
    threading.Timer(0.3, _stop_server).start()
    return {'ok': True}


@post('/api/desktop/show', needs_company=False)
def api_desktop_show(conn, b):
    """再次双击软件图标时调用：已经有独立窗口就把它调到最前面。"""
    return {'window': desktop.show_existing()}


@get('/api/desktop/status', needs_company=False)
def api_desktop_status(conn, q):
    return desktop.status()


@post('/api/desktop/settings', needs_company=False)
def api_desktop_settings(conn, b):
    desktop.set_prefer(b.get('prefer'))
    return desktop.status()


def _show_existing(url):
    """让已经在运行的软件把窗口调到前面；它没有独立窗口时返回 False。"""
    import urllib.request
    try:
        req = urllib.request.Request(url + 'api/desktop/show', data=b'{}', headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=3) as r:
            return bool(json.loads(r.read().decode('utf-8')).get('window'))
    except Exception:
        return False


def run(port=8765, open_browser=True):
    global _httpd
    existing = _existing_instance()
    if existing:
        # 已经在运行：只打开浏览器，不再启动第二份
        print('软件已经在运行：%s' % existing)
        if open_browser and not _show_existing(existing):
            desktop.open_browser(existing)
        return
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
    print('  在软件界面右上角点“退出软件”即可关闭。')
    print('=' * 56)
    if open_browser:
        import threading
        # 能用独立窗口就开窗口（关掉窗口 = 退出软件），否则用浏览器
        threading.Timer(0.3, lambda: desktop.open_ui(url, on_closed=_stop_server)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        desktop.stop()
        try:
            if os.path.exists(INSTANCE_FILE):
                with open(INSTANCE_FILE, encoding='utf-8') as f:
                    if json.load(f).get('pid') == os.getpid():
                        os.remove(INSTANCE_FILE)
        except Exception:
            pass
