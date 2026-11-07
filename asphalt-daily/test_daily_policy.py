import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import live_watch
from execution_policy import authorization_for
from jev_dispatch import route_for,execute_local

TZ=timezone(timedelta(hours=8))
NOW=datetime(2026,10,22,18,0,tzinfo=TZ)
CONFIG={'executor':'jev_local','mode':'daily','save_policy':'daily_once','actual_send':True,'stop_before_save':False,'enabled_at':'2026-10-21T17:43:11+08:00'}
EVENT={'source':'daily','id':'test-daily','category':'实验','date':'2026-10-22','version_key':'today-new-version','detected_at':'2026-10-22T10:00:00+00:00'}

class DailyTests(unittest.TestCase):
    def test_scroll_recovery_resumes_without_pasting_and_never_after_save(self):
        for paste_state,saved in [('confirmed_complete',False),('dispatched_outcome_unknown',False),('confirmed_complete',True)]:
            with self.subTest(paste_state=paste_state,saved=saved),tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as directory:
                root=Path(directory);runs=root/'live-runs';folder=runs/hashlib.sha256(EVENT['version_key'].encode()).hexdigest();folder.mkdir(parents=True)
                (root/'execution-mode.json').write_text(json.dumps(CONFIG),encoding='utf-8')
                (folder/'claim.json').write_text(json.dumps(EVENT),encoding='utf-8')
                (folder/'execution-receipt.json').write_text(json.dumps({'status':'BLOCKED','saved':False,'stage':'滚动到定时区域','reason':'滚动四次仍未找到可见定时入口'}),encoding='utf-8')
                (folder/'paste-state.json').write_text(json.dumps({'state':paste_state}),encoding='utf-8')
                if saved:(folder/'save-state.json').write_text('{}',encoding='utf-8')
                with patch.object(live_watch,'HERE',root),patch('jev_dispatch.local_now',return_value=NOW),patch('jev_dispatch.execute_local',return_value='SCHEDULED') as worker:
                    allowed=paste_state=='confirmed_complete' and not saved
                    self.assertEqual(live_watch._dispatch(EVENT,runs),'SCHEDULED' if allowed else 'DUPLICATE_SKIPPED')
                    if allowed:
                        self.assertIs(worker.call_args.kwargs['resume_after_paste'],True)
                    else:worker.assert_not_called()
                    self.assertEqual(live_watch._dispatch(EVENT,runs),'DUPLICATE_SKIPPED')

    def test_window_recovery_requires_no_prior_input_and_only_window_reads(self):
        for command,prior_action in [(['window','find'],None),(['mouse','click'],None),(['window','find'],'paste-state.json')]:
            with self.subTest(command=command,prior_action=prior_action),tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as directory:
                root=Path(directory);runs=root/'live-runs';folder=runs/hashlib.sha256(EVENT['version_key'].encode()).hexdigest();folder.mkdir(parents=True)
                (root/'execution-mode.json').write_text(json.dumps(CONFIG),encoding='utf-8')
                (folder/'claim.json').write_text(json.dumps(EVENT),encoding='utf-8')
                (folder/'execution-receipt.json').write_text(json.dumps({'status':'BLOCKED','saved':False,'stage':'定位钉钉','reason':'钉钉窗口未唯一识别'}),encoding='utf-8')
                (folder/'result.json').write_text(json.dumps({'calls':[{'command':command}]}),encoding='utf-8')
                if prior_action:(folder/prior_action).write_text('{}',encoding='utf-8')
                with patch.object(live_watch,'HERE',root),patch('jev_dispatch.local_now',return_value=NOW),patch('jev_dispatch.execute_local',return_value='SCHEDULED') as worker:
                    allowed=command==['window','find'] and prior_action is None
                    self.assertEqual(live_watch._dispatch(EVENT,runs),'SCHEDULED' if allowed else 'DUPLICATE_SKIPPED')
                    self.assertEqual(live_watch._dispatch(EVENT,runs),'DUPLICATE_SKIPPED')
                    self.assertEqual(worker.call_count,1 if allowed else 0)

    def test_authorization_rolls_by_day_not_per_upload(self):
        with patch('execution_policy.local_now',return_value=NOW):
            self.assertEqual(authorization_for(EVENT,CONFIG),'daily-20261022')
            self.assertEqual(authorization_for(dict(EVENT,version_key='changed'),CONFIG),'daily-20261022')
        with patch('execution_policy.local_now',return_value=NOW+timedelta(days=1)):
            self.assertEqual(authorization_for(dict(EVENT,date='2026-10-23'),CONFIG),'daily-20261023')

    def test_old_reports_are_not_scheduled_today(self):
        with patch('execution_policy.local_now',return_value=NOW),patch('jev_dispatch.local_now',return_value=NOW):
            self.assertEqual(route_for(EVENT,CONFIG),'local_test')
            self.assertEqual(route_for(dict(EVENT,date='2026-10-21'),CONFIG),'ignore')
            with self.assertRaises(ValueError):authorization_for(dict(EVENT,date='2026-10-21'),CONFIG)

    def test_today_saved_or_uncertain_prevents_new_worker(self):
        for status,expected in [('SCHEDULED','ALREADY_SCHEDULED'),('UNKNOWN','BLOCKED')]:
            with self.subTest(status=status),tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as directory:
                root=Path(directory);run=root/'live-runs/new';run.mkdir(parents=True)
                old=root/'live-runs/old';old.mkdir()
                (old/'execution-receipt.json').write_text(json.dumps({'status':status,'scheduled_time':'2026-10-22 23:30'}),encoding='utf-8')
                with patch('jev_dispatch.HERE',root),patch('jev_dispatch.load_mode',return_value=CONFIG),patch('jev_dispatch.local_now',return_value=NOW),patch('execution_policy.local_now',return_value=NOW),patch('jev_dispatch.subprocess.run') as worker:
                    self.assertEqual(execute_local(EVENT,run,lambda *_:None),expected)
                    worker.assert_not_called()

    def test_only_pre_desktop_authorization_failure_recovers_once(self):
        for prior_action in (None,'paste-state.json','save-state.json','worker.stdout.jsonl'):
            with self.subTest(prior_action=prior_action),tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as directory:
                root=Path(directory);runs=root/'live-runs';folder=runs/hashlib.sha256(EVENT['version_key'].encode()).hexdigest();folder.mkdir(parents=True)
                (root/'execution-mode.json').write_text(json.dumps(CONFIG),encoding='utf-8')
                (folder/'claim.json').write_text(json.dumps(EVENT),encoding='utf-8')
                (folder/'execution-receipt.json').write_text(json.dumps({'status':'BLOCKED','saved':False,'reason':'本次保存授权已使用'}),encoding='utf-8')
                if prior_action:(folder/prior_action).write_text('{}',encoding='utf-8')
                with patch.object(live_watch,'HERE',root),patch('jev_dispatch.local_now',return_value=NOW),patch('jev_dispatch.execute_local',return_value='SCHEDULED') as worker:
                    self.assertEqual(live_watch._dispatch(EVENT,runs),'SCHEDULED' if prior_action is None else 'DUPLICATE_SKIPPED')
                    self.assertEqual(live_watch._dispatch(EVENT,runs),'DUPLICATE_SKIPPED')
                    self.assertEqual(worker.call_count,1 if prior_action is None else 0)

if __name__=='__main__':unittest.main()
