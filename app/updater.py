"""
软件更新：上传新版本的压缩包，替换程序文件（app、web、启动文件、说明），
data（账套数据）和 backups（备份）文件夹不会被改动。替换前会自动备份所有账套和旧版程序。
"""
import datetime
import io
import os
import re
import stat
import zipfile

import hashlib
import hmac
import json
import threading
import time
import urllib.request

from . import VERSION, UPDATE_URL
from .db import AppError, ROOT, BACKUP_DIR, DATA_DIR, list_companies, backup_company

# 只允许更新这些位置的文件
ALLOWED_TOP = ('app/', 'web/')
ALLOWED_FILES = ('start.py', '使用说明.md', '开发说明.md', '更新记录.md')


# ---------------------------------------------------------------- 进度
# 更新在后台线程里进行，界面每隔半秒读取一次进度（/api/update/progress），显示进度条、
# 当前步骤、正在用哪个下载地址，以及每一步的提示（例如“ghfast.top 连接超时，换下一个”）。

STAGES = {
    'online': [('manifest', '获取更新信息'), ('download', '下载更新包'), ('verify', '校验 sha256'),
               ('backup', '备份账套和旧版程序'), ('install', '安装（替换程序文件）'), ('restart', '重新打开软件')],
    'file': [('check', '检查更新包'), ('backup', '备份账套和旧版程序'),
             ('install', '安装（替换程序文件）'), ('restart', '重新打开软件')],
}


class Progress:
    """记录一次更新的进度。不传进度对象时用 Progress()，什么也不显示，照常运行。"""

    def __init__(self, kind='online'):
        self._lock = threading.Lock()
        self.d = {'kind': kind, 'state': 'running', 'stages': [{'key': k, 'name': n} for k, n in STAGES[kind]],
                  'stage': STAGES[kind][0][0], 'message': '', 'source': '', 'done': 0, 'total': 0,
                  'speed': 0, 'log': [], 'error': '', 'result': None, 'started': time.time()}
        self._t0 = time.time()

    def stage(self, key, message=''):
        with self._lock:
            self.d.update(stage=key, message=message, done=0, total=0, speed=0)
            self._t0 = time.time()

    def message(self, message, source=None):
        with self._lock:
            self.d['message'] = message
            if source is not None:
                self.d['source'] = source

    def bytes(self, done, total=None):
        with self._lock:
            self.d['done'] = done
            if total is not None:
                self.d['total'] = total
            dt = time.time() - self._t0
            self.d['speed'] = int(done / dt) if dt > 0.2 else 0

    def log(self, text):
        with self._lock:
            self.d['log'].append('%s  %s' % (datetime.datetime.now().strftime('%H:%M:%S'), text))
            del self.d['log'][:-50]

    def finish(self, result=None, error=''):
        with self._lock:
            self.d['state'] = 'error' if error else 'done'
            self.d['error'] = error
            self.d['result'] = result
            if not error:
                self.d.update(stage='restart', message='更新完成，请点右上角“退出软件”，然后重新打开软件')

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


def start_job(kind, arg):
    """在后台开始更新。kind='online' 时 arg 是更新地址；kind='file' 时 arg 是更新包内容。"""
    global _job
    with _job_lock:
        if _job and _job.d['state'] == 'running':
            raise AppError('已经有一个更新正在进行，请等它完成')
        p = Progress(kind)
        _job = p

    def run():
        try:
            r = update_online(arg, p) if kind == 'online' else apply_update(arg, p)
            p.finish(r)
        except AppError as e:
            p.log('失败：%s' % e)
            p.finish(error=str(e))
        except Exception as e:  # 意外错误也要在界面上显示出来，不能一直卡在“进行中”
            import traceback
            traceback.print_exc()
            p.log('程序出错：%s' % e)
            p.finish(error='更新时程序出错：%s。账套数据和旧版程序已在开始安装前备份，可以稍后重试' % e)

    threading.Thread(target=run, daemon=True).start()
    return p.snapshot()


def _find_prefix(names):
    for n in names:
        if n.endswith('app/server.py'):
            prefix = n[:-len('app/server.py')]
            if prefix + 'web/index.html' in names and prefix + 'start.py' in names:
                return prefix
    raise AppError('这不是本软件的安装包：压缩包中找不到 app/server.py、web/index.html 和 start.py')


