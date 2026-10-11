import io
import json
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from deployment.study_store import StudyStore
from deployment.companion import install, parse_unit
from deployment.speech_text import speech_runs
from src.open_llm_vtuber.utils.tts_preprocessor import tts_filter


class SpeechTests(unittest.TestCase):
    def test_bold_vocabulary_survives_stage_direction_filter(self):
        text=tts_filter('**upkeep**（维护费） *smiles*',True,True,True,True,True)
        self.assertIn('upkeep',text)
        self.assertNotIn('smiles',text)
        self.assertEqual(list(speech_runs(text)),[('en','upkeep'),('zh','维护费')])

    def test_ordered_bilingual_runs_and_contractions(self):
        self.assertEqual(list(speech_runs("这是 **don't give up**（不要放弃），还有 upkeep（维护费）。")),
            [('zh','这是'),('en',"don't give up"),('zh','不要放弃），还有'),('en','upkeep'),('zh','维护费）。')])

    def test_ascii_gloss_keeps_both_languages(self):
        text=tts_filter('**ship upkeep** (船只维护费) (smiles)',True,True,True,True,True)
        self.assertEqual(list(speech_runs(text)),[('en','ship upkeep'),('zh','船只维护费')])


class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=StudyStore(self.tmp.name)
        bid,_=self.store.begin_import('example.md',b'Recall means remembering without looking. Example: close the book and explain the concept.')
        self.store.process_import(bid)
        self.task=self.store.create_plan({'subject':'Recall','mode':'general','language':'en','start':'2026-10-11','minutes':20,'books':[bid]})['tasks'][0]
        self.sid=self.task['chunk_ids'][0];self.calls=[]
        self.pack={'objectives':['Recall a concept'],'concepts':['Active recall'],'terms':['recall'], 'outline':'Close the book and explain.','quizzes':[{'question':'What is recall?','options':['Remember without looking','Copy the page'],'correct':0,'explanation':'The source says remembering without looking.','source_ids':[self.sid]}]}
        async def events(messages,model):
            self.calls.append(messages)
            yield json.dumps(self.pack) if 'Prepare a short' in messages[0]['content'] else 'Corrected: I study English.'
        app=FastAPI()
        def check(r):
            if r.headers.get('x-sqe-csrf')!='test':raise HTTPException(403)
        install(app,self.store,check,events,lambda:{'model':'fake'})
        self.client=TestClient(app);self.headers={'X-SQE-CSRF':'test'}
    def tearDown(self):self.client.close();self.tmp.cleanup()
    def post(self,path,body):return self.client.post('/study/'+path,json=body,headers=self.headers)
    def prepare(self):
        r=self.post('prepare',{'id':self.task['id']});self.assertEqual(r.status_code,200,r.text);return r.json()
    def test_cached_pack_hides_answers_and_rejects_old_generation(self):
        old=self.prepare();self.prepare();self.assertEqual(len(self.calls),1)
        self.assertNotIn('correct',old['pack']['quizzes'][0]);self.assertNotIn('explanation',old['pack']['quizzes'][0])
        new=self.post('prepare',{'id':self.task['id'],'regenerate':True}).json()
        self.assertNotEqual(old['revision'],new['revision'])
        self.assertEqual(self.post('quiz-answer',{'id':self.task['id'],'revision':old['revision'],'question':0,'choice':0}).status_code,400)
    def test_wrong_answer_enters_course_review_once(self):
        p=self.prepare();body={'id':self.task['id'],'revision':p['revision'],'question':0,'choice':1}
        for _ in range(2):self.assertFalse(self.post('quiz-answer',body).json()['matched'])
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM recall_cards').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM board_attempts').fetchone()[0],2)
    def test_invalid_source_is_not_saved(self):
        self.pack['quizzes'][0]['source_ids']=['invented']
        self.assertEqual(self.post('prepare',{'id':self.task['id']}).status_code,400)
        self.assertIsNone(self.client.get('/study/prepared/'+self.task['id']).json()['pack'])
    def test_edit_invalidates_analysis_and_export_keeps_text(self):
        ident=self.post('expression',{'text':'I studies English','scope':'game'}).json()['id']
        self.post('expression-analyze',{'id':ident});self.post('expression-edit',{'id':ident,'text':'I study English'})
        turn=self.client.get('/study/expressions?scope=game').json()['turns'][0]
        self.assertEqual(turn['analysis'],'');self.assertEqual(turn['text'],'I study English')
        self.assertIn('I study English',self.client.get('/study/expression-export?scope=game').text)
    def test_review_requires_attempt_and_rejects_stale_rating(self):
        self.post('companion/save',{'original':'upkeep','context':'Ship upkeep','explanation':'维护费'})
        data=self.client.get('/study/companion/cards').json()['cards'][0]
        self.assertNotIn('explanation',data)
        self.assertEqual(self.post('companion/reveal',{'id':data['id'],'answer':''}).status_code,400)
        body={'id':data['id'],'due':data['due'],'answer':'维护费','rating':3}
        self.assertEqual(self.post('companion/review',body).status_code,200)
        self.assertEqual(self.post('companion/review',body).status_code,400)
    def test_capture_is_local_ocr_and_requires_csrf(self):
        from PIL import Image
        stream=io.BytesIO();Image.new('RGB',(200,80),'white').save(stream,format='PNG')
        raw=stream.getvalue()
        self.assertEqual(self.client.post('/study/companion/capture',content=raw).status_code,403)
        with patch('deployment.companion.ocr_image',return_value='Ship upkeep'):
            r=self.client.post('/study/companion/capture',content=raw,headers=self.headers)
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['text'],'Ship upkeep');self.assertFalse(self.calls)
        self.assertEqual(self.client.post('/study/companion/capture',content=b'invalid',headers=self.headers).status_code,400)

if __name__=='__main__':unittest.main()
