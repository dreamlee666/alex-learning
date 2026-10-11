import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from deployment.study_store import StudyStore
from deployment.learning import parse_pack
from deployment.learning_routes import install_learning_routes
from deployment.providers import validate_config, compatible_events
from deployment import plan_gateway as gateway


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = patch.object(gateway, 'STATE_FILE', Path(self.temp.name)/'test.dpapi')
        self.storage.start()
        self.client = TestClient(gateway.app, base_url=gateway.ORIGIN)
        self.headers = {'X-SQE-CSRF': gateway.CSRF}

    def tearDown(self):
        self.storage.stop()
        self.temp.cleanup()

    def config(self, **changes):
        return {'provider':'deepseek','base_url':'https://example.com/v1','api_key':'secret-test-key','model':'test-model',**changes}

    def test_switch_preserves_oauth_and_encrypts_key(self):
        gateway.save_connection({'access_token':'oauth-test-secret','model':'account-model'})
        r = self.client.post('/provider', json=self.config(), headers=self.headers)
        self.assertEqual(r.status_code, 200)
        for path in ('/providers','/status'):
            self.assertNotIn('secret-test-key', self.client.get(path).text)
            self.assertNotIn('oauth-test-secret', self.client.get(path).text)
        self.assertNotIn(b'secret-test-key', gateway.STATE_FILE.read_bytes())
        self.assertEqual(gateway.load_connection()['access_token'],'oauth-test-secret')
        self.client.post('/provider',json={'provider':'chatgpt'},headers=self.headers)
        self.assertEqual(gateway.load_connection()['model'],'account-model')
        self.assertEqual(gateway.load_connection()['api_configs']['deepseek']['model'],'test-model')

    def test_csrf_and_destination_change_protect_secret(self):
        self.assertEqual(self.client.post('/provider',json=self.config()).status_code,403)
        old=validate_config(self.config(),{})
        self.assertEqual(validate_config(self.config(api_key=''),old)['api_key'],'secret-test-key')
        for url in ('http://example.com/v1','https://user:pass@example.com','https://example.com/?key=x','file:///tmp'):
            with self.assertRaises(ValueError):validate_config(self.config(base_url=url),{})
        with self.assertRaises(ValueError):validate_config(self.config(base_url='https://other.example/v1',api_key=''),old)
        local=validate_config(self.config(provider='ollama',base_url='http://127.0.0.1:11434/v1',api_key='',use_proxy=True),{})
        self.assertFalse(local['use_proxy'])

    def run_stream(self, lines, status=200):
        observed=[]
        def handle(r):
            observed.append(r)
            return httpx.Response(status,text=lines)
        actual=httpx.AsyncClient
        def client(**kwargs):return actual(transport=httpx.MockTransport(handle))
        config=validate_config(self.config(),{})
        async def collect():return [s async for s in compatible_events([{'role':'user','content':'Hello'}],config,client)]
        with patch('deployment.providers.httpx.AsyncClient',client):
            result=asyncio.run(collect())
        self.assertEqual(observed[0].headers['Authorization'],'Bearer secret-test-key')
        self.assertEqual(str(observed[0].url),'https://example.com/v1/chat/completions')
        return result

    def test_compatible_stream_handles_reasoning_and_completion(self):
        stream='data: '+json.dumps({'choices':[{'delta':{'reasoning_content':'private chain'}}]})+'\n\n'
        stream+='data: '+json.dumps({'choices':[{'delta':{'content':'Hello'},'finish_reason':None}]})+'\n\n'
        stream+='data: '+json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n'
        self.assertEqual(self.run_stream(stream),['Hello'])

    def test_failed_empty_truncated_stream_does_not_succeed(self):
        for stream in ('data: [DONE]\n\n','data: '+json.dumps({'choices':[{'delta':{'content':'partial'}}]})+'\n\n','data: '+json.dumps({'error':{'message':'secret-test-key'}})+'\n\n','data: {bad}\n\n','data: '+json.dumps({'choices':[{'delta':{'content':'partial'},'finish_reason':'length'}]})+'\n\n'):
            with self.assertRaises(HTTPException):self.run_stream(stream)
        with self.assertRaises(HTTPException) as error:self.run_stream('secret-test-key',401)
        self.assertNotIn('secret-test-key',error.exception.detail)

    def test_completion_external_provider_does_not_require_oauth(self):
        self.client.post('/provider',json=self.config(),headers=self.headers)
        async def events(*args):yield 'Hello'
        with patch.object(gateway,'response_events',events),patch.object(gateway,'access_token',side_effect=AssertionError('OAuth should not be used')):
            r=self.client.post('/v1/chat/completions',json={'messages':[{'role':'user','content':'Hi'}]},headers={'Authorization':'Bearer '+gateway.LOCAL_KEY})
        self.assertEqual(r.status_code,200)
        self.assertIn('Hello',r.text)


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=StudyStore(self.temp.name)
        bid,_=self.store.begin_import('sample.md',b'Active recall means retrieving knowledge before looking at the answer. Use examples to explain ideas. '*8)
        self.store.process_import(bid)
        self.plan=self.store.create_plan({'subject':'Learning','start':'2026-10-10','minutes':30,'books':[bid]})
        self.task=self.plan['tasks'][0]
        self.source=self.task['chunk_ids'][0]
        self.pack={'summary':'A cited summary ['+self.source+']','cards':[{'kind':kind,'question':'What is recall?','answer':'Retrieve before looking.','source_ids':[self.source]} for kind in ('recall','exercise')]}
        self.app=FastAPI()
        self.calls=[]
        async def events(messages,model):
            self.calls.append(messages)
            yield json.dumps(self.pack)
        def check(request):
            if request.headers.get('x-sqe-csrf')!='test':raise HTTPException(403)
        install_learning_routes(self.app,self.store,check,events,lambda:{'model':'fake-model'})
        self.client=TestClient(self.app)
        self.headers={'X-SQE-CSRF':'test'}

    def tearDown(self):self.temp.cleanup()

    def test_additive_migration_preserves_old_progress(self):
        self.store.complete(self.task['id'],'2026-10-10',note='Keep this note')
        other=StudyStore(self.temp.name)
        self.assertEqual(other.task(self.task['id'])['status'],'done')
        self.assertEqual(other.notes()[0]['text'],'Keep this note')

    def test_pack_validation_rejects_invented_citations(self):
        self.assertEqual(parse_pack(json.dumps(self.pack),{self.source}),self.pack)
        self.pack['cards'][0]['source_ids']=['forged']
        with self.assertRaises(ValueError):parse_pack(json.dumps(self.pack),{self.source})
        with self.assertRaises(ValueError):parse_pack('not json',{self.source})

    def test_generation_uses_recorded_turns_and_deduplicates(self):
        self.store.record_turn(self.task['id'],'user','My explanation of recall')
        for i in range(2):
            r=self.client.post('/study/lesson-pack',json={'id':self.task['id']},headers=self.headers)
            self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(len(self.calls),1)
        self.assertIn('My explanation of recall',self.calls[0][1]['content'])
        self.assertEqual(len(self.store.cards(self.plan['id'],'all')),2)
        self.assertEqual(self.store.task(self.task['id'])['status'],'pending')
        self.assertEqual(self.client.post('/study/lesson-pack',json={'id':self.task['id']}).status_code,403)

    def test_fsrs_persists_answers_and_blocks_duplicate_submission(self):
        self.store.save_pack(self.task['id'],self.pack)
        card=self.store.cards(self.plan['id'])[0]
        due=card['due']
        result=self.store.review_card(card['id'],1,'I forgot','Feedback',due)
        self.assertGreater(datetime.fromisoformat(result['due']),datetime.now(timezone.utc))
        with self.assertRaises(ValueError):self.store.review_card(card['id'],1,'I forgot','',due)
        p=self.store.progress(self.plan['id'])
        self.assertEqual(p['weak'],1)
        self.assertEqual(p['recent_recall_rate'],0)
        self.assertEqual(p['history'][0]['answer'],'I forgot')
        self.assertEqual(StudyStore(self.temp.name).progress(self.plan['id'])['recent_reviews'],1)
        self.store.review_card(card['id'],3,'Now remembered','',result['due'])
        self.assertEqual(self.store.progress(self.plan['id'])['weak'],0)
        self.assertEqual(self.store.progress(self.plan['id'])['recent_recall_rate'],50)

    def test_answers_hidden_until_attempt_and_course_isolated(self):
        self.store.save_pack(self.task['id'],self.pack)
        data=self.client.get('/study/cards',params={'plan_id':self.plan['id']}).json()
        self.assertNotIn('answer',data['cards'][0])
        cid=data['cards'][0]['id']
        self.assertEqual(self.client.post('/study/card-answer',json={'id':cid,'answer':''},headers=self.headers).status_code,400)
        response=self.client.post('/study/card-answer',json={'id':cid,'answer':'Attempt'},headers=self.headers).json()
        self.assertEqual(response['sources'][0]['id'],self.source)
        self.assertEqual(self.store.cards('other-course'),[])
        self.assertIsNone(self.store.progress('other-course'))

    def test_export_contains_summary_sources_answers_and_notes(self):
        self.store.save_pack(self.task['id'],self.pack)
        self.store.add_note(self.task['id'],'My own note')
        export=self.store.learning_export(self.plan['id'])
        for text in ('A cited summary','Retrieve before looking.',self.source,'My own note'):
            self.assertIn(text,export)

    def test_summary_update_preserves_card_schedule(self):
        self.store.save_pack(self.task['id'],self.pack)
        cards=self.store.cards(self.plan['id'],'all')
        self.store.review_card(cards[0]['id'],3,'My answer','',cards[0]['due'])
        previous=self.store.card(cards[0]['id'])
        self.store.save_pack(self.task['id'],{**self.pack,'summary':'Updated summary'},True)
        self.assertEqual(self.store.card(cards[0]['id']),previous)
        self.assertEqual(len(self.store.cards(self.plan['id'],'all')),2)
        self.assertEqual(self.store.lesson_result(self.task['id'])['pack']['summary'],'Updated summary')


if __name__=='__main__':unittest.main()
