"""Time-setting regressions using UI observations; never operate the desktop."""
import unittest
from continuous_trial import Trial

TARGET='2026-10-21 23:30'

def edit(identity,value=''):
    return dict(id=identity,type='Edit',name='选择发送时间',value=value,click=[100,100,0])

CONFIRM=dict(id='confirm',type='Button',name='确 定',click=[200,200,0])

class RecordedTrial(Trial):
    def __init__(self,frames):
        self.frames=iter(frames)
        self.actions=[]
        self.bounds=(0,0,1000,1000)
        self.handle=123
    def phase(self,stage):
        pass
    def call(self,*args):
        self.actions.append(args)
        return {}
    def wait(self,predicate,seconds=10):
        ns=next(self.frames)
        found=predicate(ns)
        if not found:
            raise RuntimeError('Expected UI state did not appear')
        return ns,found

class TimeTests(unittest.TestCase):
    def test_correct_default_does_not_click_or_type(self):
        t=RecordedTrial([[edit('form',TARGET)]])
        self.assertFalse(t.ensure_schedule_time(TARGET))
        self.assertEqual(t.actions,[])

    def successful_fill(self,old):
        form=edit('form',old)
        t=RecordedTrial([[form],[form,edit('popup'),CONFIRM],
                         [form,edit('popup',TARGET),CONFIRM],[edit('form',TARGET)]])
        self.assertTrue(t.ensure_schedule_time(TARGET))
        typed=[a for a in t.actions if a[:2]==('ui','type')]
        self.assertEqual(len(typed),1)
        self.assertEqual(typed[0][typed[0].index('--element-id')+1],'popup')
        self.assertEqual(typed[0][typed[0].index('--text')+1],TARGET)
        self.assertEqual(t.actions[-1],('ui','click','--window',123,'--element-id','confirm'))

    def test_blank_time_is_filled(self):
        self.successful_fill('')

    def test_wrong_time_is_replaced(self):
        self.successful_fill('2026-10-21 16:30')

    def test_previous_date_is_replaced(self):
        self.successful_fill('2026-10-20 23:30')

    def test_popup_value_alone_is_not_success(self):
        form=edit('form','')
        t=RecordedTrial([[form],[form,edit('popup'),CONFIRM],
                         [form,edit('popup',TARGET),CONFIRM],[form]])
        with self.assertRaises(RuntimeError):
            t.ensure_schedule_time(TARGET)
        self.assertEqual(sum(a[:2]==('ui','type') for a in t.actions),1)

    def test_unverified_input_does_not_confirm(self):
        form=edit('form')
        t=RecordedTrial([[form],[form,edit('popup'),CONFIRM],
                         [form,edit('popup','wrong'),CONFIRM]])
        with self.assertRaises(RuntimeError):
            t.ensure_schedule_time(TARGET)
        self.assertFalse(any(a[:2]==('ui','click') for a in t.actions))

    def test_ambiguous_popup_stops_without_typing(self):
        form=edit('form')
        t=RecordedTrial([[form],[form,edit('popup1'),edit('popup2'),CONFIRM]])
        with self.assertRaises(RuntimeError):
            t.ensure_schedule_time(TARGET)
        self.assertFalse(any(a[:2]==('ui','type') for a in t.actions))

if __name__=='__main__':
    unittest.main()
