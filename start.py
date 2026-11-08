"""
明簿 —— 启动入口。
Windows：双击软件文件夹里的“明簿.exe”（老用户文件夹里叫“财务记账软件.exe”，同样可以用），
它会找到 versions/current.txt 里写的版本，用自带的 Python 运行那个版本里的 start.py。
Mac（测试用）：双击“明簿.app”。
开发时也可以在命令行运行：python3 start.py
  --no-browser  只启动后台服务，不打开界面（关掉页面后也不会自动退出）
界面用浏览器的“应用模式”打开（Edge / Chrome 的 --app 窗口，看起来像独立软件）；都没有时用默认浏览器。
所有界面窗口都关掉后，后台程序自动退出。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _quiet_output():
    """用 pythonw 启动（没有黑色窗口）时，把输出写进日志文件，方便排查问题。"""
    if sys.stdout is None or sys.stderr is None or '--log' in sys.argv:
        try:
            from app import paths
            os.makedirs(paths.DATA_DIR, exist_ok=True)
            log_file = os.path.join(paths.DATA_DIR, '运行日志.txt')
            # 日志太大时只保留后面一部分
            try:
                if os.path.getsize(log_file) > 2 * 1024 * 1024:
                    with open(log_file, 'rb') as f:
                        f.seek(-512 * 1024, 2)
                        tail = f.read()
                    with open(log_file, 'wb') as f:
                        f.write(tail)
            except OSError:
                pass
            log = open(log_file, 'a', encoding='utf-8', buffering=1)
            sys.stdout = sys.stderr = log
        except Exception:
            pass


def _desktop_shortcut():
    """Windows：在桌面创建“明簿”快捷方式，指向软件文件夹里的启动程序。
    每个软件文件夹只创建一次；软件文件夹换了位置（例如拷到别的电脑）会重新创建。"""
    if os.name != 'nt' or '--no-shortcut' in sys.argv:
        return
    from app import paths
    exe = paths.launcher()
    if not exe or not os.path.exists(exe):
        return
    flag = os.path.join(paths.DATA_DIR, '.shortcut_created')
    try:
        with open(flag, encoding='utf-8') as f:
            if os.path.normcase(f.read().strip()) == os.path.normcase(exe):
                return
    except OSError:
        pass
    try:
        import subprocess
        ps = ("$d=[Environment]::GetFolderPath('Desktop');"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d '明簿.lnk'));"
              "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.IconLocation='%s,0';$s.Save()") % (
            exe.replace("'", "''"), paths.HOME.replace("'", "''"), exe.replace("'", "''"))
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
                       creationflags=0x08000000, timeout=20)  # CREATE_NO_WINDOW
        os.makedirs(paths.DATA_DIR, exist_ok=True)
        with open(flag, 'w', encoding='utf-8') as f:
            f.write(exe)
    except Exception as e:
        print('创建桌面快捷方式失败：', e)


def _cleanup():
    """从老结构更新过来后，把老结构留下的程序文件移到 backups/旧版本程序 里（账套数据不动）。"""
    try:
        from app import updater
        moved = updater.cleanup_legacy()
        if moved:
            print('已把老版本留下的程序文件移到 backups/旧版本程序：', '、'.join(moved))
    except Exception as e:
        print('整理老版本文件失败：', e)


def _alert(msg):
    """没有黑色窗口时，用系统对话框显示错误。"""
    try:
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, '明簿', 0x10)
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.run(['osascript', '-e', 'display dialog "%s" with title "明簿" buttons {"好"} with icon stop'
                            % msg.replace('"', "'").replace('\\', '/')], timeout=120)
    except Exception:
        pass


if __name__ == '__main__':
    if sys.version_info < (3, 8):
        sys.exit('需要 Python 3.8 或更高版本')
    _quiet_output()
    try:
        _desktop_shortcut()
        _cleanup()
        from app.server import run
        port = int(os.environ.get('PORT', '8765'))
        run(port=port, open_browser='--no-browser' not in sys.argv)
    except Exception as e:
        import traceback
        traceback.print_exc()
        _alert('软件启动失败：%s\n\n详细信息已写入 data 文件夹里的“运行日志.txt”。\n'
               '常见原因：软件放在了没有写入权限的文件夹（如 C:\\Program Files），请移到 D 盘或“文档”里再打开。' % e)
        sys.exit(1)
