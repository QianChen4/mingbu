"""
找回旧版本的账套：在这台电脑上查找以前装过的“明簿 / 财务记账软件”文件夹里的账套，导入到现在的软件里。

用在两个地方：
- 第一次打开新版本、还没有账套时，账套列表页会自动查找一次，找到了就问要不要导入；
- “设置 → 数据位置”里可以随时手动查找，或者自己选一个文件夹。

只读取，不改动找到的文件；导入用的是和“导入账套”相同的流程（覆盖前会自动备份）。
"""
import os
import re
import sqlite3
import string
import sys
import time

from .db import AppError, DATA_DIR, BACKUP_DIR, import_companies

DB_RE = re.compile(r'c\d+\.db$')
SKIP_DIRS = {'windows', 'program files', 'program files (x86)', 'programdata', '$recycle.bin', 'system volume information',
             'appdata', 'node_modules', '.git', 'library', 'system', 'applications', 'versions', 'backups', 'runtime',
             'runtime-x86', 'runtime-x64', 'web', 'app', 'msocache', 'recovery', 'perflogs', 'boot', 'intel', 'drivers'}


def _company_info(path):
    """读取一个账套文件的公司名称、凭证张数、最后修改时间；不是本软件的账套返回 None。"""
    try:
        conn = sqlite3.connect('file:%s?mode=ro' % path.replace('?', '%3F').replace('#', '%23'), uri=True, timeout=2)
        try:
            meta = {k: v for k, v in conn.execute('SELECT key, value FROM meta')}
            if 'company_name' not in meta:
                return None
            n = conn.execute('SELECT COUNT(*) FROM vouchers').fetchone()[0]
            try:
                modified = conn.execute('SELECT MAX(at) FROM logs').fetchone()[0] or ''
            except sqlite3.Error:
                modified = ''
        finally:
            conn.close()
        return {'name': meta['company_name'], 'vouchers': n, 'modified': modified}
    except sqlite3.Error:
        return None


def inspect_folder(folder):
    """folder 可以是软件文件夹（里面有 data）或 data 文件夹本身。返回 {'folder', 'data_dir', 'companies'} 或 None。"""
    folder = os.path.abspath(folder)
    for d in (os.path.join(folder, 'data'), folder):
        if not os.path.isdir(d):
            continue
        if os.path.normcase(os.path.abspath(d)) == os.path.normcase(os.path.abspath(DATA_DIR)):
            continue
        try:
            names = sorted(n for n in os.listdir(d) if DB_RE.match(n))
        except OSError:
            continue
        comps = []
        for n in names:
            info = _company_info(os.path.join(d, n))
            if info:
                info['file'] = n
                comps.append(info)
        if comps:
            return {'folder': folder, 'data_dir': d, 'companies': comps}
    return None


def _roots():
    home = os.path.expanduser('~')
    roots = []
    for sub in ('Desktop', '桌面', 'Documents', '文档', 'Downloads', '下载', ''):
        p = os.path.join(home, sub) if sub else home
        if os.path.isdir(p):
            roots.append((p, 3))
    if sys.platform == 'darwin':
        roots.insert(0, (os.path.join(home, 'Library', 'Application Support', '财务记账软件'), 1))
        roots.insert(1, (os.path.join(home, 'Library', 'Application Support', '明簿'), 1))
    if os.name == 'nt':
        for letter in string.ascii_uppercase[2:]:
            drive = letter + ':\\'
            if os.path.isdir(drive):
                roots.append((drive, 3))
    return roots


def _looks_like_app(folder, names):
    lower = {n.lower() for n in names}
    return 'data' in lower and bool(lower & {'明簿.exe', '财务记账软件.exe', 'start.py', 'versions', '明簿.app',
                                              '财务记账软件.app', '使用说明.md'})


def scan(time_limit=12.0):
    """在常见位置查找旧的软件文件夹，最多查 time_limit 秒。"""
    t0 = time.time()
    found, seen = [], set()
    here = {os.path.normcase(os.path.abspath(os.path.dirname(DATA_DIR)))}

    def visit(folder, depth):
        if time.time() - t0 > time_limit:
            return
        try:
            names = os.listdir(folder)
        except OSError:
            return
        key = os.path.normcase(os.path.abspath(folder))
        if key in seen:
            return
        seen.add(key)
        if key not in here and _looks_like_app(folder, names):
            r = inspect_folder(folder)
            if r:
                found.append(r)
            return
        if depth <= 0:
            return
        for n in names:
            if n.startswith('.') or n.lower() in SKIP_DIRS:
                continue
            p = os.path.join(folder, n)
            if os.path.isdir(p) and not os.path.islink(p):
                visit(p, depth - 1)

    for root, depth in _roots():
        if os.path.isdir(root):
            # Mac 的数据目录本身就是“软件文件夹”
            if 'Application Support' in root:
                r = inspect_folder(root)
                if r and os.path.normcase(root) not in here:
                    found.append(r)
                    seen.add(os.path.normcase(os.path.abspath(root)))
                continue
            visit(root, depth)
    return {'found': found, 'seconds': round(time.time() - t0, 1), 'complete': time.time() - t0 <= time_limit}


def import_from(folder, files=None, mode='new'):
    """把 folder 里的账套导入到现在的软件。files 为空表示全部。mode 同“导入账套”：replace 覆盖同名 / new 作为新账套。"""
    r = inspect_folder(folder)
    if not r:
        raise AppError('这个文件夹里没有找到账套（c1.db 这样的文件）')
    results = []
    for c in r['companies']:
        if files and c['file'] not in files:
            continue
        with open(os.path.join(r['data_dir'], c['file']), 'rb') as f:
            data = f.read()
        res = import_companies(data, c['file'], mode, force=True)
        results.extend(res.get('results', []))
    if not results:
        raise AppError('没有选择要导入的账套')
    return {'ok': True, 'results': results}


def data_location():
    return {'data_dir': DATA_DIR, 'backup_dir': BACKUP_DIR,
            'files': sorted(n for n in os.listdir(DATA_DIR) if DB_RE.match(n)) if os.path.isdir(DATA_DIR) else []}


def open_folder(path):
    """在资源管理器 / 访达里打开文件夹。"""
    import subprocess
    if not os.path.isdir(path):
        raise AppError('文件夹不存在：%s' % path)
    if os.name == 'nt':
        os.startfile(path)  # noqa
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])
    return {'ok': True}
