"""完整包的安装、切换版本、退回；以及老版本（v1.6.3）的更新程序也能认出新的完整包。"""
import io
import os
import re
import shutil
import tempfile
import unittest
import zipfile

from tests import helpers
from app import paths, updater


def make_package(version, with_runtime=False):
    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, 'w')
    pre = '明簿/versions/v%s/' % version
    z.writestr('明簿/明簿.exe', b'MZ fake launcher')
    z.writestr('明簿/versions/current.txt', 'v%s\n' % version)
    z.writestr('明簿/使用说明.md', '说明')
    for d, dirs, files in os.walk(os.path.join(helpers.ROOT, 'app')):
        dirs[:] = [x for x in dirs if x != '__pycache__']
        for fn in files:
            if fn.endswith('.pyc'):
                continue
            full = os.path.join(d, fn)
            rel = os.path.relpath(full, helpers.ROOT).replace(os.sep, '/')
            data = open(full, 'rb').read()
            if rel == 'app/__init__.py':
                data = re.sub(rb"VERSION = '[^']+'", ("VERSION = '%s'" % version).encode(), data)
            z.writestr(pre + rel, data)
    z.writestr(pre + 'web/index.html', '<html></html>')
    z.writestr(pre + 'start.py', 'print(1)')
    if with_runtime:
        z.writestr(pre + 'runtime/pythonw.exe', b'')
    z.close()
    return buf.getvalue()


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix='mingbu-home-')

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_install_and_keep_two_versions(self):
        for v in ('97.0.0', '98.0.0', '99.0.0'):
            r = updater.install_package(make_package(v), home=self.home, is_windows=False)
            self.assertEqual(r['new_version'], v)
            self.assertEqual(updater.current_version_name(self.home), 'v' + v)
        self.assertEqual(updater.installed_versions(self.home), ['v99.0.0', 'v98.0.0'])
        self.assertTrue(os.path.isfile(os.path.join(self.home, '使用说明.md')))

    def test_windows_replaces_launchers(self):
        open(os.path.join(self.home, '财务记账软件.exe'), 'wb').write(b'old')
        updater.install_package(make_package('97.0.0', True), home=self.home, is_windows=True, self_test=False)
        for n in ('明簿.exe', '财务记账软件.exe'):
            self.assertEqual(open(os.path.join(self.home, n), 'rb').read(), b'MZ fake launcher')

    def test_old_version_rejected(self):
        with self.assertRaises(Exception):
            updater.install_package(make_package('0.0.1'), home=self.home, is_windows=False)

    def test_bad_zip(self):
        with self.assertRaises(Exception):
            updater.install_package(b'not a zip', home=self.home, is_windows=False)

    def test_v163_updater_finds_program(self):
        """v1.6.3 的离线更新：找 app/server.py 旁边有 web/index.html 和 start.py 的位置。"""
        names = zipfile.ZipFile(io.BytesIO(make_package('97.0.0'))).namelist()
        found = None
        for n in names:
            if n.endswith('app/server.py'):
                prefix = n[:-len('app/server.py')]
                if prefix + 'web/index.html' in names and prefix + 'start.py' in names:
                    found = prefix
        self.assertEqual(found, '明簿/versions/v97.0.0/')


class PathsTest(unittest.TestCase):
    def test_dev_layout_is_flat(self):
        self.assertEqual(paths.LAYOUT, 'flat')


if __name__ == '__main__':
    unittest.main()
