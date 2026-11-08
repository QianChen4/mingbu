"""账簿和报表按日期查询：整月日期查询和按期间查询结果一致；某一天、某几天也能查。"""
import unittest

from tests import helpers  # noqa: F401
from app import db, ledger, reports
from app.vouchers import save_voucher


def leaf(conn, prefix):
    rows = conn.execute("SELECT code FROM accounts WHERE code LIKE ? ORDER BY code", (prefix + '%',)).fetchall()
    codes = [r[0] for r in rows]
    return [c for c in codes if not any(o != c and o.startswith(c) for o in codes)][0]


class DateLedgerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cid = db.create_company('日期测试', 2026, 1, standard='small', industry='general')
        conn = db.connect(cls.cid)
        cls.bank, cls.rev = leaf(conn, '1002'), leaf(conn, '5001')
        cash = leaf(conn, '1001')
        bank_aux = conn.execute("SELECT id FROM aux_items WHERE type = '银行账户' ORDER BY code").fetchone()[0]
        for d, amt in (('2026-01-05', 10000), ('2026-01-12', 20000), ('2026-01-20', 30000), ('2026-02-03', 40000)):
            save_voucher(conn, {'date': d, 'lines': [
                {'summary': '收入', 'account': cls.bank, 'aux_id': bank_aux, 'debit': amt, 'cf_item': 'CF01'},
                {'summary': '收入', 'account': cls.rev, 'credit': amt}]})
        save_voucher(conn, {'date': '2026-01-15', 'lines': [
            {'summary': '提现', 'account': cash, 'debit': 5000},
            {'summary': '提现', 'account': cls.bank, 'aux_id': bank_aux, 'credit': 5000}]})
        conn.commit()
        cls.conn = conn

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_month_same_as_period(self):
        a = ledger.balance_table(self.conn, '2026-01-01', '2026-01-31')
        b = ledger.balance_table(self.conn, 202601, 202601)
        self.assertEqual(a['totals'], b['totals'])
        self.assertTrue(a['balanced'])

    def test_day_range(self):
        r = ledger.detail_ledger(self.conn, self.bank, '2026-01-05', '2026-01-20')
        amounts = [x['debit'] for x in r['rows'] if x.get('voucher')]
        self.assertEqual(sorted(a for a in amounts if a), [10000, 20000, 30000])
        one = ledger.detail_ledger(self.conn, self.bank, '2026-01-12', '2026-01-12')
        self.assertEqual([x['debit'] for x in one['rows'] if x.get('voucher')], [20000])

    def test_balance_table_format(self):
        r = ledger.balance_table(self.conn, '2026-01-01', '2026-01-31')
        row = next(x for x in r['rows'] if x['code'] == self.bank)
        self.assertEqual(row['end_dir'], '借')
        self.assertEqual(row['end'], 55000)
        self.assertTrue(row['path'].startswith('1002\\'))

    def test_balance_sheet_begin_first(self):
        bs = reports.balance_sheet(self.conn, '2026-01-16', '2026-01-31')
        self.assertEqual(bs['begin_label'], '期初余额')
        self.assertEqual(bs['end_label'], '期末余额')
        cash_row = next(x for x in bs['rows'] if x.get('key') == 'cash')
        self.assertEqual(cash_row['begin'], 30000)  # 1 月 15 日结束时：1万+2万（提现不改变货币资金合计）
        self.assertEqual(cash_row['end'], 60000)
        self.assertEqual(reports.balance_sheet(self.conn, '2026-01-01', '2026-01-31')['begin_label'], '年初余额')

    def test_income_statement_by_days(self):
        r = reports.income_statement(self.conn, '2026-01-05', '2026-01-12')
        self.assertEqual(r['label'], '2026-01-05 至 2026-01-12')
        self.assertEqual(r['year'], 2026)


if __name__ == '__main__':
    unittest.main()
