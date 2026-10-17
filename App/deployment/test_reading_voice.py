import io
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

from deployment import reading_voice


class ReadingVoiceTests(unittest.TestCase):
    def setUp(self):
        self.voice = AsyncMock(return_value=httpx.Response(200, content=b'RIFF-audio'))
        self.app = FastAPI()
        reading_voice.install(self.app, 'test-local-key', Path(__file__).resolve().parents[1], self.voice)
        self.client = TestClient(self.app)
        self.headers = {'Authorization': 'Bearer test-local-key'}

    def test_audio_routes_require_local_authorization(self):
        self.assertEqual(self.client.post('/v1/audio/speech', json={'input': 'Hello'}).status_code, 401)
        self.assertEqual(self.client.post('/v1/audio/transcriptions', files={'file': ('a.wav', b'audio')}).status_code, 401)

    def test_speech_uses_existing_voice_and_preserves_bilingual_text(self):
        response = self.client.post('/v1/audio/speech', headers=self.headers,
            json={'input': 'Evidence（证据）', 'response_format': 'wav'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('audio/wav', response.headers['content-type'])
        self.voice.assert_awaited_once()
        payload = self.voice.call_args.args[1]
        self.assertEqual(payload['input'], 'Evidence（证据）')
        self.assertEqual(payload['voice'], 'youthful')
        self.assertEqual(payload['model'], 'kokoro-local-youthful')

    def test_invalid_speech_is_rejected_before_synthesis(self):
        for payload in ({'input': ''}, {'input': 'x' * 6001}, {'input': 'Hi', 'response_format': 'mp3'}):
            self.assertEqual(self.client.post('/v1/audio/speech', headers=self.headers, json=payload).status_code, 400)
        self.voice.assert_not_called()

    def test_browser_audio_is_decoded_to_standard_pcm_wav(self):
        original = io.BytesIO()
        with wave.open(original, 'wb') as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(b'\0\0\0\0' * 4800)
        result = reading_voice.wav_for_asr(original.getvalue(), reading_voice.locate_ffmpeg(Path(__file__).resolve().parents[1]))
        with wave.open(io.BytesIO(result), 'rb') as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 16000))
            self.assertEqual(w.getnframes(), 1600)
        self.assertEqual(result[36:40], b'data')

    def test_invalid_audio_is_rejected(self):
        with self.assertRaises(Exception) as error:
            reading_voice.wav_for_asr(b'not an audio file', reading_voice.locate_ffmpeg(Path(__file__).resolve().parents[1]))
        self.assertEqual(error.exception.status_code, 400)


if __name__ == '__main__':
    unittest.main()
