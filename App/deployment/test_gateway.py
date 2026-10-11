import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock
from urllib.parse import parse_qs, urlparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from deployment import plan_gateway as gateway


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = patch.object(gateway, 'STATE_FILE', Path(self.temp.name) / 'test.dpapi')
        self.storage.start()
        self.client = TestClient(gateway.app, base_url=gateway.ORIGIN)
        gateway.pending.clear()

    def tearDown(self):
        self.storage.stop()
        self.temp.cleanup()

    def test_tokens_encrypted_and_not_exposed_in_status(self):
        dummy = {'access_token': 'test-access-secret', 'refresh_token': 'test-refresh-secret',
                 'scopes': ['chatgpt.tokens.use.direct'], 'expires_at': time.time() + 3600}
        gateway.save_connection(dummy)
        self.assertEqual(gateway.load_connection(), dummy)
        self.assertNotIn(b'test-access-secret', gateway.STATE_FILE.read_bytes())
        self.assertNotIn('test-access-secret', self.client.get('/status').text)

    def test_missing_gateway_auth_rejected(self):
        self.assertEqual(self.client.post('/v1/chat/completions', json={}).status_code, 401)

    def test_network_failure_returns_json(self):
        with patch.object(gateway, 'access_token', AsyncMock(side_effect=httpx.ConnectTimeout('offline test'))):
            response = self.client.get('/models')
        self.assertEqual(response.status_code, 502)
        self.assertIn('网络', response.json()['detail'])

    def test_upstream_uses_windows_proxy(self):
        with patch.object(gateway, 'getproxies', return_value={'https': 'http://127.0.0.1:7897'}), \
             patch.object(gateway.httpx, 'AsyncClient') as client:
            gateway.openai_client(timeout=30)
        client.assert_called_once_with(timeout=30, proxy='http://127.0.0.1:7897', trust_env=False)

    def test_upstream_can_run_without_proxy(self):
        with patch.object(gateway, 'getproxies', return_value={}), \
             patch.object(gateway.httpx, 'AsyncClient') as client:
            gateway.openai_client(timeout=30)
        client.assert_called_once_with(timeout=30, proxy=None, trust_env=False)

    def test_csrf_host_and_origin_rejected(self):
        self.assertEqual(self.client.post('/auth/start', json={}).status_code, 403)
        self.assertEqual(self.client.get('/status', headers={'Host': 'attacker.example'}).status_code, 403)
        self.assertEqual(self.client.post('/auth/start', headers={'Origin': 'https://attacker.example',
            'X-SQE-CSRF': gateway.CSRF}, json={}).status_code, 403)

    def test_pkce_and_state_callback_rejection(self):
        response = self.client.post('/auth/start', json={}, headers={'X-SQE-CSRF': gateway.CSRF})
        query = parse_qs(urlparse(response.json()['url']).query)
        self.assertEqual(query['client_id'], ['dynamic_agent_client'])
        self.assertEqual(query['resource'], [gateway.RESOURCE])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertNotIn('code_verifier', query)
        self.assertEqual(self.client.get('/auth/callback?state=wrong&code=test').status_code, 400)
        state = query['state'][0]
        self.assertEqual(self.client.get('/auth/callback?state=' + state + '&error=access_denied').status_code, 400)
        self.assertNotIn(state, gateway.pending)

    def test_no_inference_without_plan_permission(self):
        gateway.save_connection({'access_token': 'identity-only', 'scopes': ['openid']})
        with self.assertRaises(HTTPException) as failure:
            asyncio.run(gateway.access_token())
        self.assertEqual(failure.exception.status_code, 401)

    def test_messages_converted_without_system_items(self):
        instructions, inputs = gateway.convert_messages([{'role': 'system', 'content': 'Tutor rules'},
            {'role': 'user', 'content': 'Hello'}, {'role': 'assistant', 'content': 'Welcome'}])
        self.assertEqual(instructions, 'Tutor rules')
        self.assertEqual([item['role'] for item in inputs], ['user', 'assistant'])
        with self.assertRaises(HTTPException):
            gateway.convert_messages([{'role': 'user', 'content': [{'type': 'input_audio'}]}])

    def run_stream(self, terminal):
        gateway.save_connection({'access_token': 'dummy-test-token', 'scopes': ['chatgpt.tokens.use.direct'],
            'expires_at': time.time() + 3600, 'client_id': 'test-client'})
        observed = []
        def upstream(request):
            observed.append(json.loads(request.content))
            self.assertEqual(str(request.url), gateway.RESOURCE + '/responses')
            events = [{'type': 'response.output_text.delta', 'delta': 'Hello'}, {'type': terminal}]
            return httpx.Response(200, text=''.join('data: ' + json.dumps(e) + '\n\n' for e in events))
        actual_client = httpx.AsyncClient
        def mock_client(**kwargs):
            return actual_client(transport=httpx.MockTransport(upstream))
        async def collect():
            return [part async for part in gateway.response_events([{'role': 'system', 'content': 'Tutor'},
                {'role': 'user', 'content': 'Hi'}], 'test-model')]
        with patch.object(gateway.httpx, 'AsyncClient', mock_client):
            result = asyncio.run(collect())
        payload = observed[0]
        self.assertEqual(set(payload), {'model', 'input', 'instructions', 'store', 'stream'})
        self.assertFalse(payload['store'])
        self.assertTrue(payload['stream'])
        return result

    def test_classroom_text_parts_are_converted(self):
        instructions, inputs = gateway.convert_messages([
            {'role': 'system', 'content': 'Tutor'},
            {'role': 'user', 'content': [{'type': 'text', 'text': 'Start a lesson.'},
                                         {'type': 'input_text', 'text': 'Ask one question.'}]}])
        self.assertEqual(instructions, 'Tutor')
        self.assertEqual(inputs, [{'role': 'user', 'content': 'Start a lesson.\nAsk one question.'}])
        with self.assertRaises(HTTPException):
            gateway.convert_messages([{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {}}]}])

    def test_stream_requires_completed_inference(self):
        self.assertEqual(self.run_stream('response.completed'), ['Hello'])

    def test_failed_and_interrupted_streams_fail(self):
        for terminal in ('response.failed', 'response.incomplete', 'other.event'):
            with self.assertRaises(HTTPException):
                self.run_stream(terminal)


if __name__ == '__main__':
    unittest.main()
