import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from deployment.study_store import StudyStore
from deployment import semantic,adaptive,companion,workspace,reading
from deployment.response_router import prepare_messages,reasoning_options,route_for


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=StudyStore(self.temp.name);semantic.init(self.store);workspace.init(self.store)
        self.a,_=self.store.begin_import('Contract.txt',b'Acceptance sent through the postal system is effective on dispatch.');self.store.process_import(self.a)
        self.b,_=self.store.begin_import('Space.txt',b'A fleet of spaceships can cross the galaxy.');self.store.process_import(self.b)
        semantic.STOP.clear()
        def embed(store,texts,query=False):return np.array([[1.,0.,0.] if 'postal' in t or '信件' in t else [0.,1.,0.] for t in texts],dtype='float32')
        self.patches=[patch.object(semantic,'ensure_model'),patch.object(semantic,'installed',return_value=True),patch.object(semantic,'embed',side_effect=embed)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def test_cross_language_retrieval_and_book_filter(self):
        semantic.build_index(self.store)
        hits=self.store.retrieve('信件何时有效',[self.a])
        self.assertTrue(hits);self.assertEqual(hits[0]['book_id'],self.a);self.assertEqual(hits[0]['retrieval'],'semantic')
        self.assertEqual(semantic.search(self.store,'信件何时有效',[self.b]),[])
    def test_incremental_refresh_preserves_other_books(self):
        semantic.build_index(self.store)
        with patch.object(semantic,'embed',side_effect=AssertionError('unchanged content must not re-embed')):
            semantic.build_index(self.store,[self.a])
        self.assertTrue(semantic.search(self.store,'spaceships',[self.b]))
    def test_changed_notes_are_not_returned_from_stale_vectors(self):
        with self.store.connect() as c:c.execute('INSERT INTO workspace_notes VALUES(?,?,?,?)',('note.md','h',self.a,'postal memory'))
        semantic.build_index(self.store,[self.a]);self.assertTrue(semantic.search(self.store,'信件',[self.a],kind='note'))
        with self.store.connect() as c:c.execute("UPDATE workspace_notes SET text='edited unrelated note'")
        self.assertFalse(semantic.search(self.store,'信件',[self.a],kind='note'))
        semantic.build_index(self.store,notes_only=True)
        self.assertTrue(semantic.search(self.store,'信件',[self.a]))
    def test_missing_model_falls_back_to_lexical_without_downloading(self):
        with patch.object(semantic,'installed',return_value=False),patch.object(semantic,'ensure_model',side_effect=AssertionError('search must not download')):
            self.assertTrue(self.store.retrieve('postal',[self.a]))


class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=StudyStore(self.temp.name);adaptive.init(self.store);companion.init(self.store)
        bid,_=self.store.begin_import('sample.txt',b'A practice book about reading and language.');self.store.process_import(bid)
        self.plan=self.store.create_plan({'books':[bid],'subject':'Practice','start':'2026-10-17','minutes':60});self.tid=self.plan['tasks'][0]['id'];self.pid=self.plan['id']
    def tearDown(self):self.temp.cleanup()
    def attempt(self,i,correct):
        with self.store.connect() as c:c.execute('INSERT INTO board_attempts VALUES(?,?,?,?,?,?,?)',(str(i),self.tid,'version',i,0,int(correct),datetime.now(timezone.utc).isoformat()))
    def test_no_evidence_keeps_baseline_and_never_completes_task(self):
        r=adaptive.recommendation(self.store,self.pid);self.assertEqual(r['mode'],'foundation');self.assertEqual(sum(r['minutes'].values()),60)
        self.assertEqual(self.store.task(self.tid)['status'],'pending')
    def test_repeated_quiz_does_not_masquerade_as_independent_evidence(self):
        for i in range(6):
            with self.store.connect() as c:c.execute('INSERT INTO board_attempts VALUES(?,?,?,?,?,?,?)',(str(i),self.tid,'version',0,0,0,datetime.now(timezone.utc).isoformat()))
        r=adaptive.recommendation(self.store,self.pid);self.assertEqual(r['evidence']['quiz_attempts'],1);self.assertEqual(r['mode'],'foundation')
    def test_weak_practice_changes_time_budget_without_unlocking_content(self):
        for i in range(4):self.attempt(i,False)
        r=adaptive.recommendation(self.store,self.pid);self.assertEqual(r['mode'],'consolidate');self.assertEqual(r['minutes']['recall'],15)
        self.assertEqual(sum(r['minutes'].values()),60);self.assertEqual(self.store.task(self.tid)['status'],'pending')
    def test_english_diagnostic_keeps_dimensions_separate_and_checks_evidence(self):
        value={'content':{'level':'insufficient','evidence':'','feedback':'Need more source evidence.'},'english':{'level':'needs_support','evidence':'It give','feedback':'Use It gives.'},'retry':'Try again.'}
        adaptive.parse_diagnostic(json.dumps(value),'It give examples.','')
        with self.store.connect() as c:c.execute('INSERT INTO learning_diagnostics VALUES(?,?,?,?,?,?,?)',('d',self.tid,self.pid,'It give examples.','',json.dumps(value),datetime.now(timezone.utc).isoformat()))
        r=adaptive.recommendation(self.store,self.pid);self.assertEqual(r['mode'],'language_support');self.assertEqual(sum(r['minutes'].values()),60)
        value['english']['evidence']='Invented learner sentence'
        with self.assertRaises(ValueError):adaptive.parse_diagnostic(json.dumps(value),'It give examples.','')
    def test_old_diagnostic_expires_and_does_not_keep_support_mode_forever(self):
        value={'content':{'level':'needs_support'},'english':{'level':'needs_support'}}
        with self.store.connect() as c:c.execute('INSERT INTO learning_diagnostics VALUES(?,?,?,?,?,?,?)',('old',self.tid,self.pid,'answer','',json.dumps(value),'2000-01-01T00:00:00+00:00'))
        self.assertEqual(adaptive.recommendation(self.store,self.pid)['mode'],'foundation')
    def test_repeating_one_easy_card_does_not_hide_other_weak_cards(self):
        with self.store.connect() as c:
            for i in range(20):c.execute('INSERT INTO recall_reviews VALUES(?,?,?,?,?,?,?,?)',(str(i),'easy',self.pid,'answer',4,'',datetime.now(timezone.utc).isoformat(),'{}'))
            for i in range(3):c.execute('INSERT INTO recall_reviews VALUES(?,?,?,?,?,?,?,?)',('weak'+str(i),'weak'+str(i),self.pid,'answer',1,'',datetime.now(timezone.utc).isoformat(),'{}'))
        r=adaptive.recommendation(self.store,self.pid)
        self.assertEqual(r['evidence']['self_rated_recall_rate'],25);self.assertEqual(r['mode'],'consolidate')


class LatencyPolicyTests(unittest.TestCase):
    def test_model_specific_effort_and_deep_question_detection(self):
        self.assertEqual(reasoning_options('gpt-6.1-sol','brief'),{'effort':'low'})
        self.assertEqual(reasoning_options('gpt-6.1-sol','deep'),{'effort':'high'})
        self.assertIsNone(reasoning_options('unknown-provider-model','brief'))
        self.assertEqual(route_for('Compare these two legal cases.'),'deep')
        self.assertEqual(route_for('why是什么意思？'),'brief')
    def test_word_prompt_is_bounded_but_retains_selected_word_and_source(self):
        data={'title':'Book','location':'page 1','passage':'text '*2000+'exhaustive'+' more '*1000,'material_excerpts':[{'id':'source-1','text':'prefix '*1000+'exhaustive means complete'}],'recent_dialogue':[{'text':'history '*1000,'role':'user'}]*8}
        prompt='Current reading session:\n<reading_data>\n'+json.dumps(data)+'\n</reading_data>\nLearner message: exhaustive是什么意思？'
        messages,_=prepare_messages([{'role':'user','content':prompt}]);body=messages[-1]['content']
        self.assertIn('exhaustive',body);self.assertIn('source-1',body);self.assertLess(len(body),5000)
        deep=prompt.rsplit('Learner message:',1)[0]+'Learner message: 详细分析这个案例'
        prepared,_=prepare_messages([{'role':'user','content':deep}]);self.assertGreater(len(prepared[-1]['content']),10000)


if __name__=='__main__':unittest.main()
