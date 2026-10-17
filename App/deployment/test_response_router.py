from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from deployment.response_router import local_reply, prepare_messages, route_for
from deployment.teaching import preferences, teaching_instructions


class RouterTests(unittest.TestCase):
    def test_scoped_exact_local_answer_and_expiry(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'quick_answers.json').write_text(json.dumps({'verified':'2026-10-13','cards':[{'patterns':['what is IRAC[?]?'],'answer':'Issue, Rule, Application, Conclusion','source_label':'原创学习卡'}]}),encoding='utf-8')
            message={'role':'user','content':'Current study task: [CALBAR_COURSE]\nLearner message: what is IRAC?'}
            self.assertIn('Application',local_reply([message],folder,date(2026,10,13)))
            self.assertIsNone(local_reply([message],folder,date(2026,12,1)))
            self.assertIsNone(local_reply([{'role':'user','content':'what is IRAC?'}],folder,date(2026,10,13)))
            self.assertIsNone(local_reply([{**message,'content':message['content']+' Explain this case in detail.'}],folder,date(2026,10,13)))
    def test_source_reading_is_verbatim_and_scoped(self):
        content='Current study task: [CALBAR_COURSE]\n<material_excerpts>\n[id] supplied text\n</material_excerpts>\nLearner message: 读一下教材原文'
        self.assertIn('[id] supplied text',local_reply([{'role':'user','content':content}],'.'))
        self.assertEqual(route_for('详细分析这个案例'),'deep')
        self.assertEqual(route_for('what does plaintiff mean?'),'brief')
    def test_current_excerpts_and_question_survive_history_compaction(self):
        old='Current study task: <material_excerpts> old text </material_excerpts> Learner message: earlier question'
        current='Current study task: <material_excerpts> CURRENT </material_excerpts> Learner message: analyze case'
        original=[{'role':'system','content':'ORIGINAL SYSTEM'},{'role':'user','content':old},{'role':'assistant','content':'prior answer'},{'role':'user','content':current}]
        prepared,mode=prepare_messages(original)
        self.assertEqual(prepared[-1]['content'],current);self.assertIn({'role':'user','content':'earlier question'},prepared)
        self.assertTrue(any(m['content']=='prior answer' for m in prepared));self.assertEqual(original[1]['content'],old)
        self.assertTrue(any(m['content']=='ORIGINAL SYSTEM' for m in prepared))
    def test_california_mode_preserves_other_courses(self):
        self.assertIn('[CALBAR_COURSE]',teaching_instructions({'mode':'calbar'}))
        self.assertEqual(preferences({'mode':'sqe1'})['mode'],'sqe1')


if __name__=='__main__':unittest.main()
