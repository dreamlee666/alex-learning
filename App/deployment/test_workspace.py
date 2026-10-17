import asyncio
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import fitz
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from deployment.study_store import StudyStore
from deployment import reading,workspace
from deployment.response_router import cached_events,local_reply


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=StudyStore(Path(self.temp.name)/'study')
        reading.init(self.store);workspace.init(self.store)
        doc=fitz.open();p=doc.new_page();p.insert_text((50,60),'A contract is an agreement supported by consideration. Illustrative means giving examples.')
        p=doc.new_page();p.insert_text((50,60),'Future chapter: exhaustive coverage of remedies and damages.')
        self.bid,_=self.store.begin_import('Contract.pdf',doc.tobytes());doc.close();self.store.process_import(self.bid)
        self.sid=reading.save_session(self.store,{'title':'Contract','book_id':self.bid,'language':'bilingual'})['id']
        self.plan=self.store.create_plan({'books':[self.bid],'subject':'Law and English','mode':'general','language':'bilingual','level':'beginner','start':'2026-10-17','minutes':60})
        self.tid=self.plan['tasks'][0]['id']
        self.vault=Path(self.temp.name)/'vault';self.vault.mkdir()
        (self.store.directory/'workspace-settings.json').write_text(json.dumps({'vault':str(self.vault)}))
        async def events(messages,model):yield '内容理解：结合教材核对。\n英语表达：An agreement needs consideration.'
        def check(request):
            if request.headers.get('X-SQE-CSRF')!='test':raise HTTPException(403)
        app=FastAPI();workspace.install(app,self.store,check,events,lambda:{'model':'test'})
        self.client=TestClient(app);self.headers={'X-SQE-CSRF':'test'}
    def tearDown(self):self.client.close();self.temp.cleanup()
    def post(self,p,b):return self.client.post('/study/workspace/'+p,json=b,headers=self.headers)
    def summarize(self):
        _,snapshot=reading.reading_context(self.store,self.sid,'What is consideration?')
        eid=reading.begin_turn(self.store,self.sid,'What is consideration?',snapshot);reading.finish_turn(self.store,self.sid,eid,'It supports an agreement.')
        d=reading.detail(self.store,self.sid);turn=d['turns'][0]
        report={'overview':'AI summary','questions':[{'turn_id':turn['id'],'question':turn['text'],'answer_summary':'AI discussion, verify in the source.','source_ids':[],'status':'discussed','location':''}],
                'vocabulary':[{'term':'illustrative','meaning':'giving examples','example':'An illustrative list.','source_ids':[]}],'connections':[],'next_steps':[],'uncertainties':[]}
        with self.store.connect() as c:c.execute('INSERT INTO reading_summaries VALUES(?,?,?,?,?)',('report',self.sid,d['turns'][-1]['id'],json.dumps(report),workspace.stamp()))
    def test_position_is_exact_and_pending_turn_cannot_change_context(self):
        result=workspace.position(self.store,self.sid,1)
        self.assertEqual(result['total'],2);self.assertNotIn('Future chapter',reading.session(self.store,self.sid)['passage'])
        _,snap=reading.reading_context(self.store,self.sid,'Explain current page');eid=reading.begin_turn(self.store,self.sid,'Explain',snap)
        with self.assertRaises(ValueError):workspace.position(self.store,self.sid,2)
        self.assertEqual(self.client.get('/study/workspace/position/'+self.sid).json()['page'],1)
        reading.finish_turn(self.store,self.sid,eid,'Done');workspace.position(self.store,self.sid,2)
        self.assertIn('Future chapter',reading.session(self.store,self.sid)['passage'])
    def test_annotation_validates_geometry_and_pdf_export_retains_it(self):
        body={'session_id':self.sid,'page':1,'quote':'contract','rects':[[.1,.1,.4,.13]],'note':'my note'}
        self.assertEqual(self.post('annotation',body).status_code,200)
        for rect in ([0,0,2,1],[.5,.5,.1,.2],[0,0,float('inf'),1]):
            with self.assertRaises(ValueError):workspace.annotation(self.store,{**body,'rects':[rect]})
        with fitz.open(stream=workspace.pdf_export(self.store,self.bid),filetype='pdf') as d:self.assertEqual(next(d[0].annots()).info['content'],'my note')
    def test_reviews_are_confirmed_idempotent_and_do_not_complete_lesson(self):
        self.summarize();items=workspace.review_candidates(self.store,self.sid)
        body={'session_id':self.sid,'task_id':self.tid,'keys':[i['key'] for i in items]}
        self.assertEqual(workspace.add_reviews(self.store,body)['added'],2)
        self.assertEqual(workspace.add_reviews(self.store,body)['added'],0)
        self.assertEqual(self.store.task(self.tid)['status'],'pending')
        self.assertEqual(self.client.get('/study/workspace/today',params={'plan_id':self.plan['id']}).json()['due_count'],2)
        self.assertEqual(len(self.store.cards(self.plan['id'])),2)
    def test_offline_organization_preserves_words_and_missing_answer(self):
        _,snapshot=reading.reading_context(self.store,self.sid,'illustrative')
        eid=reading.begin_turn(self.store,self.sid,'My exact question',snapshot);reading.finish_turn(self.store,self.sid,eid,'','error')
        d=workspace.organize_local(self.store,self.sid)
        self.assertIn('未调用模型',d['summary']['report']['overview'])
        self.assertEqual(d['summary']['report']['questions'][0]['question'],'My exact question')
        self.assertEqual(d['summary']['report']['questions'][0]['status'],'unanswered')
        self.assertEqual(workspace.review_candidates(self.store,self.sid),[])
    def test_word_selection_keeps_surrounding_page_sources(self):
        workspace.position(self.store,self.sid,1,'illustrative')
        _,snapshot=reading.reading_context(self.store,self.sid,'Explain this word')
        self.assertIn('agreement supported by consideration',snapshot['sources'][0]['text'])
    def test_vault_export_preserves_personal_changes_and_indexes_notes(self):
        self.summarize();r=workspace.export_vault(self.store);self.assertEqual(r['sessions'],1)
        path=next((self.vault/'03_交流记录').glob('*.md'));text=path.read_text(encoding='utf-8');self.assertTrue(text.startswith('---\n'))
        path.write_text(text+'\nMy personal interpretation.\n',encoding='utf-8');workspace.export_vault(self.store)
        self.assertIn('My personal interpretation.',path.read_text(encoding='utf-8'))
        path.write_text(path.read_text(encoding='utf-8').replace('It supports an agreement.','My corrected interpretation.'),encoding='utf-8')
        result=workspace.export_vault(self.store);self.assertTrue(result['conflicts'])
        self.assertIn('My corrected interpretation.',path.read_text(encoding='utf-8'))
        self.assertTrue(workspace.memory(self.store,'consideration',self.bid))
        self.assertFalse(workspace.memory(self.store,'consideration','other-book'))
    def test_assessment_is_saved_without_awarding_progress(self):
        r=self.post('assessment',{'session_id':self.sid,'question':'What supports a contract?','answer':'Agreement need consideration.'})
        self.assertEqual(r.status_code,200);self.assertIn('英语表达',r.json()['feedback'])
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM reading_assessments').fetchone()[0],1)
        self.assertEqual(self.store.task(self.tid)['status'],'pending')
    def test_mutations_need_csrf_and_backup_excludes_credentials(self):
        self.assertEqual(self.client.post('/study/workspace/sync',json={}).status_code,403)
        r=self.client.get('/study/workspace/pdf/nonexistent');self.assertEqual(r.status_code,400)
        (self.store.directory/'connection.dpapi').write_bytes(b'private-model-credential')
        result=self.client.get('/study/workspace/backup');self.assertEqual(result.status_code,200)
        with zipfile.ZipFile(io.BytesIO(result.content)) as z:
            self.assertIn('study/library.sqlite3',z.namelist());self.assertFalse(any('connection' in n for n in z.namelist()))


