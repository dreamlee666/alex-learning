"""Conservative local answers and prompt routing, with no hidden model calls. MIT."""
from datetime import date
import json
from pathlib import Path
import re
import time


def learner_message(messages):
    last=next((m.get('content','') for m in reversed(messages) if m.get('role')=='user'),'')
    if not isinstance(last,str):return '', ''
    return last,last.rsplit('Learner message: ',1)[-1].strip()


def route_for(query):
    if word_question(query):return 'brief'
    if re.search(r'\b(compare|contrast|analy[sz]e|evaluate|critique|why)\b',query,re.I):return 'deep'
    if re.search(r'深入|详细|仔细|(?:用|做|apply|use).*IRAC|IRAC.*(?:分析|analysis)|essay|performance test|批改|评分|案例|案情|为什么|比较|分析.*事实',query,re.I) or len(query)>300:return 'deep'
    if re.fullmatch(r'(?:请|帮我)?(?:读|念|显示|查)(?:一下)?(?:当前|这段|教材)(?:的)?(?:原文|内容)?[。！？?\s]*',query):return 'source'
    return 'brief'


def local_reply(messages,directory,today=None):
    last,query=learner_message(messages)
    if last.startswith('Current reading session:'):
        try:
            data=json.loads(last.split('<reading_data>\n',1)[1].split('\n</reading_data>',1)[0])
            if route_for(query)=='source' and data.get('passage'):
                return '当前阅读原文（'+data.get('location','')+'）：\n'+data['passage'][:6000]
            word=reading_lexeme(last,query)
            if word:
                for v in data.get('saved_vocabulary',[]):
                    if v.get('term','').strip().casefold()==word.casefold():
                        return word+'：'+v['meaning']+'\n'+v.get('example','')+'\n（来自本次阅读已保存词句；AI整理，请结合原文核对。）'
        except (ValueError,IndexError,KeyError,TypeError):pass
    if '[CALBAR_COURSE]' not in last:return None
    route=route_for(query)
    if route=='deep':return None
    if route=='source':
        excerpt=re.search(r'<material_excerpts>\n(.*?)\n</material_excerpts>',last,re.S)
        if excerpt:return '以下是当前教材原文节选：\n'+excerpt[1][:1600]
    path=Path(directory)/'quick_answers.json'
    if not path.exists():return None
    try:
        data=json.loads(path.read_text(encoding='utf-8'));today=today or date.today()
        if not 0<=(today-date.fromisoformat(data['verified'])).days<=30:return None
        for item in data['cards']:
            if any(re.fullmatch(pattern,query,re.I) for pattern in item['patterns']):
                return item['answer']+'\n（本机学习卡；核验 '+data['verified']+'。'+item['source_label']+'）'
    except (OSError,ValueError,KeyError,re.error):return None
    return None


def word_question(query):
    """Only narrow lexical questions are reusable; legal analysis never is."""
    for pattern in (r'(?:请)?(?:解释|翻译)(?:一下)?\s*([a-zA-Z][a-zA-Z\-]{1,35})[。？?\s]*',
                    r'([a-zA-Z][a-zA-Z\-]{1,35})\s*(?:什么意思|是什么意思)[。？?\s]*',
                    r'(?:what does|define|translate)\s+([a-zA-Z][a-zA-Z\-]{1,35})(?:\s+mean)?[.?!\s]*'):
        m=re.fullmatch(pattern,query,re.I)
        if m:return m[1]
    return None


def reading_lexeme(last,query):
    word=word_question(query)
    if word:return word
    try:
        data=json.loads(last.split('<reading_data>\n',1)[1].split('\n</reading_data>',1)[0])
        selected=data.get('passage','').strip()
        if re.fullmatch(r'[A-Za-z][A-Za-z\-]{1,35}',selected) and re.fullmatch(r'(?:请)?(?:解释|翻译)(?:一下)?(?:这个|当前|选中的)?(?:词|单词)|(?:这个|当前|选中的)(?:词|单词)(?:是)?什么意思[？?。\s]*|what does this word mean[?\s]*',query,re.I):return selected
    except (ValueError,IndexError,KeyError,TypeError):pass
    return None


