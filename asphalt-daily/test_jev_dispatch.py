import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from jev_dispatch import route_for,execute_local
import live_watch

CONFIG={'executor':'jev_local','mode':'test','actual_send':False,'stop_before_save':True,'enabled_at':'2026-10-21T16:00:00+08:00'}
EVENT={'source':'daily','id':'test','version_key':'test-new-event','detected_at':'2026-10-21T08:00:01+00:00','sha256':'hash'}

class Routes(unittest.TestCase):
    def test_saved_and_uncertain_worker_results_are_preserved(self):
        config=dict(CONFIG,actual_send=True,stop_before_save=False,save_authorization='authorized-once')
        for status,saved in [('SCHEDULED',True),('UNKNOWN',None)]:
            with self.subTest(status=status),tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as directory:
                folder=Path(directory)
                def worker(*args,**kwargs):
                    (folder/'result.json').write_text(json.dumps({'status':status,'saved':saved,'scheduled_time':'2026-10-21 23:30'}),encoding='utf-8')
                    return SimpleNamespace(returncode=0)
                with patch('jev_dispatch.subprocess.run',side_effect=worker),patch('jev_dispatch.load_mode',return_value=config):
                    self.assertEqual(execute_local(EVENT,folder,lambda item,where:None),status)
                receipt=json.loads((folder/'execution-receipt.json').read_text(encoding='utf-8'))
                self.assertEqual(receipt['saved'],saved)

    def test_worker_result_is_test_not_scheduled(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as directory:
            folder=Path(directory)
            def worker(*args,**kwargs):
                (folder/'result.json').write_text(json.dumps({'status':'TIME_SET','saved':False,'scheduled_time':'2026-10-21 23:30'}),encoding='utf-8')
                return SimpleNamespace(returncode=0)
            with patch('jev_dispatch.subprocess.run',side_effect=worker) as run,patch('jev_dispatch.load_mode',return_value=CONFIG):
                self.assertEqual(execute_local(EVENT,folder,lambda item,where:None),'TEST_TIME_SET')
            receipt=json.loads((folder/'execution-receipt.json').read_text(encoding='utf-8'))
            self.assertFalse(receipt['saved'])
            self.assertTrue(any('jev_worker.py' in str(arg) for arg in run.call_args.args[0]))

    def test_new_event_uses_local(self):
        self.assertEqual(route_for(EVENT,CONFIG),'local_test')

    def test_old_event_does_not_replay(self):
        self.assertEqual(route_for(dict(EVENT,detected_at='2026-10-21T07:59:59+00:00'),CONFIG),'ignore')

    def test_test_cannot_enable_sending(self):
        with self.assertRaises(ValueError):route_for(EVENT,dict(CONFIG,actual_send=True))

    def test_save_requires_complete_single_use_authorization(self):
        with self.assertRaises(ValueError):
            route_for(EVENT,dict(CONFIG,actual_send=True,stop_before_save=False))
        self.assertEqual(route_for(EVENT,dict(CONFIG,actual_send=True,stop_before_save=False,save_authorization='authorized-once')),'local_test')

    def test_no_submit_cannot_route_to_legacy(self):
        with self.assertRaises(ValueError):route_for(EVENT,dict(CONFIG,executor='codex'))

    def test_scheduled_today_does_not_block_no_submit_test(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as directory:
            root=Path(directory)
            (root/'execution-mode.json').write_text(json.dumps(CONFIG),encoding='utf-8')
            job=root/'outbox/2026-10-21/job.json'
            job.parent.mkdir(parents=True)
            job.write_text('{"status":"scheduled"}',encoding='utf-8')
            original=job.read_bytes()
            with patch.object(live_watch,'HERE',root),patch('jev_dispatch.execute_local',return_value='TEST_TIME_SET') as local,patch.object(live_watch.shutil,'which',side_effect=AssertionError('旧Codex入口不应调用')):
                runs=root/'live-runs'
                self.assertEqual(live_watch._dispatch(EVENT,runs),'TEST_TIME_SET')
                self.assertEqual(live_watch._dispatch(EVENT,runs),'DUPLICATE_SKIPPED')
                local.assert_called_once()
            self.assertEqual(job.read_bytes(),original)

if __name__=='__main__':unittest.main()
