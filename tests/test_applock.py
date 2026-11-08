import os
import unittest

from tests import helpers  # noqa: F401
from app import applock
from app.db import AppError


class AppLockTest(unittest.TestCase):
    def tearDown(self):
        if os.path.exists(applock.SECURITY_FILE):
            os.remove(applock.SECURITY_FILE)
        applock.lock_all()
        applock._fails.update(n=0, until=0.0)

    def test_no_password_always_unlocked(self):
        self.assertTrue(applock.token_valid(''))
        self.assertFalse(applock.status('')['enabled'])

    def test_set_unlock_recover_disable(self):
        r = applock.set_password('abcd', hint='四个字母')
        self.assertRegex(r['recovery_code'], r'^[A-Z0-9]{4}(-[A-Z0-9]{4}){3}$')
        self.assertTrue(applock.token_valid(r['token']))
        self.assertFalse(applock.token_valid('bad'))
        with self.assertRaises(AppError):
            applock.unlock('wrong')
        t = applock.unlock('abcd')['token']
        self.assertTrue(applock.token_valid(t))
        applock.lock_all()
        self.assertFalse(applock.token_valid(t))
        r2 = applock.recover(r['recovery_code'].lower(), 'efgh')
        self.assertTrue(applock.token_valid(r2['token']))
        with self.assertRaises(AppError):
            applock.recover(r['recovery_code'], 'zzzz')  # 旧恢复码作废
        applock._fails.update(n=0, until=0.0)
        applock.disable('efgh')
        self.assertFalse(applock.enabled())


if __name__ == '__main__':
    unittest.main()
