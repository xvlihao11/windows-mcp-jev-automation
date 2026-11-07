import unittest
import sys
from datetime import date
from unittest.mock import patch
import jev_dispatch
from report_day_policy import expected_report
from weekly_sections import split_weekly
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'wincli-trial'))
from continuous_trial import work_section_signal


class ReportDayPolicyTest(unittest.TestCase):
    def test_weekly_day_allows_only_weekly(self):
        day = date(2026, 11, 12)
        choice = {'date': '2026-11-12', 'kind': 'weekly', 'send_authorized': True}
        item = {'source': 'daily', 'date': '2026-11-12', 'category': '实验'}
        self.assertIsNone(expected_report(item, choice, day))
        item['category'] = '周报'
        self.assertEqual(expected_report(item, choice, day), 'weekly')

    def test_daily_day_and_fail_closed(self):
        day = date(2026, 11, 12)
        item = {'source': 'daily', 'date': '2026-11-12', 'category': '实验'}
        choice = {'date': '2026-11-12', 'kind': 'daily', 'send_authorized': True}
        self.assertEqual(expected_report(item, choice, day), 'daily')
        self.assertEqual(expected_report(item, None, day), 'daily')
        self.assertIsNone(expected_report(item, dict(choice, send_authorized=False), day))
        self.assertEqual(expected_report(item, dict(choice, date='2026-11-11', kind='weekly'), day), 'daily')
        self.assertIsNone(expected_report(dict(item, category=''), choice, day))
        self.assertIsNone(expected_report(dict(item, date='2026-11-11'), choice, day))
        self.assertIsNone(expected_report(dict(item, category='周报'), choice, day))
        self.assertIsNone(expected_report(dict(item, category='周报'), None, day))

    def test_yesterdays_weekly_selection_does_not_block_daily_router(self):
        now = jev_dispatch.local_now()
        from datetime import timedelta
        config = {'executor': 'jev_local', 'mode': 'daily', 'save_policy': 'daily_once',
                  'actual_send': True, 'stop_before_save': False,
                  'enabled_at': '2020-01-01T00:00:00+00:00'}
        item = {'source': 'daily', 'date': now.date().isoformat(), 'category': '实验',
                'detected_at': now.isoformat()}
        yesterday = {'date': (now.date()-timedelta(days=1)).isoformat(),
                     'kind': 'weekly', 'send_authorized': True}
        with patch.object(jev_dispatch, 'read_selection', return_value=yesterday):
            self.assertEqual(jev_dispatch.route_for(item, config), 'local_test')
            self.assertEqual(jev_dispatch.route_for(item, dict(config, mode='paused')), 'ignore')

    def test_live_router_selects_only_weekly_on_weekly_day(self):
        from datetime import datetime, timezone
        now = jev_dispatch.local_now()
        day = now.date().isoformat()
        config = {'executor': 'jev_local', 'mode': 'daily', 'save_policy': 'daily_once',
                  'actual_send': True, 'stop_before_save': False,
                  'enabled_at': '2020-01-01T00:00:00+00:00'}
        item = {'source': 'daily', 'date': day, 'category': '实验',
                'detected_at': datetime.now(timezone.utc).isoformat()}
        selection = {'date': day, 'kind': 'weekly', 'send_authorized': True}
        with patch.object(jev_dispatch, 'read_selection', return_value=selection):
            self.assertEqual(jev_dispatch.route_for(item, config), 'ignore')
            with self.assertRaisesRegex(ValueError, '双栏目'):
                jev_dispatch.route_for(dict(item, category='周报'), config)

    def test_weekly_fields_are_separate_and_required(self):
        body = '# 本周完成工作\n\n完成试验。\n\n# 下周工作计划\n\n复测样品。'
        self.assertEqual(split_weekly(body), ('完成试验。', '复测样品。'))
        with self.assertRaises(ValueError):
            split_weekly('# 本周完成工作\n\n完成试验。')
        with self.assertRaises(ValueError):
            split_weekly('# 本周完成工作\n\n完成试验。\n\n# 下周工作计划\n')

    def test_weekly_content_check_requires_weekly_section(self):
        tree = [{'type': 'Text', 'name': '本周完成工作'},
                {'type': 'Text', 'name': '已粘贴内容'},
                {'type': 'Text', 'name': '下周工作计划'}]
        self.assertTrue(work_section_signal(tree, 'weekly')['nonempty'])
        self.assertFalse(work_section_signal(tree, 'daily')['nonempty'])
        empty = [dict(n, name='请输入') if n['name'] == '已粘贴内容' else n for n in tree]
        self.assertFalse(work_section_signal(empty, 'weekly')['nonempty'])
        plan_tree = [{'type': 'Text', 'name': '下周工作计划'},
                     {'type': 'Text', 'name': '继续检测'},
                     {'type': 'Text', 'name': '图片'}]
        self.assertTrue(work_section_signal(plan_tree, 'weekly', 'plan')['nonempty'])
        plan_with_remark = [plan_tree[0], plan_tree[1],
                            {'type':'Text','name':'备注'},
                            {'type':'Text','name':'图片'}]
        self.assertTrue(work_section_signal(plan_with_remark, 'weekly', 'plan')['nonempty'])
        empty_plan = [plan_tree[0], {'type':'Text','name':'请输入'},
                      {'type':'Text','name':'备注'},
                      {'type':'Text','name':'这是备注，不是计划'},
                      {'type':'Text','name':'图片'}]
        self.assertFalse(work_section_signal(empty_plan, 'weekly', 'plan')['nonempty'])

    def test_export_work_sections_split_at_explicit_plan_heading(self):
        work = '# 本周工作周报\n\n## 一、检测\n\n已审核工作内容。'
        self.assertEqual(split_weekly(work+'\n\n## 下周工作计划\n\n已审核计划。'),
                         (work, '已审核计划。'))
        with self.assertRaises(ValueError):
            split_weekly(work+'\n\n## 下周工作计划\n')
        with self.assertRaises(ValueError):
            split_weekly(work+'\n\n## 下周工作计划\n计划\n## 下周工作计划\n重复')


if __name__ == '__main__':
    unittest.main()
