"""Bounded DingTalk executor with explicit mode guards and single-use save."""
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from fast_clipboard import FastClipboard, PasteGuard


def flatten(nodes):
    for node in nodes:
        yield node
        yield from flatten(node.get('children', []))


def dingtalk_auxiliary_window(window):
    # Observed DingTalk overlays may remain when its main frame is in the tray.
    return (window.get('title') == 'Form'
            or window.get('className') in ('water_mask_wnd', 'DuiShadowWnd'))


def main_dingtalk_window(windows):
    """Prefer the observed main-frame class over DingTalk toast/tool windows."""
    mains=[w for w in windows if w.get('className')=='StandardFrame_DingTalk']
    if len(mains)==1:
        return mains[0]
    candidates=[w for w in windows if not dingtalk_auxiliary_window(w)]
    if not mains and len(candidates)==1:
        return candidates[0]
    raise RuntimeError('钉钉主窗口未唯一识别')


def work_section_signal(tree, report_kind='daily', section='work'):
    """Presence only, scoped strictly between the two fixed form headings.

    DingTalk exposes rich content as siblings of a hidden Edit, whose value is
    empty even after successful input. Never return the report text.
    """
    if report_kind not in ('daily', 'weekly'):
        raise ValueError('未知日志类型')
    start_label, end_label = (('本周完成工作', '下周工作计划') if report_kind == 'weekly'
                              else ('今日完成工作', '明日计划'))
    if section == 'plan' and report_kind == 'weekly':
        start_label, end_label = '下周工作计划', ('备注','图片')
    elif section != 'work':
        raise ValueError('未知日志栏目')
    sections=[]
    def visit(nodes):
        starts=[i for i,n in enumerate(nodes) if n.get('name')==start_label and n.get('type')=='Text']
        ends=[i for i,n in enumerate(nodes) if (n.get('name') in end_label if isinstance(end_label,tuple) else n.get('name')==end_label) and n.get('type')=='Text']
        if isinstance(end_label,tuple) and len(starts)==1:
            ends=[i for i in ends if i>starts[0]][:1]
        if len(starts)==len(ends)==1 and starts[0]<ends[0]:
            section=nodes[starts[0]+1:ends[0]]
            meaningful=[n for n in flatten(section) if n.get('type')=='Text' and n.get('name','').strip(' \t\r\n\u200b\ufeff') not in ('','请输入','-')]
            tables=sum(n.get('type')=='Table' for n in flatten(section))
            sections.append({'nonempty':bool(meaningful or tables),'text_blocks':len(meaningful),'tables':tables})
        for n in nodes:
            visit(n.get('children',[]))
    visit(tree)
    if len(sections)!=1:
        return {'nonempty':False,'reason':'工作章节未唯一识别'}
    return sections[0]


