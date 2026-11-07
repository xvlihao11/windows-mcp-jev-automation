"""One local Windows notification per terminal report result; no model call."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone, timedelta

HERE = Path(__file__).resolve().parent


def display(path):
    record = json.loads(path.read_text(encoding='utf-8'))
    user = ctypes.WinDLL('user32', use_last_error=True)
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    class GUID(ctypes.Structure):
        _fields_ = [('a', wintypes.DWORD), ('b', wintypes.WORD), ('c', wintypes.WORD), ('d', ctypes.c_ubyte * 8)]
    class NID(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('hWnd', wintypes.HWND), ('uID', wintypes.UINT), ('uFlags', wintypes.UINT), ('uCallbackMessage', wintypes.UINT), ('hIcon', wintypes.HICON), ('szTip', wintypes.WCHAR * 128), ('dwState', wintypes.DWORD), ('dwStateMask', wintypes.DWORD), ('szInfo', wintypes.WCHAR * 256), ('uTimeout', wintypes.UINT), ('szInfoTitle', wintypes.WCHAR * 64), ('dwInfoFlags', wintypes.DWORD), ('guidItem', GUID), ('hBalloonIcon', wintypes.HICON)]
    user.CreateWindowExW.restype = wintypes.HWND
    user.CreateWindowExW.argtypes = [wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.HWND,wintypes.HMENU,wintypes.HINSTANCE,wintypes.LPVOID]
    user.DestroyWindow.argtypes = [wintypes.HWND]
    user.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user.LoadIconW.restype = wintypes.HICON
    shell.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NID)]
    shell.Shell_NotifyIconW.restype = wintypes.BOOL
    hwnd = user.CreateWindowExW(0, 'STATIC', '日报结果通知', 0,0,0,0,0,None,None,None,None)
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    data = NID()
    data.cbSize = ctypes.sizeof(data)
    data.hWnd = hwnd
    data.uID = 1
    data.uFlags = 2 | 4 | 16  # ICON, TIP, INFO
    data.hIcon = user.LoadIconW(None, 32512)
    data.szTip = '日报流程结果'
    data.szInfoTitle = record['title'][:63]
    data.szInfo = record['message'][:255]
    data.dwInfoFlags = 1
    data.uTimeout = 10000
    added = False
    try:
        if not shell.Shell_NotifyIconW(0, ctypes.byref(data)):
            raise ctypes.WinError(ctypes.get_last_error())
        added = True
        print('NOTIFICATION_REQUESTED', flush=True)
        until = time.monotonic() + 10
        msg = wintypes.MSG()
        while time.monotonic() < until:
            while user.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                user.TranslateMessage(ctypes.byref(msg))
                user.DispatchMessageW(ctypes.byref(msg))
            time.sleep(.1)
    finally:
        if added:
            shell.Shell_NotifyIconW(2, ctypes.byref(data))
        user.DestroyWindow(hwnd)


def message(status, reason='', scheduled_time=None):
    if status=='TEST_TIME_SET':
        return '日报测试完成 · 未保存', '新程序已核实'+(scheduled_time or '今天23:30')+'；未创建排程，不会因这次测试发送。'
    if status == 'SCHEDULED':
        return '日报定时已保存', '钉钉已受理原生定时：' + (scheduled_time or '23:30') + '。尚不代表到时已发送。'
    if status == 'ALREADY_SCHEDULED':
        return '日报未重复提交', '当天已有排程，本次未新增。'
    if status == 'BLOCKED':
        return '日报处理未完成', reason or '执行遇到阻断，请查看本地结果。'
    if status in ('UNKNOWN', 'UNKNOWN_TIMEOUT'):
        return '日报结果待确认', reason or '尚未确认保存成功，未自动重试。'
    return '日报执行出错', reason or '后台执行异常，请查看本地结果。'


def notify(event, outcome, folder=None):
    status = outcome['status']
    if status == 'DUPLICATE_SKIPPED':
        return {'status': 'SKIPPED'}
    notices = HERE / 'notifications' if folder is None else folder
    notices.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((event['version_key'] + ':' + status).encode()).hexdigest()
    path = notices / (key + '.json')
    title, body = message(status, outcome.get('reason', ''), outcome.get('scheduled_time'))
    record = {'status': status, 'report_id': event.get('id'), 'report_title': event.get('title'),
              'title': title, 'message': body, 'created_at': datetime.now(timezone(timedelta(hours=8))).isoformat()}
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {'status': 'DUPLICATE_SKIPPED'}
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    # Human-readable result remains available even if Windows suppresses the toast.
    (HERE / '最新执行结果.txt').write_text(title + '\n' + body + '\n日报：' + str(event.get('title', '')) + '\n' + record['created_at'], encoding='utf-8')
    try:
        if status=='TEST_TIME_SET':
            subprocess.Popen([sys.executable,str(HERE/'result_notify.py'),'--display',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            delivery={'status':'NOTIFICATION_STARTED'}
            path.with_suffix('.delivery.json').write_text(json.dumps(delivery,ensure_ascii=False),encoding='utf-8')
            return delivery
        result = subprocess.run([sys.executable, str(HERE / 'result_notify.py'), '--display', str(path)], capture_output=True, text=True, timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        delivery = {'status': 'NOTIFICATION_REQUESTED' if result.returncode == 0 else 'NOTIFY_FAILED', 'exit_code': result.returncode}
        if result.returncode:
            delivery['error'] = result.stderr[-1000:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        delivery = {'status': 'NOTIFY_FAILED', 'error': type(exc).__name__}
    path.with_suffix('.delivery.json').write_text(json.dumps(delivery, ensure_ascii=False, indent=2), encoding='utf-8')
    return delivery


if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--display':
    display(Path(sys.argv[2]))
