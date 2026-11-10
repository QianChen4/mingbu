# 软件版本号。每次发布新版本时修改这里（“设置 → 软件更新”页面和在线更新都用它比较新旧）。
# 注意：这个数字一变，推送到 main 分支后 GitHub 就会自动打包发布（见 .github/workflows/release.yml）。
VERSION = '1.8.0'

# 默认的在线更新地址（指向 latest.json）。留空表示不检查；也可以在“设置 → 软件更新”里填写。
# 原来的仓库 Rowinrain/caiwu-jizhang 所在账号已被封，从这一版起改为新仓库。
UPDATE_URL = 'https://github.com/QianChen4/mingbu/releases/latest/download/latest.json'