class Trial:
    def __init__(self,event=None,folder=None,progress_path=None):
        self.start = time.monotonic()
        self.handle = None
        self.calls = []
        self.stage = '启动'
        self.clipboard=None
        self.save_dispatched=False
        self.paste_guard=PasteGuard()
        self.event=event
        self.monitor_mode=event is not None
        self.progress_path=Path(progress_path) if progress_path else HERE/'continuous-status.json'
        self.folder = Path(folder) if folder else HERE / ('continuous-' + datetime.now().strftime('%Y%m%dT%H%M%S'))
        self.folder.mkdir(parents=True,exist_ok=True)

    def phase(self, stage):
        self.stage = stage
        from agent_watch import save
        save(self.progress_path,{'stage': stage, 'active':True})

    def check_test_mode(self):
        if not self.monitor_mode:
            return
        config=json.loads((HERE.parent/'execution-mode.json').read_text(encoding='utf-8-sig'))
        from execution_policy import daily_mode,authorization_for
        no_submit=config.get('mode')=='test' and config.get('actual_send') is False and config.get('stop_before_save') is True
        expected_authorization=authorization_for(self.event,config) if config.get('actual_send') is True else None
        authorized_save=(config.get('actual_send') is True and config.get('stop_before_save') is False
                         and self.event.get('save_authorization')
                         and self.event.get('save_authorization')==expected_authorization)
        permitted=authorized_save if self.event.get('stop_before_save') is False else no_submit
        if (HERE.parent/'AUTOMATION_DISABLED').exists() or config.get('mode') not in ('test','daily') or config.get('executor')!='jev_local' or not permitted:
            raise RuntimeError('执行模式已停止或本次保存授权不匹配')

    def decide(self, state, expected):
        """Optional decision adapter; the base trial uses its deterministic stages."""
        return expected

    def call(self, *args):
        self.check_test_mode()
        began = time.monotonic()
        p = subprocess.run([str(HERE/'bin/wincli.exe'), *map(str,args)], capture_output=True, text=True, encoding='utf-8', timeout=25)
        result = json.loads(p.stdout) if p.stdout.strip() else {'error':p.stderr}
        self.calls.append({'stage':self.stage,'command':args[:2], 'seconds':round(time.monotonic()-began,3),'ok':p.returncode==0})
        if p.returncode or result.get('success') is False:
            raise RuntimeError(result.get('error', p.stderr)[:350])
        return result

    def nodes(self):
        result = self.call('ui','snapshot','--window',self.handle,'--mode','auto','--max-depth','24')
        if result.get('snapshotIncomplete'):
            raise RuntimeError('控件快照不完整，停止自动判断')
        self.last_tree=result.get('tree',[])
        return list(flatten(result.get('tree',[])))

    def confirm_rich_input(self):
        self.phase('确认富文本输入状态 · 不检查正文')
        kind = (self.event or {}).get('report_kind', 'daily')
        self.wait(lambda ns: work_section_signal(self.last_tree, kind).get('nonempty'),seconds=4)
        self.input_signal=work_section_signal(self.last_tree, kind)
        (self.folder/'input-signal.json').write_text(json.dumps(self.input_signal,ensure_ascii=False),encoding='utf-8')

    def wait(self, predicate, seconds=10):
        deadline = time.monotonic()+seconds
        while True:
            nodes = self.nodes()
            found = predicate(nodes)
            if found:
                return nodes, found
            if time.monotonic() >= deadline:
                summary=[{k:n.get(k) for k in ('id','name','type','click')} for n in nodes
                         if n.get('type') in ('Edit','Document') or n.get('name') in
                         ('今日完成工作','本周完成工作','下周工作计划','备注','图片','请输入')]
                (self.folder/'wait-timeout-controls.json').write_text(json.dumps(
                    {'stage':self.stage,'bounds':self.bounds,'controls':summary},ensure_ascii=False,indent=2),encoding='utf-8')
                raise RuntimeError('当前阶段未出现预期控件，停止，不重放点击')
            time.sleep(.15)

    def inside(self, node):
        x,y,*_ = node.get('click',[0,0])
        bx,by,w,h = self.bounds
        return bx < x < bx+w and by < y < by+h

    def recover_input_window(self):
        foreground=self.call('window','get_foreground').get('window',{})
        if foreground.get('handle')==self.handle:
            return
        current=self.call('window','get_state','--handle',self.handle)['window']
        if current.get('state')=='minimized':
            current=self.call('window','restore','--handle',self.handle)['window']
        self.bounds=current['bounds']
        self.call('window','activate','--handle',self.handle)
        if self.call('window','get_foreground').get('window',{}).get('handle')!=self.handle:
            raise RuntimeError('钉钉未恢复到前台，停止输入')

    def locate_weekly_plan_editor(self):
        """Bottom first, then scroll up until heading and editor are unobscured."""
        self.recover_input_window()
        bx,by,w,h=self.bounds
        current=self.nodes()
        if not (any(n.get('type')=='Document' and n.get('name')=='写日志' for n in current)
                and any(n.get('name') in ('本周完成工作','下周工作计划') for n in current)):
            raise RuntimeError('当前已离开周报填写页，停止；未滚动、未粘贴计划')
        self.phase('滑到底后上滑定位下周计划')
        self.call('mouse','scroll','--window',self.handle,'--x',round(w*.245),
                  '--y',round(h*.52),'--direction','down','--amount','80')
        self.call('mouse','scroll','--window',self.handle,'--x',round(w*.245),
                  '--y',round(h*.52),'--direction','up','--amount','1')
        def ready(nodes):
            labels=[n for n in nodes if n.get('name')=='下周工作计划' and self.inside(n)
                    and n['click'][1]>by+h*.20]
            if len(labels)==1:
                label=labels[0]
                candidates=[n for n in nodes if n.get('type')=='Edit' and self.inside(n)
                            and 0<n['click'][1]-label['click'][1]<180
                            and abs(n['click'][0]-label['click'][0])<400]
                if len(candidates)==1:
                    return candidates[0]
                if len(candidates)>1:
                    raise RuntimeError('下周计划对应多个编辑器，停止输入')
                # DingTalk can expose an offscreen hidden Edit while rendering
                # a visible placeholder inside the actual contenteditable.
                # Use only the unique observed placeholder under this heading,
                # bounded above the next section; never pick a global prompt.
                ends=[n['click'][1] for n in nodes if n.get('name')=='备注'
                      and self.inside(n) and n['click'][1]>label['click'][1]]
                limit=min(ends) if ends else label['click'][1]+180
                placeholders=[n for n in nodes if n.get('type')=='Text' and n.get('name')=='请输入'
                              and self.inside(n) and 0<n['click'][1]-label['click'][1]<180
                              and n['click'][1]<limit
                              and abs(n['click'][0]-label['click'][0])<400]
                if len(placeholders)==1:
                    return placeholders[0]
                if len(placeholders)>1:
                    raise RuntimeError('下周计划输入位置不唯一，停止输入')
            return None
        # Reobserve this position while the page settles; never scroll up again.
        _,editor=self.wait(ready,seconds=5)
        return editor

    def click(self, node):
        if not self.inside(node):
            raise RuntimeError('目标不在当前窗口可视边界内')
        # Never allow a final save/submit/send control into this trial.
        if node.get('name','').replace(' ','') in ('保存','提交','发送'):
            raise RuntimeError('测试禁止最终提交')
        x,y,*_ = node['click']
        bx,by,_,_ = self.bounds
        self.call('mouse','click','--window',self.handle,'--x',round(x-bx),'--y',round(y-by))

    def ensure_dingtalk_window(self):
        observations=[]
        def record(windows, stage):
            observations.append({'stage':stage,'windows':[
                {key:w.get(key) for key in ('handle','className','title','processName','pid','state')}
                for w in windows]})
            folder=getattr(self,'folder',None)
            if folder:
                (folder/'window-discovery.json').write_text(json.dumps(observations,ensure_ascii=False,indent=2),encoding='utf-8')
        windows=self.call('window','find','--process','DingTalk').get('windows',[])
        record(windows,'initial-find')
        if not windows:
            all_windows=self.call('window','list','--include-all-desktops').get('windows',[])
            windows=[w for w in all_windows if w.get('processName','').lower()=='dingtalk']
            record(windows,'all-desktops')
        try:
            return main_dingtalk_window(windows)
        except RuntimeError:
            # A visible ambiguous application is not a reason to launch again.
            # Only an absent main window / toast-only state allows one handoff.
            if any(not dingtalk_auxiliary_window(w) for w in windows):
                raise
        config=json.loads((HERE.parent/'execution-mode.json').read_text(encoding='utf-8-sig'))
        program=Path(config.get('dingtalk_executable',''))
        if not program.is_absolute() or program.suffix.lower()!='.exe' or not program.is_file():
            raise RuntimeError('未找到钉钉主窗口，且本机钉钉启动路径未配置或失效')
        self.phase('自动调出钉钉主窗口')
        # Installed DingTalk handles this as a singleton handoff when in tray.
        # Never launch repeatedly; rediscover and verify the resulting window.
        self.call('app','--path',program,'--timeout-ms','10000')
        deadline=time.monotonic()+12
        while True:
            windows=self.call('window','find','--process','DingTalk').get('windows',[])
            record(windows,'after-single-launch')
            if windows:
                try:
                    return main_dingtalk_window(windows)
                except RuntimeError:
                    if any(not dingtalk_auxiliary_window(w) for w in windows):
                        raise
            if time.monotonic()>=deadline:
                raise RuntimeError('已唤起一次钉钉，但主窗口仍未出现；不重复启动')
            time.sleep(.15)

    def run(self):
        # Start direct-file preparation before the first desktop call.
        if self.event is None:
            raise RuntimeError('A staged report event is required')
        staged = dict(self.event)
        now=datetime.now(timezone(timedelta(hours=8)))
        if now>=now.replace(hour=23,minute=30,second=0,microsecond=0):
            raise RuntimeError('今天23:30已过，停止测试，不顺延或立即发送')
        self.clipboard=FastClipboard(staged)
        self.clipboard.start()
        self.phase('定位钉钉')
        w = self.ensure_dingtalk_window()
        self.handle = w['handle']
        if w.get('state')=='minimized':
            w = self.call('window','restore','--handle',self.handle)['window']
        self.bounds = w['bounds']
        self.call('window','activate','--handle',self.handle)
        fg = self.call('window','get_foreground')['window']
        if fg['handle']!=self.handle:
            raise RuntimeError('钉钉不在前台')
        kind=staged.get('report_kind', 'daily')
        if kind not in ('daily','weekly'):
            raise RuntimeError('日志类型不明确，停止')
        heading='本周完成工作' if kind=='weekly' else '今日完成工作'
        template='周报' if kind=='weekly' else '日报'
        nodes = self.nodes()
        # A navigation-only reset makes this trial include the complete entry path.
        messages=[n for n in nodes if n.get('name')=='消息' and n.get('type')=='Button' and self.inside(n)]
        if len(messages)!=1:
            raise RuntimeError('消息入口未唯一识别，无法建立可比较起点')
        self.click(messages[0])
        nodes,_=self.wait(lambda ns: next((n for n in ns if n.get('name')=='消息' and n.get('type')=='Button'),None) if not any(n.get('name')=='今日完成工作' for n in ns) else None)
        if not any(n.get('name')=='今日完成工作' for n in nodes):
            self.phase('打开日志')
            sidebar = [n for n in nodes if n.get('name')=='日志' and n.get('type')=='Button' and self.inside(n)]
            if len(sidebar)!=1:
                raise RuntimeError('侧栏日志未唯一识别')
            self.click(sidebar[0])
            bx,by,w,h = self.bounds
            def write_entry(ns):
                # The app's create button is inside content, above the report list.
                xs=[n for n in ns if n.get('name')=='写日志' and self.inside(n) and bx+w*.14<n['click'][0]<bx+w*.30 and by+h*.12<n['click'][1]<by+h*.32]
                return xs[0] if len(xs)==1 else None
            _,entry = self.wait(write_entry)
            self.phase('打开新建'+template)
            self.click(entry)
            nodes,_ = self.wait(lambda ns:next((n for n in ns if n.get('type')=='Document' and n.get('name')=='写日志'),None))
        # Reopened drafts can retain the previous page scroll offset. The
        # visible plan heading proves the form opened, but input starts at top.
        if not any(n.get('name') in ('今日完成工作','本周完成工作') and self.inside(n) for n in nodes):
            bx,by,w,h=self.bounds
            self.phase('回到日志表单顶部')
            self.call('mouse','scroll','--window',self.handle,'--x',round(w*.245),
                      '--y',round(h*.52),'--direction','up','--amount','80')
            nodes,_=self.wait(lambda ns:next((n for n in ns if n.get('name') in ('今日完成工作','本周完成工作') and self.inside(n)),None))
        # Click only a uniquely identified top-row template; verify the actual
        # work-section heading after switching before allowing any paste.
        if not any(n.get('name') == heading and self.inside(n) for n in nodes):
            bx,by,w,h=self.bounds
            choices=[n for n in nodes if n.get('name')==template and self.inside(n)
                     and by < n.get('click',[0,0])[1] < by+h*.25]
            if len(choices)!=1:
                raise RuntimeError('目标日志模板未唯一识别，停止')
            self.phase('选择'+template+'模板')
            self.click(choices[0])
            nodes,_=self.wait(lambda ns:next((n for n in ns if n.get('name')==heading and self.inside(n)),None))
        # Associate the first editor below the observed work-section heading.
        def editor_ready(ns):
            headings=[n for n in ns if n.get('name')==heading and self.inside(n)]
            if len(headings)!=1:
                return None
            label=headings[0]
            candidates=[n for n in ns if n.get('type')=='Edit' and self.inside(n) and 0<n['click'][1]-label['click'][1]<180 and abs(n['click'][0]-label['click'][0])<400]
            return candidates[0] if len(candidates)==1 else None
        nodes,editor=self.wait(editor_ready,seconds=8)
        editors=[editor]
        self.phase('本地确认剪贴板已就绪')
        copied=self.clipboard.ensure_ready()
        self.phase('Jev判断 · 只粘贴一次')
        self.decide('富文本剪贴板已准备完成，当前目标编辑器已唯一定位。正文粘贴动作尚未派发。现在只进行一次粘贴，不滚动。','paste_once')
        self.click(editors[0])
        steps=[{'action':'key','key':'a','modifiers':'ctrl'},{'action':'key','key':'backspace'},{'action':'key','key':'v','modifiers':'ctrl'}]
        steps_path=self.folder/'paste.json'
        steps_path.write_text(json.dumps(steps),encoding='utf-8')
        # Recheck after model latency/focus changes, immediately before input.
        self.clipboard.ensure_ready()
        self.paste_guard.dispatch(clipboard_ready=True)
        (self.folder/'paste-state.json').write_text(json.dumps({'state':self.paste_guard.state}),encoding='utf-8')
        self.call('ui','batch','--window',self.handle,'--steps-file',steps_path)
        self.confirm_rich_input()
        self.paste_guard.confirm()
        (self.folder/'paste-state.json').write_text(json.dumps({'state':self.paste_guard.state}),encoding='utf-8')
        if kind=='weekly':
            if not staged.get('staged_plan_path') or not staged.get('staged_plan_sha256'):
                raise RuntimeError('周报缺少已审核的下周计划，停止')
            self.phase('定位下周工作计划栏目')
            plan_editor=self.locate_weekly_plan_editor()
            plan_event=dict(staged,staged_report_path=staged['staged_plan_path'],
                            staged_content_sha256=staged['staged_plan_sha256'])
            plan_clipboard=FastClipboard(plan_event)
            try:
                plan_clipboard.start()
                plan_clipboard.ensure_ready()
                self.phase('填写下周工作计划')
                self.click(plan_editor)
                plan_steps=self.folder/'plan-paste.json'
                plan_steps.write_text(json.dumps(steps),encoding='utf-8')
                plan_clipboard.ensure_ready()
                (self.folder/'plan-paste-state.json').write_text(json.dumps({'state':'dispatched_outcome_unknown'}),encoding='utf-8')
                self.call('ui','batch','--window',self.handle,'--steps-file',plan_steps)
                self.wait(lambda ns:work_section_signal(self.last_tree,'weekly','plan').get('nonempty'),seconds=4)
                (self.folder/'plan-paste-state.json').write_text(json.dumps({'state':'confirmed_complete'}),encoding='utf-8')
            finally:
                plan_clipboard.close()
        return self.continue_after_paste(copied)

    def continue_after_paste(self,copied=None):
        self.phase('滚动到定时区域')
        bx,by,w,h = self.bounds
        if (self.event or {}).get('report_kind')=='weekly':
            self.recover_input_window()
            self.call('mouse','scroll','--window',self.handle,'--x',round(w*.245),
                      '--y',round(h*.52),'--direction','down','--amount','80')
        def schedule_target(ns):
            checks=[n for n in ns if n.get('type')=='CheckBox' and n.get('name','').startswith('定时发送')]
            labels=[n for n in ns if n.get('type')=='Text' and n.get('name')=='定时发送' and self.inside(n)]
            if len(checks)==1:
                if self.inside(checks[0]):
                    return checks[0]
                if len(labels)==1:
                    # Hidden input has no bounds; its current visible HTML label
                    # is the observed click target. Verify toggle state afterward.
                    return dict(checks[0],click=labels[0]['click'])
            return None
        schedule=schedule_target(self.nodes())
        if schedule is None:
            self.phase('Jev判断 · 粘贴已完成，只滚动页面')
            self.decide('正文已粘贴，章节非空输入状态已通过本地确认，不需要检查正文。定时发送入口尚不可见，需要在正文外侧页面滚动区域向下滚动，让底部定时发送出现。严禁再次复制或粘贴。','scroll_page')
            self.phase('滚动到定时区域')
        for _ in range(4):
            if schedule is not None:
                break
            # Observed page gutter left of the document, outside the editor and
            # outside DingTalk's lower-right calendar/notification overlays.
            self.call('mouse','scroll','--window',self.handle,'--x',round(w*.245),'--y',round(h*.52),'--direction','down','--amount','80')
            nodes=self.nodes()
            schedule=schedule_target(nodes)
        if schedule is None:
            raise RuntimeError('滚动四次仍未找到可见定时入口')
        self.phase('核实定时发送时间')
        if schedule.get('toggle')=='Off':
            self.click(schedule)
            self.wait(lambda ns:next((n for n in ns if n.get('type')=='CheckBox' and n.get('name','').startswith('定时发送') and n.get('toggle')=='On'),None),seconds=4)
        elif schedule.get('toggle')!='On':
            raise RuntimeError('定时开关状态未知')
        # Hong Kong is UTC+08:00; no external tzdata dependency on Windows.
        expected=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')+' 23:30'
        entered=self.ensure_schedule_time(expected)
        if self.monitor_mode and self.event.get('stop_before_save') is False:
            return self.save_schedule_once(expected,entered)
        self.decide(f'正文粘贴已经确认，定时开启。表单已可靠读回{expected}，目标同为{expected}。本轮测试要求立即停止，不点击最终保存。','stop_success')
        self.phase('已核实23:30 · 未点击保存')
        return {'status':'TIME_SET','scheduled_time':expected,'saved':False,'clipboard_seconds':copied['elapsed_seconds'] if copied else None,'time_entry_tested':entered,'note':'已填写并核实表单时间' if entered else '表单时间已正确，跳过重输'}

    def ensure_schedule_time(self, expected):
        """Fill a missing/wrong time once; success requires the form readback.

        The form input and popup input have the same accessible name. Keep the
        observed form identity to exclude it while locating the popup input.
        No recipient controls or report content participate in this selection.
        """
        def fields(ns):
            return [n for n in ns if n.get('type')=='Edit'
                    and n.get('name')=='选择发送时间' and self.inside(n)]
        def confirms(ns):
            return [n for n in ns if n.get('type')=='Button'
                    and ''.join(n.get('name','').split())=='确定' and self.inside(n)]
        def matches(n):
            # Some clients expose seconds. Only zero seconds preserve the target.
            return str(n.get('value','')).strip() in (expected, expected+':00')
        def form(ns):
            fs=fields(ns)
            return fs[0] if len(fs)==1 and not confirms(ns) else None

        _,field=self.wait(form,seconds=4)
        if matches(field):
            return False
        if not field.get('id'):
            raise RuntimeError('时间输入框缺少有效引用，停止')
        form_id=field['id']
        self.phase('填写定时发送时间')
        self.click(field)

        def popup(ns):
            fs=[n for n in fields(ns) if n.get('id')!=form_id]
            buttons=confirms(ns)
            if len(fs)==1 and len(buttons)==1:
                return fs[0]
            return None

        _,editor=self.wait(popup,seconds=4)
        self.call('ui','type','--window',self.handle,'--element-id',editor['id'],
                  '--text',expected,'--clear-first','--input-mode','auto')
        def popup_ready(ns):
            target=popup(ns)
            return confirms(ns)[0] if target and matches(target) else None
        _,confirm=self.wait(popup_ready,seconds=4)
        # This is the date popup's confirmation, never the final report Save.
        self.call('ui','click','--window',self.handle,'--element-id',confirm['id'])
        self.phase('核实表单定时发送时间')
        self.wait(lambda ns: (f if (f:=form(ns)) and matches(f) else None),seconds=4)
        return True

    def save_schedule_once(self,expected,entered):
        if (self.event or {}).get('stop_before_save') is True:
            raise RuntimeError('本次不保存测试禁止创建定时')
        self.check_test_mode()
        if (self.event or {}).get('report_kind') == 'weekly':
            for name in ('paste-state.json','plan-paste-state.json'):
                path=self.folder/name
                if not path.exists() or json.loads(path.read_text(encoding='utf-8-sig')).get('state')!='confirmed_complete':
                    raise RuntimeError('周报两个栏目未均确认粘贴完成，禁止保存')
        now=datetime.now(timezone(timedelta(hours=8)))
        if expected!=now.strftime('%Y-%m-%d')+' 23:30' or now.hour==23 and now.minute>=30:
            raise RuntimeError('目标日期时间已过或不符，停止保存')
        def save_button(ns):
            buttons=[n for n in ns if n.get('type')=='Button'
                     and ''.join(n.get('name','').split())=='保存' and self.inside(n)]
            return buttons[0] if len(buttons)==1 else None
        _,button=self.wait(save_button,seconds=4)
        # Persist a single-use authorization BEFORE dispatch; even an uncertain
        # click cannot cause another upload to save under the same authorization.
        from agent_watch import save
        authorization=self.event['save_authorization']
        if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}',authorization):
            raise RuntimeError('保存授权标识无效')
        authorizations=HERE.parent/'save-authorizations'
        authorizations.mkdir(exist_ok=True)
        self.check_test_mode()
        with (authorizations/(authorization+'.json')).open('x',encoding='utf-8') as stream:
            json.dump({'version_key':self.event['version_key'],'scheduled_time':expected,'status':'DISPATCHING'},stream)
        self.save_dispatched=True
        save(self.folder/'save-state.json',{'status':'DISPATCHING','scheduled_time':expected})
        self.phase('保存定时 · 等待钉钉回执')
        self.call('ui','click','--window',self.handle,'--element-id',button['id'])
        def published(ns):
            for n in ns:
                if n.get('type')!='Text':
                    continue
                text=' '.join(n.get('name','').split())
                if re.search(r'将于\s*'+re.escape(expected)+r'(?::00)?\s*发布',text):
                    return text
            return None
        _,evidence=self.wait(published,seconds=10)
        save(self.folder/'save-state.json',{'status':'SCHEDULED','scheduled_time':expected,'evidence':evidence})
        save(authorizations/(authorization+'.json'),{'status':'SCHEDULED','version_key':self.event['version_key'],'scheduled_time':expected,'evidence':evidence})
        self.phase('完成 · 钉钉23:30定时已保存')
        return {'status':'SCHEDULED','saved':True,'scheduled_time':expected,'evidence':evidence,'time_entry_tested':entered}

    def finish(self):
        outcome={}
        try:
            outcome=self.run()
        except Exception as error:
            outcome={'status':'UNKNOWN' if self.save_dispatched else 'BLOCKED','stage':self.stage,'reason':str(error),'saved':None if self.save_dispatched else False}
        finally:
            if self.clipboard:
                self.clipboard.close()
                (self.folder/'clipboard-timings.json').write_text(json.dumps(self.clipboard.timings,ensure_ascii=False,indent=2),encoding='utf-8')
            if self.handle:
                try:
                    self.call('screenshot','--window',self.handle,'--no-annotate','--output-mode','file','--output-path',self.folder/'endpoint.jpg')
                except Exception:
                    pass
            outcome.update(total_seconds=round(time.monotonic()-self.start,3), calls=self.calls)
            (self.folder/'result.json').write_text(json.dumps(outcome,ensure_ascii=False,indent=2),encoding='utf-8')
            from agent_watch import save
            label={'TIME_SET':'测试完成 · 未保存','SCHEDULED':'完成 · 钉钉定时已保存'}.get(outcome.get('status'),'执行停止 · '+outcome.get('reason',''))
            save(self.progress_path,{'stage':label,'active':False})
        print(json.dumps({'folder':str(self.folder),**outcome},ensure_ascii=False))
