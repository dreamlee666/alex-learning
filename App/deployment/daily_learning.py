"""Mastery-based daily sessions; dates are forecasts, not progression triggers. MIT."""
import json
import uuid
from datetime import date, datetime, timezone

BLOCKS=[('recall',5,'回忆与到期复习'),('concept',15,'法律概念与三个英文术语'),('reading',15,'教材英文精读与复述'),('practice',15,'一道题／一段 IRAC'),('wrap',10,'纠错、记录与复习安排')]


def init(store):
    with store.connect() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS daily_units(task_id TEXT PRIMARY KEY,ordinal INTEGER,data TEXT);
        CREATE TABLE IF NOT EXISTS daily_results(id TEXT PRIMARY KEY,task_id TEXT,day TEXT,passed INTEGER,data TEXT,created TEXT);
        CREATE INDEX IF NOT EXISTS daily_results_task ON daily_results(task_id,created);''')


def detail(store,tid):
    with store.connect() as c:
        row=c.execute('SELECT data FROM daily_units WHERE task_id=?',(tid,)).fetchone()
        if not row:return None
        previous=list(c.execute('SELECT r.data,r.day,r.passed FROM daily_results r JOIN tasks t ON r.task_id=t.id WHERE t.plan_id=(SELECT plan_id FROM tasks WHERE id=?) ORDER BY r.rowid DESC LIMIT 2',(tid,)))
    value=json.loads(row['data'])
    value['recent_learning']=[{'day':r['day'],'passed':bool(r['passed']),'learner_english':json.loads(r['data']).get('english_output','')[:600],'learner_recall':json.loads(r['data']).get('legal_recall','')[:600],'problems':json.loads(r['data']).get('problems',[]),'label':'个人学习记录，不是法律依据'} for r in previous]
    return value


def overview(store,pid):
    plan=store.plan(pid)
    if not plan or not plan['config'].get('daily_mastery'):return {'enabled':False}
    with store.connect() as c:
        units=list(c.execute('SELECT t.id,t.status,t.title,u.ordinal,u.data FROM tasks t JOIN daily_units u ON t.id=u.task_id WHERE t.plan_id=? ORDER BY u.ordinal',(pid,)))
        current=next((u for u in units if u['status']!='done'),None)
        logs=list(c.execute('SELECT r.*,t.title FROM daily_results r JOIN tasks t ON r.task_id=t.id WHERE t.plan_id=? ORDER BY r.rowid DESC LIMIT 12',(pid,)))
    return {'enabled':True,'plan_id':pid,'total':len(units),'completed':sum(u['status']=='done' for u in units),
            'current':({'task_id':current['id'],**json.loads(current['data'])} if current else None),
            'history':[{'id':r['id'],'task_id':r['task_id'],'day':r['day'],'passed':bool(r['passed']),'title':r['title'],'data':json.loads(r['data'])} for r in logs],
            'config':plan['config']}


def record(store,body):
    tid=body.get('task_id','');task=store.task(tid);unit=detail(store,tid)
    if not unit:raise ValueError('这不是每日学习任务。')
    on=date.fromisoformat(body.get('date','')).isoformat()
    checks=body.get('checks',{})
    if not isinstance(checks,dict) or any(checks.get(k) is not True for k,_,_ in BLOCKS):raise ValueError('请先完成并勾选五个学习环节。')
    evidence={}
    for name,label in [('english_output','英文复述／修改后的句子'),('legal_recall','不看教材的法律概念回忆')]:
        text=body.get(name,'')
        if not isinstance(text,str) or not 5<=len(text.strip())<=4000:raise ValueError('请记录'+label+'（5–4000 字符）。')
        evidence[name]=text.strip()
    metrics=body.get('metrics',{})
    if not isinstance(metrics,dict):raise ValueError('检查结果格式错误。')
    clean={};problems=[]
    if unit['checkpoint']:
        for name,maximum in [('quiz_total',200),('quiz_correct',200),('legal_score',3),('english_score',3),('essay_minutes',180),('pt_minutes',180)]:
            value=metrics.get(name,0)
            if type(value) is not int or not 0<=value<=maximum:raise ValueError('请填写有效的练习数量、分钟和自评分数。')
            clean[name]=value
        if clean['quiz_correct']>clean['quiz_total']:raise ValueError('正确数不能超过总题数。')
        source=metrics.get('question_source','none')
        if source not in ('official_seen','licensed_unseen','ai_generated','none'):raise ValueError('请选择练习来源。')
        clean.update(question_source=source,set_label=str(metrics.get('set_label','')).strip()[:100],
                     essay_continuous=metrics.get('essay_continuous') is True,pt_continuous=metrics.get('pt_continuous') is True)
        if source=='none':problems.append('请记录练习题／检查问题的来源。')
        minimum=20 if unit['week']>=37 else 10
        if clean['quiz_total']<minimum:problems.append(f'本周至少记录 {minimum} 个检查问题／练习题。')
        if clean['quiz_total']==0 or clean['quiz_correct']/max(1,clean['quiz_total'])<.7:problems.append('练习正确率尚未达到本计划的 70% 巩固目标（不是官方及格线）。')
        if clean['legal_score']<2:problems.append('法律理解仍需巩固：需能指出争点、依据与适用事实。')
        if clean['english_score']<2:problems.append('英语仍需练习：需能用简单英语表达本周概念／一个分析段落。')
    passed=not problems
    payload={'checks':checks,**evidence,'metrics':clean,'problems':problems,'measurement':'个人记录／自评，非官方评分','ordinal':unit['ordinal'],'week':unit['week']}
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        first=c.execute("SELECT t.id FROM tasks t JOIN daily_units u ON t.id=u.task_id WHERE t.plan_id=? AND t.status!='done' ORDER BY u.ordinal LIMIT 1",(task['plan_id'],)).fetchone()
        fresh=c.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()
        if fresh['status']=='done':return {'passed':True,'already_done':True,'problems':[]}
        if not first or first['id']!=tid:raise ValueError('先完成当前每日任务与周检，再推进；未来内容仍可预览。')
        if unit['week']==48 and unit['checkpoint']:
            if clean['question_source']!='licensed_unseen' or clean['quiz_total']<50:problems.append('最终检查需至少 50 道合法取得、未做过的真实 MBE 题，不能用重复样题或 AI 自编题替代。')
            if not clean['set_label']:problems.append('为本次独立题组填写编号，避免重复题组被当作新题。')
            prior=list(c.execute('SELECT data FROM daily_results r JOIN tasks t ON r.task_id=t.id WHERE t.plan_id=? AND r.passed=1',(task['plan_id'],)))
            groups={}
            for r in prior:
                old=json.loads(r['data']);m=old.get('metrics',{});label=m.get('set_label','')
                if old.get('week',0)>=37 and label and m.get('question_source')=='licensed_unseen' and m.get('quiz_total',0)>=30 and m.get('quiz_correct',0)/max(1,m.get('quiz_total',0))>=.7:groups[label]=True
            if clean['set_label']:groups[clean['set_label']]=True
            if len(groups)<3:problems.append('至少三个不同未见真实题组达到巩固目标；一次好成绩不足以判断稳定性。')
            if clean['essay_minutes']<60 or not clean['essay_continuous']:problems.append('还需记录一次连续 60 分钟的完整 Essay 练习。')
            if clean['pt_minutes']<90 or not clean['pt_continuous']:problems.append('还需另外安排一次连续 90 分钟的完整 PT，分段练习不等同限时模拟。')
        passed=not problems;payload['problems']=problems
        c.execute('INSERT INTO daily_results VALUES(?,?,?,?,?,?)',(uuid.uuid4().hex,tid,on,int(passed),json.dumps(payload,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
        if passed:c.execute("UPDATE tasks SET status='done',completed=?,note=? WHERE id=?",(on,json.dumps(evidence,ensure_ascii=False),tid))
    return {'passed':passed,'problems':problems,'message':'本日记录已保存，可进入下一组任务。' if passed else '记录已保存；下一次先巩固这一周，不按日历强行跳过。'}


def install(app,store,check_action):
    from fastapi import Request,HTTPException
    import asyncio
    init(store)
    @app.get('/study/daily')
    async def daily(plan_id:str=''):
        try:return await asyncio.to_thread(overview,store,plan_id)
        except ValueError as e:raise HTTPException(400,str(e))
    @app.post('/study/daily/record')
    async def save(request:Request):
        check_action(request)
        try:return await asyncio.to_thread(record,store,await request.json())
        except (ValueError,TypeError,KeyError) as e:raise HTTPException(400,str(e))