class CacheTests(unittest.IsolatedAsyncioTestCase):
    def messages(self,passage='An illustrative list.',query='illustrative是什么意思？'):
        return [{'role':'user','content':'Current reading session:\n<reading_data>\n'+json.dumps({'title':'A','location':'1','passage':passage,'language':'bilingual'})+'\n</reading_data>\nLearner message: '+query}]
    async def test_cache_is_contextual_and_does_not_cache_partial_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            calls=[]
            async def producer(messages,model):calls.append(1);yield 'giving examples'
            async def collect(msg):return ''.join([s async for s in cached_events(msg,'model',{},producer,folder)])
            await collect(self.messages());self.assertIn('已保存解释',await collect(self.messages()));self.assertEqual(len(calls),1)
            await collect(self.messages('A different passage.'));self.assertEqual(len(calls),2)
            await collect(self.messages(query='详细分析这个案例'));await collect(self.messages(query='详细分析这个案例'));self.assertEqual(len(calls),4)
            async def failed(messages,model):yield 'partial';raise RuntimeError('network')
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    [s async for s in cached_events(self.messages('new context'),'model',{},failed,folder)]
    def test_local_source_and_saved_word_use_no_model(self):
        self.assertIn('An illustrative list.',local_reply(self.messages(query='读一下当前原文'),'.'))


if __name__=='__main__':unittest.main()
