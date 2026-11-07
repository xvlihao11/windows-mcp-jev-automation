"""Regression checks for the actual rich-editor/hidden-Edit discrepancy."""
import unittest
from continuous_trial import work_section_signal

def text(name):
    return {'type':'Text','name':name}

class SignalTests(unittest.TestCase):
    def test_rich_sibling_text_with_empty_edit(self):
        tree=[{'type':'Group','children':[text('今日完成工作'),text('示例内容'),text('明日计划')]},{'type':'Edit','value':''}]
        self.assertTrue(work_section_signal(tree)['nonempty'])

    def test_other_sections_do_not_count(self):
        tree=[text('今日完成工作'),text('请输入'),text('明日计划'),text('其他栏目内容')]
        self.assertFalse(work_section_signal(tree)['nonempty'])

    def test_rich_table_counts(self):
        self.assertTrue(work_section_signal([text('今日完成工作'),{'type':'Table'},text('明日计划')])['nonempty'])

    def test_ambiguous_headings_stop(self):
        group={'type':'Group','children':[text('今日完成工作'),text('示例内容'),text('明日计划')]}
        self.assertFalse(work_section_signal([group,group])['nonempty'])

if __name__=='__main__':
    unittest.main()
