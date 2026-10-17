"""Local OpenAI Chat Completions adapter for official ChatGPT plan OAuth.

Tokens are encrypted with Windows DPAPI, never sent to the browser or logged.
Protocol: https://developers.openai.com/siwc/token-sharing-open-source
"""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode
from urllib.request import getproxies
import uuid

import httpx
import jwt
import win32crypt
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse, Response
from deployment.providers import PRESETS, validate_config, compatible_events

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ['LOCALAPPDATA']) / 'SQEEnglishTutorPortable'
DATA.mkdir(parents=True, exist_ok=True)
ORIGIN = 'http://127.0.0.1:32194'
CALLBACK = ORIGIN + '/auth/callback'
ISSUER = 'https://auth.openai.com'
TOKEN_URL = ISSUER + '/api/accounts/oauth/token'
RESOURCE = 'https://api.openai.com/v1'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
STATE_FILE = DATA / 'connection.dpapi'
HOST_FILE = DATA / 'host.json'
RUNTIME = ROOT / 'deployment' / 'runtime.json'
LOCAL_KEY = json.loads(RUNTIME.read_text(encoding='utf-8'))['gateway_key']
CSRF = secrets.token_urlsafe(32)
pending = {}
refresh_lock = asyncio.Lock()
inference_lock = asyncio.Semaphore(2)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def openai_client(timeout=30):
    # HTTPX does not read Windows Internet Settings. Use the same proxy as
    # the user's browser, only for upstream OpenAI requests.
    proxies = getproxies()
    proxy = proxies.get('https') or proxies.get('http') or proxies.get('all')
    return httpx.AsyncClient(timeout=timeout, proxy=proxy, trust_env=False)


async def voice_request(path, body=None):
    try:
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            if body is None:
                response = await client.get('http://127.0.0.1:32195' + path)
            else:
                response = await client.post('http://127.0.0.1:32195' + path, json=body,
                                            headers={'Authorization': 'Bearer ' + LOCAL_KEY})
        if response.status_code >= 400:
            detail = response.json().get('detail', '语音生成失败。')
            raise HTTPException(response.status_code, detail)
        return response
    except httpx.HTTPError:
        raise HTTPException(503, '本地语音服务未就绪，请重新启动课堂。')


@app.get('/voice/status')
async def voice_status():
    return (await voice_request('/health')).json()


@app.post('/voice/profile')
async def voice_profile(request: Request):
    check_action(request)
    return (await voice_request('/profile', await request.json())).json()


@app.post('/voice/preview')
async def voice_preview(request: Request):
    check_action(request)
    response = await voice_request('/v1/audio/speech', {
        'model': 'kokoro-local-youthful', 'voice': 'youthful', 'response_format': 'wav',
        'input': "Hey, welcome back! What would you like to learn today? Pick a topic or bring your own materials. We'll explore one idea at a time. Tell me what you think.",
    })
    return Response(response.content, media_type='audio/wav')


