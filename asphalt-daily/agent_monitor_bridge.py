"""Imported by agent server startup; starts one hidden local watcher."""
import os
import sys
from pathlib import Path
import subprocess
import threading
import time

ROOT = Path(os.environ['DAILY_WORKFLOW_ROOT']).resolve()
PYTHON = Path(sys.executable)
_process = None
_lock = threading.Lock()
_last_attempt = 0


def ensure_started():
    global _process, _last_attempt
    if (ROOT / 'asphalt-daily/AUTOMATION_DISABLED').exists():
        return
    with _lock:
        if _process is not None and _process.poll() is None:
            return
        if time.monotonic() - _last_attempt < 30:
            return
        _last_attempt = time.monotonic()
        script = ROOT / 'asphalt-daily/live_watch.py'
        if not script.exists() or not PYTHON.exists():
            raise RuntimeError('Daily watcher installation unavailable')
        env = dict(os.environ)
        # Codex launcher location is stable across individual CLI build updates.
        codex_root = Path(os.environ.get('LOCALAPPDATA', '')) / 'OpenAI/Codex/bin'
        candidates = sorted(codex_root.glob('*/codex.exe'), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            env['PATH'] = str(candidates[0].parent) + os.pathsep + env.get('PATH', '')
        with (ROOT / 'asphalt-daily/agent-bound-watch.log').open('ab', buffering=0) as log:
            _process = subprocess.Popen([str(PYTHON), str(script), '--parent-pid', str(os.getpid())], cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
