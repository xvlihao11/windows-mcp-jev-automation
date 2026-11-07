import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from test_schedule_time import RecordedTrial

class SaveTests(unittest.TestCase):
    def test_no_submit_mode_cannot_reach_save(self):
        trial=RecordedTrial([])
        trial.event={'stop_before_save':True}
        with self.assertRaisesRegex(RuntimeError,'不保存'):
            trial.save_schedule_once('2026-11-05 23:30',True)
        self.assertEqual(trial.actions,[])

    def test_save_is_single_use_even_without_confirmation(self):
        target=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')+' 23:30'
        if datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M')>='23:30':
            self.skipTest('Scheduling target passed')
        button={'id':'save','name':'保 存','type':'Button','click':[200,200,0]}
        for confirmed in (True,False):
            with self.subTest(confirmed=confirmed),tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as root:
                root=Path(root)
                here=root/'trial';here.mkdir()
                frames=[[button],[{'type':'Text','name':'将于 '+target+' 发布'}] if confirmed else []]
                trial=RecordedTrial(frames)
                trial.event={'version_key':'event-one','save_authorization':'save-test-once'}
                trial.folder=root
                trial.save_dispatched=False
                trial.check_test_mode=lambda:None
                with patch('continuous_trial.HERE',here):
                    if confirmed:
                        result=trial.save_schedule_once(target,True)
                        self.assertEqual(result['status'],'SCHEDULED')
                        self.assertTrue(result['saved'])
                    else:
                        with self.assertRaises(RuntimeError):trial.save_schedule_once(target,True)
                    self.assertTrue(trial.save_dispatched)
                    self.assertEqual(len(trial.actions),1)
                    self.assertEqual(trial.actions[0],('ui','click','--window',123,'--element-id','save'))
                    self.assertEqual(json.loads((root/'save-authorizations/save-test-once.json').read_text())['version_key'],'event-one')
                    second=RecordedTrial([[button]])
                    second.event=trial.event;second.folder=root;second.check_test_mode=lambda:None
                    with self.assertRaises(FileExistsError):second.save_schedule_once(target,True)
                    self.assertEqual(second.actions,[])

if __name__=='__main__':unittest.main()
