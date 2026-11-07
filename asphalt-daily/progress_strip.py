"""Local desktop status strip; never invokes a model or operates DingTalk."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tkinter as tk
import time

HERE = Path(__file__).resolve().parent


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def execution_visible(status):
    if status.get('status')!='EXECUTING':
        return False
    key=status.get('last_event',{}).get('version_key')
    if key:
        folder=HERE/'live-runs'/hashlib.sha256(key.encode()).hexdigest()
        # A finished local worker must not remain visible while the notifier
        # displays its one terminal notification or a legacy status is stale.
        if read_json(folder/'progress.json').get('active') is False:
            return False
    return True


def progress():
    status = read_json(HERE / 'live-watch-status.json')
    state = status.get('status', '')
    if (HERE / 'AUTOMATION_DISABLED').exists() or state in ('STOPPED_BY_USER', 'DISABLED_BY_USER', 'STOPPED_WITH_AGENT'):
        return '自动日报已停止', '#bbbbbb'
    if state == 'EXECUTING':
        event = status.get('last_event', {})
        key = event.get('version_key', '')
        folder = HERE / 'live-runs' / hashlib.sha256(key.encode()).hexdigest()
        local_progress=read_json(folder/'progress.json')
        if local_progress.get('active') is True and local_progress.get('stage'):
            return local_progress['stage'], '#72b7ff'
        receipt = read_json(folder / 'execution-receipt.json')
        phase = str(receipt.get('status', '')).upper()
        if phase == 'SCHEDULED':
            return '完成 · 钉钉定时已保存', '#69d5a5'
        if phase in ('SCHEDULING', 'SUBMITTING'):
            return '正在保存 · 等待钉钉确认', '#72b7ff'
        label = '已检测到新日报 · 正在启动执行'
        path = folder / 'events.jsonl'
        # Read only a bounded tail. Ignore screenshots, report text and tool results.
        try:
            with path.open('rb') as stream:
                stream.seek(0, 2)
                size = stream.tell()
                stream.seek(max(0, size - 65536))
                lines = stream.read().decode('utf-8', errors='replace').splitlines()
            for line in lines:
                try:
                    item = json.loads(line).get('item', {})
                except ValueError:
                    continue
                tool = item.get('tool', '')
                args = item.get('arguments') or {}
                if item.get('type') == 'command_execution' and 'file_clipboard.py' in item.get('command', ''):
                    label = '正在复制日报 · 保留原有排版'
                elif tool == 'window_management':
                    label = '正在定位钉钉窗口'
                elif tool == 'ui_batch' and '"v"' in args.get('steps', ''):
                    label = '正在粘贴日报到钉钉'
                elif tool == 'ui_type' and ':' in args.get('text', '') and '-' in args.get('text', ''):
                    label = '正在设置定时发送时间'
                elif tool in ('ui_find', 'ui_click', 'mouse_control') and label.startswith('已检测'):
                    label = '正在打开钉钉日报表单'
        except OSError:
            pass
        return label, '#72b7ff'
    if state in ('ERROR', 'ATTENTION_REQUIRED'):
        return '日报执行未完成 · 请查看结果通知', '#ffb978'
    if state == 'STARTING':
        return '正在启动日报监控', '#72b7ff'
    return '自动日报已开启 · 等待新日报', '#bbbbbb'


def main(parent_pid, preview_seconds=0):
    # One normal progress window per listener; repeated starts are harmless.
    if not preview_seconds:
        import msvcrt
        singleton = (HERE / 'progress-strip.lock').open('a+b')
        singleton.write(b'0')
        singleton.flush()
        singleton.seek(0)
        try:
            msvcrt.locking(singleton.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
    root = tk.Tk()
    root.withdraw()
    root.title('日报实时进度')
    root.attributes('-topmost', True)
    root.attributes('-disabled', True)  # A status display must not take keyboard focus from DingTalk.
    root.configure(bg='#202124')
    width, height = 440, 88
    root.geometry(f'{width}x{height}+{max(0, root.winfo_screenwidth()-width-28)}+{max(0, root.winfo_screenheight()-height-95)}')
    root.resizable(False, False)
    tk.Label(root, text='自动日报', fg='#ffffff', bg='#202124', font=('Microsoft YaHei UI', 10)).pack(anchor='w', padx=16, pady=(9, 2))
    text = tk.Label(root, text='', fg='#72b7ff', bg='#202124', font=('Microsoft YaHei UI', 12), anchor='w')
    text.pack(fill='x', padx=16)
    preview_until = time.monotonic() + preview_seconds if preview_seconds else 0.0
    result_until = preview_until
    if preview_seconds:
        text.configure(text='进度条显示测试 · 不操作或发送日报')
    visible = False

    def tick():
        nonlocal result_until, visible
        if preview_seconds and time.monotonic() >= preview_until:
            root.destroy()
            return
        status = read_json(HERE / 'live-watch-status.json')
        if not status:
            root.after(700, tick)
            return
        stale = False
        try:
            checked = datetime.fromisoformat(status['checked_at'])
            stale = (datetime.now(checked.tzinfo) - checked).total_seconds() > 40 and status.get('status') != 'EXECUTING'
        except (ValueError, KeyError):
            pass
        if status.get('pid') != parent_pid:
            root.destroy()
            return
        if stale:
            # Sleep/resume or a long idle pause must not permanently kill the strip.
            root.withdraw()
            visible = False
            root.after(700, tick)
            return
        executing = execution_visible(status)
        if executing:
            label, color = progress()
            text.configure(text=label, fg=color)
        # Completion/failure is shown by result_notify exactly once, not by a
        # second popup here. The strip is reserved for live execution progress.
        show = executing or time.monotonic() < result_until
        if show and not visible:
            root.deiconify()
            visible = True
        elif not show and visible:
            root.withdraw()
            visible = False
        root.after(700, tick)

    tick()
    root.mainloop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent-pid', required=True, type=int)
    parser.add_argument('--preview-seconds', type=float, default=0)
    args = parser.parse_args()
    main(args.parent_pid, args.preview_seconds)