def _read_version(z, prefix):
    try:
        txt = z.read(prefix + 'app/__init__.py').decode('utf-8')
        m = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", txt)
        return m.group(1) if m else '未知'
    except KeyError:
        return '未知'


def _backup_current_code():
    folder = os.path.join(BACKUP_DIR, '旧版本程序')
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    path = os.path.join(folder, 'v%s-%s.zip' % (VERSION, stamp))
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for top in ('app', 'web'):
            for root, dirs, files in os.walk(os.path.join(ROOT, top)):
                dirs[:] = [d for d in dirs if d != '__pycache__']
                for f in files:
                    full = os.path.join(root, f)
                    z.write(full, os.path.relpath(full, ROOT))
        for f in ALLOWED_FILES:
            full = os.path.join(ROOT, f)
            if os.path.exists(full):
                z.write(full, f)
    return path


def apply_update(data, progress=None):
    p = progress or Progress('file')
    if p.d['kind'] == 'file':
        p.stage('check', '正在检查更新包…')
    else:
        p.message('正在检查更新包…')
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise AppError('文件不是有效的压缩包')
    names = z.namelist()
    prefix = _find_prefix(names)
    new_version = _read_version(z, prefix)
    if new_version != '未知' and _vtuple(new_version) < _vtuple(VERSION):
        raise AppError('压缩包里是旧版本（v%s），比现在的版本（v%s）还旧，不能用来更新' % (new_version, VERSION))

    members = []
    for n in names:
        if not n.startswith(prefix) or n.endswith('/'):
            continue
        rel = n[len(prefix):]
        if '..' in rel.split('/') or rel.startswith('/') or '__pycache__' in rel:
            continue
        if rel.startswith(ALLOWED_TOP) or rel in ALLOWED_FILES:
            members.append((n, rel))
    if not members:
        raise AppError('压缩包里没有可更新的文件')
    p.log('更新包检查通过：v%s，共 %d 个程序文件' % (new_version, len(members)))

    # 先备份：所有账套 + 旧版程序
    p.stage('backup', '正在备份账套…')
    companies = [c for c in list_companies() if not c.get('broken')]
    for i, c in enumerate(companies):
        p.message('正在备份账套（%d/%d）：%s' % (i + 1, len(companies), c.get('name') or c['id']))
        p.bytes(i, len(companies))
        try:
            backup_company(c['id'], '更新前备份')
        except AppError as e:
            raise AppError('备份账套“%s”失败，已停止更新，程序文件没有改动：%s' % (c.get('name') or c['id'], e))
        except OSError as e:
            raise AppError('备份账套“%s”失败（%s），已停止更新，程序文件没有改动。'
                           '请检查硬盘空间是否足够' % (c.get('name') or c['id'], e))
    p.message('正在备份旧版程序…')
    try:
        old_code = _backup_current_code()
    except OSError as e:
        raise AppError('备份旧版程序失败（%s），已停止更新，程序文件没有改动。请检查硬盘空间是否足够' % e)
    p.log('已备份 %d 个账套和旧版程序' % len(companies))

    p.stage('install', '正在替换程序文件…')
    for i, (n, rel) in enumerate(members):
        p.bytes(i, len(members))
        target = os.path.normpath(os.path.join(ROOT, rel))
        if not target.startswith(ROOT) or target.startswith(DATA_DIR) or target.startswith(BACKUP_DIR):
            continue
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, 'wb') as f:
                f.write(z.read(n))
        except OSError as e:
            raise AppError('替换文件 %s 时出错（%s）。可能是文件被占用或没有写入权限；'
                           '旧版程序已备份在 %s，可以用它恢复，或关闭软件后重新打开再试'
                           % (rel, e, os.path.relpath(old_code, ROOT)))
        if rel.endswith('.command'):
            os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    p.bytes(len(members), len(members))
    p.log('已替换 %d 个文件，从 v%s 更新到 v%s' % (len(members), VERSION, new_version))
    return {'old_version': VERSION, 'new_version': new_version, 'files': len(members),
            'code_backup': os.path.relpath(old_code, ROOT)}


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


def get_update_url():
    return _load_settings().get('update_url') or UPDATE_URL


