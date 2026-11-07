"""Jev validates bounded stages; local guards prohibit replay and unauthorized save."""
import ast
import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from continuous_trial import HERE, Trial, main_dingtalk_window


class JevTrial(Trial):
    def __init__(self,key,**kwargs):
        super().__init__(**kwargs)
        self.key=key
        self.decisions=[]
        parsed=ast.parse((HERE/'compare_split_actions.py').read_text(encoding='utf-8'))
        values={n.targets[0].id:ast.literal_eval(n.value) for n in parsed.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('criteria','instructions')}
        self.criteria=values['criteria']
        self.instructions=values['instructions']

    def decide(self,state,expected):
        self.check_test_mode()
        # State is deliberately handwritten metadata from local observations.
        # No accessibility tree, editor text, file name, or recipient is uploaded.
        payload={'model':'jev-1.13.0','state':state,'questions':{'next':{'type':'choice','instructions':self.instructions,'criteria':self.criteria}}}
        req=urllib.request.Request('https://api.typesafe.ai/v1/systemone',data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'})
        started=time.perf_counter()
        item={'stage':self.stage,'expected':expected}
        try:
            for attempt in range(2):
                try:
                    with urllib.request.urlopen(req,timeout=15) as r:
                        answer=json.loads(r.read(65536))['answers']['next']
                    break
                except urllib.error.HTTPError as error:
                    # The HTTP request only asks a question; no desktop action
                    # has run yet. One retry is safe and cannot duplicate input.
                    if error.code==503 and attempt==0:
                        item['retried_http_status']=503
                        continue
                    raise
            item.update(choice=answer.get('choice'),confidence=answer.get('confidence'))
            if answer.get('choice')!=expected:
                raise RuntimeError('Jev选择不符合当前阶段，动作已阻止')
        except urllib.error.HTTPError as error:
            item['http_status']=error.code
            raise RuntimeError(f'Jev接口HTTP {error.code}，停止，不自动重试动作') from None
        finally:
            item['seconds']=round(time.perf_counter()-started,3)
            self.decisions.append(item)
            (self.folder/'jev-decisions.json').write_text(json.dumps(self.decisions,ensure_ascii=False,indent=2),encoding='utf-8')
        return expected


class ResumeJevTrial(JevTrial):
    def run(self):
        if (self.event or {}).get('report_kind') == 'weekly':
            plan_file=self.folder/'plan-paste-state.json'
            if not plan_file.exists() or json.loads(plan_file.read_text(encoding='utf-8-sig')).get('state')!='confirmed_complete':
                raise RuntimeError('下周计划未确认，禁止恢复定时发送')
        self.phase('恢复已粘贴表单 · 不重新粘贴')
        w=self.ensure_dingtalk_window()
        self.handle=w['handle']
        if w.get('state')=='minimized':
            w=self.call('window','restore','--handle',self.handle)['window']
        self.bounds=w['bounds']
        self.call('window','activate','--handle',self.handle)
        foreground=self.call('window','get_foreground')['window']
        if foreground['handle']!=self.handle:
            raise RuntimeError('钉钉不在前台')
        self.wait(lambda ns:next((n for n in ns if n.get('type')=='Document' and n.get('name')=='写日志'),None))
        self.confirm_rich_input()
        return self.continue_after_paste()


class ResumeWeeklyPlanTrial(JevTrial):
    """Continue a verified work-only paste; never replay the first field."""
    def run(self):
        from fast_clipboard import FastClipboard
        from continuous_trial import work_section_signal
        event=self.event or {}
        if event.get('report_kind')!='weekly':
            raise RuntimeError('只允许恢复周报计划栏目')
        prior=json.loads((self.folder/'paste-state.json').read_text(encoding='utf-8-sig'))
        if prior.get('state')!='confirmed_complete' or any((self.folder/n).exists() for n in ('plan-paste-state.json','save-state.json')):
            raise RuntimeError('恢复条件不符，不重放输入')
        self.phase('恢复周报 · 只填写下周工作计划')
        w=self.ensure_dingtalk_window()
        self.handle=w['handle']
        if w.get('state')=='minimized':
            w=self.call('window','restore','--handle',self.handle)['window']
        self.bounds=w['bounds']
        self.call('window','activate','--handle',self.handle)
        def editor(ns):
            labels=[n for n in ns if n.get('name')=='下周工作计划' and self.inside(n)]
            if len(labels)!=1:return None
            label=labels[0]
            edits=[n for n in ns if n.get('type')=='Edit' and self.inside(n)
                   and 0<n['click'][1]-label['click'][1]<180
                   and abs(n['click'][0]-label['click'][0])<400]
            return edits[0] if len(edits)==1 else None
        target=self.locate_weekly_plan_editor()
        if not work_section_signal(self.last_tree,'weekly').get('nonempty'):
            raise RuntimeError('本周栏目非空状态未确认，停止恢复')
        if work_section_signal(self.last_tree,'weekly','plan').get('nonempty'):
            raise RuntimeError('计划栏目已有内容，停止，不覆盖或重复粘贴')
        self.clipboard=FastClipboard(dict(event,staged_report_path=event['staged_plan_path'],
                                            staged_content_sha256=event['staged_plan_sha256']))
        self.clipboard.start()
        self.clipboard.ensure_ready()
        self.click(target)
        steps=self.folder/'plan-paste.json'
        steps.write_text(json.dumps([{'action':'key','key':'a','modifiers':'ctrl'},
                                    {'action':'key','key':'backspace'},
                                    {'action':'key','key':'v','modifiers':'ctrl'}]),encoding='utf-8')
        self.clipboard.ensure_ready()
        (self.folder/'plan-paste-state.json').write_text(json.dumps({'state':'dispatched_outcome_unknown'}),encoding='utf-8')
        self.call('ui','batch','--window',self.handle,'--steps-file',steps)
        self.wait(lambda ns:work_section_signal(self.last_tree,'weekly','plan').get('nonempty'),seconds=5)
        (self.folder/'plan-paste-state.json').write_text(json.dumps({'state':'confirmed_complete'}),encoding='utf-8')
        return self.continue_after_paste()
