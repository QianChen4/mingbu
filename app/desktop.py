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
    """返回 [(浏览器 .app 的位置, 里面的可执行文件)]"""
    out = []
    for name in ('Google Chrome', 'Microsoft Edge'):
        for base in ('/Applications', os.path.expanduser('~/Applications')):
            app = os.path.join(base, name + '.app')
            exe = os.path.join(app, 'Contents', 'MacOS', name)
            if os.path.exists(exe):
                out.append((app, exe))
                break
    return out


def _spawn(cmd):
    kw = {'close_fds': True}
    if os.name == 'nt':
        kw['creationflags'] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw['start_new_session'] = True
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


def mac_ways(url):
    """Mac 上打开窗口的几种办法，按顺序试：[(说明, 命令, 浏览器 .app)]。
    1. 请系统（open 命令）启动浏览器的应用模式窗口——和在“应用程序”里双击浏览器是同一条路，最稳；
    2. 直接运行浏览器里面的程序（以前一直用的办法，个别电脑上浏览器只在程序坞里跳一下、不出窗口）；
    3. 用默认浏览器打开一个普通的标签页（一定能打开，只是多了地址栏）。"""
    ways = []
    for app, exe in _mac_browsers():
        name = os.path.basename(app)[:-4]
        ways.append(('请系统打开 %s 的应用模式窗口' % name,
                     ['/usr/bin/open', '-n', '-a', app, '--args', '--app=' + url, WINDOW_SIZE], app))
        ways.append(('直接运行 %s' % name, [exe, '--app=' + url, WINDOW_SIZE], app))
    ways.append(('用默认浏览器打开', ['/usr/bin/open', url], ''))
    return ways


def open_ui_mac(url, connected, wait=7):
    """Mac：一种办法打开后等几秒，页面一直没连上后台（connected() 为假）就换下一种。
    页面连上后把浏览器叫到最前面（有时窗口开在了别的窗口后面）。在后台线程里运行。"""
    import time
    for label, cmd, app in mac_ways(url):
        try:
            _spawn(cmd)
        except OSError as e:
            print('打开窗口：%s 失败：%s' % (label, e))
            continue
        print('打开窗口：%s' % label)
        end = time.time() + wait
        while time.time() < end:
            time.sleep(0.4)
            if connected():
                print('打开窗口：页面已连上')
                if app:
                    try:
                        _spawn(['/usr/bin/open', '-a', app])
                    except OSError:
                        pass
                return True
        print('打开窗口：等了 %d 秒页面还没连上，换一种办法' % wait)
    print('打开窗口：几种办法都试过了，页面仍没有连上。可以手工在浏览器里打开 %s' % url)
    return False


def app_mode_browsers():
    if os.name == 'nt':
        return _windows_browsers()
    if sys.platform == 'darwin':
        return [exe for _app, exe in _mac_browsers()]
    return []


def open_ui(url, connected=None):
    """打开软件界面。返回 'app'（应用模式窗口）或 'browser'（默认浏览器）。
    connected：一个函数，页面连上后台后返回真。Mac 上靠它判断窗口有没有真的打开，没打开就换一种办法。"""
    if os.environ.get('MINGBU_NO_BROWSER'):
        return 'none'
    if sys.platform == 'darwin' and connected:
        import threading
        threading.Thread(target=open_ui_mac, args=(url, connected), daemon=False).start()
        return 'app' if _mac_browsers() else 'browser'
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
