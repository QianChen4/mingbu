"""打包：生成 Windows 完整包、Mac 测试包和 latest.json。

    python3 tools/build.py                    # 版本号取 app/__init__.py 里的 VERSION
    python3 tools/build.py --version 1.8.0    # 临时指定版本号（只用于测试打包，不改代码里的版本号）
    python3 tools/build.py --only windows     # 只打 Windows 包（windows / mac）

输出在 dist/：
  caiwu-jizhang-windows.zip   Windows 7 / 10 / 11 通用。新装和离线更新都用这一个文件
  caiwu-jizhang-mac.zip       Mac 测试用，解压出“明簿.app”
  latest.json                 在线更新信息（顶层 url/sha256 是 Windows 包，"mac" 里是 Mac 包）

Windows 包的结构（解压后整个文件夹拷到哪里都能用）：
  明簿/明簿.exe
  明簿/versions/current.txt
  明簿/versions/v1.8.0/{app, web, start.py, runtime(自带 Python 3.8 32 位)}
  明簿/使用说明.md、更新记录.md

需要：Python 3.8+。图标用 tools/icon.py 生成后已经放在 assets/ 里；
启动程序有 i686-w64-mingw32-gcc 时现场编译，没有时用 tools/launcher/明簿.exe。
Mac 包要下载 python-build-standalone（按下面写死的 sha256 校验），下载后缓存在 tools/.cache。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, 'tools')
DIST = os.path.join(ROOT, 'dist')
CACHE = os.path.join(TOOLS, '.cache')
REPO = 'QianChen4/mingbu'
DOWNLOAD = 'https://github.com/%s/releases/latest/download/' % REPO

WIN_ZIP = 'caiwu-jizhang-windows.zip'
MAC_ZIP = 'caiwu-jizhang-mac.zip'
TOP = '明簿'

# 程序文件：这些会放进版本文件夹
PROGRAM = ['app', 'web', 'start.py']
DOCS = ['使用说明.md', '更新记录.md']

# Mac 用的 Python（python-build-standalone，按 sha256 校验）
MAC_PY = {
    'arm64': ('https://github.com/indygreg/python-build-standalone/releases/download/20241002/'
              'cpython-3.12.7+20241002-aarch64-apple-darwin-install_only.tar.gz',
              '5a9cdbb8536839a83edae3e41eb44161b640d78181fec083e07c668ba796a875'),
    'x86_64': ('https://github.com/indygreg/python-build-standalone/releases/download/20241002/'
               'cpython-3.12.7+20241002-x86_64-apple-darwin-install_only.tar.gz',
               '60eaf2c9a63926f5edfe7a0ecf4b2fbb37de6764f0c0100be245d098e3995da7'),
}
# Mac 版 Python 里用不到的部分，去掉减小体积
MAC_PY_SKIP = re.compile(r'(^|/)(test|tests|idlelib|tkinter|turtledemo|ensurepip|lib2to3|__pycache__)(/|$)'
                         r'|(^|/)include/|(^|/)share/|\.a$|libtcl|libtk|_tkinter')

FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def code_version():
    with open(os.path.join(ROOT, 'app', '__init__.py'), encoding='utf-8') as f:
        return re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", f.read()).group(1)


def program_files():
    """(压缩包里的相对路径, 本地文件) 列表，不含缓存文件。"""
    out = []
    for item in PROGRAM:
        p = os.path.join(ROOT, item)
        if os.path.isfile(p):
            out.append((item, p))
            continue
        for d, dirs, files in os.walk(p):
            dirs[:] = sorted(x for x in dirs if x != '__pycache__')
            for fn in sorted(files):
                if fn.endswith(('.pyc', '.pyo')) or fn == '.DS_Store':
                    continue
                full = os.path.join(d, fn)
                out.append((os.path.relpath(full, ROOT).replace(os.sep, '/'), full))
    return out


class Zip:
    """写 zip：文件名用 UTF-8 标记（中文文件名在 Windows 自带解压里不会乱码），时间固定，方便比较。"""

    def __init__(self, path):
        self.z = zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9)

    def add_bytes(self, name, data, mode=0o644):
        info = zipfile.ZipInfo(name, FIXED_TIME)
        info.flag_bits |= 0x800
        info.external_attr = (0o100000 | mode) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        self.z.writestr(info, data)

    def add_file(self, name, path, mode=None):
        with open(path, 'rb') as f:
            data = f.read()
        if mode is None:
            mode = 0o755 if os.access(path, os.X_OK) and not path.endswith(('.py', '.md', '.js', '.css', '.html')) else 0o644
        self.add_bytes(name, data, mode)

    def add_link(self, name, target):
        info = zipfile.ZipInfo(name, FIXED_TIME)
        info.flag_bits |= 0x800
        info.external_attr = (0o120777) << 16
        self.z.writestr(info, target)

    def close(self):
        self.z.close()


def set_version(data, version):
    """测试打包时把 app/__init__.py 里的版本号换成 --version 指定的。"""
    return re.sub(rb"VERSION\s*=\s*['\"][^'\"]+['\"]", ("VERSION = '%s'" % version).encode(), data, count=1)


def add_program(z, prefix, version):
    for rel, full in program_files():
        if rel == 'app/__init__.py':
            with open(full, 'rb') as f:
                z.add_bytes(prefix + rel, set_version(f.read(), version))
        else:
            z.add_file(prefix + rel, full, 0o644)


def build_launcher():
    out = os.path.join(TOOLS, 'launcher', '明簿.exe')
    gcc, windres = shutil.which('i686-w64-mingw32-gcc'), shutil.which('i686-w64-mingw32-windres')
    if not (gcc and windres):
        print('  没有 mingw，用现成的启动程序 tools/launcher/明簿.exe')
        return out
    d = os.path.join(TOOLS, 'launcher')
    tmp = tempfile.mkdtemp()
    res = os.path.join(tmp, 'launcher.res')
    built = os.path.join(tmp, 'launcher.exe')
    subprocess.check_call([windres, 'launcher.rc', '-O', 'coff', '-o', res], cwd=d)
    subprocess.check_call([gcc, '-municode', '-mwindows', '-O2', '-s', 'launcher.c', res, '-o', built], cwd=d)
    print('  已编译启动程序')
    return built


def build_windows(version):
    vname = 'v' + version
    path = os.path.join(DIST, WIN_ZIP)
    z = Zip(path)
    top = TOP + '/'
    z.add_file(top + '明簿.exe', build_launcher(), 0o755)
    z.add_bytes(top + 'versions/current.txt', (vname + '\n').encode())
    vp = top + 'versions/' + vname + '/'
    add_program(z, vp, version)
    rt = os.path.join(TOOLS, 'runtime', 'win32')
    if not os.path.isfile(os.path.join(rt, 'pythonw.exe')):
        raise SystemExit('找不到 Windows 运行环境 tools/runtime/win32')
    for fn in sorted(os.listdir(rt)):
        z.add_file(vp + 'runtime/' + fn, os.path.join(rt, fn), 0o644)
    for d in DOCS:
        if os.path.isfile(os.path.join(ROOT, d)):
            z.add_file(top + d, os.path.join(ROOT, d), 0o644)
    z.close()
    return path


def fetch_python(arch):
    url, sha = MAC_PY[arch]
    os.makedirs(CACHE, exist_ok=True)
    dest = os.path.join(CACHE, url.rsplit('/', 1)[1])
    if not (os.path.isfile(dest) and sha256_file(dest) == sha):
        print('  下载 Mac 版 Python（%s）…' % arch)
        with urllib.request.urlopen(url, timeout=120) as r, open(dest + '.part', 'wb') as f:
            shutil.copyfileobj(r, f)
        os.replace(dest + '.part', dest)
    if sha256_file(dest) != sha:
        raise SystemExit('Mac 版 Python 的 sha256 不对：%s' % dest)
    return dest


def build_mac(version):
    vname = 'v' + version
    path = os.path.join(DIST, MAC_ZIP)
    z = Zip(path)
    app = '明簿.app/Contents/'
    plist = {
        'CFBundleName': '明簿', 'CFBundleDisplayName': '明簿', 'CFBundleExecutable': '明簿',
        'CFBundleIdentifier': 'local.caiwu.jizhang', 'CFBundleIconFile': 'app.icns',
        'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': version, 'CFBundleVersion': version,
        'LSMinimumSystemVersion': '10.13', 'LSUIElement': True, 'NSHighResolutionCapable': True,
    }
    z.add_bytes(app + 'Info.plist', plist_xml(plist))
    z.add_file(app + 'MacOS/明簿', os.path.join(TOOLS, 'mac', 'launch.sh'), 0o755)
    z.add_file(app + 'Resources/boot.py', os.path.join(TOOLS, 'mac', 'boot.py'), 0o644)
    z.add_file(app + 'Resources/app.icns', os.path.join(ROOT, 'assets', 'app.icns'), 0o644)
    add_program(z, app + 'Resources/program/' + vname + '/', version)
    for arch in ('arm64', 'x86_64'):
        tgz = fetch_python(arch)
        with tarfile.open(tgz) as t:
            for m in t.getmembers():
                rel = m.name.split('/', 1)[1] if '/' in m.name else ''
                if not rel or MAC_PY_SKIP.search(rel):
                    continue
                name = app + 'Resources/python-%s/%s' % (arch, rel)
                if m.issym():
                    z.add_link(name, m.linkname)
                elif m.isfile():
                    z.add_bytes(name, t.extractfile(m).read(), m.mode & 0o777)
    for d in DOCS:
        if os.path.isfile(os.path.join(ROOT, d)):
            z.add_file(d, os.path.join(ROOT, d), 0o644)
    z.close()
    return path


def plist_xml(d):
    def val(v):
        if v is True:
            return '<true/>'
        if v is False:
            return '<false/>'
        return '<string>%s</string>' % str(v).replace('&', '&amp;').replace('<', '&lt;')
    body = ''.join('\t<key>%s</key>\n\t%s\n' % (k, val(v)) for k, v in d.items())
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n<dict>\n%s</dict>\n</plist>\n' % body).encode('utf-8')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def release_notes(version):
    """更新记录.md 里这个版本的说明（没有就用“下一版（还没发布）”那一段）。"""
    try:
        with open(os.path.join(ROOT, '更新记录.md'), encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return ''
    parts = re.split(r'(?m)^## ', text)
    for want in ('v' + version, '下一版'):
        for p in parts:
            if p.startswith(want):
                return '\n'.join(p.splitlines()[1:]).strip()[:1500]
    return ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--version')
    ap.add_argument('--only', choices=['windows', 'mac'])
    args = ap.parse_args()
    version = args.version or code_version()
    os.makedirs(DIST, exist_ok=True)
    info = {'version': version, 'notes': release_notes(version), 'date': time.strftime('%Y-%m-%d')}
    if args.only in (None, 'windows'):
        print('打包 Windows 版…')
        p = build_windows(version)
        info.update(url=DOWNLOAD + WIN_ZIP, sha256=sha256_file(p), size=os.path.getsize(p))
        print('  %s  %.1f MB' % (p, os.path.getsize(p) / 1048576))
    if args.only in (None, 'mac'):
        print('打包 Mac 版…')
        p = build_mac(version)
        info['mac'] = {'url': DOWNLOAD + MAC_ZIP, 'sha256': sha256_file(p), 'size': os.path.getsize(p)}
        print('  %s  %.1f MB' % (p, os.path.getsize(p) / 1048576))
    with open(os.path.join(DIST, 'latest.json'), 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print('完成：', DIST)


if __name__ == '__main__':
    main()
