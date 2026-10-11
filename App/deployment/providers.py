"""OpenAI-compatible providers. Credentials live only in the gateway's DPAPI store."""
import json
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException

PRESETS = {
    'deepseek': ('DeepSeek', 'https://api.deepseek.com/v1'),
    'qwen': ('通义千问 / 百炼', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
    'doubao': ('豆包 / 火山方舟', 'https://ark.cn-beijing.volces.com/api/v3'),
    'ollama': ('Ollama 本地模型', 'http://127.0.0.1:11434/v1'),
    'custom': ('其他兼容 API', ''),
}

def validate_config(body, old):
    provider = body.get('provider')
    if provider not in PRESETS:
        raise ValueError('请选择受支持的 AI 来源。')
    base = str(body.get('base_url', '')).strip().rstrip('/')
    parsed = urlsplit(base)
    local = parsed.hostname in ('127.0.0.1', 'localhost', '::1')
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or (parsed.scheme != 'https' and not (parsed.scheme == 'http' and local)):
        raise ValueError('接口地址须为 HTTPS；本机服务可使用 HTTP。不要在地址中填写密钥或参数。')
    model = str(body.get('model', '')).strip()
    if not model or len(model) > 200:
        raise ValueError('请填写平台给出的模型名称或推理接入点 ID。')
    key = str(body.get('api_key', '')).strip()
    # Never carry a secret to a changed endpoint implicitly.
    if not key and base == old.get('base_url'):
        key = old.get('api_key', '')
    if not key and not (provider == 'ollama' and local):
        raise ValueError('请填写 API 密钥；更换接口地址时需要重新填写。')
    if len(key) > 4096 or '\n' in key or '\r' in key:
        raise ValueError('API 密钥格式无效。')
    return {'base_url': base, 'model': model, 'api_key': key, 'use_proxy': bool(body.get('use_proxy', False)) and not local}

async def compatible_events(messages, config, client_factory):
    headers = {'Authorization': 'Bearer ' + config['api_key']} if config.get('api_key') else {}
    payload = {'model': config['model'], 'messages': messages, 'stream': True}
    client = client_factory(timeout=httpx.Timeout(180, connect=20)) if config.get('use_proxy') else httpx.AsyncClient(timeout=httpx.Timeout(180, connect=20), trust_env=False)
    finished, emitted = False, False
    try:
        async with client:
            async with client.stream('POST', config['base_url'] + '/chat/completions', json=payload, headers=headers) as response:
                if response.status_code != 200:
                    raise HTTPException(502, f'AI 接口返回 HTTP {response.status_code}。请检查密钥、模型名称、额度和接口地址。')
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    raw = line[5:].strip()
                    if raw == '[DONE]':
                        finished = True
                        continue
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        raise HTTPException(502, 'AI 接口返回了无法识别的流式数据。')
                    if event.get('error'):
                        raise HTTPException(502, 'AI 服务未完成回答，请检查服务额度后重试。')
                    for choice in event.get('choices', []):
                        if choice.get('index', 0) != 0:
                            continue
                        reason = choice.get('finish_reason')
                        if reason and reason != 'stop':
                            raise HTTPException(502, 'AI 回答被截断或拒绝，请缩短问题后重试。')
                        finished |= reason == 'stop'
                        content = choice.get('delta', {}).get('content')
                        if isinstance(content, str) and content:
                            emitted = True
                            yield content
        if not finished or not emitted:
            raise HTTPException(502, 'AI 回答连接中断或没有返回正文，请重试。')
    except httpx.RequestError:
        raise HTTPException(502, '无法连接所选 AI，请检查接口地址、网络或代理设置。')
