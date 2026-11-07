"""Ordinary daily routing, overridden only by today's explicit selection."""
import json
from datetime import date
from pathlib import Path


def expected_report(item, selection, today):
    """Default to daily; explicit same-day choices override the standing rule."""
    if item.get('source') != 'daily' or item.get('date') != today.isoformat():
        return None
    kind = 'daily'
    if isinstance(selection, dict) and selection.get('date') == today.isoformat():
        kind = selection.get('kind')
        if kind not in ('daily', 'weekly') or selection.get('send_authorized') is not True:
            return None
    category = item.get('category')
    if not isinstance(category, str) or not category.strip():
        return None
    actual = 'weekly' if category.strip() == '周报' else 'daily'
    return kind if kind == actual else None


def read_selection(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
