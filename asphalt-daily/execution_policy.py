"""Shared execution-mode rules; no UI, credentials, or external writes."""
from datetime import datetime,timezone,timedelta

def local_now():
    return datetime.now(timezone(timedelta(hours=8)))

def daily_mode(config):
    return (config.get('executor')=='jev_local' and config.get('mode')=='daily'
            and config.get('save_policy')=='daily_once'
            and config.get('actual_send') is True and config.get('stop_before_save') is False)

def authorization_for(item,config):
    if daily_mode(config):
        today=local_now().date().isoformat()
        if item.get('source')!='daily' or item.get('date')!=today:
            raise ValueError('日常模式只处理当天个人日报，不补发历史稿')
        kind='weekly' if item.get('category') == '周报' else 'daily'
        return kind+'-'+today.replace('-','')
    if config.get('mode')=='test' and config.get('actual_send') is True and config.get('stop_before_save') is False and config.get('save_authorization'):
        return config['save_authorization']
    raise ValueError('保存策略未获启用')
