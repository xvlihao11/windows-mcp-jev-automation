import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from fast_clipboard import FastClipboard, PasteGuard


class GuardTests(unittest.TestCase):
    def test_not_ready_blocks(self):
        g=PasteGuard()
        with self.assertRaises(RuntimeError):g.dispatch(False)
        self.assertEqual(g.state,'not_dispatched')

    def test_unknown_paste_cannot_repeat(self):
        g=PasteGuard();g.dispatch(True)
        with self.assertRaises(RuntimeError):g.dispatch(True)

    def test_confirmed_paste_cannot_repeat(self):
        g=PasteGuard();g.dispatch(True);g.confirm()
        with self.assertRaises(RuntimeError):g.dispatch(True)

    @patch('fast_clipboard.clipboard_sequence',return_value=12)
    @patch('fast_clipboard.clipboard_reusable',side_effect=[False,True,True,False,True])
    @patch('fast_clipboard.publish')
    @patch('fast_clipboard.prepare',return_value=({'html':'<p>example</p>','plain':'example'},{}))
    def test_changed_clipboard_restores_without_rerender(self,render,publish,reusable,sequence):
        e={'id':'test','sha256':'test','staged_report_path':'staged','staged_renderer_path':'renderer','staged_content_sha256':'hash'}
        c=FastClipboard(e)
        try:
            c.start();c.ensure_ready();c.ensure_ready()
            self.assertEqual(render.call_count,1)
            self.assertEqual(publish.call_count,2)
        finally:c.close()


if __name__=='__main__':unittest.main()
