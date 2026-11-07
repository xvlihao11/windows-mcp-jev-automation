"""Listener entry for time-only Jev tests; contains no save/schedule creation."""
import argparse
import json
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'wincli-trial'))
from jev_desktop_trial import JevTrial,ResumeJevTrial,ResumeWeeklyPlanTrial
from jev_secret import load_key

def main(folder,resume_after_paste=False,resume_weekly_plan=False):
    folder=Path(folder).resolve()
    if not folder.is_relative_to((HERE/'live-runs').resolve()):
        raise ValueError('Run outside workspace')
    event=json.loads((folder/'claim.json').read_text(encoding='utf-8-sig'))
    if event.get('execution_engine')!='jev_local' or (event.get('stop_before_save') is not True and not event.get('save_authorization')):
        raise ValueError('Missing execution mode or save authorization')
    if resume_after_paste:
        pasted=json.loads((folder/'paste-state.json').read_text(encoding='utf-8-sig'))
        if pasted.get('state')!='confirmed_complete' or (folder/'save-state.json').exists():
            raise ValueError('Cannot resume without confirmed input or after a save attempt')
    trial=(ResumeWeeklyPlanTrial if resume_weekly_plan else ResumeJevTrial if resume_after_paste else JevTrial)(load_key(),event=event,folder=folder,progress_path=folder/'progress.json')
    trial.check_test_mode()
    trial.finish()

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--folder')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--resume-after-paste',action='store_true')
    parser.add_argument('--resume-weekly-plan',action='store_true')
    args=parser.parse_args()
    if args.check:
        from datetime import datetime,timezone
        from jev_dispatch import route_for
        mode=json.loads((HERE/'execution-mode.json').read_text(encoding='utf-8-sig'))
        if route_for({'source':'daily','detected_at':datetime.now(timezone.utc).isoformat()},mode)!='local_test':
            raise RuntimeError('Route not active')
        if not load_key() or not (HERE/'wincli-trial/bin/wincli.exe').is_file():
            raise RuntimeError('Worker dependency unavailable')
        print(json.dumps({'status':'WORKER_COMPONENTS_READY','executor':'jev_local','api':'official_typesafe','stop_before_save':mode.get('stop_before_save')},ensure_ascii=False))
    elif args.folder:
        main(args.folder,args.resume_after_paste,args.resume_weekly_plan)
    else:
        parser.error('--folder or --check required')
