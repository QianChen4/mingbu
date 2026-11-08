"""
软件用到的各个位置。

从 v1.8 起，Windows 版和 Mac 版都按“版本文件夹”安装：

    明簿/                       ← 软件文件夹（HOME），整个拷到别的电脑就能用
      明簿.exe                  ← Windows 启动程序：读 versions/current.txt，运行对应版本
      versions/
        current.txt             ← 当前使用的版本，例如 v1.8.0
        v1.8.0/                 ← 一个完整的程序（app、web、start.py，Windows 还带 runtime 运行环境）
        v1.7.9/                 ← 上一个版本，留着可以退回
      data/                     ← 账套数据（更新时不动）
      backups/                  ← 备份

Mac 版的软件文件夹是 ~/Library/Application Support/财务记账软件（老版本就在这里，故意不改名），
由“明簿.app”里的启动脚本通过环境变量 MINGBU_HOME 告诉程序。

开发时直接运行仓库里的 start.py（没有 versions 文件夹），软件文件夹就是代码所在的文件夹，和老版本一样。
"""
import os
import sys

# 程序代码所在的文件夹（里面有 app、web、start.py）
CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VERSIONS = 'versions'
CURRENT_FILE = 'current.txt'


def _home():
    env = os.environ.get('MINGBU_HOME')
    if env:
        return os.path.abspath(env)
    parent = os.path.dirname(CODE_DIR)
    if os.path.basename(parent).lower() == VERSIONS:
        return os.path.dirname(parent)
    return CODE_DIR


HOME = _home()
# versioned：新的版本文件夹结构；flat：开发环境，或 v1.7 及以前的老结构（app、web 直接放在软件文件夹里）
LAYOUT = 'versioned' if os.path.normcase(os.path.dirname(CODE_DIR)) == os.path.normcase(os.path.join(HOME, VERSIONS)) \
    else 'flat'
VERSIONS_DIR = os.path.join(HOME, VERSIONS)

DATA_DIR = os.environ.get('RENTAL_DATA_DIR') or os.path.join(HOME, 'data')
BACKUP_DIR = os.environ.get('RENTAL_BACKUP_DIR') or os.path.join(HOME, 'backups')

IS_WINDOWS = os.name == 'nt'
IS_MAC = sys.platform == 'darwin'


def launcher():
    """重新打开软件用的启动程序。Windows 是软件文件夹里的“明簿.exe”；Mac 是 .app 里的启动脚本（由它通过环境变量告诉我们）。
    找不到时返回 None（开发环境），那就直接用当前的 Python 运行 start.py。"""
    env = os.environ.get('MINGBU_LAUNCHER')
    if env and os.path.exists(env):
        return env
    if IS_WINDOWS:
        for name in ('明簿.exe', '财务记账软件.exe'):
            p = os.path.join(HOME, name)
            if os.path.exists(p):
                return p
    return None
