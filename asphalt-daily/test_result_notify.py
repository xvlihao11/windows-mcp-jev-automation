import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import result_notify


class NotificationTest(unittest.TestCase):
    def test_terminal_classification(self):
        self.assertIn('已保存', result_notify.message('SCHEDULED')[0])
        self.assertIn('未完成', result_notify.message('BLOCKED')[0])
        self.assertIn('待确认', result_notify.message('UNKNOWN_TIMEOUT')[0])

    def test_duplicate_only_notifies_once_and_keeps_reason(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent, ignore_cleanup_errors=True) as temp:
            root = Path(temp)
            event = {'version_key': 'report:v1', 'id': 'test', 'title': 'Test'}
            with patch.object(result_notify, 'HERE', root), patch.object(result_notify.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as runner:
                result_notify.notify(event, {'status': 'BLOCKED', 'reason': '复制失败'})
                second = result_notify.notify(event, {'status': 'BLOCKED', 'reason': '复制失败'})
                self.assertEqual(second['status'], 'DUPLICATE_SKIPPED')
                self.assertEqual(runner.call_count, 1)
                self.assertIn('复制失败', (root / '最新执行结果.txt').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
