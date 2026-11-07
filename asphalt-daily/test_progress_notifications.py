import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import live_watch
import progress_strip
from jev_dispatch import execute_local

CONFIG={'executor':'jev_local','mode':'test','actual_send':False,'stop_before_save':True,'enabled_at':'2026-10-21T16:00:00+08:00'}
EVENT={'source':'daily','id':'example','version_key':'example-event','detected_at':'2026-10-21T08:00:01+00:00'}

class ProgressTests(unittest.TestCase):
    def test_repeated_duplicate_and_historical_events_never_announce(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as directory:
            root=Path(directory);runs=root/'live-runs';folder=runs/hashlib.sha256(EVENT['version_key'].encode()).hexdigest();folder.mkdir(parents=True)
            (root/'execution-mode.json').write_text(json.dumps(CONFIG),encoding='utf-8')
            (folder/'claim.json').write_text(json.dumps(EVENT),encoding='utf-8')
            callback=Mock()
            old=dict(EVENT,detected_at='2026-10-20T08:00:00+00:00')
            with patch.object(live_watch,'HERE',root),patch('jev_dispatch.execute_local') as worker,patch('result_notify.notify') as notifier:
                for _ in range(50):
                    self.assertEqual(live_watch.dispatch(EVENT,runs,on_start=callback),'DUPLICATE_SKIPPED')
                    self.assertEqual(live_watch.dispatch(old,runs,on_start=callback),'OLD_EVENT_IGNORED')
                callback.assert_not_called();worker.assert_not_called();notifier.assert_not_called()

    def test_only_real_worker_announces_after_staging(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as directory:
            folder=Path(directory);order=[]
            def stage(*_):order.append('stage')
            def announce(event):order.append('start')
            def worker(*_,**__):
                order.append('worker')
                (folder/'result.json').write_text(json.dumps({'status':'TIME_SET','saved':False}),encoding='utf-8')
                return SimpleNamespace(returncode=0)
            with patch('jev_dispatch.load_mode',return_value=CONFIG),patch('jev_dispatch.subprocess.run',side_effect=worker):
                self.assertEqual(execute_local(EVENT,folder,stage,on_start=announce),'TEST_TIME_SET')
            self.assertEqual(order,['stage','start','worker'])

    def test_preflight_failure_does_not_show_execution_strip(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as directory:
            callback=Mock()
            with patch('jev_dispatch.load_mode',return_value=CONFIG),patch('jev_dispatch.subprocess.run') as worker:
                result=execute_local(EVENT,Path(directory),Mock(side_effect=ValueError('stale input')),on_start=callback)
            self.assertEqual(result,'BLOCKED');callback.assert_not_called();worker.assert_not_called()

    def test_finished_worker_hides_while_notification_is_displaying(self):
        status={'status':'EXECUTING','last_event':EVENT,'last_result':'SCHEDULED'}
        with patch.object(progress_strip,'read_json',return_value={'active':False,'stage':'钉钉定时已保存'}):
            self.assertFalse(progress_strip.execution_visible(status))
        with patch.object(progress_strip,'read_json',return_value={'active':True,'stage':'正在粘贴'}):
            self.assertTrue(progress_strip.execution_visible(status))

    def test_idle_status_never_replays_saved_result(self):
        with patch.object(progress_strip,'read_json') as reader:
            self.assertFalse(progress_strip.execution_visible({'status':'LISTENING','last_result':'SCHEDULED','last_event':EVENT}))
            reader.assert_not_called()

if __name__=='__main__':unittest.main()
