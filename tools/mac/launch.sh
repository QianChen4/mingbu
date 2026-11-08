#!/bin/bash
# 明簿.app 的启动脚本（Mac 测试版）。
# 程序和数据都放在 ~/Library/Application Support/财务记账软件（老版本就在这里，故意不改名）：
#   versions/current.txt、versions/v1.8.0/…、data/、backups/
# .app 里带了 Python（Apple 芯片和 Intel 各一份）和打包时的程序；boot.py 负责把程序放进上面的文件夹并运行。
# 在线更新只往 versions 里装新版本，不改 .app，所以更新后 .app 不用换。
HERE="$(cd "$(dirname "$0")/../Resources" && pwd)"
case "$(uname -m)" in
  arm64) PY="$HERE/python-arm64/bin/python3" ;;
  *)     PY="$HERE/python-x86_64/bin/python3" ;;
esac
export MINGBU_HOME="$HOME/Library/Application Support/财务记账软件"
export MINGBU_LAUNCHER="$0"
mkdir -p "$MINGBU_HOME/data"
# boot.py 会把后台程序分离出去，然后这个 .app 马上结束（不会一直挂着“正在运行”）。
# 再次双击时，新启动的程序发现后台已经在运行，就只打开一个新窗口。
"$PY" -I "$HERE/boot.py" "$HERE" --detach < /dev/null >> "$MINGBU_HOME/data/运行日志.txt" 2>&1
exit 0
