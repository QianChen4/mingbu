"""明簿.app 的启动程序（Mac 测试版）。

软件文件夹就是 明簿.app 所在的文件夹：读 versions/current.txt，用 .app 里带的 Python 运行那个版本的 start.py。
账套数据在软件文件夹的 data 里，不放到别的地方。

从“下载”里直接双击没签名的 .app 时，macOS 会把它临时复制到一个随机位置运行（App Translocation），
这时用系统接口（SecTranslocateCreateOriginalPathForURL）找回 .app 原来所在的文件夹。
"""
import os
import re
import subprocess
import sys

APP = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))  # …/明簿.app


def original_app_path(app):
    """被系统临时挪走时，找回 .app 原来的位置；没被挪走就原样返回；找不回返回 None。"""
    if '/AppTranslocation/' not in app:
        return app
    try:
        import ctypes
        import ctypes.util
        cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library('CoreFoundation'))
        sec = ctypes.cdll.LoadLibrary(ctypes.util.find_library('Security'))
        cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
        cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long,
                                                               ctypes.c_bool]
        cf.CFURLGetFileSystemRepresentation.restype = ctypes.c_bool
        cf.CFURLGetFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_char_p, ctypes.c_long]
        sec.SecTranslocateCreateOriginalPathForURL.restype = ctypes.c_void_p
        sec.SecTranslocateCreateOriginalPathForURL.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        raw = app.encode('utf-8')
        url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), True)
        orig = sec.SecTranslocateCreateOriginalPathForURL(url, None)
        if orig:
            buf = ctypes.create_string_buffer(4096)
            if cf.CFURLGetFileSystemRepresentation(orig, True, buf, 4096):
                return buf.value.decode('utf-8')
    except Exception:
        pass
    return None


def alert(msg):
    try:
        subprocess.run(['osascript', '-e', 'display dialog "%s" with title "明簿" buttons {"好"} with icon stop'
                        % msg.replace('"', "'")], timeout=300)
    except Exception:
        pass


def vtuple(v):
    return tuple(int(x) for x in re.findall(r'\d+', v or '0')[:4])


def current(versions):
    try:
        with open(os.path.join(versions, 'current.txt'), encoding='utf-8-sig') as f:
            v = f.read().strip()
        if re.fullmatch(r'v[\w.\-]+', v) and os.path.isfile(os.path.join(versions, v, 'start.py')):
            return v
    except OSError:
        pass
    # current.txt 不对时，用编号最大的版本
    try:
        vs = [n for n in os.listdir(versions) if re.fullmatch(r'v\d[\w.\-]*', n)
              and os.path.isfile(os.path.join(versions, n, 'start.py'))]
    except OSError:
        vs = []
    return max(vs, key=vtuple) if vs else ''


def main():
    app = original_app_path(APP)
    if not app:
        alert('打不开：找不到软件文件夹。请把整个“明簿”文件夹移到“文稿”等位置，再双击里面的“明簿.app”。')
        return
    home = os.path.dirname(app)
    versions = os.path.join(home, 'versions')
    cur = current(versions)
    if not cur:
        alert('找不到程序文件（versions 文件夹）。请把完整的压缩包重新解压，然后双击里面的“明簿.app”。')
        return
    os.environ['MINGBU_HOME'] = home
    os.makedirs(os.path.join(home, 'data'), exist_ok=True)
    log = open(os.path.join(home, 'data', '运行日志.txt'), 'a', encoding='utf-8', buffering=1)
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)
    code = os.path.join(versions, cur)
    os.chdir(code)
    # 让 .app 自己马上结束，后台程序脱离出去单独运行。
    if '--detach' in sys.argv and hasattr(os, 'fork'):
        if os.fork() > 0:
            os._exit(0)
        os.setsid()
    os.execv(sys.executable, [sys.executable, '-I', os.path.join(code, 'start.py')])


if __name__ == '__main__':
    main()
