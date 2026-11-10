"""2026-11 检查后修的几处：年中启用账套的年初余额、车辆处置、备份保留、日期校验、更新地址。"""
import os
import unittest

from tests import helpers  # noqa: F401
from app import db, reports, updater, vehicles as VH
from app.db import AppError
from app.vouchers import save_voucher, save_opening


def leaf(conn, prefix):
    codes = [r[0] for r in conn.execute("SELECT code FROM accounts WHERE code LIKE ? ORDER BY code", (prefix + '%',))]
    return [c for c in codes if not any(o != c and o.startswith(c) for o in codes)][0]


class AuditFixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cid = db.create_company('检查修复测试', 2026, 7, standard='small', industry='car_rental')
        conn = db.connect(cls.cid)
        km = db.company_profile(conn)['keymap']
        cls.bank, cls.cap, cls.rev = leaf(conn, km['bank']), leaf(conn, km['capital']), leaf(conn, km['main_rev'])
        cls.profit = km['profit']
        cls.aux = conn.execute("SELECT id FROM aux_items WHERE type = '银行账户'").fetchone()[0]
        save_opening(conn, [
            {'account_code': cls.bank, 'aux_id': cls.aux, 'year_begin': 10000000, 'ytd_debit': 5000000, 'ytd_credit': 2000000},
            {'account_code': cls.cap, 'year_begin': -10000000},
            {'account_code': cls.profit, 'ytd_debit': 2000000, 'ytd_credit': 5000000},
        ])
        conn.commit()
        cls.conn = conn

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def lines(self, amt):
        return [{'summary': '收入', 'account': self.bank, 'aux_id': self.aux, 'debit': amt, 'cf_item': 'CF01'},
                {'summary': '收入', 'account': self.rev, 'credit': amt}]

    def test_year_begin_for_mid_year_start(self):
        bs = reports.balance_sheet(self.conn, '2026-01-01', '2026-12-31')
        cash = next(r for r in bs['rows'] if r['key'] == 'cash')
        self.assertEqual(bs['begin_label'], '年初余额')
        self.assertEqual(cash['begin'], 10000000)
        self.assertEqual(bs['checks']['begin_diff'], 0)
        bs = reports.balance_sheet(self.conn, '2026-07-01', '2026-07-31')
        cash = next(r for r in bs['rows'] if r['key'] == 'cash')
        self.assertEqual(bs['begin_label'], '期初余额')
        self.assertEqual(cash['begin'], 13000000)

    def test_strict_dates(self):
        with self.assertRaises(AppError):
            save_voucher(self.conn, {'date': '2026-07-32', 'lines': self.lines(100)})
        with self.assertRaises(AppError):
            save_voucher(self.conn, {'date': '2026-09-31', 'lines': self.lines(100)})
        vid = save_voucher(self.conn, {'date': '2026-7-5', 'lines': self.lines(100)})
        self.assertEqual(self.conn.execute('SELECT date FROM vouchers WHERE id = ?', (vid,)).fetchone()[0], '2026-07-05')

    def test_dispose_only_after_voucher_saved(self):
        vid = VH.save_vehicle(self.conn, {'plate': '测A0001', 'purchase_date': '2026-07-02', 'original': 5000000})
        draft = VH.dispose(self.conn, {'id': vid, 'date': '2026-08-20', 'price': 3000000, 'cash_account': self.bank,
                                       'cash_aux': self.aux, 'vat_mode': '不计税'})
        status = lambda: self.conn.execute('SELECT status FROM vehicles WHERE id = ?', (vid,)).fetchone()[0]
        self.assertEqual(status(), '在用')          # 只有草稿，车辆还在用
        self.assertEqual(draft['dispose_vehicle_id'], vid)
        lines = [dict(l, account=l['account']) for l in draft['lines']]
        save_voucher(self.conn, {'date': draft['date'], 'lines': lines, 'dispose_vehicle_id': vid})
        self.assertEqual(status(), '已处置')
        with self.assertRaises(AppError):           # 不能重复处置
            save_voucher(self.conn, {'date': draft['date'], 'lines': lines, 'dispose_vehicle_id': vid})

    def test_backup_pruning_keeps_manual(self):
        folder = db._backup_folder(self.cid)
        for i in range(70):
            open(os.path.join(folder, '202501%02d-0000%02d-每日自动.db' % (i % 28 + 1, i)), 'w').close()
        for i in range(5):
            open(os.path.join(folder, '20240101-0000%02d-手动.db' % i), 'w').close()
        for i in range(25):
            open(os.path.join(folder, '20240201-0000%02d-结账前.db' % i), 'w').close()
        db._prune_backups(self.cid)
        names = os.listdir(folder)
        self.assertEqual(sum('每日自动' in n for n in names), 60)
        self.assertEqual(sum('手动' in n for n in names), 5)
        self.assertEqual(sum('结账前' in n for n in names), 20)

    def test_update_url_https_only(self):
        with self.assertRaises(AppError):
            updater.set_update_url('http://example.com/latest.json')
        with self.assertRaises(AppError):
            updater.check_online('http://example.com/latest.json')
        updater.set_update_url('https://example.com/latest.json')
        self.assertEqual(updater.get_update_url(), 'https://example.com/latest.json')
        updater.set_update_url('')


if __name__ == '__main__':
    unittest.main()
