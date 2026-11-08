"""
数据库与账套管理。

每家公司是一个独立的账套，对应 data 文件夹里的一个 SQLite 文件（c1.db、c2.db……）。
所有金额都以“分”为单位存成整数，避免小数误差。
余额统一用“借方为正、贷方为负”的带符号整数表示。
"""
import datetime
import json
import os
import re
import shutil
import sqlite3

from . import presets, charts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get('RENTAL_DATA_DIR') or os.path.join(ROOT, 'data')
BACKUP_DIR = os.environ.get('RENTAL_BACKUP_DIR') or os.path.join(ROOT, 'backups')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS accounts (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,          -- 资产 / 负债 / 权益 / 损益
    direction TEXT NOT NULL,         -- 借 / 贷
    aux_type TEXT NOT NULL DEFAULT '',
    aux_required INTEGER NOT NULL DEFAULT 0,
    is_cash INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    report_line TEXT NOT NULL DEFAULT ''   -- 自建一级科目在报表中归入的项目
);

CREATE TABLE IF NOT EXISTS aux_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(type, code)
);

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aux_id INTEGER NOT NULL UNIQUE,
    plate TEXT NOT NULL UNIQUE,
    model TEXT NOT NULL DEFAULT '',
    purchase_date TEXT NOT NULL,
    original INTEGER NOT NULL,          -- 原值（分）
    salvage_bp INTEGER NOT NULL DEFAULT 500,  -- 残值率，万分之几：500 = 5%
    life_months INTEGER NOT NULL DEFAULT 48,
    opening_accum INTEGER NOT NULL DEFAULT 0, -- 启用账套时已计提的累计折旧
    status TEXT NOT NULL DEFAULT '在用',  -- 在用 / 已处置
    dispose_period INTEGER,
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS depr_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period INTEGER NOT NULL,
    vehicle_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    voucher_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_depr_period ON depr_records(period);
CREATE INDEX IF NOT EXISTS idx_depr_vehicle ON depr_records(vehicle_id);

CREATE TABLE IF NOT EXISTS opening (
    account_code TEXT NOT NULL,
    aux_id INTEGER NOT NULL DEFAULT 0,
    year_begin INTEGER NOT NULL DEFAULT 0,   -- 年初余额（带符号）
    ytd_debit INTEGER NOT NULL DEFAULT 0,    -- 启用前本年累计借方
    ytd_credit INTEGER NOT NULL DEFAULT 0,   -- 启用前本年累计贷方
    PRIMARY KEY (account_code, aux_id)
);

CREATE TABLE IF NOT EXISTS vouchers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period INTEGER NOT NULL,
    number INTEGER NOT NULL,
    date TEXT NOT NULL,
    attachments INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT '普通',    -- 普通 / 折旧 / 结转增值税 / 计提附加税 / 结转损益 / 年末结转
    audited INTEGER NOT NULL DEFAULT 0,
    maker TEXT NOT NULL DEFAULT '',
    auditor TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    UNIQUE(period, number)
);

CREATE TABLE IF NOT EXISTS lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_id INTEGER NOT NULL,
    period INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    account_code TEXT NOT NULL,
    aux_id INTEGER NOT NULL DEFAULT 0,
    debit INTEGER NOT NULL DEFAULT 0,
    credit INTEGER NOT NULL DEFAULT 0,
    cf_item TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_lines_voucher ON lines(voucher_id);
CREATE INDEX IF NOT EXISTS idx_lines_acct_period ON lines(account_code, period);
CREATE INDEX IF NOT EXISTS idx_lines_period ON lines(period);

CREATE TABLE IF NOT EXISTS closed_periods (period INTEGER PRIMARY KEY, closed_at TEXT);

CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    lines_json TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cf_items (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    section TEXT NOT NULL,
    flow TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


class AppError(Exception):
    """业务错误，会以提示信息的形式显示给操作人员。"""


def now_str():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def company_path(cid):
    if not re.fullmatch(r'c\d+', cid or ''):
        raise AppError('请先选择账套')
    path = os.path.join(DATA_DIR, cid + '.db')
    if not os.path.exists(path):
        raise AppError('账套不存在，请重新选择')
    return path


_migrated = set()

# 以后新版本给已有的表加字段时，在这里登记：表名 -> [(字段名, 字段定义)]
# 旧版本建立的账套在第一次打开时会自动补上这些字段，数据不受影响。
EXTRA_COLUMNS = {
    'accounts': [('report_line', "TEXT NOT NULL DEFAULT ''")],
}


def migrate(conn):
    """把旧版本的账套数据库升级到当前结构（只增加，不删除任何数据）。"""
    conn.executescript(SCHEMA)  # 新增的表会被创建，已有的表不受影响
    for table, cols in EXTRA_COLUMNS.items():
        have = {r[1] for r in conn.execute('PRAGMA table_info(%s)' % table)}
        for name, ddl in cols:
            if name not in have:
                conn.execute('ALTER TABLE %s ADD COLUMN %s %s' % (table, name, ddl))
    _migrate_profile(conn)
    _migrate_keymap(conn)
    _migrate_vehicle_aux(conn)
    old = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if not old or int(old[0]) < SCHEMA_VERSION:
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    conn.commit()


def connect(cid):
    path = company_path(cid)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    if path not in _migrated:
        migrate(conn)
        _migrated.add(path)
    return conn


def last_modified(conn):
    r = conn.execute('SELECT MAX(at) FROM logs').fetchone()
    return r[0] or ''


def get_meta(conn):
    return {r['key']: r['value'] for r in conn.execute('SELECT key, value FROM meta')}


def set_meta(conn, key, value):
    conn.execute('INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)', (key, str(value)))


def log(conn, action, detail=''):
    conn.execute('INSERT INTO logs(at, action, detail) VALUES (?, ?, ?)', (now_str(), action, detail))


def list_companies():
    result = []
    for fn in os.listdir(DATA_DIR):
        m = re.fullmatch(r'(c\d+)\.db', fn)
        if not m:
            continue
        cid = m.group(1)
        try:
            conn = connect(cid)
            meta = get_meta(conn)
            from .ledger import current_period
            cur = current_period(conn)
            cnt = conn.execute('SELECT COUNT(*) FROM vouchers').fetchone()[0]
            modified = last_modified(conn)
            prof = company_profile(conn)
            conn.close()
        except Exception as e:  # 文件损坏等情况
            result.append({'id': cid, 'name': f'{cid}（无法打开：{e}）', 'broken': True})
            continue
        result.append({
            'id': cid,
            'name': meta.get('company_name', cid),
            'start_period': int(meta.get('start_period', 0)),
            'current_period': cur,
            'voucher_count': cnt,
            'modified': modified,
            'industry_name': prof['industry_name'],
            'standard_name': prof['standard_name'],
        })
    result.sort(key=lambda x: int(x['id'][1:]))
    return result


def _next_company_id():
    nums = [int(m.group(1)) for fn in os.listdir(DATA_DIR) if (m := re.fullmatch(r'c(\d+)\.db', fn))]
    return 'c%d' % (max(nums, default=0) + 1)


COMPANY_META_KEYS = ('standard', 'industry', 'industry_name', 'keymap', 'aux_types', 'features', 'cf_suggest',
                     'vehicle_label')


def create_company(name, start_year, start_month, copy_from='', standard='enterprise', industry='car_rental'):
    name = (name or '').strip()
    if not name:
        raise AppError('请填写公司名称')
    if any(c['name'] == name for c in list_companies()):
        raise AppError('已经有同名的账套了')
    start_year, start_month = int(start_year), int(start_month)
    if not (2000 <= start_year <= 2100 and 1 <= start_month <= 12):
        raise AppError('启用年月不正确')
    if not copy_from:
        try:
            chart = charts.build(standard or 'enterprise', industry or 'general')
        except ValueError as e:
            raise AppError(str(e))
    cid = _next_company_id()
    path = os.path.join(DATA_DIR, cid + '.db')
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        set_meta(conn, 'schema_version', SCHEMA_VERSION)
        set_meta(conn, 'company_name', name)
        set_meta(conn, 'start_period', start_year * 100 + start_month)
        set_meta(conn, 'maker', '')
        set_meta(conn, 'created_at', now_str())
        set_meta(conn, 'fix_vehicle_aux', '1')  # 新账套的科目表已经是新设置，不需要再调整
        if copy_from:
            src = connect(copy_from)
            smeta = get_meta(src)
            for k in COMPANY_META_KEYS:
                if k in smeta:
                    set_meta(conn, k, smeta[k])
            for r in src.execute('SELECT * FROM cf_items'):
                conn.execute('INSERT INTO cf_items VALUES (?,?,?,?,?)', (r['code'], r['name'], r['section'], r['flow'], r['sort']))
            for r in src.execute('SELECT * FROM accounts'):
                conn.execute('INSERT INTO accounts(code, name, category, direction, aux_type, aux_required, is_cash, '
                             'enabled, report_line) VALUES (?,?,?,?,?,?,?,?,?)',
                             (r['code'], r['name'], r['category'], r['direction'], r['aux_type'], r['aux_required'],
                              r['is_cash'], r['enabled'], r['report_line']))
            for r in src.execute("SELECT type, code, name FROM aux_items WHERE type = '银行账户'"):
                conn.execute('INSERT INTO aux_items(type, code, name) VALUES (?,?,?)', tuple(r))
            for r in src.execute('SELECT name, lines_json, sort FROM templates'):
                conn.execute('INSERT INTO templates(name, lines_json, sort) VALUES (?,?,?)', tuple(r))
            src.close()
        else:
            set_meta(conn, 'standard', chart['standard'])
            set_meta(conn, 'industry', chart['industry'])
            set_meta(conn, 'industry_name', chart['industry_name'])
            set_meta(conn, 'keymap', json.dumps(chart['keymap'], ensure_ascii=False))
            set_meta(conn, 'aux_types', json.dumps(chart['aux_types'], ensure_ascii=False))
            set_meta(conn, 'features', json.dumps(chart['features']))
            set_meta(conn, 'cf_suggest', json.dumps(chart['cf_suggest']))
            set_meta(conn, 'vehicle_label', chart['vehicle_label'])
            for code, cname, section, flow, sort in chart['cf_items']:
                conn.execute('INSERT INTO cf_items VALUES (?,?,?,?,?)', (code, cname, section, flow, sort))
            for a in chart['accounts']:
                conn.execute('INSERT INTO accounts(code, name, category, direction, aux_type, aux_required, is_cash)'
                             ' VALUES (?,?,?,?,?,?,?)', a)
            for t, code, aname in chart['preset_aux']:
                conn.execute('INSERT INTO aux_items(type, code, name) VALUES (?,?,?)', (t, code, aname))
            for i, (tname, lines) in enumerate(chart['templates']):
                conn.execute('INSERT INTO templates(name, lines_json, sort) VALUES (?,?,?)',
                             (tname, json.dumps(lines, ensure_ascii=False), i))
        log(conn, '新建账套', name)
        conn.commit()
    finally:
        conn.close()
    return cid


# ---------------------------------------------------------------- 准则、行业与“科目关键字”

def company_profile(conn):
    """账套的准则、行业、关键字对照表、辅助核算类型、功能开关等。"""
    meta = get_meta(conn)

    def js(k, default):
        try:
            return json.loads(meta[k]) if meta.get(k) else default
        except ValueError:
            return default
    return {
        'standard': meta.get('standard', 'enterprise'),
        'standard_name': charts.STANDARDS.get(meta.get('standard', 'enterprise'), ''),
        'industry': meta.get('industry', 'general'),
        'industry_name': meta.get('industry_name', ''),
        'keymap': js('keymap', {}),
        'aux_types': js('aux_types', list(charts.BASE_AUX_TYPES)),
        'features': js('features', []),
        'cf_suggest': js('cf_suggest', {'': ['CF03', 'CF07']}),
        'vehicle_label': meta.get('vehicle_label', '车辆'),
    }


def acct_key(conn, key, required=True):
    """按关键字找科目编码，例如 acct_key(conn, 'profit') -> '4103'（企业）或 '3103'（小企业）。"""
    code = company_profile(conn)['keymap'].get(key)
    if code:
        exists = conn.execute('SELECT 1 FROM accounts WHERE code = ?', (code,)).fetchone()
        if exists:
            return code
    if required:
        raise AppError('找不到“%s”对应的会计科目，请在“设置 → 会计科目”中检查（可能被删除了）' % KEY_LABELS.get(key, key))
    return None


KEY_LABELS = {
    'profit': '本年利润', 'retained': '利润分配—未分配利润', 'dist': '利润分配', 'vehicle_fa': '固定资产—车辆',
    'vehicle_depr': '累计折旧—车辆', 'depr_exp': '车辆折旧费用', 'vat_in': '进项税额', 'vat_out': '销项税额',
    'vat_simple': '简易计税', 'ap': '应付账款', 'disposal_gain': '资产处置收益', 'disposal_loss': '资产处置损失',
    'bank': '银行存款',
}


def _migrate_profile(conn):
    """v1.3 及以前建立的账套：补上准则、行业和关键字对照表（当时只有企业准则 + 汽车租赁）。"""
    meta = get_meta(conn)
    if 'standard' in meta:
        return
    codes = {r[0] for r in conn.execute('SELECT code FROM accounts')}
    keymap = {k: v for k, v in charts.LEGACY_CAR_RENTAL_KEYMAP.items() if v in codes}
    set_meta(conn, 'standard', 'enterprise')
    set_meta(conn, 'industry', 'car_rental')
    set_meta(conn, 'industry_name', '汽车租赁')
    set_meta(conn, 'keymap', json.dumps(keymap, ensure_ascii=False))
    set_meta(conn, 'aux_types', json.dumps(charts.LEGACY_AUX_TYPES, ensure_ascii=False))
    set_meta(conn, 'features', json.dumps(['vehicles']))
    set_meta(conn, 'cf_suggest', json.dumps({k: list(v) for k, v in presets.CF_SUGGEST.items()}))
    set_meta(conn, 'vehicle_label', '租赁车辆')


def _migrate_keymap(conn):
    """新版本给一级科目增加了关键字（如 1603 固定资产减值准备）：旧账套里如果自己建过同编码、同名称的科目，
    补上关键字，报表才能取到数。"""
    prof = company_profile(conn)
    keymap = dict(prof['keymap'])
    base = charts.ENTERPRISE_L1 if prof['standard'] == 'enterprise' else charts.SMALL_L1
    names = {r[0]: r[1] for r in conn.execute('SELECT code, name FROM accounts WHERE length(code) = 4')}
    changed = False
    for row in base:
        code, key, name = row[0], row[1], row[2]
        if key not in keymap and names.get(code) == name:
            keymap[key] = code
            changed = True
    if changed:
        set_meta(conn, 'keymap', json.dumps(keymap, ensure_ascii=False))


def _migrate_vehicle_aux(conn):
    """v1.5：有车辆的账套，“累计折旧—车辆”“固定资产清理”改为可按车辆辅助核算（可选）。
    以前这两个科目没有设辅助核算，录凭证时辅助核算格子不能填。只调整一次，之后用户在科目设置里改了就以用户为准。"""
    if get_meta(conn).get('fix_vehicle_aux'):
        return
    prof = company_profile(conn)
    if 'vehicles' in prof['features'] and '车辆' in prof['aux_types']:
        codes = [r[0] for r in conn.execute('SELECT code FROM accounts')]
        for key in ('vehicle_depr', 'fa_clear'):
            code = prof['keymap'].get(key)
            if not code or code not in codes:
                continue
            for c in codes:  # 科目本身是末级时改它自己，有下级时改它的各个末级下级
                if c.startswith(code) and not any(o != c and o.startswith(c) for o in codes):
                    conn.execute("UPDATE accounts SET aux_type = '车辆', aux_required = 0 WHERE code = ? AND aux_type = ''",
                                 (c,))
    set_meta(conn, 'fix_vehicle_aux', '1')


# ---------------------------------------------------------------- 备份

def _backup_folder(cid):
    folder = os.path.join(BACKUP_DIR, cid)
    os.makedirs(folder, exist_ok=True)
    return folder


def backup_company(cid, label='手动'):
    src = connect(cid)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    fn = f'{stamp}-{label}.db'
    dst = sqlite3.connect(os.path.join(_backup_folder(cid), fn))
    src.backup(dst)
    dst.close()
    src.close()
    _prune_backups(cid)
    return fn


def _prune_backups(cid, keep=60):
    files = sorted(f for f in os.listdir(_backup_folder(cid)) if f.endswith('.db'))
    for f in files[:-keep]:
        os.remove(os.path.join(_backup_folder(cid), f))


def list_backups(cid):
    folder = _backup_folder(cid)
    out = []
    for f in sorted(os.listdir(folder), reverse=True):
        if f.endswith('.db'):
            p = os.path.join(folder, f)
            out.append({'name': f, 'size': os.path.getsize(p)})
    return out


def backup_file_path(cid, name):
    if not re.fullmatch(r'[\w\-一-龥]+\.db', name or ''):
        raise AppError('备份文件名不正确')
    p = os.path.join(_backup_folder(cid), name)
    if not os.path.exists(p):
        raise AppError('备份文件不存在')
    return p


def restore_backup(cid, name):
    p = backup_file_path(cid, name)
    backup_company(cid, '恢复前自动备份')
    shutil.copyfile(p, company_path(cid))
    _migrated.discard(company_path(cid))


def auto_backup_all():
    """每天第一次启动时，给每个账套自动备份一次。"""
    today = datetime.datetime.now().strftime('%Y%m%d')
    for c in list_companies():
        if c.get('broken'):
            continue
        files = [f for f in os.listdir(_backup_folder(c['id'])) if f.startswith(today)]
        if not files:
            try:
                backup_company(c['id'], '每日自动')
            except Exception:
                pass


def delete_company(cid):
    path = company_path(cid)
    backup_company(cid, '删除前备份')
    trash = os.path.join(BACKUP_DIR, '已删除的账套')
    os.makedirs(trash, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    shutil.move(path, os.path.join(trash, f'{cid}-{stamp}.db'))


# ---------------------------------------------------------------- 多台电脑之间导出 / 导入账套

def _safe_name(name):
    return re.sub(r'[\\/:*?"<>|\s]+', '_', name).strip('_') or '账套'


def export_company_file(cid):
    """把一个账套导出为一个 .db 文件（返回 文件名, 内容）。"""
    import tempfile
    src = connect(cid)
    name = get_meta(src).get('company_name', cid)
    fd, tmp = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    dst = sqlite3.connect(tmp)
    src.backup(dst)
    dst.close()
    src.close()
    with open(tmp, 'rb') as f:
        data = f.read()
    os.remove(tmp)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M')
    return '%s-账套-%s.db' % (_safe_name(name), stamp), data


def export_all_zip():
    import io
    import zipfile
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for c in list_companies():
            if c.get('broken'):
                continue
            fn, data = export_company_file(c['id'])
            zi = zipfile.ZipInfo(_safe_name(c['name']) + '.db', datetime.datetime.now().timetuple()[:6])
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.flag_bits |= 0x800
            z.writestr(zi, data)
            n += 1
    if not n:
        raise AppError('还没有账套可以导出')
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M')
    return '全部账套-%s.zip' % stamp, buf.getvalue()


def _inspect_db(data):
    """检查上传的文件是不是本软件的账套，返回 (临时文件路径, 信息)。"""
    import tempfile
    if not data.startswith(b'SQLite format 3'):
        raise AppError('文件不是本软件导出的账套文件')
    fd, tmp = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    with open(tmp, 'wb') as f:
        f.write(data)
    try:
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        meta = {r['key']: r['value'] for r in conn.execute('SELECT key, value FROM meta')}
        if 'company_name' not in meta or 'start_period' not in meta:
            raise AppError('文件不是本软件导出的账套文件')
        migrate(conn)
        info = {'name': meta['company_name'], 'modified': last_modified(conn),
                'vouchers': conn.execute('SELECT COUNT(*) FROM vouchers').fetchone()[0]}
        conn.close()
    except sqlite3.DatabaseError:
        os.remove(tmp)
        raise AppError('账套文件已损坏，无法读取')
    except AppError:
        os.remove(tmp)
        raise
    return tmp, info


def import_companies(data, filename, mode='replace', force=False):
    """
    导入账套：支持单个 .db 文件，或“导出全部账套”得到的 .zip 文件。
    mode = 'replace'：有同名账套时覆盖（覆盖前自动备份）；'new'：一律作为新账套导入。
    本机的同名账套比导入的文件更新时，需要 force=True 才会覆盖。
    """
    import io
    import zipfile
    files = []
    if data[:2] == b'PK':
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise AppError('压缩包已损坏')
        for n in z.namelist():
            if n.lower().endswith('.db'):
                files.append(z.read(n))
        if not files:
            raise AppError('压缩包里没有账套文件')
    else:
        files = [data]
    inspected = [_inspect_db(d) for d in files]
    existing = {c['name']: c for c in list_companies() if not c.get('broken')}
    try:
        warnings = []
        if mode == 'replace' and not force:
            for tmp, info in inspected:
                cur = existing.get(info['name'])
                if cur and cur['modified'] and info['modified'] and cur['modified'] > info['modified']:
                    warnings.append('“%s”：本机最后修改于 %s，导入文件最后修改于 %s（本机更新）' % (
                        info['name'], cur['modified'], info['modified']))
            if warnings:
                return {'need_confirm': True, 'warnings': warnings}
        results = []
        for tmp, info in inspected:
            cur = existing.get(info['name'])
            if cur and mode == 'replace':
                backup_company(cur['id'], '导入覆盖前')
                shutil.copyfile(tmp, company_path(cur['id']))
                _migrated.discard(company_path(cur['id']))
                results.append('覆盖：%s（%d 张凭证）' % (info['name'], info['vouchers']))
            else:
                cid = _next_company_id()
                shutil.copyfile(tmp, os.path.join(DATA_DIR, cid + '.db'))
                if cur:
                    conn = connect(cid)
                    set_meta(conn, 'company_name', info['name'] + '（导入）')
                    conn.commit()
                    conn.close()
                results.append('新增：%s（%d 张凭证）' % (info['name'], info['vouchers']))
        return {'ok': True, 'results': results}
    finally:
        for tmp, info in inspected:
            if os.path.exists(tmp):
                os.remove(tmp)
