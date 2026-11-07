"""Read one exact report and publish CF_HTML without opening the agent UI."""
import argparse
import ctypes
from ctypes import wintypes
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
from agent_watch import DEFAULT_DB, fingerprint

HERE = Path(__file__).resolve().parent
AGENT = DEFAULT_DB.parent.parent


def clipboard_sequence():
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetClipboardSequenceNumber.restype = wintypes.DWORD
    return user.GetClipboardSequenceNumber()


def clipboard_reusable(path, content_hash, expected_sequence):
    if not path or expected_sequence is None:
        return False
    staged = Path(path).resolve()
    if not staged.is_relative_to(HERE.parent.resolve()):
        raise ValueError('Staged report outside workspace')
    if hashlib.sha256(staged.read_text(encoding='utf-8-sig').encode()).hexdigest() != content_hash:
        raise ValueError('Staged report fingerprint mismatch')
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    before = clipboard_sequence()
    formats = user.IsClipboardFormatAvailable(13) and user.IsClipboardFormatAvailable(user.RegisterClipboardFormatW('HTML Format')) and user.IsClipboardFormatAvailable(user.RegisterClipboardFormatW('CodexDailyReport:'+content_hash))
    return bool(formats and before and before == expected_sequence and clipboard_sequence() == before)


def node_runtime():
    config = HERE / 'runtime-paths.json'
    if config.exists():
        path = Path(json.loads(config.read_text(encoding='utf-8-sig'))['node_executable'])
        if path.is_absolute() and path.is_file():
            return str(path)
    found = shutil.which('node')
    if found:
        return found
    raise FileNotFoundError('Node runtime unavailable; check asphalt-daily/runtime-paths.json')


def cf_html(fragment):
    prefix = b'<html><body><!--StartFragment-->'
    suffix = b'<!--EndFragment--></body></html>'
    body = fragment.encode('utf-8')
    template = 'Version:1.0\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\nStartFragment:{:010d}\r\nEndFragment:{:010d}\r\n'
    start = len(template.format(0, 0, 0, 0).encode('ascii'))
    header = template.format(start, start + len(prefix) + len(body) + len(suffix), start + len(prefix), start + len(prefix) + len(body)).encode('ascii')
    return header + prefix + body + suffix + b'\0'


