import unittest

from tests import helpers  # noqa: F401
from app import charts, db


class IndustryTest(unittest.TestCase):
    def test_all_industries_build(self):
        for std in ('small', 'enterprise'):
            for code in charts.INDUSTRY_ORDER:
                b = charts.build(std, code)
                self.assertTrue(b['accounts'], code)
                self.assertIn(b['vat_mode'], ('general', 'simple', 'mixed'), code)

    def test_names_and_default(self):
        names = {o['code']: o['name'] for o in charts.options()['industries']}
        self.assertEqual(names['passenger'], '旅客运输（一般计税）')
        self.assertEqual(names['passenger_simple'], '公路旅客运输（简易计税）')
        self.assertEqual(names['passenger_mixed'], '公路旅客运输（简易+一般计税）')
        self.assertEqual(names['auto_repair'], '汽车修理修配')
        self.assertEqual(charts.options()['default_industry'], 'passenger_mixed')

    def test_new_company_defaults_to_mixed(self):
        cid = db.create_company('默认行业测试', 2026, 1)
        conn = db.connect(cid)
        try:
            prof = db.company_profile(conn)
            self.assertEqual(prof['industry'], 'passenger_mixed')
            self.assertEqual(prof['vat_mode'], 'mixed')
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
