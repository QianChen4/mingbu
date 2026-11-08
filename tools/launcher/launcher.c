/*
 * 明簿 Windows 启动程序（明簿.exe）。Windows 7 / 10 / 11 通用，32 位。
 *
 * 软件文件夹的结构：
 *   明簿.exe
 *   versions\current.txt      当前版本，例如 v1.8.0
 *   versions\v1.8.0\          完整程序：app、web、start.py、runtime（自带的 Python 3.8）
 *   data\  backups\
 *
 * 做的事：读 current.txt 找到版本文件夹（找不到就用编号最大的 v 开头文件夹；再找不到就按老结构，
 * start.py 直接放在软件文件夹里），设置环境变量 MINGBU_HOME、MINGBU_LAUNCHER，
 * 用那个版本自带的 pythonw.exe 运行 start.py，然后自己退出。出错时弹框说明。
 *
 * 编译（在 Linux 上用 mingw）：见 tools/build.py，或
 *   i686-w64-mingw32-windres launcher.rc -O coff -o launcher.res
 *   i686-w64-mingw32-gcc -municode -mwindows -O2 -s launcher.c launcher.res -o 明簿.exe
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>

#define BIG 2048

static wchar_t home[BIG], self[BIG];

static int exists(const wchar_t *p) { return GetFileAttributesW(p) != INVALID_FILE_ATTRIBUTES; }

static void join(wchar_t *out, const wchar_t *a, const wchar_t *b) {
    lstrcpynW(out, a, BIG);
    size_t n = wcslen(out);
    if (n && out[n - 1] != L'\\') wcsncat(out, L"\\", BIG - wcslen(out) - 1);
    wcsncat(out, b, BIG - wcslen(out) - 1);
}

static void fail(const wchar_t *msg, const wchar_t *detail) {
    wchar_t buf[BIG * 2];
    _snwprintf(buf, BIG * 2 - 1, L"%s\n\n%s\n\n软件文件夹：%s", msg, detail ? detail : L"", home);
    buf[BIG * 2 - 1] = 0;
    MessageBoxW(NULL, buf, L"明簿", MB_ICONERROR | MB_OK);
}

/* "v1.10.2" -> 可比较的数字；不是 v+数字 的返回 -1 */
static long long vnum(const wchar_t *name) {
    if (name[0] != L'v' && name[0] != L'V') return -1;
    long long parts[4] = {0, 0, 0, 0};
    int i = 0, any = 0;
    for (const wchar_t *p = name + 1; *p; p++) {
        if (*p >= L'0' && *p <= L'9') { parts[i] = parts[i] * 10 + (*p - L'0'); any = 1; }
        else if (*p == L'.' && i < 3) i++;
        else return -1;
    }
    if (!any) return -1;
    return ((parts[0] * 1000 + parts[1]) * 1000 + parts[2]) * 1000 + parts[3];
}

/* 版本文件夹可用：有 start.py 和 runtime\pythonw.exe */
static int usable(const wchar_t *dir) {
    wchar_t a[BIG], b[BIG];
    join(a, dir, L"start.py");
    join(b, dir, L"runtime\\pythonw.exe");
    return exists(a) && exists(b);
}

static int read_current(wchar_t *out) {
    wchar_t path[BIG];
    join(path, home, L"versions\\current.txt");
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return 0;
    char buf[128] = {0};
    DWORD n = 0;
    ReadFile(h, buf, sizeof(buf) - 1, &n, NULL);
    CloseHandle(h);
    buf[n] = 0;
    char *s = buf;
    if ((unsigned char)s[0] == 0xEF && (unsigned char)s[1] == 0xBB && (unsigned char)s[2] == 0xBF) s += 3;
    while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n') s++;
    char *e = s + strlen(s);
    while (e > s && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\r' || e[-1] == '\n')) *--e = 0;
    if (!*s) return 0;
    wchar_t name[128];
    if (!MultiByteToWideChar(CP_UTF8, 0, s, -1, name, 128)) return 0;
    if (wcschr(name, L'\\') || wcschr(name, L'/') || wcsstr(name, L"..")) return 0;
    wchar_t dir[BIG];
    join(dir, home, L"versions");
    join(out, dir, name);
    return usable(out);
}

static int newest_version(wchar_t *out) {
    wchar_t pattern[BIG], vdir[BIG];
    join(vdir, home, L"versions");
    join(pattern, vdir, L"v*");
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    long long best = -1;
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
        long long v = vnum(fd.cFileName);
        if (v <= best) continue;
        wchar_t cand[BIG];
        join(cand, vdir, fd.cFileName);
        if (usable(cand)) { best = v; lstrcpynW(out, cand, BIG); }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return best >= 0;
}

int WINAPI wWinMain(HINSTANCE hi, HINSTANCE hp, LPWSTR cmd, int show) {
    (void)hi; (void)hp; (void)cmd; (void)show;
    GetModuleFileNameW(NULL, self, BIG);
    lstrcpynW(home, self, BIG);
    wchar_t *slash = wcsrchr(home, L'\\');
    if (slash) *slash = 0;

    wchar_t code[BIG], python[BIG], script[BIG];
    int versioned = read_current(code) || newest_version(code);
    if (versioned) {
        join(python, code, L"runtime\\pythonw.exe");
    } else {
        /* 老结构：start.py 直接在软件文件夹里 */
        lstrcpynW(code, home, BIG);
        const wchar_t *rts[] = {L"runtime\\pythonw.exe", L"runtime-x86\\pythonw.exe", L"runtime-x64\\pythonw.exe"};
        python[0] = 0;
        for (int i = 0; i < 3; i++) {
            wchar_t p[BIG];
            join(p, home, rts[i]);
            if (exists(p)) { lstrcpynW(python, p, BIG); break; }
        }
        if (!python[0]) {
            fail(L"找不到软件的程序文件（versions 文件夹）。", L"请把完整的软件压缩包重新解压，然后双击里面的“明簿.exe”。");
            return 1;
        }
    }
    join(script, code, L"start.py");
    if (!exists(script)) {
        fail(L"找不到 start.py，软件文件不完整。", L"请把完整的软件压缩包重新解压。");
        return 1;
    }

    SetEnvironmentVariableW(L"MINGBU_HOME", home);
    SetEnvironmentVariableW(L"MINGBU_LAUNCHER", self);

    wchar_t cmdline[BIG * 3];
    _snwprintf(cmdline, BIG * 3 - 1, L"\"%s\" \"%s\"", python, script);
    cmdline[BIG * 3 - 1] = 0;
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessW(python, cmdline, NULL, NULL, FALSE, CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
                        NULL, code, &si, &pi)) {
        wchar_t detail[256];
        _snwprintf(detail, 255, L"错误代码 %lu。可以试试把软件文件夹移到 D 盘或“文档”里再打开。", GetLastError());
        detail[255] = 0;
        fail(L"软件启动失败。", detail);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