async def cached_events(messages,model,connection,producer,directory):
    """Cache only successful, short lexical explanations in the same passage."""
    import hashlib
    import sqlite3
    from contextlib import closing
    last,query=learner_message(messages);key=None;path=Path(directory)/'lexical-cache.sqlite3'
    if last.startswith('Current reading session:') and reading_lexeme(last,query):
        try:
            data=json.loads(last.split('<reading_data>\n',1)[1].split('\n</reading_data>',1)[0])
            context={k:data.get(k) for k in ('title','author','location','passage','language','material_excerpts')}
            identity={k:connection.get(k) for k in ('provider','api_configs')}
            raw=json.dumps([model,identity,reading_lexeme(last,query).casefold(),context,'lexical-v2'],sort_keys=True,ensure_ascii=False)
            key=hashlib.sha256(raw.encode()).hexdigest()
            path.parent.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(path)) as c, c:
                c.execute('CREATE TABLE IF NOT EXISTS answers(key TEXT PRIMARY KEY,text TEXT,created REAL)')
                cached=c.execute('SELECT text FROM answers WHERE key=? AND created>?',(key,time.time()-7*86400)).fetchone()
            if cached:
                yield cached[0]+'\n（同一原文的已保存解释；不代表已掌握。）';return
        except (ValueError,IndexError,KeyError,TypeError,sqlite3.Error,OSError):key=None
    parts=[]
    async for part in producer(messages,model):
        if key:parts.append(part)
        yield part
    # Reached only after a successful upstream completion; failed partial output
    # and cancelled turns cannot become a reusable answer.
    if key and parts and len(''.join(parts))<=8000:
        try:
            with closing(sqlite3.connect(path)) as c, c:
                c.execute('DELETE FROM answers WHERE created<?',(time.time()-7*86400,))
                c.execute('INSERT OR REPLACE INTO answers VALUES(?,?,?)',(key,''.join(parts),time.time()))
        except (sqlite3.Error,OSError):pass


def prepare_messages(messages):
    """Remove repeated historic excerpts, retaining the current sources and question."""
    last,query=learner_message(messages);mode=route_for(query)
    reading=last.startswith('Current reading session:')
    if not ('Current study task:' in last or '<game_passage>' in last or reading):return messages,mode
    result=[];dialogue=[i for i,m in enumerate(messages) if m.get('role') in ('user','assistant')];keep=set(dialogue[-10:]);latest=dialogue[-1] if dialogue else None
    for i,m in enumerate(messages):
        if m.get('role') in ('system','developer'):result.append(dict(m));continue
        if i not in keep:continue
        content=m.get('content','')
        if i==latest and reading and mode!='deep' and reading_lexeme(last,query):
            try:
                header,rest=content.split('<reading_data>\n',1)
                raw,tail=rest.split('\n</reading_data>',1);data=json.loads(raw)
                term=reading_lexeme(last,query).lower()
                def focus(text,limit):
                    pos=text.lower().find(term);start=max(0,pos-limit//3) if pos>=0 else 0
                    return text[start:start+limit]
                data['passage']=focus(data.get('passage',''),1400)
                data['material_excerpts']=[{k:(focus(v,700) if k=='text' else v) for k,v in s.items()} for s in data.get('material_excerpts',[])[:2]]
                data['recent_dialogue']=[{**t,'text':t.get('text','')[:350]} for t in data.get('recent_dialogue',[])[-2:]]
                data['learning_notes']=[{**n,'text':n.get('text','')[:400]} for n in data.get('learning_notes',[])[:1]]
                content=header+'<reading_data>\n'+json.dumps(data,ensure_ascii=False)+'\n</reading_data>'+tail
            except (ValueError,IndexError,TypeError,KeyError):pass
        if i!=latest and isinstance(content,str) and content.startswith(('Current study task:','Current reading session:')) and 'Learner message: ' in content:content=content.rsplit('Learner message: ',1)[1]
        result.append({**m,'content':content})
    instruction=('Answer one idea at a time, about 40-80 words. Give the direct explanation first; ask at most one short follow-up. Do not rush uncertain legal conclusions.' if mode!='deep' else 'Use careful source-based legal analysis. Explain the issue, applicable rule, factual application and conclusion; distinguish uncertainty and jurisdiction. Detailed feedback is requested, but avoid unrelated topics.')
    if reading:instruction=('Be a subject-independent reading companion. Answer the current question directly and briefly; use the current book/passage. Offer one helpful application or analogy if appropriate. Ask at most one follow-up. Do not invent book quotations or reading achievements.' if mode!='deep' else 'Analyze the reader question carefully against the supplied passage. Distinguish the author argument, your interpretation, and your extension examples. Explain uncertainty, avoid unrelated exam coaching, and ask at most one follow-up.')
    result.insert(0,{'role':'system','content':instruction})
    return result,mode


def reasoning_options(model,mode):
    # Explicit allowlist from current official Responses documentation. Do not
    # impose OpenAI-only parameters on third-party compatibility endpoints.
    if model.startswith(('gpt-6.1-sol','gpt-6-sol','gpt-6-luna','gpt-6-astra')):
        return {'effort':'high' if mode=='deep' else 'low'}
    return None
