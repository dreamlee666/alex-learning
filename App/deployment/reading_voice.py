"""Connect document readers to the classroom's existing local voice engines. MIT."""
import asyncio
import io
from pathlib import Path
import secrets
import shutil
import subprocess
import wave

import httpx
from fastapi import File, HTTPException, Request, UploadFile
from fastapi.responses import Response

MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_SECONDS = 300


def wav_for_asr(raw, ffmpeg):
    """Decode browser recordings to the ASR route's 16 kHz mono PCM WAV."""
    try:
        result = subprocess.run([str(ffmpeg), '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-i', 'pipe:0', '-vn', '-t', str(MAX_SECONDS + 1), '-ar', '16000', '-ac', '1',
            '-f', 's16le', 'pipe:1'], input=raw, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(503, '本机录音解码不可用，请检查 FFmpeg。') from exc
    if result.returncode or not result.stdout:
        raise HTTPException(400, '无法识别这段录音，请重新录制。')
    if len(result.stdout) > MAX_SECONDS * 16000 * 2:
        raise HTTPException(413, '单次录音请控制在5分钟以内。')
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(result.stdout)
    return output.getvalue()


def locate_ffmpeg(root):
    found = shutil.which('ffmpeg')
    if found:
        return Path(found)
    # Source checkout and the currently installed portable copy share this
    # workspace's bundled decoder. No system settings are changed.
    for parent in [root, *list(root.parents)[:3]]:
        candidate = parent / '.deployment' / 'tools' / 'ffmpeg.exe'
        if candidate.is_file():
            return candidate
    raise HTTPException(503, '未找到本机 FFmpeg 录音解码器。')


def install(app, key, root, voice_request):
    def authorize(request):
        if not secrets.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + key):
            raise HTTPException(401, 'Local gateway authorization required')

    @app.post('/v1/audio/speech')
    async def reader_speech(request: Request):
        authorize(request)
        body = await request.json()
        text = body.get('input')
        if not isinstance(text, str) or not text.strip() or len(text) > 6000:
            raise HTTPException(400, '请提供6000字以内的朗读文本。')
        if body.get('response_format', 'wav') != 'wav':
            raise HTTPException(400, '本机伴读声音使用 WAV 格式。')
        response = await voice_request('/v1/audio/speech', {
            'model': 'kokoro-local-youthful', 'voice': 'youthful',
            'response_format': 'wav', 'input': text,
        })
        return Response(response.content, media_type='audio/wav')

    @app.post('/v1/audio/transcriptions')
    async def reader_transcription(request: Request, file: UploadFile = File(...)):
        authorize(request)
        raw = await file.read(MAX_AUDIO_BYTES + 1)
        await file.close()
        if not raw or len(raw) > MAX_AUDIO_BYTES:
            raise HTTPException(413, '录音不能为空且不能超过25MB。')
        wav = await asyncio.to_thread(wav_for_asr, raw, locate_ffmpeg(root))
        try:
            async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                response = await client.post('http://127.0.0.1:32193/asr',
                    files={'file': ('reader.wav', wav, 'audio/wav')})
        except httpx.HTTPError as exc:
            raise HTTPException(503, '本机语音转写暂不可用，请重新启动课堂。') from exc
        if response.status_code != 200:
            raise HTTPException(502, '本机转写失败，请重录或使用文字输入。')
        text = response.json().get('text')
        if not isinstance(text, str):
            raise HTTPException(502, '本机转写返回格式无效。')
        return {'text': text}
