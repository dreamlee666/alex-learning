"""Local multilingual ONNX embeddings with incremental, source-linked retrieval. MIT."""
from contextlib import closing
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import urllib.request

MANIFEST=json.loads((Path(__file__).parent/'semantic-model.json').read_text(encoding='utf-8'))
MODEL_ID=MANIFEST['repository']+'@'+MANIFEST['revision']
DOWNLOAD_LOCK=threading.Lock()
INDEX_LOCK=threading.Lock()
ENCODE_LOCK=threading.Lock()
STOP=threading.Event()
QUERY_CACHE={}


def init(store):
    with store.connect() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS semantic_docs(
            id TEXT PRIMARY KEY,kind TEXT,book_id TEXT,location TEXT,path TEXT,text TEXT,digest TEXT,vector BLOB,model TEXT);
            CREATE INDEX IF NOT EXISTS semantic_scope ON semantic_docs(kind,book_id,model);
            CREATE TABLE IF NOT EXISTS semantic_state(id INTEGER PRIMARY KEY,data TEXT);''')


def progress(store,**changes):
    with store.connect() as c:
        row=c.execute('SELECT data FROM semantic_state WHERE id=1').fetchone()
        data=json.loads(row['data']) if row else {}
        data.update(changes,updated=time.time())
        c.execute('INSERT OR REPLACE INTO semantic_state VALUES(1,?)',(json.dumps(data,ensure_ascii=False),))
    return data


def model_dir(store):return store.directory/'semantic-model'


def installed(store):
    root=model_dir(store)
    try:verified=json.loads((root/'verified.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return False
    return verified==MANIFEST and all((root/f['name']).is_file() and (root/f['name']).stat().st_size==f['bytes'] for f in MANIFEST['files'])


def ensure_model(store,proxy=None):
    root=model_dir(store);root.mkdir(parents=True,exist_ok=True)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':proxy}) if proxy else urllib.request.ProxyHandler())
    with DOWNLOAD_LOCK:
        if installed(store):return
        for f in MANIFEST['files']:
            target=root/f['name']
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==f['sha256']:continue
            url='https://huggingface.co/'+MANIFEST['repository']+'/resolve/'+MANIFEST['revision']+'/'+f['path']
            part=target.with_suffix('.download');h=hashlib.sha256();size=0;last=0
            request=urllib.request.Request(url,headers={'User-Agent':'Alex-Learning-local-retrieval/0.6'})
            with opener.open(request,timeout=60) as response,part.open('wb') as out:
                if not response.geturl().startswith('https://'):raise ValueError('模型下载没有使用 HTTPS。')
                while block:=response.read(1024*1024):
                    out.write(block);h.update(block);size+=len(block)
                    if size-last>5*1024*1024:progress(store,state='downloading',file=f['name'],downloaded=size,total_bytes=f['bytes']);last=size
            if size!=f['bytes'] or h.hexdigest()!=f['sha256']:
                part.unlink(missing_ok=True);raise ValueError('语义模型校验失败，没有启用；请重新下载。')
            part.replace(target)
        (root/'verified.json').write_text(json.dumps(MANIFEST,indent=2),encoding='utf-8')


@lru_cache(maxsize=2)
def engine(directory):
    import onnxruntime as ort
    from tokenizers import Tokenizer
    root=Path(directory);opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
    session=ort.InferenceSession(str(root/'model.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
    tokenizer=Tokenizer.from_file(str(root/'tokenizer.json'));tokenizer.enable_truncation(max_length=256)
    tokenizer.enable_padding(pad_id=1,pad_token='<pad>')
    return session,tokenizer


def embed(store,texts,query=False):
    import numpy as np
    with ENCODE_LOCK:
        key=(str(model_dir(store)),texts[0]) if query and len(texts)==1 else None
        if key in QUERY_CACHE:return QUERY_CACHE[key].copy()
        session,tokenizer=engine(str(model_dir(store)))
        batch=tokenizer.encode_batch([('query: ' if query else 'passage: ')+t for t in texts])
        ids=np.asarray([t.ids for t in batch],dtype=np.int64);mask=np.asarray([t.attention_mask for t in batch],dtype=np.int64)
        available={'input_ids':ids,'attention_mask':mask,'token_type_ids':np.zeros_like(ids)}
        hidden=session.run(None,{i.name:available[i.name] for i in session.get_inputs()})[0]
        weighted=hidden*mask[:,:,None];vectors=weighted.sum(axis=1)/np.maximum(mask.sum(axis=1)[:,None],1)
        result=(vectors/np.maximum(np.linalg.norm(vectors,axis=1,keepdims=True),1e-12)).astype('float32')
        if key:
            if len(QUERY_CACHE)>=128:QUERY_CACHE.pop(next(iter(QUERY_CACHE)))
            QUERY_CACHE[key]=result
        return result


def pieces(text):
    # Overlapping, bounded windows avoid silently discarding a long note's tail.
    for start in range(0,len(text),480):
        part=text[start:start+640].strip()
        if part:yield start,part
        if start+640>=len(text):break


def build_index(store,book_ids=None,proxy=None,notes_only=False):
    init(store)
    if not INDEX_LOCK.acquire(blocking=False):raise ValueError('已有语义索引任务正在进行。')
    try:
        progress(store,state='starting',error='',done=0,total=0)
        ensure_model(store,proxy)
        with store.connect() as c:
            sql='SELECT id,book_id,location,text FROM chunks';args=[]
            if book_ids:
                sql+=' WHERE book_id IN ('+','.join('?' for _ in book_ids)+')';args=list(book_ids)
            sources=[] if notes_only else [dict(r) for r in c.execute(sql+' ORDER BY book_id,ordinal',args)]
            has_notes=c.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_notes'").fetchone()
            notes=[dict(r) for r in c.execute('SELECT path,book_id,text FROM workspace_notes ORDER BY path')] if has_notes else []
        docs=[]
        for s in sources:
            for offset,text in pieces(s['text']):docs.append((s['id']+':'+str(offset),'material',s['book_id'],s['location'],s['id'],text))
        for n in notes:
            for offset,text in pieces(n['text']):docs.append(('note:'+n['path']+':'+str(offset),'note',n['book_id'],'',n['path'],text))
        with store.connect() as c:
            existing={r['id']:r['digest'] for r in c.execute('SELECT id,digest FROM semantic_docs WHERE model=?',(MODEL_ID,))}
        pending=[]
        for d in docs:
            digest=hashlib.sha256(d[-1].encode()).hexdigest()
            if existing.get(d[0])!=digest:pending.append((*d,digest))
        progress(store,state='indexing',total=len(pending),done=0,corpus=len(docs),scope='notes' if notes_only else 'selected' if book_ids else 'all')
        for offset in range(0,len(pending),8):
            if STOP.is_set():return progress(store,state='paused',done=offset)
            batch=pending[offset:offset+8];vectors=embed(store,[d[5] for d in batch])
            with store.connect() as c:
                for doc,vec in zip(batch,vectors):c.execute('INSERT OR REPLACE INTO semantic_docs VALUES(?,?,?,?,?,?,?,?,?)',(*doc,vec.tobytes(),MODEL_ID))
            progress(store,done=min(offset+8,len(pending)))
        # Delete stale entries only within the scope actually indexed. A partial
        # book refresh must never erase another book's usable vectors.
        wanted={d[0] for d in docs}
        with store.connect() as c:
            for row in c.execute('SELECT id,kind,book_id FROM semantic_docs').fetchall():
                if (row['kind']=='note' or (not notes_only and (not book_ids or row['book_id'] in book_ids))) and row['id'] not in wanted:
                    c.execute('DELETE FROM semantic_docs WHERE id=?',(row['id'],))
        return progress(store,state='ready',done=len(pending),total=len(pending))
    except Exception as e:
        progress(store,state='error',error=str(e)[:350]);raise
    finally:INDEX_LOCK.release()


def status(store):
    init(store)
    with store.connect() as c:
        row=c.execute('SELECT data FROM semantic_state WHERE id=1').fetchone()
        counts={r['kind']:r['n'] for r in c.execute('SELECT kind,count(*) n FROM semantic_docs WHERE model=? GROUP BY kind',(MODEL_ID,))}
    return {'installed':installed(store),'model':'multilingual-e5-small / ONNX INT8',
            'vectors':counts,'job':json.loads(row['data']) if row else {'state':'idle'}}


def search(store,query,book_ids=None,kind='material',limit=8):
    import numpy as np
    if not query.strip() or not installed(store):return []
    with store.connect() as c:
        has=c.execute("SELECT 1 FROM sqlite_master WHERE name='semantic_docs'").fetchone()
        if not has:return []
        sql='SELECT * FROM semantic_docs WHERE kind=? AND model=?';args=[kind,MODEL_ID]
        if book_ids:
            if kind=='note':sql+=' AND (book_id IN ('+','.join('?' for _ in book_ids)+") OR book_id='')"
            else:sql+=' AND book_id IN ('+','.join('?' for _ in book_ids)+')'
            args.extend(book_ids)
        rows=c.execute(sql,args).fetchall()
        if not rows:return []
        if kind=='note':
            # Deleted or edited notes must not be retrieved from stale vectors.
            notes={r['path']:r['text'] for r in c.execute('SELECT path,text FROM workspace_notes')}
            rows=[r for r in rows if r['path'] in notes and r['text'] in notes[r['path']]]
        if not rows:return []
        vectors=np.stack([np.frombuffer(r['vector'],dtype='float32') for r in rows])
        q=embed(store,[query],query=True)[0];scores=vectors@q
        ranked=np.argsort(-scores);found=[];used=set()
        for i in ranked:
            r=rows[int(i)];score=float(scores[int(i)])
            if score<0.68:continue
            if r['path'] in used:continue
            used.add(r['path'])
            found.append({'id':r['path'],'book_id':r['book_id'],'location':r['location'],'text':r['text'],'score':round(score,4),'retrieval':'semantic'})
            if len(found)>=limit:break
        return found


def hybrid(store,query,lexical,book_ids=None,limit=4):
    """Reciprocal rank fusion preserves exact terms and cross-language matches."""
    try:dense=search(store,query,book_ids,limit=8)
    except Exception:dense=[] # Optional retrieval must not disable the classroom.
    if not dense:return lexical[:limit]
    scores={};items={}
    with store.connect() as c:
        for rank,d in enumerate(dense):
            row=c.execute('SELECT c.*,b.name book FROM chunks c JOIN books b ON b.id=c.book_id WHERE c.id=?',(d['id'],)).fetchone()
            if row:items[d['id']]={**dict(row),'retrieval':'semantic','similarity':d['score']};scores[d['id']]=1/(30+rank)
    for rank,d in enumerate(lexical):
        items[d['id']]=dict(d);scores[d['id']]=scores.get(d['id'],0)+1/(30+rank)
    return [items[key] for key in sorted(scores,key=scores.get,reverse=True)[:limit]]


def install(app,store,check):
    import asyncio
    from fastapi import Request,HTTPException
    init(store);tasks=set()
    async def job(ids=None,notes_only=False):
        try:await asyncio.to_thread(build_index,store,ids,None,notes_only)
        except Exception:pass # A readable, bounded error is persisted in state.
    def schedule(ids=None,notes_only=False):
        state=status(store)['job']
        if state.get('state') in ('starting','downloading','indexing') and time.time()-state.get('updated',0)<120:return False
        progress(store,state='starting',error='');STOP.clear()
        task=asyncio.create_task(job(ids,notes_only));tasks.add(task);task.add_done_callback(tasks.discard)
        return True

    @app.get('/study/semantic/status')
    async def get_status():return await asyncio.to_thread(status,store)

    @app.post('/study/semantic/index')
    async def start(request:Request):
        check(request);body=await request.json();bid=body.get('book_id','');scope=body.get('scope','selected')
        if scope not in ('selected','all'):raise HTTPException(400,'请选择当前教材或全部书架。')
        if scope=='selected' and bid not in {b['id'] for b in store.books() if b['status']=='ready'}:raise HTTPException(400,'请先选择已导入的教材。')
        started=schedule([bid] if scope=='selected' else None)
        return {'started':started,'status':status(store)}

    @app.get('/study/semantic/search')
    async def lookup(q:str='',book_id:str=''):
        start=time.perf_counter();sources=await asyncio.to_thread(store.retrieve,q[:2000],[book_id] if book_id else None,6)
        return {'sources':sources,'elapsed_ms':round((time.perf_counter()-start)*1000)}

    @app.on_event('startup')
    async def warmup():
        if installed(store):
            async def warm():
                try:await asyncio.to_thread(embed,store,['ready'],True)
                except Exception:pass
            task=asyncio.create_task(warm());tasks.add(task);task.add_done_callback(tasks.discard)

    @app.on_event('shutdown')
    async def shutdown():
        STOP.set()
        if tasks:await asyncio.wait(tasks,timeout=10)
    return schedule
