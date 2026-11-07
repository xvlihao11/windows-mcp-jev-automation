"""Listener routing and process adapter for no-submit Jev tests."""
import json
import subprocess
import sys
import time
from datetime import datetime,timezone,timedelta
from pathlib import Path
from agent_watch import save
from execution_policy import daily_mode,authorization_for,local_now
from report_day_policy import expected_report, read_selection

HERE=Path(__file__).resolve().parent

def load_mode():
    return json.loads((HERE/'execution-mode.json').read_text(encoding='utf-8-sig'))

def route_for(item,config):
    if config.get('mode') == 'paused':
        return 'ignore'
    engine=config.get('executor','codex')
    if engine=='codex':
        if config.get('stop_before_save'):
            raise ValueError('无提交测试禁止使用旧执行入口')
        return 'legacy'
    no_submit=config.get('actual_send') is False and config.get('stop_before_save') is True
    save_once=(config.get('actual_send') is True and config.get('stop_before_save') is False and config.get('save_authorization'))
    daily=daily_mode(config)
    if engine!='jev_local' or not (daily or config.get('mode')=='test' and (no_submit or save_once)):
        raise ValueError('新版执行配置或保存授权不完整')
    if item.get('source')!='daily':
        return 'ignore'
    if daily and item.get('date')!=local_now().date().isoformat():
        return 'ignore'
    if daily:
        selection = read_selection(HERE / 'report-day-selection.json')
        kind = expected_report(item, selection, local_now().date())
        if kind is None:
            return 'ignore'
        if kind == 'weekly':
            raise ValueError('周报双栏目输入尚未验证，停止发送')
    detected=item.get('detected_at')
    if not detected or datetime.fromisoformat(detected)<datetime.fromisoformat(config['enabled_at']):
        return 'ignore'
    return 'local_test'

def execute_local(item,folder,stage_report,resume_after_paste=False,on_start=None,resume_weekly_plan=False):
    config=load_mode()
    if route_for(item,config)=='ignore':
        return 'OLD_EVENT_IGNORED'
    allow_save=config.get('stop_before_save') is False
    item=dict(item,execution_engine='jev_local',ui_profile='jev_local',stop_before_save=not allow_save)
    item['report_kind'] = 'weekly' if str(item.get('category', '')).strip() == '周报' else 'daily'
    if allow_save:
        item['save_authorization']=authorization_for(item,config)
    started=time.perf_counter()
    began=datetime.now(timezone(timedelta(hours=8))).isoformat()
    receipt={'status':'BLOCKED','saved':False,'report_id':item.get('id'),'report_kind':item['report_kind']}
    try:
        if daily_mode(config):
            date=item['date']
            history=list((HERE/'live-runs').glob('*/execution-receipt.json'))
            job=HERE/'outbox'/date/'job.json'
            if job.exists():
                history.append(job)
            for path in history:
                record=json.loads(path.read_text(encoding='utf-8-sig'))
                # The outbox directory scopes legacy jobs that omit a time.
                if path!=job and not str(record.get('scheduled_time','')).startswith(date):
                    continue
                state=str(record.get('status','')).upper()
                if state in ('UNKNOWN','UNKNOWN_TIMEOUT','SCHEDULING','SUBMITTING','DISPATCHING'):
                    raise RuntimeError('当天已有保存结果不明的记录，停止，不能重试保存')
                if state=='SCHEDULED' and record.get('report_kind','daily')==item['report_kind']:
                    receipt.update(status='ALREADY_SCHEDULED',scheduled_time=date+' 23:30',reason='当天已有成功排程，本次未新增。')
                    break
            if receipt['status']=='ALREADY_SCHEDULED':
                save(folder/'execution-receipt.json',receipt)
                return receipt['status']
        if allow_save and (HERE/'save-authorizations'/(item['save_authorization']+'.json')).exists():
            raise RuntimeError('本次保存授权已使用，不重复创建定时')
        stage_report(item,folder)
        save(folder/'claim.json',item)
        save(folder/'progress.json',{'active':True,'stage':'新程序已接收日报 · 提前准备剪贴板'})
        if on_start:
            on_start(item)
        with (folder/'worker.stdout.jsonl').open('w',encoding='utf-8') as output, (folder/'stderr.log').open('w',encoding='utf-8') as errors:
            command=[sys.executable,str(HERE/'jev_worker.py'),'--folder',str(folder.resolve())]
            if resume_after_paste:
                command.append('--resume-after-paste')
            if resume_weekly_plan:
                command.append('--resume-weekly-plan')
            result=subprocess.run(command,cwd=HERE.parent,stdout=output,stderr=errors,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        outcome=json.loads((folder/'result.json').read_text(encoding='utf-8-sig'))
        if outcome.get('status')=='TIME_SET' and outcome.get('saved') is False and result.returncode==0:
            receipt.update(status='TEST_TIME_SET',scheduled_time=outcome.get('scheduled_time'),reason='测试完成：已读回今天23:30，未保存、未创建排程。')
        elif outcome.get('status')=='SCHEDULED' and outcome.get('saved') is True and result.returncode==0 and allow_save:
            receipt.update(outcome,reason='钉钉已显示23:30发布记录，原生定时已保存。')
        elif outcome.get('status')=='UNKNOWN':
            receipt.update(outcome,reason='已尝试保存，但未确认钉钉回执；不自动重试。')
        else:
            receipt.update(reason=outcome.get('reason','新版测试未完成，未保存。'),stage=outcome.get('stage'))
    except subprocess.TimeoutExpired:
        receipt.update(status='UNKNOWN' if (folder/'save-state.json').exists() else 'BLOCKED',saved=None if (folder/'save-state.json').exists() else False,reason='执行超时，已停止；不会重复执行粘贴或保存。')
    except Exception as error:
        uncertain=(folder/'save-state.json').exists()
        receipt.update(status='UNKNOWN' if uncertain else 'BLOCKED',saved=None if uncertain else False,reason='执行停止：'+str(error)[:200]+('；保存结果待确认，不重试。' if uncertain else '；未执行保存。'))
    save(folder/'execution-receipt.json',receipt)
    save(folder/'metrics.json',{'elapsed_seconds':round(time.perf_counter()-started,3),'execution_engine':'jev_local','detected_at':item.get('detected_at'),'execution_started_at':began,'completed_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),'saved':receipt['saved'],'status':receipt['status']})
    save(folder/'progress.json',{'active':False,'stage':receipt['reason']})
    return receipt['status']
