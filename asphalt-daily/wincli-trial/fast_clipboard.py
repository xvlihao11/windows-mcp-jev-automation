"""Prepare rich clipboard alongside navigation; local guards never call a model."""
from concurrent.futures import ThreadPoolExecutor
import time
from file_clipboard import clipboard_sequence, clipboard_reusable, prepare, publish


class FastClipboard:
    def __init__(self,event):
        self.event=event
        self.rendered=None
        self.sequence=None
        self.future=None
        self.pool=ThreadPoolExecutor(max_workers=1)
        self.timings=[]

    def reusable(self):
        e=self.event
        return clipboard_reusable(e['staged_report_path'],e['staged_content_sha256'],self.sequence)

    def prepare_once(self):
        t=time.perf_counter()
        self.sequence=clipboard_sequence()
        reused=self.reusable()
        if not reused:
            self.restore()
        result={'reused':reused,'elapsed_seconds':round(time.perf_counter()-t,6),'status':'RICH_CLIPBOARD_READY','clipboard_sequence':self.sequence}
        self.timings.append({'phase':'early_prepare',**result})
        return result

    def restore(self):
        e=self.event
        if self.rendered is None:
            self.rendered,_=prepare(e['id'],e['sha256'],'daily',e['staged_report_path'],e['staged_renderer_path'],e['staged_content_sha256'])
        publish(self.rendered['html'],self.rendered['plain'],e['staged_content_sha256'])
        self.sequence=clipboard_sequence()

    def start(self):
        if self.future is None:
            self.future=self.pool.submit(self.prepare_once)

    def ensure_ready(self):
        t=time.perf_counter()
        self.start()
        receipt=self.future.result(timeout=20)
        reused=self.reusable()
        if not reused:
            # reusable() has checked that the staged file still has its approved
            # fingerprint; republish cached HTML without launching Node again.
            self.restore()
        if not self.reusable():
            raise RuntimeError('剪贴板未就绪，禁止粘贴')
        result={**receipt,'reused':reused,'clipboard_sequence':self.sequence,'check_seconds':round(time.perf_counter()-t,6)}
        self.timings.append({'phase':'before_paste',**result})
        return result

    def close(self):
        self.pool.shutdown(wait=True,cancel_futures=True)


class PasteGuard:
    def __init__(self):
        self.state='not_dispatched'

    def dispatch(self,clipboard_ready):
        if self.state!='not_dispatched':
            raise RuntimeError('本篇粘贴已派发或已完成，禁止再次粘贴')
        if not clipboard_ready:
            raise RuntimeError('剪贴板未就绪，禁止粘贴')
        # Record before input. Even a partial batch must never be replayed.
        self.state='dispatched_outcome_unknown'

    def confirm(self):
        if self.state!='dispatched_outcome_unknown':
            raise RuntimeError('不存在待确认的粘贴动作')
        self.state='confirmed_complete'
