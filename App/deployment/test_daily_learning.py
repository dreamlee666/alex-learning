import json
import tempfile
import unittest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from deployment.study_store import StudyStore,lesson_context
from deployment.daily_learning import init,overview,record,detail,install,BLOCKS


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=StudyStore(self.temp.name);init(self.store)
        book,_=self.store.begin_import('daily.md',b'Issue means the question to be resolved. This is an original study exercise.');self.store.process_import(book)
        self.plan=self.store.create_plan({'mode':'calbar','english_support':True,'daily_mastery':True,'subject':'Daily course','books':[book],'minutes':60,'start':'2026-10-14'})
        self.ids=[self.plan['tasks'][0]['id'],'weekcheck','finalcheck'];cid=self.plan['tasks'][0]['chunk_ids']
        with self.store.connect() as c:
            for i,(tid,week,checkpoint) in enumerate(zip(self.ids,[1,1,48],[False,True,True]),1):
                if i>1:c.execute('INSERT INTO tasks(id,plan_id,due,kind,title,chunk_ids,minutes,position) VALUES(?,?,?,?,?,?,?,?)',(tid,self.plan['id'],'2026-10-14','lesson','Check',json.dumps(cid),60,i))
                c.execute('INSERT INTO daily_units VALUES(?,?,?)',(tid,i,json.dumps({'ordinal':i,'week':week,'checkpoint':checkpoint,'blocks':[],'topic':'Issue','english_goal':'Try simple English'})))
        self.body={'task_id':self.ids[0],'date':'2026-10-14','checks':{k:True for k,_,_ in BLOCKS},'english_output':'The issue is whether a rule applies.','legal_recall':'我能用自己的话说明争点。','metrics':{}}
    def tearDown(self):self.temp.cleanup()
    def checkpoint(self,tid):
        return {**self.body,'task_id':tid,'metrics':{'quiz_total':10,'quiz_correct':7,'legal_score':2,'english_score':2,'question_source':'ai_generated'}}
    def test_required_evidence_and_no_date_auto_advance(self):
        with self.assertRaises(ValueError):record(self.store,{**self.body,'checks':{}})
        with self.assertRaises(ValueError):record(self.store,{**self.body,'english_output':''})
        self.assertEqual(overview(self.store,self.plan['id'])['current']['task_id'],self.ids[0])
        with self.assertRaises(ValueError):record(self.store,self.checkpoint(self.ids[1]))
        self.assertEqual(overview(self.store,self.plan['id'])['completed'],0)
    def test_normal_record_and_idempotent_retry(self):
        self.assertTrue(record(self.store,self.body)['passed']);record(self.store,self.body)
        data=overview(self.store,self.plan['id']);self.assertEqual(data['completed'],1);self.assertEqual(len(data['history']),1)
        self.assertEqual(data['current']['task_id'],self.ids[1]);self.assertTrue(detail(self.store,self.ids[1])['recent_learning'])
    def test_failed_checkpoint_persists_and_retries_same_week(self):
        record(self.store,self.body);body=self.checkpoint(self.ids[1]);body['metrics']['quiz_correct']=5
        result=record(self.store,body);self.assertFalse(result['passed']);self.assertTrue(result['problems'])
        self.assertEqual(overview(self.store,self.plan['id'])['current']['task_id'],self.ids[1])
        self.assertTrue(record(self.store,self.checkpoint(self.ids[1]))['passed'])
    def test_final_check_does_not_accept_segmented_pt_or_generated_pool(self):
        record(self.store,self.body);record(self.store,self.checkpoint(self.ids[1]))
        body=self.checkpoint(self.ids[2]);body['metrics'].update(quiz_total=50,quiz_correct=40,essay_minutes=60,essay_continuous=True,pt_minutes=90,pt_continuous=False)
        result=record(self.store,body);self.assertFalse(result['passed']);self.assertTrue(any('PT' in p for p in result['problems']));self.assertTrue(any('真实' in p for p in result['problems']))
    def test_old_complete_cannot_bypass_daily_checks_and_teacher_gets_plan(self):
        with self.assertRaises(ValueError):self.store.complete(self.ids[0],'2026-10-14')
        prompt,_=lesson_context(self.store,self.ids[0],'Start recall')
        self.assertIn('DAILY SESSION',prompt);self.assertIn('beginner-friendly legal English',prompt)
    def test_final_check_requires_distinct_sets_and_all_timed_work(self):
        record(self.store,self.body);record(self.store,self.checkpoint(self.ids[1]))
        with self.store.connect() as c:
            for label in ('set-A','set-B'):
                data={'week':40,'metrics':{'question_source':'licensed_unseen','set_label':label,'quiz_total':30,'quiz_correct':24}}
                c.execute('INSERT INTO daily_results VALUES(?,?,?,?,?,?)',(label,self.ids[1],'2026-10-14',1,json.dumps(data),'2026-10-14'))
        body=self.checkpoint(self.ids[2]);body['metrics'].update(question_source='licensed_unseen',set_label='set-A',quiz_total=50,quiz_correct=40,essay_minutes=60,essay_continuous=True,pt_minutes=90,pt_continuous=True)
        self.assertFalse(record(self.store,body)['passed'])
        body['metrics']['set_label']='set-C';self.assertTrue(record(self.store,body)['passed'])
        self.assertIsNone(overview(self.store,self.plan['id'])['current'])
    def test_api_has_csrf_and_get_is_read_only(self):
        app=FastAPI()
        def check(r):
            if r.headers.get('X-SQE-CSRF')!='test':raise HTTPException(403)
        install(app,self.store,check)
        with TestClient(app) as client:
            self.assertEqual(client.get('/study/daily',params={'plan_id':self.plan['id']}).json()['completed'],0)
            self.assertEqual(client.post('/study/daily/record',json=self.body).status_code,403)
            self.assertTrue(client.post('/study/daily/record',json=self.body,headers={'X-SQE-CSRF':'test'}).json()['passed'])


if __name__=='__main__':unittest.main()