def prepare(rid, expected, source='library', staged_path=None, renderer_path=None, expected_content_hash=None):
    if source == 'daily' and staged_path and renderer_path:
        root = HERE.parent.resolve()
        staged = Path(staged_path).resolve()
        renderer = Path(renderer_path).resolve()
        if not staged.is_relative_to(root) or not renderer.is_relative_to(root):
            raise ValueError('Staged report outside workspace')
        text = staged.read_text(encoding='utf-8-sig')
        if not text or hashlib.sha256(text.encode('utf-8')).hexdigest() != expected_content_hash:
            raise ValueError('Staged report fingerprint mismatch')
        result = subprocess.run([node_runtime(), str(HERE / 'render_clipboard.cjs'), str(renderer)], input=text, text=True, encoding='utf-8', capture_output=True, check=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return json.loads(result.stdout), {'report_id': rid, 'source': 'staged_personal_daily', 'content_sha256': expected_content_hash}
    with closing(sqlite3.connect(DEFAULT_DB.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM daily WHERE id=?" if source == 'daily' else "SELECT * FROM library WHERE id=? AND doc_type='report'", (rid,)).fetchone()
    if row is None:
        raise ValueError('Report not found')
    row = dict(row)
    fields = ('date', 'author', 'category', 'narrative', 'polished', 'blocks') if source == 'daily' else ('title', 'author', 'category', 'text', 'filepath', 'fmt')
    payload = {k: row.get(k) for k in fields}
    if fingerprint(payload) != expected:
        raise ValueError('Report version changed')
    if source == 'daily':
        row.update(fmt='md', text=row.get('polished') or row.get('narrative') or '', filepath='')
    if row['fmt'] != 'md':
        raise ValueError('Only the existing Markdown rich-copy format is supported')
    text = row.get('text') or ''
    location = row.get('filepath')
    if location:
        path = Path(location)
        if not path.is_absolute():
            path = AGENT / path
        path = path.resolve()
        if not path.is_relative_to(AGENT.resolve()):
            raise ValueError('Report file outside agent root')
        text = path.read_text(encoding='utf-8-sig')
        if row.get('text') and text != row['text']:
            raise ValueError('Stored file and approved record differ')
    if not text:
        raise ValueError('Empty report')
    result = subprocess.run([node_runtime(), str(HERE / 'render_clipboard.cjs'), str(AGENT / 'web/js/markdown.js')], input=text, text=True, encoding='utf-8', capture_output=True, check=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    rendered = json.loads(result.stdout)
    return rendered, {'report_id': rid, 'source': 'file' if location else 'stored_report_text', 'content_sha256': hashlib.sha256(text.encode()).hexdigest()}


def publish(html, plain, content_hash=None):
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user.CreateWindowExW.restype = wintypes.HWND
    user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user.OpenClipboard.argtypes = [wintypes.HWND]
    user.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user.SetClipboardData.restype = wintypes.HANDLE
    user.DestroyWindow.argtypes = [wintypes.HWND]
    kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = wintypes.HANDLE
    kernel.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HANDLE]
    kernel.GlobalFree.argtypes = [wintypes.HANDLE]
    hwnd = user.CreateWindowExW(0, 'STATIC', 'ReportClipboard', 0, 0, 0, 0, 0, None, None, None, None)
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    allocated = []
    try:
        formats = [(user.RegisterClipboardFormatW('HTML Format'), cf_html(html)), (13, plain.encode('utf-16-le') + b'\0\0')]
        if content_hash:
            formats.append((user.RegisterClipboardFormatW('CodexDailyReport:'+content_hash), b'1\0'))
        for fmt, data in formats:
            handle = kernel.GlobalAlloc(2, len(data))
            if not handle:
                raise MemoryError('Clipboard allocation failed')
            allocated.append([fmt, handle])
            ptr = kernel.GlobalLock(handle)
            if not ptr:
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.memmove(ptr, data, len(data))
            kernel.GlobalUnlock(handle)
        for _ in range(10):
            if user.OpenClipboard(hwnd):
                break
            time.sleep(.05)
        else:
            raise RuntimeError('Clipboard busy')
        try:
            if not user.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
            for item in allocated:
                if not user.SetClipboardData(item[0], item[1]):
                    raise ctypes.WinError(ctypes.get_last_error())
                item[1] = None  # Ownership transferred to Windows.
        finally:
            user.CloseClipboard()
    finally:
        for _, handle in allocated:
            if handle:
                kernel.GlobalFree(handle)
        user.DestroyWindow(hwnd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--id', required=True)
    parser.add_argument('--expected-hash', required=True)
    parser.add_argument('--source', choices=('library', 'daily'), default='library')
    parser.add_argument('--staged-path')
    parser.add_argument('--renderer-path')
    parser.add_argument('--content-sha256')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--expected-sequence', type=int)
    args = parser.parse_args()
    if not args.prepare_only and clipboard_reusable(args.staged_path, args.content_sha256, args.expected_sequence):
        print(json.dumps({'status':'RICH_CLIPBOARD_READY','report_id':args.id,'reused':True},ensure_ascii=False))
        raise SystemExit(0)
    rendered, receipt = prepare(args.id, args.expected_hash, args.source, args.staged_path, args.renderer_path, args.content_sha256)
    if not args.prepare_only:
        publish(rendered['html'], rendered['plain'], receipt.get('content_sha256'))
    print(json.dumps(dict(receipt, status='PREPARED' if args.prepare_only else 'RICH_CLIPBOARD_READY'), ensure_ascii=False))
