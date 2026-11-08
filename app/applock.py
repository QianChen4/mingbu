"""
启动密码（v1.7.0 起）：整个软件一个密码，所有账套共用。

- 设置密码后，每次打开软件都要先输入密码；也可以随时点左下角“锁定”。
- 闲置自动锁定：一段时间没有操作就自动锁上（可以设置分钟数，0 表示不自动锁）。
- 设置密码时会给一个“恢复码”，忘记密码时用恢复码重设。恢复码只显示一次，请抄下来收好。
- 密码和恢复码都忘了：退出软件，删除 data 文件夹里的 security.json，再打开软件就没有密码了（账套数据不受影响）。

注意：这只是“门锁”，账套文件本身没有加密；能直接拿到 data 文件夹的人仍然可以复制账套文件。

实现：data/security.json 里只保存密码和恢复码的加盐哈希（PBKDF2-SHA256），不保存明文。
解锁后服务端发一个随机“通行证”（token），页面每次请求都带上；锁定时作废所有通行证。
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from .db import AppError, DATA_DIR

SECURITY_FILE = os.path.join(DATA_DIR, 'security.json')
ITERATIONS = 200000
RECOVERY_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # 去掉了容易看错的 I、O、0、1

_lock = threading.Lock()
_tokens = {}          # token -> 最后一次使用的时间
_fails = {'n': 0, 'until': 0.0}


def _hash(secret, salt, iterations=ITERATIONS):
    return hashlib.pbkdf2_hmac('sha256', secret.encode('utf-8'), bytes.fromhex(salt), iterations).hex()


def _load():
    try:
        with open(SECURITY_FILE, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get('hash') else None
    except (OSError, ValueError):
        return None


def _save(d):
    tmp = SECURITY_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SECURITY_FILE)


def enabled():
    return _load() is not None


def idle_minutes():
    d = _load()
    return int(d.get('idle_minutes', 10)) if d else 0


def _check(d, password):
    return hmac.compare_digest(_hash(password, d['salt'], d.get('iterations', ITERATIONS)), d['hash'])


def _new_recovery_code():
    raw = ''.join(secrets.choice(RECOVERY_ALPHABET) for _ in range(16))
    return '-'.join(raw[i:i + 4] for i in range(0, 16, 4))


def _norm_code(code):
    return ''.join(c for c in (code or '').upper() if c in RECOVERY_ALPHABET)


def _validate_password(pw):
    if not pw or len(pw) < 4:
        raise AppError('密码至少 4 位')
    if len(pw) > 64:
        raise AppError('密码太长了（最多 64 位）')


def _issue_token():
    t = secrets.token_hex(24)
    _tokens[t] = time.time()
    return t


def _throttle():
    now = time.time()
    if now < _fails['until']:
        raise AppError('输错次数太多，请 %d 秒后再试' % int(_fails['until'] - now + 1))


def _failed():
    _fails['n'] += 1
    if _fails['n'] >= 5:
        _fails['until'] = time.time() + 30
        _fails['n'] = 0


# ---------------------------------------------------------------- 给 server.py 用

def token_valid(token):
    """当前请求带的通行证是否有效。没设密码时永远有效。闲置超时的通行证自动作废。"""
    d = _load()
    if not d:
        return True
    with _lock:
        last = _tokens.get(token or '')
        if last is None:
            return False
        idle = int(d.get('idle_minutes', 10))
        if idle > 0 and time.time() - last > idle * 60:
            _tokens.pop(token, None)
            return False
        return True


def touch(token):
    """有操作时更新通行证的最后使用时间（心跳不算操作）。"""
    with _lock:
        if token in _tokens:
            _tokens[token] = time.time()


def status(token):
    d = _load()
    return {'enabled': bool(d), 'unlocked': token_valid(token),
            'idle_minutes': int(d.get('idle_minutes', 10)) if d else 0,
            'hint': d.get('hint', '') if d else ''}


def unlock(password):
    d = _load()
    if not d:
        return {'token': ''}
    with _lock:
        _throttle()
        if not _check(d, password or ''):
            _failed()
            raise AppError('密码不正确')
        _fails['n'] = 0
        return {'token': _issue_token()}


def lock_all():
    with _lock:
        _tokens.clear()


def set_password(new_password, old_password='', hint='', idle=None):
    """第一次设置，或修改密码（要输入原密码）。返回新的恢复码（只显示这一次）。"""
    _validate_password(new_password)
    d = _load()
    with _lock:
        if d:
            _throttle()
            if not _check(d, old_password or ''):
                _failed()
                raise AppError('原密码不正确')
        salt = secrets.token_hex(16)
        code = _new_recovery_code()
        rsalt = secrets.token_hex(16)
        nd = {'version': 1, 'iterations': ITERATIONS, 'salt': salt, 'hash': _hash(new_password, salt),
              'recovery_salt': rsalt, 'recovery_hash': _hash(_norm_code(code), rsalt),
              'idle_minutes': int(idle if idle is not None else (d or {}).get('idle_minutes', 10)),
              'hint': (hint or '').strip()[:40]}
        _save(nd)
        _tokens.clear()
        return {'recovery_code': code, 'token': _issue_token()}


def set_options(idle=None, hint=None):
    d = _load()
    if not d:
        raise AppError('还没有设置启动密码')
    if idle is not None:
        try:
            idle = int(idle)
        except (TypeError, ValueError):
            raise AppError('自动锁定的分钟数不正确')
        if idle < 0 or idle > 600:
            raise AppError('自动锁定的分钟数应在 0~600 之间（0 表示不自动锁定）')
        d['idle_minutes'] = idle
    if hint is not None:
        d['hint'] = (hint or '').strip()[:40]
    _save(d)
    return {'ok': True}


def disable(password):
    d = _load()
    if not d:
        return {'ok': True}
    with _lock:
        _throttle()
        if not _check(d, password or ''):
            _failed()
            raise AppError('密码不正确')
        os.remove(SECURITY_FILE)
        _tokens.clear()
    return {'ok': True}


def recover(code, new_password):
    """用恢复码重设密码。成功后旧恢复码作废，返回新的恢复码。"""
    d = _load()
    if not d:
        raise AppError('还没有设置启动密码')
    _validate_password(new_password)
    with _lock:
        _throttle()
        if not hmac.compare_digest(_hash(_norm_code(code), d['recovery_salt'], d.get('iterations', ITERATIONS)),
                                   d['recovery_hash']):
            _failed()
            raise AppError('恢复码不正确')
        _fails['n'] = 0
    d_idle, d_hint = d.get('idle_minutes', 10), d.get('hint', '')
    os.remove(SECURITY_FILE)
    return set_password(new_password, idle=d_idle, hint=d_hint)
