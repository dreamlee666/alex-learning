import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from deployment.study_store import StudyStore
from deployment.study_routes import install_study_routes


class ImportQueueTests(unittest.TestCase):
    def test_large_mixed_batch_serial_parser_dedup_and_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StudyStore(directory)
            original = store.process_import
            active = maximum = 0
            lock = threading.Lock()
            def parse(bid):
                nonlocal active, maximum
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                try:
                    time.sleep(.01)
                    original(bid)
                finally:
                    with lock: active -= 1
            app = FastAPI()
            with patch('deployment.study_routes.StudyStore', return_value=store):
                install_study_routes(app, lambda r: None, 'test', None, lambda: {})
            with patch.object(store, 'process_import', side_effect=parse), TestClient(app) as client:
                files = [('files', (f'课程/主题{i}/教材.md', f'Chapter {i}: unique learning material. '.encode()*20)) for i in range(12)]
                files += [('files', ('skip.jpg', b'unsupported')), ('files', ('blank.txt', b'   '))]
                result = client.post('/study/import', files=files)
                self.assertEqual(result.status_code, 200)
                data = result.json()
                self.assertEqual(len(data['ids']), 13)
                self.assertIn('error', data['results'][12])
                for _ in range(300):
                    books = store.books()
                    if all(b['status'] in ('ready', 'failed') for b in books): break
                    time.sleep(.01)
                self.assertEqual(sum(b['status']=='ready' for b in books), 12)
                self.assertEqual(maximum, 1)
                self.assertTrue(any(b['source_path']=='课程/主题0/教材.md' for b in books))
                duplicate = client.post('/study/import', files=files[:1]).json()['results'][0]
                self.assertTrue(duplicate['duplicate'])
                self.assertEqual(len(store.books()), 13)
                failed = next(b for b in books if b['status']=='failed')
                # Simulate a repaired original, then retry without duplicating the book.
                (store.directory/'originals'/(failed['id']+'.txt')).write_text('Repaired readable material. '*20)
                self.assertEqual(client.post('/study/import/retry', json={'id':failed['id']}).status_code, 200)
                for _ in range(300):
                    if all(b['status']=='ready' for b in store.books()): break
                    time.sleep(.01)
                self.assertTrue(all(b['status']=='ready' for b in store.books()))
                plan = store.create_plan({'subject':'Batch course','start':'2026-10-11','minutes':30,'books':data['ids']})
                self.assertEqual(len(plan['config']['books']), 13)

    def test_restart_recovers_uploaded_queue_and_interrupted_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StudyStore(directory)
            ids = [store.begin_import(f'{i}.txt', f'Durable book {i}. '.encode()*30)[0] for i in range(8)]
            self.assertFalse(store.begin_import('same.txt', b'Durable book 0. '*30)[1])
            with store.connect() as c:
                c.execute("UPDATE books SET status='processing',progress=5 WHERE id=?", (ids[0],))
            reopened = StudyStore(directory)
            app = FastAPI()
            with patch('deployment.study_routes.StudyStore', return_value=reopened):
                install_study_routes(app, lambda r: None, 'test', None, lambda: {})
            with TestClient(app):
                for _ in range(300):
                    if all(b['status']=='ready' for b in reopened.books()): break
                    time.sleep(.01)
                self.assertEqual({b['id'] for b in reopened.books()}, set(ids))
                self.assertTrue(all(b['status']=='ready' for b in reopened.books()))


if __name__ == '__main__': unittest.main()
