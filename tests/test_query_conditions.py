"""查询条件：科目范围、级次范围、只统计已审核凭证、凭证号和金额范围。"""
import unittest

from tests import helpers  # noqa: F401
from app import db, ledger
from app.vouchers import save_voucher, audit_vouchers, list_vouchers


class QueryConditionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cid = db.create_company('查询条件测试', 2026, 1, standard='small', industry='car_rental')
        conn = db.connect(cls.cid)
        aux = conn.execute("SELECT id FROM aux_items WHERE type = '银行账户'").fetchone()[0]
        accts = ledger.account_map(conn)
        cls.rev = [k for k, a in accts.items() if k.startswith('5001') and a['is_leaf']][0]
        v1 = save_voucher(conn, {'date': '2026-01-05', 'lines': [
            {'summary': '收入', 'account': '1002', 'aux_id': aux, 'debit': 100, 'cf_item': 'CF01'},
            {'summary': '收入', 'account': cls.rev, 'credit': 100}]})
        save_voucher(conn, {'date': '2026-01-06', 'lines': [
            {'summary': '提现', 'account': '1001', 'debit': 300},
            {'summary': '提现', 'account': '1002', 'aux_id': aux, 'credit': 300}]})
        audit_vouchers(conn, [v1], True, '审核人')
        conn.commit()
        cls.conn = conn

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_account_range(self):
        r = ledger.balance_table(self.conn, '2026-01-01', '2026-01-31', code_from='1001', code_to='1002')
        self.assertEqual([x['code'] for x in r['rows']], ['1001', '1002'])
        self.assertTrue(r['filtered'])
        self.assertEqual((r['totals']['pd'], r['totals']['pc']), (400, 300))
        full = ledger.balance_table(self.conn, '2026-01-01', '2026-01-31')
        self.assertFalse(full['filtered'])
        self.assertTrue(full['balanced'])

    def test_level_range(self):
        r = ledger.balance_table(self.conn, '2026-01-01', '2026-01-31', level=2, level_from=2)
        self.assertEqual([x['code'] for x in r['rows']], [self.rev])

    def test_audited_only(self):
        with ledger.audited_only():
            r = ledger.balance_table(self.conn, '2026-01-01', '2026-01-31')
            self.assertEqual(r['totals']['pd'], 100)
            d = ledger.detail_ledger(self.conn, '1002', '2026-01-01', '2026-01-31')
            self.assertEqual(len([x for x in d['rows'] if x['type'] == 'line']), 1)
        r = ledger.balance_table(self.conn, '2026-01-01', '2026-01-31')   # 出了 with 恢复成统计全部
        self.assertEqual(r['totals']['pd'], 400)

    def test_voucher_number_and_amount(self):
        f = lambda **kw: len(list_vouchers(self.conn, '2026-01-01', '2026-01-31', **kw))
        self.assertEqual(f(), 2)
        self.assertEqual(f(no_from=2), 1)
        self.assertEqual(f(amt_from=200, amt_to=300), 1)
        self.assertEqual(f(amt_to=50), 0)


if __name__ == '__main__':
    unittest.main()
