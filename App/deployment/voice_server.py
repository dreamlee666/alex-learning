import os
from pathlib import Path
_PORTABLE_DLL_DIRECTORY = os.add_dll_directory(str(Path(__file__).resolve().parents[2] / '.deployment' / 'vcruntime'))
"""Local Kokoro voice, with a gentle pitch shift and a Chinese Edge TTS bridge."""
import asyncio
from contextlib import asynccontextmanager
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import threading

import edge_tts
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from kokoro_onnx import Kokoro
from kokoro_onnx.config import EspeakConfig
import espeakng_loader
import numpy as np
import onnxruntime as ort
from pydantic import BaseModel, Field
import soundfile as sf
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / 'models' / 'kokoro'
PROFILE_FILE = ROOT / 'deployment' / 'voice-profile.json'
FFMPEG = ROOT.parent / '.deployment' / 'tools' / 'ffmpeg.exe'
LOCAL_KEY = json.loads((ROOT / 'deployment' / 'runtime.json').read_text(encoding='utf-8'))['gateway_key']
PREVIEW_TEXT = "Hey, welcome back! What would you like to learn today? Pick a topic or bring your own materials. We'll explore one idea at a time. Tell me what you think."
MODEL_NAME = 'kokoro-local-youthful'
VOICE_NAME = 'youthful'
DEFAULT_PROFILE = {'pitch_semitones': 4.0, 'speed': 1.02, 'brightness_db': 2.5}


class VoiceProfile(BaseModel):
    pitch_semitones: float = Field(4.0, ge=0, le=4)
    speed: float = Field(1.02, ge=0.85, le=1.15)
    brightness_db: float = Field(2.5, ge=0, le=6)


class SpeechRequest(BaseModel):
    model: str = MODEL_NAME
    voice: str = VOICE_NAME
    input: str = Field(min_length=1, max_length=4000)
    response_format: str = 'wav'
    speed: float = Field(1.0, ge=0.85, le=1.15)


def load_profile():
    value = json.loads(PROFILE_FILE.read_text(encoding='utf-8')) if PROFILE_FILE.exists() else DEFAULT_PROFILE
    return VoiceProfile(**value).model_dump()


def save_profile(profile):
    temporary = PROFILE_FILE.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(profile, indent=2), encoding='utf-8')
    os.replace(temporary, PROFILE_FILE)