def atomic_write(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_bytes(value)
    os.replace(temp, path)


if not HOST_FILE.exists():
    atomic_write(HOST_FILE, json.dumps({'host_id': 'urn:uuid:' + str(uuid.uuid4())}).encode())
HOST_ID = json.loads(HOST_FILE.read_text())['host_id']


def load_connection():
    if not STATE_FILE.exists():
        return {}
    raw = win32crypt.CryptUnprotectData(STATE_FILE.read_bytes(), None, None, None, 0)[1]
    return json.loads(raw)


def save_connection(value):
    raw = json.dumps(value).encode()
    encrypted = win32crypt.CryptProtectData(raw, 'SQE English Tutor', None, None, None, 0)
    atomic_write(STATE_FILE, encrypted)


def check_action(request):
    if not secrets.compare_digest(request.headers.get('x-sqe-csrf', ''), CSRF):
        raise HTTPException(403, 'Please reopen the local settings page.')


@app.middleware('http')
async def local_only(request, call_next):
    if request.headers.get('host') != '127.0.0.1:32194':
        return JSONResponse({'detail': 'Local host required'}, status_code=403)
    origin = request.headers.get('origin')
    if origin and origin != ORIGIN:
        return JSONResponse({'detail': 'Local origin required'}, status_code=403)
    try:
        response = await call_next(request)
    except httpx.RequestError:
        response = JSONResponse({'detail': '无法连接 OpenAI 模型服务，请检查本机网络或代理后重试。'}, status_code=502)
    except httpx.HTTPStatusError:
        response = JSONResponse({'detail': '账号服务拒绝了请求，请检查套餐授权或重新登录。'}, status_code=502)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


def plan_enabled(connection):
    return bool(connection.get('access_token')) and 'chatgpt.tokens.use.direct' in connection.get('scopes', [])


async def access_token():
    async with refresh_lock:
        connection = load_connection()
        if not plan_enabled(connection):
            raise HTTPException(401, '请先打开本地登录页面，连接 ChatGPT 并授权套餐使用。')
        if connection.get('expires_at', 0) > time.time() + 90:
            return connection['access_token']
        if not connection.get('refresh_token'):
            raise HTTPException(401, '登录已到期，请重新连接 ChatGPT。')
        async with openai_client(timeout=30) as client:
            response = await client.post(TOKEN_URL, data={
                'grant_type': 'refresh_token', 'client_id': connection['client_id'],
                'refresh_token': connection['refresh_token'], 'resource': RESOURCE,
            })
        if response.status_code != 200:
            raise HTTPException(401, '无法续期，请在设置页面重新登录 ChatGPT。')
        tokens = response.json()
        connection.update({key: tokens[key] for key in ('access_token', 'refresh_token', 'id_token') if key in tokens})
        connection['expires_at'] = time.time() + tokens.get('expires_in', 3600)
        if 'scope' in tokens:
            connection['scopes'] = tokens['scope'].split()
        save_connection(connection)
        if not plan_enabled(connection):
            raise HTTPException(403, 'ChatGPT 套餐使用授权未启用。')
        return connection['access_token']


@app.get('/')
async def home():
    return HTMLResponse((ROOT / 'deployment' / 'settings.html').read_text(encoding='utf-8').replace('__CSRF__', CSRF))


@app.get('/status')
async def status():
    connection = load_connection()
    provider = connection.get('provider', 'chatgpt')
    return {'app': 'sqe-english-tutor', 'package_instance': json.loads(RUNTIME.read_text(encoding='utf-8'))['package_instance'], 'version': '0.6.0', 'connected': bool(connection.get('access_token')) if provider == 'chatgpt' else bool(connection.get('api_configs', {}).get(provider)), 'provider': provider, 'plan_enabled': plan_enabled(connection),
            'email': connection.get('email', ''), 'model': connection.get('model', ''),
            'tested': connection.get('tested', False)}


@app.get('/providers')
async def providers():
    c = load_connection()
    saved = {p: {k: v for k, v in config.items() if k != 'api_key'} | {'has_key': bool(config.get('api_key'))}
             for p, config in c.get('api_configs', {}).items()}
    return {'selected': c.get('provider', 'chatgpt'), 'saved': saved,
            'presets': {k: {'name': v[0], 'base_url': v[1]} for k, v in PRESETS.items()}}


@app.post('/provider')
async def select_provider(request: Request):
    check_action(request)
    body = await request.json()
    async with refresh_lock:
        c = load_connection()
        previous = c.get('provider', 'chatgpt')
        provider = body.get('provider')
        if previous == 'chatgpt':
            c['chatgpt_model'] = c.get('model', '')
        if provider == 'chatgpt':
            c['model'] = c.get('chatgpt_model', '')
        else:
            try:
                config = validate_config(body, c.get('api_configs', {}).get(provider, {}))
            except ValueError as e:
                raise HTTPException(400, str(e))
            c.setdefault('api_configs', {})[provider] = config
            c['model'] = config['model']
        c.update(provider=provider, tested=False)
        save_connection(c)
    return {'ok': True}


@app.post('/auth/start')
async def start_auth(request: Request):
    check_action(request)
    existing = load_connection()
    state, nonce, verifier = (secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    client_id = existing.get('client_id', 'dynamic_agent_client')
    pending.clear()
    pending[state] = {'nonce': nonce, 'verifier': verifier, 'expires': time.time() + 600,
                      'client_id': client_id, 'subject': existing.get('subject')}
    params = {'client_id': client_id, 'ext_agent_host_id': HOST_ID, 'response_type': 'code',
              'redirect_uri': CALLBACK, 'scope': SCOPES, 'resource': RESOURCE, 'state': state,
              'nonce': nonce, 'code_challenge_method': 'S256', 'code_challenge': challenge}
    if client_id == 'dynamic_agent_client':
        params['agent_name_hint'] = 'Alex Learning Companion'
    elif existing.get('id_token'):
        params['id_token_hint'] = existing['id_token']
    return {'url': ISSUER + '/api/accounts/authorize?' + urlencode(params)}


async def validate_identity(token, client_id, nonce):
    async with openai_client(timeout=30) as client:
        response = await client.get(ISSUER + '/.well-known/jwks.json')
        response.raise_for_status()
        jwks = response.json()
    header = jwt.get_unverified_header(token)
    if header.get('alg') not in ('RS256', 'ES256'):
        raise ValueError('Unexpected signing algorithm')
    jwk = next(item for item in jwks['keys'] if item['kid'] == header['kid'])
    claims = jwt.decode(token, jwt.PyJWK.from_dict(jwk).key, algorithms=[header['alg']],
                        audience=client_id, issuer=ISSUER, leeway=5,
                        options={'require': ['sub', 'exp', 'iat', 'nonce']})
    if not secrets.compare_digest(claims['nonce'], nonce):
        raise ValueError('Nonce mismatch')
    return claims


@app.get('/auth/callback')
async def auth_callback(request: Request):
    params = request.query_params
    attempt = pending.pop(params.get('state', ''), None)
    if not attempt or attempt['expires'] < time.time():
        return HTMLResponse('登录已过期或状态不匹配，请回到设置页面重试。', status_code=400)
    if params.get('error'):
        return HTMLResponse('登录或套餐授权未完成。<a href="/">返回设置</a>', status_code=400)
    client_id = params.get('client_id', attempt['client_id'])
    if client_id == 'dynamic_agent_client' or not params.get('code'):
        return HTMLResponse('未收到完整的应用注册结果。<a href="/">返回设置</a>', status_code=400)
    if attempt['client_id'] != 'dynamic_agent_client' and client_id != attempt['client_id']:
        return HTMLResponse('应用身份不匹配，请重试。', status_code=400)
    try:
        async with refresh_lock:
            existing = load_connection()
            if not existing.get('access_token'):
                save_connection({**existing, 'client_id': client_id})
            async with openai_client(timeout=30) as client:
                response = await client.post(TOKEN_URL, data={
                    'grant_type': 'authorization_code', 'client_id': client_id, 'code': params['code'],
                    'code_verifier': attempt['verifier'], 'redirect_uri': CALLBACK, 'resource': RESOURCE,
                })
                response.raise_for_status()
                tokens = response.json()
            identity = await validate_identity(tokens['id_token'], client_id, attempt['nonce'])
            if attempt['subject'] and identity['sub'] != attempt['subject']:
                raise ValueError('Account identity mismatch')
            save_connection({**existing, 'client_id': client_id, 'subject': identity['sub'], 'email': identity.get('email', ''),
                'access_token': tokens.get('access_token'), 'refresh_token': tokens.get('refresh_token'),
                'id_token': tokens['id_token'], 'scopes': tokens.get('scope', '').split(),
                'expires_at': time.time() + tokens.get('expires_in', 3600), 'model': existing.get('model', ''),
                'tested': False})
        return RedirectResponse('/', status_code=303)
    except Exception:
        return HTMLResponse('授权验证或连接失败。请回到设置页面重新登录；如果仍失败，检查账号功能与网络。<br><a href="/">返回设置</a>', status_code=400)


@app.post('/auth/logout')
async def logout(request: Request):
    check_action(request)
    async with refresh_lock:
        connection = load_connection()
        revoked = not bool(connection.get('refresh_token'))
        if not revoked:
            try:
                async with openai_client(timeout=15) as client:
                    metadata = await client.get(ISSUER + '/.well-known/openid-configuration')
                    metadata.raise_for_status()
                    endpoint = metadata.json()['revocation_endpoint']
                    if not endpoint.startswith(ISSUER + '/'):
                        raise ValueError('Unexpected revocation endpoint')
                    for wait in (0, 1, 2):
                        await asyncio.sleep(wait)
                        response = await client.post(endpoint, data={'token': connection['refresh_token'],
                            'token_type_hint': 'refresh_token', 'client_id': connection['client_id']})
                        if response.status_code == 200:
                            revoked = True
                            break
            except Exception:
                pass
        save_connection({key: connection[key] for key in ('client_id', 'subject', 'provider', 'api_configs') if key in connection} |
                        ({'model': connection.get('model', '')} if connection.get('provider', 'chatgpt') != 'chatgpt' else {}))
    return {'remote_revoked': revoked}


@app.get('/models')
async def models():
    c = load_connection()
    if c.get('provider', 'chatgpt') != 'chatgpt':
        return [{'slug': c['model'], 'display_name': c['model']}]
    token = await access_token()
    async with openai_client(timeout=30) as client:
        response = await client.get(RESOURCE + '/models', headers={'Authorization': 'Bearer ' + token})
    if response.status_code != 200:
        raise HTTPException(502, '无法读取账号可用模型，请检查套餐授权和网络。')
    return [{'slug': item['slug'], 'display_name': item.get('display_name', item['slug'])}
            for item in response.json().get('models', []) if item.get('visibility') == 'list']


@app.post('/model')
async def select_model(request: Request):
    check_action(request)
    selected = (await request.json()).get('model')
    available = await models()
    if selected not in {item['slug'] for item in available}:
        raise HTTPException(400, '请选择账号列表中的模型。')
    async with refresh_lock:
        connection = load_connection()
        connection.update(model=selected, tested=False)
        save_connection(connection)
    return {'ok': True}


def convert_messages(messages):
    instructions, inputs = [], []
    for item in messages:
        role, content = item.get('role'), item.get('content', '')
        if isinstance(content, list):
            if not all(isinstance(part, dict) and part.get('type') in ('text', 'input_text')
                       and isinstance(part.get('text'), str) for part in content):
                if any(isinstance(part, dict) and part.get('type') in ('image_url', 'input_image') for part in content):
                    raise HTTPException(400, 'Image input is not supported by this text-only classroom gateway.')
                raise HTTPException(400, 'This classroom gateway accepts text only.')
            content = '\n'.join(part['text'] for part in content)
        if not isinstance(content, str):
            raise HTTPException(400, 'This classroom gateway accepts text only.')
        if role in ('system', 'developer'):
            instructions.append(content)
        elif role in ('user', 'assistant'):
            inputs.append({'role': role, 'content': content})
        else:
            raise HTTPException(400, 'Unsupported conversation role')
    return '\n\n'.join(instructions), inputs


async def uncached_response_events(messages, model):
    from deployment.response_router import local_reply, prepare_messages
    instructions, inputs = convert_messages(messages)
    messages = ([{'role': 'system', 'content': instructions}] if instructions else []) + inputs
    immediate = local_reply(messages, DATA / 'study')
    if immediate is not None:
        yield immediate
        return
    messages, response_mode = prepare_messages(messages)
    connection = load_connection()
    provider = connection.get('provider', 'chatgpt')
    if provider != 'chatgpt':
        config = connection.get('api_configs', {}).get(provider)
        if not config:
            raise HTTPException(400, '请先在 AI 设置中保存接口配置。')
        instructions, inputs = convert_messages(messages)
        normalized = ([{'role': 'system', 'content': instructions}] if instructions else []) + inputs
        async with inference_lock:
            async for chunk in compatible_events(normalized, config, openai_client):
                yield chunk
        return
    token = await access_token()
    instructions, inputs = convert_messages(messages)
    payload = {'model': model, 'input': inputs, 'instructions': instructions, 'store': False, 'stream': True}
    from deployment.response_router import reasoning_options
    reasoning=reasoning_options(model,response_mode)
    if reasoning:payload['reasoning']=reasoning
    completed = False
    async with inference_lock:
        async with openai_client(timeout=httpx.Timeout(180, connect=20)) as client:
            async with client.stream('POST', RESOURCE + '/responses', json=payload,
                                     headers={'Authorization': 'Bearer ' + token}) as response:
                if response.status_code != 200:
                    raise HTTPException(502, '模型请求失败（HTTP %s），请检查账号授权或套餐额度。' % response.status_code)
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    raw = line[5:].strip()
                    if raw == '[DONE]':
                        continue
                    event = json.loads(raw)
                    if event.get('type') == 'response.output_text.delta':
                        yield event.get('delta', '')
                    elif event.get('type') == 'response.completed':
                        completed = True
                    elif event.get('type') in ('response.failed', 'response.incomplete', 'error'):
                        raise HTTPException(502, '模型未完成回答，请检查套餐额度或重试。')
    if not completed:
        raise HTTPException(502, '回答连接中断，未收到完成确认。')


async def response_events(messages, model):
    from deployment.response_router import cached_events
    async for part in cached_events(messages, model, load_connection(), uncached_response_events, DATA / 'study'):
        yield part


from deployment.study_routes import install_study_routes
install_study_routes(app, check_action, CSRF, response_events, load_connection)


@app.post('/test')
async def test(request: Request):
    check_action(request)
    connection = load_connection()
    if not connection.get('model'):
        raise HTTPException(400, '请先选择并保存一个模型。')
    chunks = [chunk async for chunk in response_events([{'role': 'user', 'content': 'Say exactly: Ready to learn together.'}], connection['model'])]
    async with refresh_lock:
        current = load_connection()
        if current == connection:
            current['tested'] = True
            save_connection(current)
    return {'reply': ''.join(chunks)}


@app.post('/v1/chat/completions')
async def completion(request: Request):
    expected = 'Bearer ' + LOCAL_KEY
    if not secrets.compare_digest(request.headers.get('authorization', ''), expected):
        raise HTTPException(401, 'Local gateway authorization required')
    body = await request.json()
    if body.get('tools'):
        raise HTTPException(400, 'Tools are not supported by this classroom.')
    connection = load_connection()
    model = connection.get('model')
    if not model:
        raise HTTPException(400, '请先在本地设置页面选择模型。')
    messages = body.get('messages', [])
    convert_messages(messages)
    ident = 'chatcmpl-' + uuid.uuid4().hex
    # Reading clients and standard SDK probes also use non-streaming calls.
    # Collect the same verified upstream stream so failures cannot look like
    # successful partial answers, and never invent token-usage counters.
    if not body.get('stream', False):
        parts = [part async for part in response_events(messages, model)]
        return JSONResponse({'id': ident, 'object': 'chat.completion',
            'created': int(time.time()), 'model': model,
            'choices': [{'index': 0, 'message': {'role': 'assistant',
                'content': ''.join(parts)}, 'finish_reason': 'stop'}]})
    async def stream():
        def encode(delta, finish=None):
            return 'data: ' + json.dumps({'id': ident, 'object': 'chat.completion.chunk', 'created': int(time.time()),
                'model': model, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}) + '\n\n'
        yield encode({'role': 'assistant'})
        try:
            async for delta in response_events(messages, model):
                yield encode({'content': delta})
            yield encode({}, 'stop')
            yield 'data: [DONE]\n\n'
        except HTTPException as error:
            yield 'data: ' + json.dumps({'error': {'message': error.detail, 'type': 'gateway_error', 'code': 'inference_failed'}}) + '\n\n'
        except Exception:
            yield 'data: ' + json.dumps({'error': {'message': '模型连接失败，请检查网络并重试。', 'type': 'gateway_error'}}) + '\n\n'
    return StreamingResponse(stream(), media_type='text/event-stream')


from deployment.reading_voice import install as install_reading_voice
install_reading_voice(app, LOCAL_KEY, ROOT, voice_request)
