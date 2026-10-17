/* MIT. Daily evidence, checkpoint feedback and next-session guidance. */
(() => {
  const room=window.learningRoom,$=id=>document.getElementById(id);
  const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el};
  const run=fn=>async()=>{try{await fn()}catch(e){room.notice(e.message)}};
  const button=(text,fn)=>{const b=node('button',text,'secondary');b.onclick=run(async()=>{b.disabled=true;try{await fn()}finally{b.disabled=false}});return b};
  const localDate=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`};
  const nav=button('◎ 今日60分钟',()=>room.view('daily'));nav.className='nav';nav.dataset.view='daily';document.querySelector('nav').append(nav);
  const section=node('section',undefined,'view');section.id='view-daily';section.hidden=true;document.querySelector('main footer').before(section);
  const banner=node('section',undefined,'learning-panel');banner.hidden=true;document.querySelector('#view-classroom .classroom-grid').before(banner);
  let loadedPlan='',generation=0,last=null;
  const field=(label,input)=>{const wrap=node('label',undefined,'daily-field');wrap.append(node('span',label),input);return wrap};
  async function load(){
    const pid=room.getState().plan?.id,ticket=++generation;if(!pid){section.replaceChildren(node('p','请在「每日学习计划」选择加州每日60分钟课程。'));banner.hidden=true;return}
    const data=await room.api('/study/daily?plan_id='+encodeURIComponent(pid));if(ticket!==generation||pid!==room.getState().plan?.id)return;
    last=data;section.replaceChildren();banner.replaceChildren();banner.hidden=!data.enabled;
    if(!data.enabled){section.append(node('p','当前课程使用普通排课。请在每日计划切换到「加州律师考试＋英语 · 每日60分钟」。'));return}
    const u=data.current,newPlan=loadedPlan!==pid;loadedPlan=pid;
    if(u&&room.getTask()!==u.task_id&&!room.isBusy())await room.selectTask(u.task_id,true);
    section.append(node('div','CALIFORNIA BAR + ENGLISH · 每天60分钟','eyebrow'),node('h2',`已完成 ${data.completed}/${data.total} 个学习日`),node('p','48周是初始路线，日历不会自动解锁。漏学继续当前任务；周检不足就先巩固。记录是个人自评，不是官方评分或通过预测。','muted'));
    if(!u){section.append(node('h3','已完成本轮路线，请核对目标考期、现行范围与完整考试日模拟，再决定报考。'));return}
    banner.append(node('strong',`今日路线：第${u.ordinal}学习日 · ${u.topic}`),node('p',u.blocks.filter(b=>b.minutes).map(b=>`${b.minutes}分钟${b.title}`).join(' → ')),button('回到今日任务与记录',()=>room.view('daily')));
    section.append(node('h3',`第${u.ordinal}学习日 · 第${u.week}周第${u.day_in_week}日 · ${u.topic}`),node('p',u.phase+' / '+u.theme),node('p','材料：'+u.reading_references.join('；'),'muted'));
    if(u.adaptation){const a=u.adaptation,e=a.evidence;section.append(node('p','今日调整依据：'+a.reasons.join('；')+` 近期独立复习卡 ${e.distinct_review_cards} 张，选择题 ${e.quiz_attempts} 道，英语诊断 ${e.diagnostics} 次。`,'daily-note'),node('p',a.label,'muted'))}
    const todayDone=data.history.some(r=>r.passed&&r.day===localDate());if(todayDone)section.append(node('p','今天已有完成记录。下面是下一组任务，可明天继续，也可自愿加练。','daily-note'));
    if(u.extra_time_notice)section.append(node('p',u.extra_time_notice,'daily-note'));
    const key='alex-daily-draft-'+u.task_id;let draft={};try{draft=JSON.parse(localStorage.getItem(key)||'{}')}catch{}
    const checks={},inputs={};
    const persist=()=>{const value={checks:Object.fromEntries(Object.entries(checks).map(([k,c])=>[k,c.checked])),english_output:inputs.english_output?.value||'',legal_recall:inputs.legal_recall?.value||'',metrics:Object.fromEntries(Object.entries(inputs).filter(([k])=>!['english_output','legal_recall'].includes(k)).map(([k,c])=>[k,c.type==='checkbox'?c.checked:c.value]))};localStorage.setItem(key,JSON.stringify(value))};
    const grid=node('div',undefined,'daily-blocks');
    for(const b of u.blocks){const card=node('article',undefined,'learning-panel'),check=node('input');check.type='checkbox';check.checked=!!draft.checks?.[b.key];check.setAttribute('aria-label','完成：'+b.title);check.onchange=persist;checks[b.key]=check;const label=node('label');label.append(check,node('strong',`${b.minutes} 分钟 · ${b.title}`));card.append(label,node('p',b.instruction),button('让老师开始这一步',async()=>{if(room.isBusy())throw Error('请等当前对话或录音结束。');await room.selectTask(u.task_id);room.sendText(`Start ONLY today's activity: "${b.title}". Follow the saved daily-session instructions. Explain in Chinese first; let me try short English. Ask one question and wait.`)}));grid.append(card)}section.append(grid);
    const form=node('section',undefined,'learning-panel');form.append(node('h3','保存今日产出'));
    for(const [name,label] of [['english_output','我的英文复述／修改后的表达'],['legal_recall','不看资料，我能解释的法律概念']]){const input=node('textarea');input.rows=3;input.maxLength=4000;input.value=draft[name]||'';input.setAttribute('aria-label',label);input.oninput=persist;inputs[name]=input;form.append(field(label,input))}
    if(u.checkpoint){form.append(node('h3','本周巩固检查 · 个人记录'),node('p','法律：0未尝试，1需大量提示，2能指出争点与依据，3能结合事实分析。英语：0未尝试，1主要靠中文，2能用简单英语表达，3能较独立完成短段落。70%是训练目标，不是官方及格线。','muted'));
      const source=node('select');for(const [value,label] of [['none','请选择练习来源'],['official_seen','官方公开题／重复做过的题'],['licensed_unseen','合法取得、未做过的真实MBE题'],['ai_generated','AI自编或老师口头检查（非官方题）']])source.append(new Option(label,value));source.value=draft.metrics?.question_source||'none';source.setAttribute('aria-label','周检练习来源');source.onchange=persist;inputs.question_source=source;form.append(field('周检练习来源',source));
      for(const [name,label,max] of [['quiz_total','本周检查总题数',200],['quiz_correct','正确题数',200],['legal_score','法律理解自评（0–3）',3],['english_score','英语表达自评（0–3）',3]]){const n=node('input');n.type='number';n.min=0;n.max=max;n.value=draft.metrics?.[name]||0;n.setAttribute('aria-label',label);n.oninput=persist;inputs[name]=n;form.append(field(label,n))}
      if(u.week>=37){const n=node('input');n.maxLength=100;n.value=draft.metrics?.set_label||'';n.setAttribute('aria-label','独立题组编号');n.oninput=persist;inputs.set_label=n;form.append(field('独立题组编号（用于区别重复题）',n));
        for(const [name,label] of [['essay_minutes','完整Essay实际分钟'],['pt_minutes','完整PT实际分钟']]){const n=node('input');n.type='number';n.min=0;n.max=180;n.value=draft.metrics?.[name]||0;n.setAttribute('aria-label',label);n.oninput=persist;inputs[name]=n;form.append(field(label,n))}
        for(const [name,label] of [['essay_continuous','Essay是连续计时完成'],['pt_continuous','PT是连续计时完成（分段不算）']]){const n=node('input');n.type='checkbox';n.checked=!!draft.metrics?.[name];n.setAttribute('aria-label',label);n.onchange=persist;inputs[name]=n;form.append(field(label,n))}
      }
    }
    const feedback=node('p',undefined,'daily-note');feedback.setAttribute('aria-live','polite');
    const diagnostic=node('p',undefined,'learning-copy');diagnostic.setAttribute('aria-live','polite');
    form.append(button('用这次产出检查内容与英语',async()=>{diagnostic.textContent='正在根据原文和你的真实产出诊断…';try{const data=await room.api('/study/adaptive/diagnostic',{task_id:u.task_id,english_output:inputs.english_output.value,legal_recall:inputs.legal_recall.value});const r=data.result;diagnostic.textContent='内容理解（AI建议）：'+r.content.feedback+'\n原话依据：'+r.content.evidence+'\n\n英语表达（AI建议）：'+r.english.feedback+'\n原话依据：'+r.english.evidence+'\n\n再试一次：'+r.retry+'\n\n下次打开本日任务时会按此证据重新分配60分钟；不会自动完成任务。'}catch(e){diagnostic.textContent='诊断未完成，原始产出仍保留。';throw e}}),diagnostic);
    form.append(button('保存学习记录并检查下一步',async()=>{if(room.isBusy())throw Error('请先结束对话或录音。');const metrics={};for(const [k,c] of Object.entries(inputs)){if(['english_output','legal_recall'].includes(k))continue;metrics[k]=c.type==='number'?Number(c.value):c.type==='checkbox'?c.checked:c.value}
      const result=await room.api('/study/daily/record',{task_id:u.task_id,date:localDate(),checks:Object.fromEntries(Object.entries(checks).map(([k,c])=>[k,c.checked])),english_output:inputs.english_output.value,legal_recall:inputs.legal_recall.value,metrics});feedback.textContent=result.message+'\n'+result.problems.join('\n');if(result.passed){localStorage.removeItem(key);room.notice('今日记录已保存。下一组任务可在下次学习继续。');await room.refresh()}else{room.notice(result.message);await load()}}),button('打开课后整理与复习',async()=>{await room.selectTask(u.task_id);$('open-afterclass').click()}),feedback);section.append(form);
    for(const h of data.history.filter(h=>!h.passed).slice(0,1))section.append(node('p','最近需要巩固：'+h.data.problems.join('；'),'daily-note'));
    section.append(node('h3','最近学习记录'));for(const h of data.history.slice(0,7))section.append(node('p',`${h.day} · ${h.title} · ${h.passed?'已完成':'待巩固'} · 英文：${h.data.english_output.slice(0,100)}`));
    window.dispatchEvent(new Event('daily-ready'));
    if(newPlan&&!room.isBusy()&&new URLSearchParams(location.search).get('mode')!=='reading'){room.view('daily');room.notice('今日任务已就位。点击一个环节，让老师开始；完成后回到这里保存产出。')}
  }
  window.addEventListener('learning-state',()=>load().catch(e=>room.notice(e.message)));
  window.addEventListener('learning-view',()=>{if(!$('view-daily').hidden)load().catch(e=>room.notice(e.message))});
  load().catch(e=>room.notice(e.message));
})();
