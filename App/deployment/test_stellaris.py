import json
from pathlib import Path
import tempfile
import unittest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from deployment.stellaris_library import StellarisLibrary, game_context
from deployment.companion import install
from deployment.study_store import StudyStore


class GameLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for language in ('english','simp_chinese'):(self.root/'game/localisation'/language).mkdir(parents=True)
        (self.root/'game/localisation/english/test.yml').write_text('l_english:\n UPKEEP:0 "§YUpkeep§!"\n FLEET:0 "Fleet upkeep increases."\n REF: "$UPKEEP$ £energy£ [Root.GetName]"\n CYCLE: "$CYCLE$"\n QUOTE: "Say \\"hello\\""\n',encoding='utf-8-sig')
        (self.root/'game/localisation/simp_chinese/test.yml').write_text('l_simp_chinese:\n FLEET: "舰队维护费增加。"\n UPKEEP: "维护费"\n',encoding='utf-8-sig')
        self.lib=StellarisLibrary(self.root/'data');self.result=self.lib.import_game(self.root/'game')
    def tearDown(self):self.tmp.cleanup()
    def test_key_join_and_formatting(self):
        self.assertEqual(self.result['paired'],2)
        rows=self.lib.search('upkeep');self.assertEqual(rows[0]['english'],'Upkeep');self.assertEqual(rows[0]['chinese'],'维护费')
        with self.lib.connect() as c:
            self.assertEqual(c.execute('SELECT english FROM entries WHERE key="QUOTE"').fetchone()[0],'Say "hello"')
            self.assertEqual(c.execute('SELECT english FROM entries WHERE key="CYCLE"').fetchone()[0],'[动态文本]')
            self.assertEqual(c.execute('SELECT english FROM entries WHERE key="REF"').fetchone()[0],'Upkeep [动态文本]')
    def test_unchanged_import_and_failed_import_preserve_data(self):
        self.assertTrue(self.lib.import_game(self.root/'game')['unchanged'])
        with self.assertRaises(ValueError):self.lib.import_game(self.root/'wrong')
        self.assertEqual(self.lib.status()['entries'],5)
    def test_inflection_and_ocr_candidate(self):
        self.assertTrue(self.lib.search('fleets'))
        rows=self.lib.match_screen('Fleet upkeep increases.');self.assertEqual(rows[0]['key'],'FLEET');self.assertEqual(rows[0]['similarity'],1)
    def test_prompt_contains_selected_context_and_export(self):
        prompt=game_context(self.root/'data','Explain the word "upkeep"','Current screen text')
        self.assertIn('Current screen text',prompt);self.assertIn('维护费',prompt);self.assertNotIn('Say',prompt)
        self.lib.export(self.root/'export');self.assertTrue((self.root/'export/群星英汉词句.csv').exists())
    def test_api_requires_csrf_and_accepts_clipboard(self):
        app=FastAPI();store=StudyStore(self.root/'data')
        def check(r):
            if r.headers.get('X-SQE-CSRF')!='test':raise HTTPException(403)
        async def events(*args):yield 'unused'
        install(app,store,check,events,lambda:{})
        with TestClient(app) as client:
            self.assertEqual(client.post('/study/companion/text-capture',json={'text':'Fleet upkeep'}).status_code,403)
            result=client.post('/study/companion/text-capture',json={'text':'Fleet upkeep'},headers={'X-SQE-CSRF':'test'})
            self.assertEqual(result.status_code,200);self.assertEqual(result.json()['text'],'Fleet upkeep')
            self.assertEqual(client.get('/study/stellaris/status').json()['entries'],5)
            self.assertEqual(client.get('/study/stellaris/search',params={'q':'upkeep'}).json()['matches'][0]['chinese'],'维护费')
            self.assertEqual(client.post('/study/stellaris/import',json={'path':str(self.root/'wrong')},headers={'X-SQE-CSRF':'test'}).status_code,400)


if __name__=='__main__':unittest.main()