def _save_setting(key, value):
    s = _load_settings()
    if not isinstance(s, dict):
        s = {}
    s[key] = value
    with open(_settings_path(), 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def set_update_url(url):
    url = (url or '').strip()
    if url and not re.match(r'^https?://', url):
        raise AppError('更新地址应以 http:// 或 https:// 开头')
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


def _vtuple(v):
    return tuple(int(x) for x in re.findall(r'\d+', v or '0')[:4])


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
    req = urllib.request.Request(_quote_url(url), headers={'User-Agent': 'CaiwuJizhang/%s' % VERSION})
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
                       '请检查网络后重试，或下载更新包后用“方法一”安装。%s'
                       % (len(sources) - 1, errors[0] if errors else ''))
    groups = {}
    for src, info in got:
        key = json.dumps(info, sort_keys=True, ensure_ascii=False)
        groups.setdefault(key, (info, []))[1].append(src)
    info, ok = max(groups.values(), key=lambda g: len(g[1]))
    p.log('已从加速地址取得更新信息：%s' % '、'.join(_short(x[0]) for x in ok))
    if need_confirm and len(ok) < 2:
        raise AppError('GitHub 连不上，能用的加速地址只有一个（%s），无法交叉确认更新信息的真实性，'
                       '为安全起见已停止。请稍后重试，或下载更新包后用“方法一”安装' % ok[0][0])
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


def update_online(url, progress=None):
    p = progress or Progress()
    p.stage('manifest', '正在获取更新信息…')
    manifest, srcs = _fetch_manifest(url, need_confirm=True, progress=p)  # 只取一次，版本判断和校验用同一份内容
    if not _summary(manifest)['has_update']:
        raise AppError('已经是最新版本（%s）' % VERSION)
    if not manifest.get('url'):
        raise AppError('更新信息里没有下载地址')
    want = str(manifest.get('sha256') or '').strip().lower()
    if not re.fullmatch(r'[0-9a-f]{64}', want):
        raise AppError('更新信息里缺少有效的 sha256 校验值，为安全起见已停止更新。'
                       '请联系发布者，或下载更新包后用“离线更新”安装')
    import urllib.parse
    # 下载地址可以写相对于 latest.json 的路径；按能连上的来源依次尝试，每个都要通过 sha256 校验
    # 更新信息已经确认过，安装包有 sha256 把关，所以下载可以再试其余加速地址
    p.log('找到新版本 v%s（当前 v%s）' % (manifest['version'], VERSION))
    tried = srcs + [x for x in _sources(url) if x not in srcs]
    last = None
    for k, (name, base) in enumerate(tried):
        i = base.find(GITHUB)
        if i >= 0:  # 加速地址：先和 GitHub 原网址拼好，再加上同一个加速前缀
            dl = urllib.parse.urljoin(base[i:], manifest['url'])
            if dl.startswith(GITHUB):
                dl = base[:i] + dl
        else:
            dl = urllib.parse.urljoin(base, manifest['url'])
        if name == '直连':
            label = 'GitHub' if base.startswith(GITHUB) else urllib.parse.urlsplit(base).netloc
        else:
            label = _short(name) if name != '自定义' else urllib.parse.urlsplit(base).netloc
        p.stage('download', '正在从 %s 下载（第 %d 个下载地址，共 %d 个）' % (label, k + 1, len(tried)))
        p.message('正在从 %s 下载（第 %d 个下载地址，共 %d 个）' % (label, k + 1, len(tried)), label)
        try:
            data = _fetch(dl, progress=p)
        except AppError as e:
            p.log('%s 下载失败：%s%s' % (label, str(e).replace('无法连接更新地址：', ''),
                                    '，换下一个地址' if k + 1 < len(tried) else ''))
            last = last or e  # 校验失败的提示更重要，不被后面的连接失败覆盖
            continue
        p.log('从 %s 下载完成，%s' % (label, _mb(len(data))))
        p.stage('verify', '正在校验 sha256…')
        if hmac.compare_digest(hashlib.sha256(data).hexdigest(), want):
            p.log('sha256 校验通过')
            return apply_update(data, p)
        p.log('%s 下载的文件 sha256 校验不通过（文件不完整或被修改），已丢弃%s'
              % (label, '，换下一个地址' if k + 1 < len(tried) else ''))
        last = AppError('下载的更新包校验失败（文件不完整或被修改），为安全起见没有安装，请稍后重试')
    if 'sha256' not in str(last) and '校验' not in str(last):
        last = AppError('所有下载地址（%d 个）都没能下载成功，最后一个错误：%s。请检查网络后重试，'
                        '或下载更新包后用“方法一”安装' % (len(tried), str(last).replace('无法连接更新地址：', '')))
    raise last
