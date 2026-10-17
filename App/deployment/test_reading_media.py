import asyncio
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock,patch

import fitz
import httpx
import numpy as np
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from deployment import reading,workspace,reading_media,study_store,vision
from deployment.study_store import StudyStore


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=StudyStore(self.tmp.name)
        reading.init(self.store);workspace.init(self.store);reading_media.init(self.store)
        with fitz.open() as doc:
            p=doc.new_page();p.insert_text((60,80),'A contract is an agreement supported by consideration.');p=doc.new_page();p.insert_text((60,80),'Second page is different and has more source text.');self.raw=doc.tobytes()
        self.bid,_=self.store.begin_import('Practice.pdf',self.raw);self.store.process_import(self.bid)
        self.sid=reading.save_session(self.store,{'title':'Practice','book_id':self.bid,'language':'bilingual'})['id']
        self.app=FastAPI()
        def check(r):
            if r.headers.get('X-SQE-CSRF')!='test':raise HTTPException(403)
        reading_media.install(self.app,self.store,check);self.client=TestClient(self.app);self.headers={'X-SQE-CSRF':'test'}
    def tearDown(self):self.client.close();self.tmp.cleanup()
    def post(self,route,body):return self.client.post('/study/workspace/media/'+route,json=body,headers=self.headers)
    def external(self,note='External note',other_page=False):
        with fitz.open(stream=self.raw,filetype='pdf') as doc:
            p=doc[0];mark=p.add_highlight_annot(p.search_for('contract'));mark.set_info(content=note);mark.update()
            if other_page:doc[1].insert_text((60,110),'Changed content')
            return doc.tobytes()
    def marks(self):
        with self.store.connect() as c:return [dict(r) for r in c.execute('SELECT * FROM reading_annotations')]
    def test_verified_import_is_idempotent(self):
        raw=self.external();result=reading_media.import_annotations(self.store,self.sid,raw)
        self.assertEqual(result['added'],1);self.assertIn('contract',self.marks()[0]['quote'])
        self.assertEqual(reading_media.import_annotations(self.store,self.sid,raw)['added'],0)
        self.assertEqual(len(self.marks()),1)
    def test_changed_page_rejects_entire_import(self):
        with self.assertRaises(ValueError):reading_media.import_annotations(self.store,self.sid,self.external(other_page=True))
        self.assertEqual(self.marks(),[])
    def test_rotated_version_rejected(self):
        with fitz.open(stream=self.raw,filetype='pdf') as doc:doc[0].set_rotation(90);raw=doc.tobytes()
        with self.assertRaises(ValueError):reading_media.import_annotations(self.store,self.sid,raw)
    def add_local(self):
        with fitz.open(stream=self.raw,filetype='pdf') as doc:
            r=doc[0].search_for('contract')[0];p=doc[0];rect=[r.x0/p.rect.width,r.y0/p.rect.height,r.x1/p.rect.width,r.y1/p.rect.height]
        workspace.annotation(self.store,{'session_id':self.sid,'page':1,'quote':'contract','note':'Local note','rects':[rect]})
    def test_export_roundtrip_no_duplicate_and_changed_note_retains_both(self):
        self.add_local();raw=workspace.pdf_export(self.store,self.bid)
        with fitz.open(stream=raw,filetype='pdf') as doc:
            p=doc[0];mark=next(p.annots());self.assertTrue(mark.info['id'].startswith('alex:'))
        self.assertEqual(reading_media.import_annotations(self.store,self.sid,raw)['added'],0)
        with fitz.open(stream=raw,filetype='pdf') as doc:
            p=doc[0];mark=next(p.annots());mark.set_info(content='External revision');mark.update();changed=doc.tobytes()
        result=reading_media.import_annotations(self.store,self.sid,changed)
        self.assertEqual(result['conflicts'],1);self.assertEqual(len(self.marks()),2)
        self.assertEqual(self.marks()[0]['note'],'Local note')
        self.assertEqual(reading_media.import_annotations(self.store,self.sid,changed)['added'],0)
    def test_external_deletion_never_erases_local(self):
        self.add_local();reading_media.import_annotations(self.store,self.sid,self.raw);self.assertEqual(len(self.marks()),1)
    def test_ocr_normalizes_boxes_and_caches_without_second_inference(self):
        class Result:
            txts=['contract'];boxes=np.array([[[10,20],[80,20],[80,40],[10,40]]]);scores=[.97]
        calls=[]
        def engine(image):calls.append(image.shape);return Result()
        with patch.object(study_store,'OCR_ENGINE',engine):
            r=reading_media.scan_page(self.store,self.sid,1);self.assertEqual(r['regions'][0]['text'],'contract')
            self.assertTrue(all(0<=x<=1 for x in r['regions'][0]['rect']))
            self.assertTrue(reading_media.scan_page(self.store,self.sid,1)['cached']);self.assertEqual(len(calls),1)
    def test_page_image_is_only_selected_page(self):
        image=reading_media.page_image(self.store,self.sid,2)
        raw=base64.b64decode(image.split(',',1)[1]);self.assertTrue(raw.startswith(b'\x89PNG'))
        with self.assertRaises(ValueError):reading_media.page_image(self.store,self.sid,3)
    def test_vision_requires_explicit_send_and_csrf(self):
        body={'session_id':self.sid,'page':1,'question':'Explain this chart'}
        self.assertEqual(self.post('visual',body).status_code,400)
        self.assertEqual(self.client.post('/study/workspace/media/visual',json={**body,'send_page':True}).status_code,403)
    def test_vision_saved_as_ai_evidence_and_bound_to_page(self):
        calls=[]
        async def callback(prompt,image):calls.append((prompt,image));yield 'Visible words: A contract is an agreement.'
        self.app.state.reading_vision=callback
        r=self.post('visual',{'session_id':self.sid,'page':1,'question':'What does this say?','send_page':True})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(len(calls),1)
        turns=reading.detail(self.store,self.sid)['turns'];self.assertEqual(len(turns),2)
        self.assertNotIn('data:image',json.dumps(turns));self.assertEqual(turns[0]['state'],'complete')
        prompt,_=reading.reading_context(self.store,self.sid,'Explain further');self.assertIn('current_page_visual',prompt)
        workspace.position(self.store,self.sid,2);prompt,_=reading.reading_context(self.store,self.sid,'Explain further');self.assertNotIn('current_page_visual',prompt)
    def test_failed_visual_does_not_commit_partial_as_success(self):
        async def callback(*args):yield 'Partial';raise HTTPException(502,'Test interruption')
        self.app.state.reading_vision=callback
        r=self.post('visual',{'session_id':self.sid,'page':1,'question':'Explain','send_page':True})
        self.assertEqual(r.status_code,502)
        turns=reading.detail(self.store,self.sid)['turns'];self.assertEqual(len(turns),1);self.assertEqual(turns[0]['state'],'failed')
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM reading_visuals').fetchone()[0],0)


class VisionTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_responses_image_payload_and_completion(self):
        calls=[]
        def handler(request):
            calls.append(json.loads(request.content));return httpx.Response(200,text='data: '+json.dumps({'type':'response.output_text.delta','delta':'Chart answer'})+'\n\ndata: '+json.dumps({'type':'response.completed'})+'\n\n')
        events=vision.install(lambda:{'provider':'chatgpt','model':'gpt-6.1-sol'},AsyncMock(return_value='test-token'),lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(handler)),asyncio.Semaphore(1),'https://example.test/v1')
        self.assertEqual(''.join([x async for x in events('Explain chart','data:image/png;base64,AAA')]),'Chart answer')
        self.assertEqual(calls[0]['input'][0]['content'][1]['type'],'input_image');self.assertFalse(calls[0]['store'])
    async def test_incomplete_image_reply_raises(self):
        def handler(request):return httpx.Response(200,text='data: '+json.dumps({'type':'response.output_text.delta','delta':'partial'})+'\n\n')
        events=vision.install(lambda:{'provider':'chatgpt','model':'test'},AsyncMock(return_value='test'),lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(handler)),asyncio.Semaphore(1),'https://example.test/v1')
        with self.assertRaises(HTTPException):[x async for x in events('Question','data:image/png;base64,AAA')]
