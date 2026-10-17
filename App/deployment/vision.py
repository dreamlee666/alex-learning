"""Explicit, current-page image requests using the reader's configured provider. MIT."""
import json
import httpx
from fastapi import HTTPException
from .providers import compatible_events


def install(connection,access_token,client_factory,lock,resource):
    async def events(prompt,image):
        config=connection();provider=config.get('provider','chatgpt');model=config.get('model')
        if not model:raise HTTPException(400,'请先连接并选择支持图片输入的模型。')
        async with lock:
            if provider!='chatgpt':
                selected=config.get('api_configs',{}).get(provider)
                if not selected:raise HTTPException(400,'请先保存模型接口。')
                messages=[{'role':'user','content':[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':image}}]}]
                try:
                    async for part in compatible_events(messages,selected,client_factory):yield part
                except HTTPException as e:
                    raise HTTPException(e.status_code,'图像请求失败：请确认当前模型支持图片输入，并检查接口、额度和网络。文字课堂仍可使用。') from e
                return
            token=await access_token()
            payload={'model':model,'store':False,'stream':True,'input':[{'role':'user','content':[{'type':'input_text','text':prompt},{'type':'input_image','image_url':image,'detail':'auto'}]}]}
            from .response_router import reasoning_options
            options=reasoning_options(model,'deep')
            if options:payload['reasoning']=options
            completed=emitted=False
            try:
                async with client_factory(timeout=httpx.Timeout(180,connect=20)) as client:
                    async with client.stream('POST',resource+'/responses',json=payload,headers={'Authorization':'Bearer '+token}) as response:
                        if response.status_code!=200:raise HTTPException(502,'图像请求失败（HTTP '+str(response.status_code)+'）。请确认模型支持图片输入及账号额度。')
                        async for line in response.aiter_lines():
                            if not line.startswith('data:'):continue
                            raw=line[5:].strip()
                            if not raw or raw=='[DONE]':continue
                            event=json.loads(raw)
                            if event.get('type')=='response.output_text.delta':
                                part=event.get('delta','')
                                if part:emitted=True;yield part
                            elif event.get('type')=='response.completed':completed=True
                            elif event.get('type') in ('response.failed','response.incomplete','error'):raise HTTPException(502,'图像模型未完成回答，请重试。')
                if not completed or not emitted:raise HTTPException(502,'图像回答未完整返回，未保存为成功解释。')
            except (httpx.HTTPError,ValueError) as e:raise HTTPException(502,'无法完成图像请求，请检查模型、网络或代理。') from e
    return events
