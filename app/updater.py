"""
软件更新（v1.8 起改为“完整包 + 版本文件夹”）。

为什么改：以前的更新只替换 app、web 两个文件夹，启动程序、运行环境、图标都还是旧的；
更新包也不是完整的软件，拷到别的电脑上不能直接用。

现在：
- 完整安装包和更新包是同一个文件（Windows：caiwu-jizhang-windows.zip；Mac：caiwu-jizhang-mac.zip）。
  解压就能用；在“设置 → 软件更新”里选中它就是离线更新；在线更新下载的也是它。
- 每个版本装在软件文件夹的 versions/v版本号 里，是一套完整的程序（Windows 还带运行环境）。
  新版本先完整解压、检查能正常启动，再把 versions/current.txt 改成新版本号——
  中途出错、断电都不会弄坏正在用的版本。只保留“当前版本 + 上一个版本”，可以一键退回上一个版本。
- 启动程序“明簿.exe”也一起换新（老名字“财务记账软件.exe”同样换成新的，老快捷方式照常能用）。
- 账套数据在 data 文件夹，更新时不动；更新前照常自动备份所有账套。
- 在线下载支持断点续传：网络断了从断点接着下，每个下载地址自动重试几次，再换下一个地址。
"""
import datetime
import hashlib
import hmac
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

from . import VERSION, UPDATE_URL, paths
from .db import AppError, BACKUP_DIR, DATA_DIR, list_companies, backup_company

# 在线更新时用于下载临时文件的文件夹（断点续传的半截文件也放在这里）
DOWNLOAD_DIR = os.path.join(BACKUP_DIR, '下载')


# ---------------------------------------------------------------- 进度
# 更新在后台线程里进行，界面每隔半秒读取一次进度（/api/update/progress），显示进度条、
# 当前步骤、正在用哪个下载地址，以及每一步的提示（例如“ghfast.top 连接超时，换下一个”）。

STAGES = {
    'online': [('manifest', '获取更新信息'), ('download', '下载'), ('verify', '校验 sha256'),
               ('backup', '备份账套'), ('install', '安装新版本'), ('restart', '重新打开软件')],
    'file': [('check', '检查安装包'), ('backup', '备份账套'), ('install', '安装新版本'), ('restart', '重新打开软件')],
    'rollback': [('install', '切换版本'), ('restart', '重新打开软件')],
}


class Progress:
    """记录一次更新的进度。不传进度对象时用 Progress()，什么也不显示，照常运行。"""

    def __init__(self, kind='online'):
        self._lock = threading.Lock()
        self.d = {'kind': kind, 'state': 'running', 'stages': [{'key': k, 'name': n} for k, n in STAGES[kind]],
                  'stage': STAGES[kind][0][0], 'message': '', 'source': '', 'done': 0, 'total': 0,
                  'speed': 0, 'log': [], 'error': '', 'result': None, 'started': time.time()}
        self._t0 = time.time()
        self._b0 = 0

    def stage(self, key, message=''):
        with self._lock:
            self.d.update(stage=key, message=message, done=0, total=0, speed=0)
            self._t0 = time.time()
            self._b0 = 0

    def message(self, message, source=None):
        with self._lock:
            self.d['message'] = message
            if source is not None:
                self.d['source'] = source

    def bytes(self, done, total=None, start=None):
        with self._lock:
            if start is not None:  # 断点续传：速度只按这次新下载的部分算
                self._t0, self._b0 = time.time(), start
            self.d['done'] = done
            if total is not None:
                self.d['total'] = total
            dt = time.time() - self._t0
            self.d['speed'] = int((done - self._b0) / dt) if dt > 0.2 else 0

    def log(self, text):
        with self._lock:
            self.d['log'].append('%s  %s' % (datetime.datetime.now().strftime('%H:%M:%S'), text))
            del self.d['log'][:-60]

    def finish(self, result=None, error=''):
        with self._lock:
            self.d['state'] = 'error' if error else 'done'
            self.d['error'] = error
            self.d['result'] = result
            if not error:
                self.d.update(stage='restart', message='新版本已经装好，点“立即重启”就会用新版本打开')

    def snapshot(self):
        with self._lock:
            d = dict(self.d)
            d['log'] = list(d['log'])
            d['elapsed'] = int(time.time() - d['started'])
            return d


_job = None
_job_lock = threading.Lock()


def job_status():
    j = _job
    return j.snapshot() if j else {'state': 'idle'}


def busy():
    j = _job
    return bool(j and j.d['state'] == 'running')


