"""Split an approved weekly report into the two DingTalk template fields."""
import re


def split_weekly(text):
    pattern = re.compile(r'^#{1,3}\s*(本周完成工作|下周工作计划)\s*$', re.MULTILINE)
    matches = list(pattern.finditer(text))
    names = [m.group(1) for m in matches]
    if names == ['下周工作计划']:
        # Approved exports may begin with a report title and work sections.
        # The explicit plan heading still provides an unambiguous boundary.
        first = text[:matches[0].start()].strip()
        second = text[matches[0].end():].strip()
    elif names == ['本周完成工作', '下周工作计划']:
        first = text[matches[0].end():matches[1].start()].strip()
        second = text[matches[1].end():].strip()
    else:
        raise ValueError('周报必须包含本周完成工作、下周工作计划两个明确标题')
    if not first or not second:
        raise ValueError('周报两个栏目均需有内容')
    return first, second
