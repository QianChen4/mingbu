#!/bin/bash
# 明簿.app 的启动脚本（Mac 测试版）。
# Mac 版和 Windows 版一样是一个文件夹，程序和数据都在这个文件夹里：
#   明簿/明簿.app            ← 只负责启动（带 Python），更新时不换
#   明簿/versions/v1.8.0/    ← 程序（网页和 Python 代码），更新时只换这里
#   明簿/data/、backups/      ← 账套数据和备份
# boot.py 找到软件文件夹后运行程序。
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
# 只带苹果芯片（M1 及以后）的 Python；Intel 芯片的 Mac 不再支持。
PY="$RES/python-arm64/bin/python3"
if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null)" != "1" ]; then
  /usr/bin/osascript -e 'display dialog "这个版本只支持苹果芯片（M1 及以后）的 Mac，这台电脑是 Intel 芯片，无法运行。" with title "明簿" buttons {"好"} with icon stop' > /dev/null 2>&1
  exit 0
fi
export MINGBU_LAUNCHER="$0"
# boot.py 会把后台程序分离出去，然后这个 .app 马上结束（不会一直挂着“正在运行”，避免“无法打开 -47”）。
"$PY" -I "$RES/boot.py" --detach < /dev/null > /dev/null 2>&1
exit 0
