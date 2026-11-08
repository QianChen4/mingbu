"""
打开软件界面：Windows 7、Windows 10/11 和 Mac 都用同一种方式——浏览器的“应用模式”。

应用模式（--app）是 Edge / Chrome 自带的功能：打开的是一个单独的窗口，没有地址栏和标签栏，看起来像普通软件。
- Windows 10/11：系统自带 Edge，直接用它。
- Windows 7：装了 Chrome 或 Edge（109 版）就用它们；都没有就用默认浏览器（普通的浏览器标签页，功能一样）。
- Mac：装了 Chrome / Edge 就用应用模式，否则用默认浏览器（Safari）。

关掉窗口后，后台程序会在几秒后自动退出（见 server.py 的 Watchdog），不会一直留在后台。
以前 Windows 10/11 和 Mac 用的独立窗口组件（pywebview）不再需要，安装包也更小。
"""
import os
import subprocess
import sys
import webbrowser

WINDOW_SIZE = '--window-size=1360,860'


def _windows_browsers():
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


def _mac_browsers():
    out = []
    for name in ('Google Chrome', 'Microsoft Edge'):
        for base in ('/Applications', os.path.expanduser('~/Applications')):
            app = os.path.join(base, name + '.app')
            exe = os.path.join(app, 'Contents', 'MacOS', name)
            if os.path.exists(exe):
                out.append(exe)
                break
    return out


def app_mode_browsers():
    if os.name == 'nt':
        return _windows_browsers()
    if sys.platform == 'darwin':
        return _mac_browsers()
    return []


def open_ui(url):
    """打开软件界面。返回 'app'（应用模式窗口）或 'browser'（默认浏览器）。"""
    if os.environ.get('MINGBU_NO_BROWSER'):
        return 'none'
    for exe in app_mode_browsers():
        try:
            kw = {'close_fds': True}
            if os.name == 'nt':
                kw['creationflags'] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            else:
                kw['start_new_session'] = True
            subprocess.Popen([exe, '--app=' + url, WINDOW_SIZE], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
            return 'app'
        except OSError:
            continue
    if sys.platform == 'darwin':
        try:
            subprocess.Popen(['open', url])
            return 'browser'
        except OSError:
            pass
    webbrowser.open(url)
    return 'browser'


def status():
    found = app_mode_browsers()
    return {'app_mode': bool(found), 'browser': os.path.basename(found[0]) if found else ''}
