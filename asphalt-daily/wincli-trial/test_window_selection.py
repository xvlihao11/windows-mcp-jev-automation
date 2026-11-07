import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from continuous_trial import main_dingtalk_window,Trial

class WindowProbe(Trial):
    def __init__(self,frames):
        self.frames=iter(frames)
        self.actions=[]
    def phase(self,stage):
        pass
    def call(self,*args):
        self.actions.append(args)
        return {'success':True,'launchStatus':'possibleHandoff'} if args[0]=='app' else {'windows':next(self.frames)}

class WindowTests(unittest.TestCase):
    def test_minimized_main_selected_over_toast(self):
        toast={'handle':'toast','title':'Form','className':'Qt51511QWindowToolSaveBits'}
        main={'handle':'main','title':'Custom company title','className':'StandardFrame_DingTalk','state':'minimized'}
        self.assertEqual(main_dingtalk_window([toast,main]),main)
    def test_two_main_frames_stop(self):
        with self.assertRaises(RuntimeError):
            main_dingtalk_window([{'className':'StandardFrame_DingTalk'},{'className':'StandardFrame_DingTalk'}])
    def test_toast_alone_is_not_main(self):
        with self.assertRaises(RuntimeError):main_dingtalk_window([{'title':'Form'}])
    def test_unique_legacy_frame(self):
        window={'handle':'legacy','title':'DingTalk'}
        self.assertEqual(main_dingtalk_window([window]),window)

    def test_watermark_and_shadow_are_not_main(self):
        for class_name in ('water_mask_wnd','DuiShadowWnd'):
            with self.subTest(class_name=class_name), self.assertRaises(RuntimeError):
                main_dingtalk_window([{'title':'','className':class_name}])

    def test_auxiliary_only_state_launches_once(self):
        main={'handle':'main','className':'StandardFrame_DingTalk','title':'i京博'}
        auxiliaries=[{'title':'','className':'water_mask_wnd'},
                     {'title':'','className':'DuiShadowWnd'}]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as directory:
            here=self.configured(directory)
            trial=WindowProbe([auxiliaries,auxiliaries,[main,*auxiliaries]])
            with patch('continuous_trial.HERE',here):
                self.assertEqual(trial.ensure_dingtalk_window(),main)
            self.assertEqual(sum(a[0]=='app' for a in trial.actions),1)

    def test_unknown_ambiguous_windows_still_stop(self):
        trial=WindowProbe([[{'title':'Other A'},{'title':'Other B'}]])
        with self.assertRaises(RuntimeError):
            trial.ensure_dingtalk_window()
        self.assertFalse(any(a[0]=='app' for a in trial.actions))

    def configured(self,directory):
        root=Path(directory);(root/'trial').mkdir();program=root/'installed-dingtalk.exe';program.touch()
        (root/'execution-mode.json').write_text(json.dumps({'dingtalk_executable':str(program)}),encoding='utf-8')
        return root/'trial'

    def test_tray_only_launches_once_and_rediscover_main(self):
        main={'handle':'main','className':'StandardFrame_DingTalk','title':'Main'}
        toast={'title':'Form'}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as directory:
            here=self.configured(directory)
            trial=WindowProbe([[],[],[toast],[main]])
            with patch('continuous_trial.HERE',here):self.assertEqual(trial.ensure_dingtalk_window(),main)
            self.assertEqual(sum(a[0]=='app' for a in trial.actions),1)

    def test_existing_main_does_not_launch(self):
        main={'handle':'main','className':'StandardFrame_DingTalk','title':'Main'}
        trial=WindowProbe([[main]])
        self.assertEqual(trial.ensure_dingtalk_window(),main)
        self.assertFalse(any(a[0]=='app' for a in trial.actions))

    def test_ambiguous_main_never_launches_another(self):
        main={'className':'StandardFrame_DingTalk','title':'Main'}
        trial=WindowProbe([[main,dict(main)]])
        with self.assertRaises(RuntimeError):trial.ensure_dingtalk_window()
        self.assertFalse(any(a[0]=='app' for a in trial.actions))

    def test_failed_handoff_stops_without_second_launch(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,ignore_cleanup_errors=True) as directory:
            here=self.configured(directory);trial=WindowProbe([[],[],[]])
            with patch('continuous_trial.HERE',here),patch('continuous_trial.time.monotonic',side_effect=[0,13]):
                with self.assertRaises(RuntimeError):trial.ensure_dingtalk_window()
            self.assertEqual(sum(a[0]=='app' for a in trial.actions),1)

if __name__=='__main__':unittest.main()
