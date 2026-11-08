"""
独立桌面窗口：用电脑系统自带的网页内核（Windows 10/11 的 WebView2、Mac 的 WebKit）显示软件界面，
看起来就是一个单独的软件，没有地址栏和标签栏。窗口组件（pywebview）只打包在 Windows 10/11 版和 Mac 版里。

工作方式：
- 主进程照常运行本地服务（server.py），另开一个子进程（start.py --window 网址）显示窗口。
  这样窗口组件即使出错甚至崩溃，也只影响子进程，主进程会自动改用浏览器打开，账务数据和功能不受影响。
- 子进程通过标准输出告诉主进程：ready（页面已打开）/ unavailable 原因（打不开窗口）。
  主进程通过标准输入告诉子进程：show（再次双击图标时把窗口调到最前面）/ quit（点了“退出软件”）。
- 用户关掉窗口 = 退出软件（关闭本地服务）。
- 打不开窗口时（Windows 7、没有 WebView2、在线更新的老安装没有窗口组件……）：
  Windows 上优先用 Edge / Chrome 的“应用模式”打开（也没有地址栏），都没有就用默认浏览器。

只用标准库，兼容 Python 3.8；pywebview 只在子进程里导入。
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from . import db

ROOT = db.ROOT
APP_NAME = '明簿'
READY_TIMEOUT = 60  # 子进程这么久还没打开页面，就认为窗口打不开，改用浏览器

# 窗口组件自带的按钮和菜单文字（Mac 菜单栏、关闭确认框、保存对话框）
ZH = {
    'global.quitConfirmation': '还有没保存的内容（例如正在录入的凭证），确定要关闭软件吗？',
    'global.ok': '确定',
    'global.quit': '关闭软件',
    'global.cancel': '取消',
    'global.saveFile': '保存文件',
    'cocoa.menu.about': '关于' + APP_NAME,
    'cocoa.menu.services': '服务',
    'cocoa.menu.view': '显示',
    'cocoa.menu.edit': '编辑',
    'cocoa.menu.hide': '隐藏' + APP_NAME,
    'cocoa.menu.hideOthers': '隐藏其他',
    'cocoa.menu.showAll': '全部显示',
    'cocoa.menu.quit': '退出' + APP_NAME,
    'cocoa.menu.fullscreen': '进入全屏幕',
    'cocoa.menu.cut': '剪切',
    'cocoa.menu.copy': '拷贝',
    'cocoa.menu.paste': '粘贴',
    'cocoa.menu.selectAll': '全选',
    'windows.fileFilter.allFiles': '所有文件',
    'windows.fileFilter.otherFiles': '其他文件',
}


# ================================================================ 设置：独立窗口 / 浏览器

def _settings_path():
    return os.path.join(db.DATA_DIR, 'settings.json')


def _load_settings():
    try:
        with open(_settings_path(), encoding='utf-8') as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def get_prefer():
    """用户选择的打开方式：window（独立窗口，默认）或 browser（浏览器）。"""
    return 'browser' if _load_settings().get('ui_mode') == 'browser' else 'window'


def set_prefer(mode):
    s = _load_settings()
    s['ui_mode'] = 'browser' if mode == 'browser' else 'window'
    with open(_settings_path(), 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def has_window_component():
    """这份安装里有没有窗口组件（pywebview）。不真正导入，避免拖慢主进程。"""
    try:
        import importlib.util
        return importlib.util.find_spec('webview') is not None
    except Exception:
        return False


def window_blocker():
    """不能用独立窗口的原因；可以尝试时返回 None。"""
    if os.environ.get('RENTAL_BROWSER') == '1' or '--browser' in sys.argv:
        return '启动参数指定用浏览器打开'
    if get_prefer() == 'browser':
        return '“设置 → 软件更新”里选择了用浏览器打开'
    if os.name == 'nt' and sys.getwindowsversion().major < 10:
        return 'Windows 7/8 不支持独立窗口'
    if not has_window_component():
        return '这份安装里没有窗口组件（Windows 7 版，或从旧版本在线更新而来；重新下载完整安装包即可使用独立窗口）'
    return None


# ================================================================ 浏览器打开（窗口打不开时）

def _app_mode_browsers():
    """Windows 上能用“应用模式”（--app，独立窗口、没有地址栏）的浏览器。"""
    if os.name != 'nt':
        return []
    env = os.environ.get
    bases = [env('ProgramFiles(x86)'), env('ProgramFiles'), env('ProgramW6432'), env('LOCALAPPDATA')]
    rels = [r'Microsoft\Edge\Application\msedge.exe', r'Google\Chrome\Application\chrome.exe']
    out = []
    for rel in rels:
        for b in bases:
            if b:
                p = os.path.join(b, rel)
                if os.path.isfile(p) and p not in out:
                    out.append(p)
    return out


def open_browser(url):
    for exe in _app_mode_browsers():
        try:
            subprocess.Popen([exe, '--app=' + url], close_fds=True)
            return 'app'
        except OSError:
            continue
    webbrowser.open(url)
    return 'browser'


# ================================================================ 主进程：管理窗口子进程

class WindowProcess:
    """一个窗口子进程。on_closed：用户关掉了窗口（要退出软件）；打不开时自动改用浏览器。"""

    def __init__(self, url, on_closed, fallback=None, timeout=READY_TIMEOUT):
        self.url = url
        self.on_closed = on_closed
        self.fallback = fallback or open_browser
        self.timeout = timeout
        self.ready = threading.Event()
        self.failed = None   # 子进程报告的打不开原因
        self.reason = ''     # 最终改用浏览器的原因
        self.fell_back = False
        self.stopping = False
        self.proc = None
        self._lock = threading.Lock()

    def command(self):
        return [sys.executable, os.path.join(ROOT, 'start.py'), '--window', self.url]

    def start(self):
        kw = {'env': dict(os.environ, PYTHONIOENCODING='utf-8')}
        if os.name == 'nt':
            kw['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
        try:
            # 子进程的出错信息写到主进程的日志里（主进程没有日志文件时就继承它的 stderr）
            try:
                sys.stderr.flush()
                kw['stderr'] = sys.stderr.fileno()
            except Exception:
                pass
            self.proc = subprocess.Popen(self.command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         cwd=ROOT, **kw)
        except OSError as e:
            self._fail('无法启动窗口：%s' % e)
            return self
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._watch_timeout, daemon=True).start()
        return self

    def _read(self):
        for raw in iter(self.proc.stdout.readline, b''):
            line = raw.decode('utf-8', 'replace').strip()
            if line == 'ready':
                if not self.ready.is_set():
                    print('独立窗口已打开')
                self.ready.set()
            elif line.startswith('unavailable'):
                self.failed = line[len('unavailable'):].strip() or '窗口组件不可用'
        code = self.proc.wait()
        if self.stopping:
            return
        if os.environ.get('RENTAL_DESKTOP_SMOKE') and code != 0:
            print('自动测试：窗口程序退出代码 %s' % code)
            os._exit(7)
        if self.ready.is_set():
            self.on_closed()  # 用户关掉了窗口 → 退出软件
        else:
            self._fail(self.failed or '窗口程序意外退出（代码 %s）' % code)

    def _watch_timeout(self):
        if self.ready.wait(self.timeout) or self.stopping:
            return
        if self.proc.poll() is None:
            self.stopping = True
            self._kill()
            self._fail('窗口 %d 秒内没有打开' % self.timeout)

    def _fail(self, reason):
        with self._lock:
            if self.fell_back:
                return
            print('独立窗口打不开，改用浏览器：%s' % reason)
            self.fell_back = True
            self.reason = reason
        self.fallback(self.url)

    def alive(self):
        return self.proc is not None and self.proc.poll() is None and self.ready.is_set()

    def send(self, cmd):
        try:
            self.proc.stdin.write((cmd + '\n').encode('utf-8'))
            self.proc.stdin.flush()
            return True
        except Exception:
            return False

    def show(self):
        return self.alive() and self.send('show')

    def stop(self):
        """软件退出时关闭窗口。"""
        self.stopping = True
        if self.proc is None or self.proc.poll() is not None:
            return
        self.send('quit')
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self._kill()

    def _kill(self):
        try:
            self.proc.kill()
        except Exception:
            pass


current = None       # 当前的窗口子进程
ui_mode = 'browser'  # 本次实际的打开方式：window / browser
ui_reason = ''       # 用浏览器打开的原因


def open_ui(url, on_closed):
    """打开软件界面：能用独立窗口就用窗口，否则用浏览器。"""
    global current, ui_mode, ui_reason
    reason = window_blocker()
    if reason:
        print('用浏览器打开：%s' % reason)
        ui_mode, ui_reason = 'browser', reason
        open_browser(url)
        return None

    def fallback(u):
        global ui_mode, ui_reason
        ui_mode, ui_reason = 'browser', (current.reason if current else '') or '窗口打不开'
        if os.environ.get('RENTAL_DESKTOP_SMOKE'):
            os._exit(5)  # 自动测试：窗口打不开就算失败
        open_browser(u)

    ui_mode, ui_reason = 'window', ''
    current = WindowProcess(url, on_closed, fallback).start()
    return current


def show_existing():
    """再次双击图标：把已经打开的窗口调到最前面。没有窗口时返回 False。"""
    return bool(current and current.show())


def stop():
    if current:
        current.stop()


def status():
    return {'mode': 'window' if current and current.alive() else 'browser', 'reason': ui_reason, 'prefer': get_prefer(), 'component': has_window_component()}


# ================================================================ 子进程：显示窗口（需要 pywebview）

class Api:
    """给页面用的几个功能（页面里通过 window.pywebview.api.xxx 调用）。下划线开头的属性不会暴露给页面。"""

    def __init__(self, base_url):
        self._base = base_url.rstrip('/')
        self._window = None

    def save_file(self, path, body=None, company='', fallback_name='下载'):
        """下载文件：从本地服务取到内容后，弹出“保存”对话框让用户选位置。"""
        import webview
        if not isinstance(path, str) or not path.startswith('/api/'):
            return {'error': '不能下载这个地址'}
        headers = {'X-Company': company or ''}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self._base + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                content = r.read()
                cd = r.headers.get('Content-Disposition') or ''
        except urllib.error.HTTPError as e:
            try:
                return {'error': json.loads(e.read().decode('utf-8')).get('error') or '下载失败'}
            except Exception:
                return {'error': '下载失败：%s' % e.code}
        except Exception as e:
            return {'error': '下载失败：%s' % e}
        name = filename_from_disposition(cd) or fallback_name or '下载'
        picked = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name)
        if not picked:
            return {'cancelled': True}
        target = picked if isinstance(picked, str) else picked[0]
        with open(target, 'wb') as f:
            f.write(content)
        return {'saved': target}

    def set_unsaved(self, flag):
        """页面上有没保存的内容时，关窗口前先确认。"""
        self._window.confirm_close = bool(flag)
        return True

    def open_external(self, url):
        if isinstance(url, str) and url.startswith(('https://', 'http://')):
            webbrowser.open(url)
            return True
        return False


def filename_from_disposition(cd):
    """从 Content-Disposition 里取文件名（本软件用 filename*=UTF-8''…）。"""
    for part in (cd or '').split(';'):
        part = part.strip()
        if part.lower().startswith("filename*=utf-8''"):
            return os.path.basename(urllib.parse.unquote(part[len("filename*=utf-8''"):]))
        if part.lower().startswith('filename='):
            return os.path.basename(part[len('filename='):].strip('"'))
    return ''


def _icon():
    name = 'app.ico' if os.name == 'nt' else 'app.png'
    p = os.path.join(ROOT, 'web', name)
    return p if os.path.isfile(p) else None


def _mac_branding(icon):
    """Mac：Dock 和菜单栏显示软件名和图标，而不是“Python”。"""
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        info['CFBundleName'] = APP_NAME
        info['CFBundleDisplayName'] = APP_NAME
    except Exception:
        pass
    try:
        import AppKit
        app = AppKit.NSApplication.sharedApplication()
        if icon:
            app.setApplicationIconImage_(AppKit.NSImage.alloc().initWithContentsOfFile_(icon))
    except Exception:
        pass


def _window_size():
    try:
        import webview
        s = webview.screens[0]
        return max(1000, min(1440, int(s.width * 0.9))), max(640, min(900, int(s.height * 0.88)))
    except Exception:
        return 1366, 860


def run_window(url):
    """子进程入口：显示窗口，直到用户关掉。返回退出代码（3 = 窗口打不开）。"""
    out = sys.__stdout__

    def tell(msg):
        try:
            out.write(msg + '\n')
            out.flush()
        except Exception:
            pass

    try:
        import webview
        gui = None
        if os.name == 'nt':
            from webview.platforms import winforms
            if getattr(winforms, 'renderer', '') != 'edgechromium':
                tell('unavailable 电脑上没有 WebView2 组件（Win10/11 一般自带，可以到微软官网下载安装）')
                return 3
            gui = 'edgechromium'
        elif sys.platform == 'darwin':
            gui = 'cocoa'
    except Exception as e:
        tell('unavailable 窗口组件加载失败：%s' % e)
        return 3

    smoke = bool(os.environ.get('RENTAL_DESKTOP_SMOKE'))
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Rowinrain.CaiwuJizhang')
        except Exception:
            pass
    icon = _icon()
    if sys.platform == 'darwin':
        _mac_branding(icon)

    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    api = Api(url)
    width, height = _window_size()
    win = webview.create_window(APP_NAME, url, js_api=api, width=width, height=height, min_size=(1000, 640),
                                text_select=True, zoomable=True, localization=ZH)
    api._window = win

    def on_loaded():
        tell('ready')
        if smoke:
            threading.Thread(target=_smoke_check, args=(win,), daemon=True).start()

    win.events.loaded += on_loaded

    def listen():
        stdin = sys.__stdin__
        if stdin is None:
            return
        for line in iter(stdin.readline, ''):
            cmd = line.strip()
            try:
                if cmd == 'show':
                    win.restore()
                    win.show()
                    win.on_top = True
                    time.sleep(0.2)
                    win.on_top = False
                elif cmd == 'quit':
                    win.destroy()
                    return
            except Exception as e:
                print('窗口命令出错：', cmd, e)
        # 主进程没了（标准输入关闭）：窗口也关掉，免得留下一个连不上后台的窗口
        try:
            win.destroy()
        except Exception:
            pass

    threading.Thread(target=listen, daemon=True).start()
    storage = os.path.join(db.DATA_DIR, 'window')
    webview.start(gui=gui, private_mode=False, storage_path=storage, icon=icon)
    return 0


def _smoke_check(win):
    """自动测试（RENTAL_DESKTOP_SMOKE=1）：确认页面脚本正常运行、接口能连上，然后关窗口。"""
    ok = False
    for _ in range(40):
        time.sleep(0.5)
        try:
            r = win.evaluate_js("(typeof App === 'object' && document.body.innerText.length > 10) ? "
                                "document.title + '|' + (window.pywebview && window.pywebview.api && window.pywebview.api.save_file ? 'api' : 'noapi') : ''")
        except Exception as e:
            r = 'error %s' % e
        print('自动测试：', r)
        if r and '|api' in str(r):
            ok = True
            break
    print('自动测试结果：', 'OK' if ok else 'FAIL')
    if not ok:
        os._exit(6)
    win.destroy()
