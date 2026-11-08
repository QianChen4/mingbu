"""
明簿 —— 启动入口。
免安装版：双击“明簿.exe”（Windows）或“明簿.app”（Mac）。旧版安装的启动器名字是“财务记账软件”，同样可以用。
开发时也可以在命令行运行：python3 start.py
  --browser     不用独立窗口，用浏览器打开（也可以设置环境变量 RENTAL_BROWSER=1）
  --no-browser  只启动后台服务，不打开界面
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _quiet_output():
    """用 pythonw 启动（没有黑色窗口）时，把输出写进日志文件，方便排查问题。"""
    if sys.stdout is None or sys.stderr is None or '--log' in sys.argv:
        try:
            data_dir = os.environ.get('RENTAL_DATA_DIR') or os.path.join(HERE, 'data')
            os.makedirs(data_dir, exist_ok=True)
            log = open(os.path.join(data_dir, '运行日志.txt'), 'a', encoding='utf-8', buffering=1)
            sys.stdout = sys.stderr = log
        except Exception:
            pass


def _desktop_shortcut():
    """Windows：第一次运行时在桌面创建快捷方式（只创建一次）。"""
    if os.name != 'nt' or '--no-shortcut' in sys.argv:
        return
    # 软件改名为“明簿”；在线更新不替换启动器，老用户文件夹里仍是“财务记账软件.exe”
    exe = os.path.join(HERE, '明簿.exe')
    if not os.path.exists(exe):
        exe = os.path.join(HERE, '财务记账软件.exe')
    data_dir = os.environ.get('RENTAL_DATA_DIR') or os.path.join(HERE, 'data')
    flag = os.path.join(data_dir, '.shortcut_created')
    if not os.path.exists(exe) or os.path.exists(flag):
        return
    try:
        import subprocess
        ps = ("$d=[Environment]::GetFolderPath('Desktop');"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d '明簿.lnk'));"
              "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.IconLocation='%s,0';$s.Save()") % (exe, HERE, exe)
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
                       creationflags=0x08000000, timeout=20)  # CREATE_NO_WINDOW
        os.makedirs(data_dir, exist_ok=True)
        open(flag, 'w').close()
    except Exception as e:
        print('创建桌面快捷方式失败：', e)


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
    if '--window' in sys.argv:
        # 独立窗口子进程（由主进程启动，见 app/desktop.py）。标准输出留给和主进程通信，普通输出写到 stderr / 日志
        if sys.stderr is not None:
            sys.stdout = sys.stderr
        _quiet_output()
        try:
            from app.desktop import run_window
            sys.exit(run_window(sys.argv[sys.argv.index('--window') + 1]))
        except SystemExit:
            raise
        except BaseException as e:
            import traceback
            traceback.print_exc()
            try:
                sys.__stdout__.write('unavailable %s\n' % e)
                sys.__stdout__.flush()
            except Exception:
                pass
            sys.exit(3)
    _quiet_output()
    _desktop_shortcut()
    try:
        from app.server import run
        port = int(os.environ.get('PORT', '8765'))
        run(port=port, open_browser='--no-browser' not in sys.argv)
    except Exception as e:
        import traceback
        traceback.print_exc()
        _alert('软件启动失败：%s\n\n详细信息已写入 data 文件夹里的“运行日志.txt”。\n'
               '常见原因：软件放在了没有写入权限的文件夹（如 C:\\Program Files），请移到 D 盘或“文档”里再打开。' % e)
        sys.exit(1)
