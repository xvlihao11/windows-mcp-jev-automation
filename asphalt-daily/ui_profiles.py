"""Select versioned UI instructions; never operates the desktop or schedules reports."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILES = {'stable': 'stable-v3.txt', 'batch_v1': 'batch-v1.txt', 'batch_v2': 'batch-v2.txt'}


def load_profile(profile=None):
    if profile is None:
        config = HERE / 'ui-execution-profile.json'
        profile = json.loads(config.read_text(encoding='utf-8-sig'))['active_profile'] if config.exists() else 'stable'
    if profile not in PROFILES:
        raise ValueError('Unknown UI execution profile; stop rather than select another route')
    rules = (HERE / 'ui-profiles' / PROFILES[profile]).read_text(encoding='utf-8-sig')
    return profile, rules, hashlib.sha256(rules.encode('utf-8')).hexdigest()
