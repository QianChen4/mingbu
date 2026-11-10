"""Mac 打开窗口：一种办法没打开（页面没连上后台）就换下一种。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from app import desktop  # noqa: E402


class MacOpenTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._spawn, self._browsers = desktop._spawn, desktop._mac_browsers
        desktop._spawn = lambda cmd: self.calls.append(cmd)
        desktop._mac_browsers = lambda: [('/Applications/Google Chrome.app',
                                          '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')]

    def tearDown(self):
        desktop._spawn, desktop._mac_browsers = self._spawn, self._browsers

    def test_first_way_works(self):
        ok = desktop.open_ui_mac('http://127.0.0.1:1/', lambda: True, wait=1)
        self.assertTrue(ok)
        self.assertEqual(self.calls[0][:4], ['/usr/bin/open', '-n', '-a', '/Applications/Google Chrome.app'])
        self.assertIn('--app=http://127.0.0.1:1/', self.calls[0])
        # 页面连上后把浏览器叫到最前面
        self.assertEqual(self.calls[1], ['/usr/bin/open', '-a', '/Applications/Google Chrome.app'])
        self.assertEqual(len(self.calls), 2)

    def test_falls_back_to_default_browser(self):
        # 前两种办法都没让页面连上，第三种（默认浏览器）才连上
        ok = desktop.open_ui_mac('http://127.0.0.1:1/', lambda: len(self.calls) >= 3, wait=1)
        self.assertTrue(ok)
        self.assertEqual(self.calls[1][0], '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        self.assertEqual(self.calls[2], ['/usr/bin/open', 'http://127.0.0.1:1/'])
        self.assertEqual(len(self.calls), 3)

    def test_nothing_works(self):
        self.assertFalse(desktop.open_ui_mac('http://127.0.0.1:1/', lambda: False, wait=1))
        self.assertEqual(len(self.calls), 3)


if __name__ == '__main__':
    unittest.main()