class VoiceEngine:
    def __init__(self):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        opts.inter_op_num_threads = 1
        session = ort.InferenceSession(str(MODEL_DIR / 'kokoro-v1.0.onnx'), sess_options=opts, providers=['CPUExecutionProvider'])
        # The Windows eSpeak DLL uses narrow file paths. Keep its data outside
        # the Chinese-named workspace so it can resolve its phoneme tables.
        espeak_data = Path(os.environ['LOCALAPPDATA']) / 'SQEEnglishTutorPortable' / 'espeak-ng-data'
        if not (espeak_data / 'phontab').exists():
            shutil.copytree(espeakng_loader.get_data_path(), espeak_data, dirs_exist_ok=True)
        self.kokoro = Kokoro.from_session(session, str(MODEL_DIR / 'voices-v1.0.bin'),
                                          espeak_config=EspeakConfig(data_path=str(espeak_data)))
        self.style = self.kokoro.get_voice_style('af_sky') * 0.7 + self.kokoro.get_voice_style('af_heart') * 0.3
        self.lock = threading.Lock()

    @staticmethod
    def process_audio(raw, pitch=0, brightness=0):
        factor = 2 ** (pitch / 12)
        effect = (f'rubberband=pitch={factor}:tempo=1:transients=smooth:formant=shifted:pitchq=quality,'
                  f'treble=g={brightness}:f=3000:w=0.5,alimiter=limit=0.92:level=false')
        process = subprocess.run([
            str(FFMPEG), '-hide_banner', '-loglevel', 'error', '-i', 'pipe:0',
            '-af', effect, '-ar', '24000', '-ac', '1', '-f', 'wav', 'pipe:1',
        ], input=raw, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        if process.returncode:
            raise RuntimeError('Audio processing failed')
        return sf.read(io.BytesIO(process.stdout), dtype='float32')[0]

    @staticmethod
    def chinese_audio(text, brightness=0):
        with tempfile.TemporaryDirectory(prefix='sqe-voice-') as temporary:
            path = Path(temporary) / 'speech.mp3'
            edge_tts.Communicate(text, 'zh-CN-XiaoyiNeural', rate='-3%', pitch='+15Hz').save_sync(str(path))
            return VoiceEngine.process_audio(path.read_bytes(), brightness=brightness)

    def render(self, text, speed=1):
        profile = load_profile()
        with self.lock:
            parts = []
            for sentence in re.split(r'(?<=[.!?。！？；;])\s*', text):
                if not sentence.strip() or not any(character.isalnum() for character in sentence):
                    continue
                if re.search(r'[\u3400-\u9fff]', sentence):
                    samples = self.chinese_audio(sentence, profile['brightness_db'])
                else:
                    spoken = re.sub(r'\bSQE\b', 'S Q E', sentence, flags=re.I)
                    samples, rate = self.kokoro.create(spoken, voice=self.style, speed=profile['speed'] * speed, lang='en-us')
                    stream = io.BytesIO()
                    sf.write(stream, samples, rate, format='WAV', subtype='PCM_16')
                    samples = self.process_audio(stream.getvalue(), profile['pitch_semitones'], profile['brightness_db'])
                parts.extend([samples, np.zeros(2400, dtype=np.float32)])
            if not parts:
                raise ValueError('Please provide spoken text.')
            samples = np.concatenate(parts)
            stream = io.BytesIO()
            sf.write(stream, samples, 24000, format='WAV', subtype='PCM_16')
            return stream.getvalue()


engine = None
speech_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app):
    global engine
    engine = await asyncio.to_thread(VoiceEngine)
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def local_only(request, call_next):
    if request.headers.get('host') != '127.0.0.1:32195' or request.headers.get('origin'):
        return JSONResponse({'detail': 'Local server requests required'}, status_code=403)
    if request.url.path != '/health' and not secrets.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + LOCAL_KEY):
        return JSONResponse({'detail': 'Local authorization required'}, status_code=401)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.get('/health')
async def health():
    return {'app': 'sqe-local-voice', 'ready': engine is not None, 'engine': 'Kokoro ONNX',
            'english_local': True, 'chinese_online': True, 'profile': load_profile()}


@app.post('/profile')
async def profile(value: VoiceProfile):
    async with speech_lock:
        save_profile(value.model_dump())
    return load_profile()


@app.post('/v1/audio/speech')
async def speech(value: SpeechRequest):
    if value.model != MODEL_NAME or value.voice != VOICE_NAME or value.response_format != 'wav':
        raise HTTPException(400, 'Use the configured local model, voice and WAV format.')
    if engine is None:
        raise HTTPException(503, 'The local voice is still loading.')
    try:
        async with speech_lock:
            audio = await asyncio.to_thread(engine.render, value.input, value.speed)
        return Response(audio, media_type='audio/wav')
    except Exception:
        raise HTTPException(502, 'Speech generation failed. Chinese speech needs an Edge TTS connection.')


if __name__ == '__main__':
    if '--check' in os.sys.argv:
        import time
        start = time.perf_counter()
        voice = VoiceEngine()
        preview = voice.render(PREVIEW_TEXT)
        destination = ROOT / 'deployment' / 'voice-samples' / 'local-youthful-preview.wav'
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(preview)
        samples, rate = sf.read(io.BytesIO(preview))
        assert len(samples) > rate and np.max(np.abs(samples)) > 0.01
        print(json.dumps({'file': str(destination), 'seconds': len(samples) / rate,
                          'generation_seconds_including_load': round(time.perf_counter() - start, 2),
                          'profile': load_profile(), 'providers': voice.kokoro.sess.get_providers()}))
    else:
        uvicorn.run(app, host='127.0.0.1', port=32195, log_level='warning', access_log=False)
