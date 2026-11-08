"""明簿.app 的启动程序（Mac 测试版）：确定要运行的版本，然后运行它的 start.py。

1. .app 里带的程序（Resources/program/v版本号）比软件文件夹里的新，就复制过去并设为当前版本
   （第一次打开、或者换了新的 .app 时）；
2. 读 versions/current.txt，运行那个版本的 start.py（用 .app 里带的 Python）。
"""
import os
import re
import shutil
import sys

RES = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
HOME = os.environ['MINGBU_HOME']
VERSIONS = os.path.join(HOME, 'versions')
CURRENT = os.path.join(VERSIONS, 'current.txt')


def vtuple(v):
    return tuple(int(x) for x in re.findall(r'\d+', v or '0')[:4])


def current():
    try:
        with open(CURRENT, encoding='utf-8-sig') as f:
            v = f.read().strip()
        if re.fullmatch(r'v[\w.\-]+', v) and os.path.isfile(os.path.join(VERSIONS, v, 'start.py')):
            return v
    except OSError:
        pass
    return ''


def write_current(v):
    tmp = CURRENT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(v + '\n')
    os.replace(tmp, CURRENT)


def main():
    os.makedirs(VERSIONS, exist_ok=True)
    prog = os.path.join(RES, 'program')
    bundled = sorted((n for n in os.listdir(prog) if n.startswith('v')), key=vtuple)[-1:] if os.path.isdir(prog) else []
    cur = current()
    if bundled:
        b = bundled[0]
        if not cur or vtuple(b) > vtuple(cur):
            dest = os.path.join(VERSIONS, b)
            if not os.path.isfile(os.path.join(dest, 'start.py')):
                tmp = dest + '.part'
                shutil.rmtree(tmp, ignore_errors=True)
                shutil.copytree(os.path.join(prog, b), tmp)
                shutil.rmtree(dest, ignore_errors=True)
                os.rename(tmp, dest)
            write_current(b)
            cur = b
    if not cur:
        raise SystemExit('找不到程序文件，请重新下载明簿.app')
    code = os.path.join(VERSIONS, cur)
    os.chdir(code)
    os.execv(sys.executable, [sys.executable, '-I', os.path.join(code, 'start.py')])


if __name__ == '__main__':
    main()