def start_job(kind, arg):
    """在后台开始更新。kind='online' 时 arg 是更新地址；'file' 时 arg 是安装包内容；'rollback' 时 arg 不用。"""
    global _job
    with _job_lock:
        if _job and _job.d['state'] == 'running':
            raise AppError('已经有一个更新正在进行，请等它完成')
        p = Progress(kind)
        _job = p

    def run():
        try:
            if kind == 'online':
                r = update_online(arg, p)
            elif kind == 'rollback':
                r = rollback(p)
            else:
                r = apply_update(arg, p)
            p.finish(r)
        except AppError as e:
            p.log('失败：%s' % e)
            p.finish(error=str(e))
        except Exception as e:  # 意外错误也要在界面上显示出来，不能一直卡在“进行中”
            import traceback
            traceback.print_exc()
            p.log('程序出错：%s' % e)
            p.finish(error='更新时程序出错：%s。正在用的版本没有改动，账套数据也已备份，可以稍后重试' % e)

    threading.Thread(target=run, daemon=True).start()
    return p.snapshot()


# ---------------------------------------------------------------- 安装包

LAUNCHER_NAMES = ('明簿.exe',)
LEGACY_LAUNCHER = '财务记账软件.exe'


def _vtuple(v):
    return tuple(int(x) for x in re.findall(r'\d+', v or '0')[:4])


def _find_prefix(names):
    """找到程序所在的位置（里面有 app/server.py、web/index.html、start.py）。"""
    best = None
    for n in names:
        if n.endswith('app/server.py'):
            prefix = n[:-len('app/server.py')]
            if prefix + 'web/index.html' in names and prefix + 'start.py' in names:
                if best is None or len(prefix) < len(best):
                    best = prefix
    if best is None:
        raise AppError('这不是明簿的安装包：压缩包里找不到 app/server.py、web/index.html 和 start.py。'
                       '请选择从发布页面下载的 caiwu-jizhang-windows.zip（Mac 用 caiwu-jizhang-mac.zip）')
    return best


def _read_version(z, prefix):
    try:
        txt = z.read(prefix + 'app/__init__.py').decode('utf-8')
        m = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", txt)
        return m.group(1) if m else ''
    except KeyError:
        return ''


def _safe_rel(rel):
    parts = rel.replace('\\', '/').split('/')
    return not (rel.startswith('/') or '..' in parts or ':' in parts[0] or '__pycache__' in parts)


def inspect_package(data):
    """检查安装包，返回 (zipfile, 信息)。"""
    try:
        z = zipfile.ZipFile(io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data)
    except zipfile.BadZipFile:
        raise AppError('文件不是有效的压缩包（可能没下载完整）')
    names = z.namelist()
    prefix = _find_prefix(names)
    version = _read_version(z, prefix)
    if not version:
        raise AppError('安装包里找不到版本号（app/__init__.py）')
    # 新结构：<根>/versions/v1.8.0/…；根目录下还有启动程序和说明
    m = re.match(r'^(.*?)versions/[^/]+/$', prefix)
    root = m.group(1) if m else prefix
    launcher = next((root + n for n in LAUNCHER_NAMES if root + n in names), None)
    docs = [n for n in names if n.startswith(root) and n.endswith('.md') and '/' not in n[len(root):]]
    has_runtime = any(n.startswith(prefix + 'runtime/') for n in names)
    return z, {'version': version, 'prefix': prefix, 'root': root, 'launcher': launcher, 'docs': docs,
               'has_runtime': has_runtime, 'files': sum(1 for n in names if n.startswith(prefix) and not n.endswith('/'))}


def _legacy_runtime_dir(home):
    """老结构（v1.7 及以前）的运行环境：软件文件夹里的 runtime-x86 / runtime-x64。"""
    for name in ('runtime-x86', 'runtime-x64', 'runtime'):
        d = os.path.join(home, name)
        if os.path.isfile(os.path.join(d, 'pythonw.exe')):
            return d
    return None


def _current_runtime_dir():
    """正在用的运行环境：Windows 新结构在版本文件夹的 runtime 里。"""
    d = os.path.dirname(sys.executable)
    return d if os.path.isfile(os.path.join(d, 'pythonw.exe')) else None


def current_version_name(home):
    try:
        with open(os.path.join(home, paths.VERSIONS, paths.CURRENT_FILE), encoding='utf-8-sig') as f:
            v = f.read().strip()
        return v if re.fullmatch(r'v[\w.\-]+', v) else ''
    except OSError:
        return ''


