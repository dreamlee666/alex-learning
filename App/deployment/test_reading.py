import json
import tempfile
import unittest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from deployment.study_store import StudyStore
from deployment import reading
from deployment.response_router import prepare_messages


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=StudyStore(self.temp.name);reading.init(self.store)
        self.a,_=self.store.begin_import('book-a.txt',b'Alpha discusses active reading and asking thoughtful questions.');self.store.process_import(self.a)
        self.b,_=self.store.begin_import('book-b.txt',b'Other text: active reading can happen in a spaceship.');self.store.process_import(self.b)
        self.sid=reading.save_session(self.store,{'title':'Book A','book_id':self.a,'language':'zh','location':'Chapter 1'})['id']
        self.calls=0;self.invalid=False
        async def events(messages,model):
            self.calls+=1
            if self.invalid:yield '{}';return
            items=json.loads(messages[-1]['content'])['conversation']
            yield json.dumps(self.report(items),ensure_ascii=False)
        def check(request):
            if request.headers.get('X-SQE-CSRF')!='test':raise HTTPException(403)
        self.app=FastAPI();reading.install(self.app,self.store,check,events,lambda:{'model':'test-model'})
        self.client=TestClient(self.app);self.headers={'X-SQE-CSRF':'test'}
    def tearDown(self):self.client.close();self.temp.cleanup()
    def report(self,items):
        return {'overview':'讨论了主动阅读。','questions':[{'turn_id':t['turn_id'],'question':'invented text ignored','answer_summary':'提出问题帮助理解。','status':'discussed','source_ids':[]} for t in items],
                'connections':[{'idea':'AI延伸示例','example':'工作中也可以先提问。','check_question':'你会先问什么？','source_ids':[]}],'vocabulary':[], 'next_steps':['下次复述一段。'],'uncertainties':['AI解释需要对照原文。']}
    def turn(self,text='如何主动阅读？',reply='先问作者在回答什么问题。',state='complete'):
        _,snapshot=reading.reading_context(self.store,self.sid,text)
        eid=reading.begin_turn(self.store,self.sid,text,snapshot)
        reading.finish_turn(self.store,self.sid,eid,reply,state)
        return eid
    def post(self,path,body):return self.client.post('/study/reading/'+path,json=body,headers=self.headers)
    def test_book_scope_and_reconnect_memory(self):
        prompt,snapshot=reading.reading_context(self.store,self.sid,'active reading')
        self.assertTrue(snapshot['sources']);self.assertTrue(all(s['book_id']==self.a for s in snapshot['sources']))
        self.assertNotIn('spaceship',prompt);self.assertIn('title alone does NOT',prompt)
        self.turn();self.assertIn('如何主动阅读',reading.reading_context(self.store,self.sid,'接着说')[0])
        paper=reading.save_session(self.store,{'title':'Paper book','language':'zh'})
        self.assertEqual(reading.reading_context(self.store,paper['id'],'active reading')[1]['sources'],[])
    def test_selected_source_pinned_and_later_text_excluded(self):
        with self.store.connect() as c:
            cid=self.a[:10]+'-999';c.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?)',(cid,self.a,999,'future','active reading future spoiler','text'))
            from deployment.study_store import tokens
            c.execute('INSERT INTO search VALUES(?,?)',(cid,tokens('active reading future spoiler')))
        data=reading.session(self.store,self.sid);anchor=self.store.book_chunks(self.a)[0]
        reading.save_session(self.store,{**data,'anchor_id':anchor['id'],'passage':anchor['text']})
        _,snap=reading.reading_context(self.store,self.sid,'future active reading')
        self.assertIn(anchor['id'],[s['id'] for s in snap['sources']]);self.assertNotIn(cid,[s['id'] for s in snap['sources']])
    def test_auto_saved_turns_no_fake_completion_and_book_immutable(self):
        self.turn();data=reading.detail(self.store,self.sid);self.assertEqual(len(data['turns']),2)
        self.assertEqual(data['turns'][0]['context']['location'],'Chapter 1')
        reading.finish_turn(self.store,self.sid,data['turns'][0]['exchange_id'],'duplicate')
        self.assertEqual(len(reading.detail(self.store,self.sid)['turns']),2)
        with self.assertRaises(ValueError):reading.save_session(self.store,{**data,'title':'Book B'})
        self.assertEqual(self.store.courses(),[])
    def test_summary_uses_real_questions_cache_and_stale_flag(self):
        self.turn('我不懂这句为什么要主动提问？')
        r=self.post('summarize',{'id':self.sid,'close':True});self.assertEqual(r.status_code,200,r.text)
        data=r.json();self.assertEqual(data['status'],'closed');self.assertEqual(data['summary']['report']['questions'][0]['question'],'我不懂这句为什么要主动提问？')
        self.assertEqual(self.post('summarize',{'id':self.sid}).status_code,200);self.assertEqual(self.calls,1)
        with self.assertRaises(ValueError):reading.reading_context(self.store,self.sid,'问问题')
        self.post('status',{'id':self.sid,'status':'active'});self.turn('还有什么？')
        self.assertTrue(reading.detail(self.store,self.sid)['summary_stale'])
        exported=self.client.get('/study/reading/export/'+self.sid).text;self.assertIn('还有什么',exported);self.assertIn('完整原始记录',exported)
    def test_failed_summary_retains_raw_data_and_does_not_close(self):
        self.turn();self.invalid=True
        r=self.post('summarize',{'id':self.sid,'close':True});self.assertEqual(r.status_code,400)
        data=reading.detail(self.store,self.sid);self.assertEqual(data['status'],'active');self.assertEqual(len(data['turns']),2);self.assertIsNone(data['summary'])
    def test_unanswered_interrupted_and_unknown_source(self):
        self.turn(reply='',state='error');data=reading.detail(self.store,self.sid);items=reading.questions(data)
        report=self.report([{'turn_id':items[0]['id']}]);parsed=reading.parse_report(json.dumps(report),items)
        self.assertEqual(parsed['questions'][0]['status'],'unanswered')
        report['questions'][0]['source_ids']=['invented']
        with self.assertRaises(ValueError):reading.parse_report(json.dumps(report),items)
        with self.assertRaises(ValueError):reading.parse_report('{}',items)
    def test_batch_summarization_keeps_every_question(self):
        for i in range(12):self.turn(f'问题 {i}')
        r=self.post('summarize',{'id':self.sid});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(len(r.json()['summary']['report']['questions']),12);self.assertEqual(self.calls,2)
    def test_batch_can_reference_an_earlier_verified_excerpt(self):
        self.turn('active reading');self.turn('问题二')
        batch=reading.questions(reading.detail(self.store,self.sid))
        known=batch[0]['context']['sources'][0]['id'];batch[1]['context']['sources']=[]
        report=self.report([{'turn_id':t['id']} for t in batch]);report['questions'][1]['source_ids']=[known]
        parsed=reading.parse_report(json.dumps(report),batch)
        self.assertEqual(parsed['questions'][1]['source_ids'],[known])
    def test_csrf_pending_and_validation(self):
        self.assertEqual(self.client.post('/study/reading/save',json={}).status_code,403)
        self.assertEqual(self.post('save',{'title':'','language':'zh'}).status_code,400)
        self.assertEqual(self.post('save',{'title':'x','language':'zh','book_id':'missing'}).status_code,400)
        eid=reading.begin_turn(self.store,self.sid,'pending',{})
        self.assertEqual(self.post('summarize',{'id':self.sid}).status_code,400)
        self.assertEqual(self.post('status',{'id':self.sid,'status':'closed'}).status_code,400)
        reading.finish_turn(self.store,self.sid,eid,'','interrupted')
        self.assertEqual(self.post('status',{'id':self.sid,'status':'closed'}).status_code,200)
    def test_history_compaction_preserves_latest_sources(self):
        old='Current reading session: lots of old text\nLearner message: old question'
        new=reading.reading_context(self.store,self.sid,'为什么这样？')[0]
        prepared,_=prepare_messages([{'role':'user','content':old},{'role':'assistant','content':'explanation'},{'role':'user','content':new}])
        self.assertEqual(prepared[-1]['content'],new);self.assertIn({'role':'user','content':'old question'},prepared)
        self.assertNotIn('legal analysis',prepared[0]['content'])


if __name__=='__main__':unittest.main()
