import unittest
from continuous_trial import Trial


class Probe(Trial):
    def __init__(self, frames):
        self.frames=iter([[{'type':'Document','name':'写日志'},
                           {'type':'Text','name':'本周完成工作'}],*frames])
        self.handle='current-main'
        self.bounds=[0,0,1600,1000]
        self.actions=[]
    def recover_input_window(self):
        pass
    def phase(self, label):
        pass
    def nodes(self):
        return next(self.frames)
    def call(self,*args):
        self.actions.append(args)
        return {}
    def wait(self,predicate,seconds=5):
        for nodes in self.frames:
            found=predicate(nodes)
            if found:return nodes,found
        raise RuntimeError('未完整显示')


def frame(y, edits=1):
    return [{'name':'下周工作计划','type':'Text','click':[650,y,0]}]+[
        {'id':'plan-'+str(i),'name':'','type':'Edit','click':[600+i*20,y+85,0]}
        for i in range(edits)]


class PlanScrollTests(unittest.TestCase):
    def test_bottom_then_up_until_heading_clears_toolbar(self):
        trial=Probe([frame(100),frame(400)])
        self.assertEqual(trial.locate_weekly_plan_editor()['id'],'plan-0')
        directions=[a[a.index('--direction')+1] for a in trial.actions]
        self.assertEqual(directions,['down','up'])
        self.assertTrue(all(a[:2]==('mouse','scroll') for a in trial.actions))

    def test_visible_editor_has_only_one_small_up_scroll(self):
        trial=Probe([frame(400)])
        self.assertEqual(trial.locate_weekly_plan_editor()['id'],'plan-0')
        self.assertEqual(len(trial.actions),2)
        self.assertEqual(trial.actions[-1][-1],'1')

    def test_hidden_edit_uses_only_plan_placeholder_not_remark(self):
        nodes=[{'type':'Text','name':'下周工作计划','click':[650,400,0]},
               {'id':'hidden-plan','type':'Edit','name':'','click':[0,0,0]},
               {'id':'plan-placeholder','type':'Text','name':'请输入','click':[610,485,0]},
               {'type':'Text','name':'备注','click':[650,690,0]},
               {'id':'remark-placeholder','type':'Text','name':'请输入','click':[610,775,0]}]
        trial=Probe([nodes])
        self.assertEqual(trial.locate_weekly_plan_editor()['id'],'plan-placeholder')
        self.assertEqual(len(trial.actions),2)

    def test_ambiguous_editor_never_receives_input(self):
        trial=Probe([frame(400,edits=2)])
        with self.assertRaisesRegex(RuntimeError,'多个编辑器'):
            trial.locate_weekly_plan_editor()
        self.assertTrue(all(a[:2]==('mouse','scroll') for a in trial.actions))

    def test_missing_editor_is_bounded_and_never_pastes(self):
        trial=Probe([[] for _ in range(9)])
        with self.assertRaisesRegex(RuntimeError,'未完整显示'):
            trial.locate_weekly_plan_editor()
        self.assertEqual(len(trial.actions),2)
        self.assertTrue(all(a[:2]==('mouse','scroll') for a in trial.actions))


if __name__=='__main__':
    unittest.main()