def installed_versions(home):
    d = os.path.join(home, paths.VERSIONS)
    try:
        names = [n for n in os.listdir(d) if re.fullmatch(r'v\d[\w.\-]*', n)
                 and os.path.isfile(os.path.join(d, n, 'start.py'))]
    except OSError:
        return []
    return sorted(names, key=_vtuple, reverse=True)


def _write_current(home, vname):
    d = os.path.join(home, paths.VERSIONS)
    tmp = os.path.join(d, paths.CURRENT_FILE + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(vname + '\n')
    os.replace(tmp, os.path.join(d, paths.CURRENT_FILE))


def _rmtree(path):
    def onerror(func, p, exc):
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerror)


def _self_test(vdir, home, is_windows):
    """用新版本自己的运行环境试着加载一次程序，确认能启动。加载失败就不切换过去。"""
    if is_windows:
        py = os.path.join(vdir, 'runtime', 'python.exe')
        if not os.path.isfile(py):
            return None
    else:
        py = sys.executable
    code = ('import sys; sys.path.insert(0, sys.argv[1]); import app, app.server; '
            'print("ok", app.VERSION)')
    env = dict(os.environ)
    env['MINGBU_HOME'] = home
    env.pop('PYTHONPATH', None)
    kw = {}
    if os.name == 'nt':
        kw['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
    try:
        r = subprocess.run([py, '-I' if not is_windows else '-s', '-c', code, vdir], cwd=vdir, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90, **kw)
    except (OSError, subprocess.SubprocessError) as e:
        return '无法运行新版本的程序：%s' % e
    if r.returncode != 0 or b'ok' not in r.stdout:
        err = (r.stderr or b'').decode('utf-8', 'replace').strip().splitlines()
        return '新版本试运行失败：%s' % (err[-1] if err else '未知原因')
    return None


def install_package(data, home=None, progress=None, is_windows=None, allow_same=False, self_test=True):
    """把安装包装进 home/versions/v版本号，并切换过去。返回结果信息。

    home：软件文件夹，默认是正在运行的这个；is_windows：按哪个平台安装（测试时可以指定）。"""
    p = progress or Progress('file')
    home = home or paths.HOME
    is_windows = (os.name == 'nt') if is_windows is None else is_windows
    p.stage('check', '正在检查安装包…') if p.d['kind'] == 'file' else p.message('正在检查安装包…')
    z, info = inspect_package(data)
    new_v = info['version']
    if _vtuple(new_v) < _vtuple(VERSION) and not allow_same:
        raise AppError('压缩包里是旧版本（v%s），比现在的版本（v%s）还旧，不能用来更新。'
                       '想退回上一个版本请用“退回上一个版本”' % (new_v, VERSION))
    if is_windows and not info['has_runtime'] and not (_current_runtime_dir() or _legacy_runtime_dir(home)):
        raise AppError('这个压缩包里没有运行环境，请用 Windows 完整安装包（caiwu-jizhang-windows.zip）')
    p.log('安装包检查通过：v%s，共 %d 个文件' % (new_v, info['files']))

    # 1. 备份所有账套
    p.stage('backup', '正在备份账套…')
    companies = [c for c in list_companies() if not c.get('broken')]
    for i, c in enumerate(companies):
        p.message('正在备份账套（%d/%d）：%s' % (i + 1, len(companies), c.get('name') or c['id']))
        p.bytes(i, len(companies))
        try:
            backup_company(c['id'], '更新前备份')
        except (AppError, OSError) as e:
            raise AppError('备份账套“%s”失败，已停止更新，正在用的版本没有改动：%s' % (c.get('name') or c['id'], e))
    p.log('已备份 %d 个账套' % len(companies))

    # 2. 解压到 versions/v版本号.part
    p.stage('install', '正在解压新版本…')
    vname = 'v' + new_v
    vroot = os.path.join(home, paths.VERSIONS)
    os.makedirs(vroot, exist_ok=True)
    part = os.path.join(vroot, vname + '.part')
    if os.path.exists(part):
        _rmtree(part)
    members = [n for n in z.namelist() if n.startswith(info['prefix']) and not n.endswith('/')]
    try:
        for i, n in enumerate(members):
            rel = n[len(info['prefix']):]
            if not _safe_rel(rel):
                continue
            target = os.path.join(part, *rel.split('/'))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(n) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            if i % 20 == 0:
                p.bytes(i, len(members))
        p.bytes(len(members), len(members))
        if is_windows and not os.path.isfile(os.path.join(part, 'runtime', 'pythonw.exe')):
            src_rt = _current_runtime_dir() or _legacy_runtime_dir(home)
            p.log('安装包里没有运行环境，沿用现在的运行环境')
            shutil.copytree(src_rt, os.path.join(part, 'runtime'))
    except OSError as e:
        _rmtree(part)
        raise AppError('解压新版本时出错（%s）。可能是硬盘空间不够或没有写入权限；正在用的版本没有改动' % e)

    # 3. 试运行
    if self_test:
        p.message('正在检查新版本能否正常启动…')
        err = _self_test(part, home, is_windows)
        if err:
            _rmtree(part)
            raise AppError(err + '。没有切换到新版本，正在用的版本没有改动')
        p.log('新版本试运行正常')

    # 4. 放到正式位置
    final = os.path.join(vroot, vname)
    running_here = os.path.normcase(os.path.abspath(final)) == os.path.normcase(paths.CODE_DIR)
    if os.path.exists(final):
        if running_here:
            _rmtree(part)
            raise AppError('v%s 就是正在使用的版本，不需要重新安装' % new_v)
        old = final + '.old-%d' % int(time.time())
        os.rename(final, old)
        _rmtree(old)
    os.rename(part, final)

    # 5. 启动程序和说明文档
    notes = []
    if is_windows and info['launcher']:
        exe = z.read(info['launcher'])
        for name in LAUNCHER_NAMES + (LEGACY_LAUNCHER,):
            target = os.path.join(home, name)
            if name != LAUNCHER_NAMES[0] and not os.path.exists(target):
                continue  # 老名字的启动程序只在原来就有时才替换（让老快捷方式照常能用）
            try:
                with open(target + '.new', 'wb') as f:
                    f.write(exe)
                os.replace(target + '.new', target)
            except OSError as e:
                notes.append('启动程序 %s 没能替换（%s），下次更新时会再试' % (name, e))
        p.log('启动程序已更新')
    for n in info['docs']:
        try:
            with open(os.path.join(home, n[len(info['root']):]), 'wb') as f:
                f.write(z.read(n))
        except OSError:
            pass

    # 6. 切换版本，清理更早的版本（只留当前和上一个）
    prev = current_version_name(home) or (os.path.basename(paths.CODE_DIR) if paths.LAYOUT == 'versioned' else '')
    _write_current(home, vname)
    p.log('已切换到 v%s' % new_v)
    keep = {vname, prev, os.path.basename(paths.CODE_DIR)}
    for n in os.listdir(vroot):
        full = os.path.join(vroot, n)
        if os.path.isdir(full) and n not in keep and n != paths.VERSIONS:
            if re.fullmatch(r'v\d[\w.\-]*', n) or '.part' in n or '.old-' in n:
                _rmtree(full)
    for n in notes:
        p.log(n)
    return {'old_version': VERSION, 'new_version': new_v, 'files': len(members), 'notes': notes}


def apply_update(data, progress=None):
    """离线更新：选中的完整安装包。"""
    return install_package(data, progress=progress)


def rollback(progress=None):
    """退回上一个版本：把 current.txt 改回上一个版本文件夹。"""
    p = progress or Progress('rollback')
    home = paths.HOME
    cur = current_version_name(home) or os.path.basename(paths.CODE_DIR)
    others = [v for v in installed_versions(home) if v != cur]
    if paths.LAYOUT != 'versioned' or not others:
        raise AppError('没有可以退回的上一个版本')
    target = others[0]
    p.stage('install', '正在切换到 %s…' % target)
    _write_current(home, target)
    p.log('已切换到 %s，重启后生效' % target)
    return {'old_version': VERSION, 'new_version': target.lstrip('v'), 'rollback': True}


def version_info():
    home = paths.HOME
    cur = current_version_name(home)
    return {'version': VERSION, 'layout': paths.LAYOUT, 'home': home, 'current': cur,
            'installed': installed_versions(home),
            'can_rollback': paths.LAYOUT == 'versioned' and any(v != (cur or 'v' + VERSION)
                                                               for v in installed_versions(home)),
            'pending_restart': bool(cur) and cur != 'v' + VERSION and paths.LAYOUT == 'versioned',
            'platform': 'windows' if os.name == 'nt' else ('mac' if sys.platform == 'darwin' else 'other')}


def cleanup_legacy():
    """从老结构（app、web 直接放在软件文件夹里）更新到版本文件夹后，把老结构留下的程序文件移到 backups 里，
    免得以后分不清用的是哪个。只在新结构下运行；账套数据不动。"""
    if paths.LAYOUT != 'versioned':
        return []
    home = paths.HOME
    olds = [n for n in ('app', 'web', 'start.py', 'runtime-x86', 'runtime-x64', 'pylib', '开发说明.md')
            if os.path.exists(os.path.join(home, n))]
    if not ('app' in olds and 'start.py' in olds):
        return []
    dest = os.path.join(BACKUP_DIR, '旧版本程序', '老版本文件-%s' % datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    moved = []
    for n in olds:
        try:
            os.makedirs(dest, exist_ok=True)
            shutil.move(os.path.join(home, n), os.path.join(dest, n))
            moved.append(n)
        except (OSError, shutil.Error):
            pass
    return moved


# ---------------------------------------------------------------- 在线更新
# 更新地址指向一个 JSON 文件（例如放在 GitHub、Gitee 或任何网站上），内容如：
# {"version": "1.5.0", "notes": "本次更新内容……", "url": "https://…/明簿-更新包-v1.6.3.zip", "sha256": "…"}

def _settings_path():
    return os.path.join(DATA_DIR, 'settings.json')


def _load_settings():
    try:
        with open(_settings_path(), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _secure_url(url):
    """更新地址必须是加密的 https（本机地址除外，开发测试用）：不加密的 http 在网络上可以被人换掉内容。"""
    return bool(re.match(r'^https://', url or '', re.I) or
                re.match(r'^http://(127\.0\.0\.1|localhost)(:\d+)?(/|$)', url or '', re.I))


def get_update_url():
    url = _load_settings().get('update_url')
    return url if url and _secure_url(url) else UPDATE_URL


def _save_setting(key, value):
    s = _load_settings()
    if not isinstance(s, dict):
        s = {}
    s[key] = value
    with open(_settings_path(), 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def set_update_url(url):
    url = (url or '').strip()
    if url and not _secure_url(url):
        raise AppError('更新地址应以 https:// 开头（不加密的 http:// 地址不安全，不能使用）')
    _save_setting('update_url', url)


# ---------------------------------------------------------------- 启动时自动检查
# 打开软件时在后台查一次有没有新版本，有就在界面右下角提示。每次打开软件只真正联网查一次
# （刷新页面、切换账套不会重复查）；连不上（国内网络常见）就当没查过，什么也不提示。
# 可以在“设置 → 软件更新”里关掉（data/settings.json 的 "auto_check": false）。

def get_auto_check():
    return _load_settings().get('auto_check') is not False


def set_auto_check(on):
    _save_setting('auto_check', bool(on))


_auto = {'done': False, 'result': None}
_auto_lock = threading.Lock()


def auto_check():
    """返回 {'enabled': bool, 'has_update': bool, 'latest': …, 'current': …, 'notes': …}。不会报错。"""
    if not get_auto_check():
        return {'enabled': False, 'has_update': False, 'current': VERSION}
    with _auto_lock:  # 同时来几个请求时只查一次，后来的等前一个的结果
        if not _auto['done']:
            r = None
            try:
                url = get_update_url()
                if url:
                    r = check_online(url)
            except Exception:
                r = None
            _auto['result'], _auto['done'] = r, True
        r = _auto['result']
    if not r or not r.get('has_update'):
        return {'enabled': True, 'has_update': False, 'current': VERSION}
    return {'enabled': True, 'has_update': True, 'current': VERSION, 'latest': r['latest'],
            'notes': r.get('notes', '')}


def _quote_url(url):
    """网址里有中文（如文件名）时转成 %xx 编码。"""
    import urllib.parse
    p = urllib.parse.urlsplit(url.strip())
    path = urllib.parse.quote(p.path, safe='/%~+-._')
    query = urllib.parse.quote(p.query, safe='=&%~+-._')
    return urllib.parse.urlunsplit((p.scheme, p.netloc, path, query, p.fragment))


def _net_error(e):
    """把网络错误翻译成看得懂的中文，后面括号里保留原始错误，方便排查。"""
    import socket
    import ssl
    import urllib.error
    import http.client
    if isinstance(e, urllib.error.HTTPError):
        msg = {404: '服务器上找不到这个文件（404），可能新版本还在发布中，请过几分钟再试',
               403: '服务器拒绝访问（403）', 429: '访问太频繁被限制了（429），请稍后再试',
               }.get(e.code, '服务器出错（%s）' % e.code if e.code >= 500 else '服务器返回错误（%s）' % e.code)
        return msg
    reason = getattr(e, 'reason', e)
    if isinstance(reason, (socket.timeout, TimeoutError)) or 'timed out' in str(reason):
        msg = '连接超时（网络太慢或这个地址打不开）'
    elif isinstance(reason, socket.gaierror):
        msg = '找不到服务器（域名解析失败，可能没联网或这个地址被屏蔽）'
    elif isinstance(reason, ConnectionRefusedError):
        msg = '服务器拒绝连接'
    elif isinstance(reason, (ConnectionResetError, ConnectionAbortedError, http.client.RemoteDisconnected,
                             http.client.IncompleteRead)):
        msg = '连接被中断'
    elif isinstance(reason, (ssl.SSLError, ssl.CertificateError)):
        msg = '安全证书校验失败（电脑日期时间不对、或网络被拦截时常见）'
    else:
        msg = '网络错误'
    return '%s（%s）' % (msg, e)


def _mb(n):
    return '%.1f MB' % (n / 1048576.0) if n >= 1048576 else '%d KB' % max(1, n // 1024)


def _fetch(url, limit=200 * 1024 * 1024, timeout=30, progress=None):
    req = urllib.request.Request(_quote_url(url), headers={'User-Agent': 'Mingbu/%s' % VERSION})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
    except Exception as e:
        raise AppError('无法连接更新地址：%s' % _net_error(e))
    with r:
        try:
            total = int(r.headers.get('Content-Length') or 0)
        except ValueError:
            total = 0
        if total > limit:
            raise AppError('下载的文件太大')
        if progress:
            progress.bytes(0, total)
        buf = io.BytesIO()
        got = 0
        while True:
            try:
                chunk = r.read(64 * 1024)
            except Exception as e:
                raise AppError('下载到一半中断了（已下载 %s%s）：%s'
                               % (_mb(got), ' / 共 %s' % _mb(total) if total else '', _net_error(e)))
            if not chunk:
                break
            got += len(chunk)
            if got > limit:
                raise AppError('下载的文件太大')
            buf.write(chunk)
            if progress:
                progress.bytes(got)
    if total and got < total:
        raise AppError('下载不完整（只收到 %s，应为 %s），连接可能中途断开了' % (_mb(got), _mb(total)))
    return buf.getvalue()


# 国内网络经常打不开 GitHub。更新地址是 GitHub 上的文件时，直连失败会自动改走下面这些
# GitHub 加速地址（格式都是“加速地址 + 完整的 GitHub 网址”）。这些是第三方公益服务，
# 可能随时失效，所以准备了好几个；也可以在 data/settings.json 里用 "update_mirrors" 自己指定。
MIRRORS = (
    'https://ghfast.top/',
    'https://gh-proxy.com/',
    'https://ghproxy.net/',
    'https://gh.llkk.cc/',
)
GITHUB = 'https://github.com/'


def _mirrors():
    m = _load_settings().get('update_mirrors')
    if isinstance(m, list) and m:
        return tuple(x.rstrip('/') + '/' for x in m if isinstance(x, str) and re.match(r'^https?://', x))
    return MIRRORS


def _sources(url):
    """返回 [(名称, 网址)]：先直连，GitHub 网址再加上各个加速地址。"""
    url = (url or '').strip()
    i = url.find(GITHUB)
    if i < 0:
        return [('直连', url)]
    gh = url[i:]  # 已经填了加速地址的，也还原成 GitHub 原网址
    out = [('直连', gh)] + [(m, m + gh) for m in _mirrors()]
    if i > 0 and url not in [u for _, u in out]:
        out.insert(0, ('自定义', url))
    return out


def _parse_manifest(raw):
    try:
        info = json.loads(raw.decode('utf-8-sig'))
        info['version'] = str(info['version'])
    except Exception:
        raise AppError('更新地址返回的内容格式不正确')
    return info


def _fetch_manifest(url, need_confirm=False, progress=None):
    """取 latest.json，返回 (内容, 成功的来源列表[(名称, 网址)])。

    直连成功就用直连的。直连失败改走加速地址；need_confirm 为 True（要真正安装）时，
    至少两个加速地址返回完全一致的内容才算数，防止某一个第三方加速地址被篡改。
    """
    if not url:
        raise AppError('还没有设置更新地址')
    if not _secure_url(url):
        raise AppError('更新地址应以 https:// 开头（不加密的 http:// 地址不安全，不能使用）')
    p = progress or Progress()
    sources = _sources(url)
    direct = sources[0]
    errors = []
    p.message('正在连接 %s…' % ('GitHub' if len(sources) > 1 else '更新地址'), direct[0])
    try:
        return _parse_manifest(_fetch(direct[1], 1024 * 1024, timeout=10)), [direct]
    except AppError as e:
        if len(sources) == 1:
            raise
        errors.append(str(e))
        p.log('GitHub 直连失败：%s' % str(e).replace('无法连接更新地址：', ''))
        p.message('GitHub 连不上，正在同时尝试 %d 个国内加速地址…' % (len(sources) - 1), '国内加速地址')

    from concurrent.futures import ThreadPoolExecutor

    def get(src):
        try:
            return src, _parse_manifest(_fetch(src[1], 1024 * 1024, timeout=15))
        except AppError as e:
            p.log('%s：%s' % (_short(src[0]), str(e).replace('无法连接更新地址：', '')))
            return src, None

    with ThreadPoolExecutor(max_workers=len(sources) - 1) as ex:
        got = [(src, info) for src, info in ex.map(get, sources[1:]) if info is not None]
    if not got:
        raise AppError('无法连接更新地址（GitHub 直连和 %d 个国内加速地址都连不上）。'
                       '请检查网络后重试，或下载安装包后用“从文件更新”安装。%s'
                       % (len(sources) - 1, errors[0] if errors else ''))
    groups = {}
    for src, info in got:
        key = json.dumps(info, sort_keys=True, ensure_ascii=False)
        groups.setdefault(key, (info, []))[1].append(src)
    info, ok = max(groups.values(), key=lambda g: len(g[1]))
    p.log('已从加速地址取得更新信息：%s' % '、'.join(_short(x[0]) for x in ok))
    if need_confirm and len(ok) < 2:
        raise AppError('GitHub 连不上，能用的加速地址只有一个（%s），无法交叉确认更新信息的真实性，'
                       '为安全起见已停止。请稍后重试，或下载安装包后用“从文件更新”安装' % ok[0][0])
    return info, ok


def _short(name):
    """加速地址显示成短名字，例如 https://ghfast.top/ → ghfast.top。"""
    return re.sub(r'^https?://|/$', '', name)


def _summary(info, srcs=None):
    latest = info['version']
    r = {'current': VERSION, 'latest': latest, 'notes': info.get('notes', ''),
         'has_update': _vtuple(latest) > _vtuple(VERSION), 'download': info.get('url', '')}
    if srcs:
        r['source'] = srcs[0][0]
    return r


def check_online(url):
    return _summary(*_fetch_manifest(url))


def _platform_entry(info):
    """latest.json 里按平台取下载地址：顶层的 url/sha256 是 Windows 完整包（老版本软件也认这个），
    "mac": {"url", "sha256", "size"} 是 Mac 包。"""
    if sys.platform == 'darwin':
        m = info.get('mac')
        if not isinstance(m, dict) or not m.get('url'):
            raise AppError('这次发布没有 Mac 版')
        return m
    return info


def _download(url, dest, want_size, progress, label, attempts=3, timeout=30):
    """下载到 dest，支持断点续传：dest 已经有一部分就从那里接着下。每个地址最多试 attempts 次。
    返回 True 表示下载完整；连不上或一直断返回错误信息。"""
    p = progress
    last = ''
    for attempt in range(1, attempts + 1):
        have = os.path.getsize(dest) if os.path.exists(dest) else 0
        if want_size and have >= want_size:
            return True, ''
        headers = {'User-Agent': 'Mingbu/%s' % VERSION}
        if have:
            headers['Range'] = 'bytes=%d-' % have
        req = urllib.request.Request(_quote_url(url), headers=headers)
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:
            import urllib.error
            if isinstance(e, urllib.error.HTTPError) and e.code == 416 and have:
                return True, ''  # 服务器说“已经下完了”
            last = _net_error(e)
            p.log('%s 第 %d 次连接失败：%s' % (label, attempt, last))
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 8))
            continue
        with r:
            status = getattr(r, 'status', 200)
            if have and status != 206:
                have = 0  # 这个地址不支持断点续传，从头下载
            try:
                length = int(r.headers.get('Content-Length') or 0)
            except ValueError:
                length = 0
            total = want_size or (have + length if length else 0)
            if have:
                p.log('从 %s 断点续传：已有 %s，接着下载' % (label, _mb(have)))
            p.bytes(have, total, start=have)
            got = have
            try:
                with open(dest, 'ab' if have else 'wb') as f:
                    while True:
                        chunk = r.read(64 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if got > 500 * 1024 * 1024:
                            raise AppError('下载的文件太大')
                        p.bytes(got)
            except AppError:
                raise
            except Exception as e:
                last = '下载到一半中断了（已下载 %s%s）：%s' % (_mb(got), ' / 共 %s' % _mb(total) if total else '',
                                                    _net_error(e))
                p.log('%s：%s' % (label, last))
                if attempt < attempts:
                    time.sleep(min(2 ** attempt, 8))
                continue
        if total and got < total:
            last = '下载不完整（只收到 %s，应为 %s）' % (_mb(got), _mb(total))
            p.log('%s：%s，再试一次' % (label, last))
            continue
        return True, ''
    return False, last


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def update_online(url, progress=None):
    p = progress or Progress()
    p.stage('manifest', '正在获取更新信息…')
    manifest, srcs = _fetch_manifest(url, need_confirm=True, progress=p)  # 只取一次，版本判断和校验用同一份内容
    if not _summary(manifest)['has_update']:
        raise AppError('已经是最新版本（%s）' % VERSION)
    entry = _platform_entry(manifest)
    if not entry.get('url'):
        raise AppError('更新信息里没有下载地址')
    want = str(entry.get('sha256') or '').strip().lower()
    if not re.fullmatch(r'[0-9a-f]{64}', want):
        raise AppError('更新信息里缺少有效的 sha256 校验值，为安全起见已停止更新。'
                       '请联系发布者，或下载安装包后用“从文件更新”安装')
    try:
        want_size = int(entry.get('size') or 0)
    except ValueError:
        want_size = 0
    import urllib.parse
    p.log('找到新版本 v%s（当前 v%s）' % (manifest['version'], VERSION))
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    dest = os.path.join(DOWNLOAD_DIR, want[:16] + '.part')
    # 清理以前没下完的其他版本
    for n in os.listdir(DOWNLOAD_DIR):
        if n.endswith('.part') and n != os.path.basename(dest):
            try:
                os.remove(os.path.join(DOWNLOAD_DIR, n))
            except OSError:
                pass
    # 下载地址可以写相对于 latest.json 的路径；能连上 latest.json 的来源排在前面，其余加速地址作为后备
    tried = srcs + [x for x in _sources(url) if x not in srcs]
    last = None
    for k, (name, base) in enumerate(tried):
        i = base.find(GITHUB)
        if i >= 0:  # 加速地址：先和 GitHub 原网址拼好，再加上同一个加速前缀
            dl = urllib.parse.urljoin(base[i:], entry['url'])
            if dl.startswith(GITHUB):
                dl = base[:i] + dl
        else:
            dl = urllib.parse.urljoin(base, entry['url'])
        if name == '直连':
            label = 'GitHub' if base.startswith(GITHUB) else urllib.parse.urlsplit(base).netloc
        else:
            label = _short(name) if name != '自定义' else urllib.parse.urlsplit(base).netloc
        p.stage('download', '正在从 %s 下载（第 %d 个下载地址，共 %d 个）' % (label, k + 1, len(tried)))
        p.message('正在从 %s 下载（第 %d 个下载地址，共 %d 个）' % (label, k + 1, len(tried)), label)
        ok, err = _download(dl, dest, want_size, p, label)
        if not ok:
            p.log('%s 下载失败：%s%s' % (label, err, '，换下一个地址' if k + 1 < len(tried) else ''))
            last = last or AppError(err)
            continue
        p.stage('verify', '正在校验 sha256…')
        if hmac.compare_digest(_sha256_file(dest), want):
            p.log('下载完成（%s），sha256 校验通过' % _mb(os.path.getsize(dest)))
            try:
                with open(dest, 'rb') as f:
                    result = install_package(f.read(), progress=p)
            finally:
                try:
                    os.remove(dest)
                except OSError:
                    pass
            return result
        p.log('%s 下载的文件 sha256 校验不通过（文件不完整或被修改），已丢弃%s'
              % (label, '，换下一个地址' if k + 1 < len(tried) else ''))
        os.remove(dest)
        last = AppError('下载的安装包校验失败（文件不完整或被修改），为安全起见没有安装，请稍后重试')
    if last is None or ('sha256' not in str(last) and '校验' not in str(last)):
        last = AppError('所有下载地址（%d 个）都没能下载完整，最后一个错误：%s。已下载的部分会保留，'
                        '再点一次“检查更新”会从断点接着下载；也可以下载安装包后用“从文件更新”安装'
                        % (len(tried), str(last or '未知错误')))
    raise last
