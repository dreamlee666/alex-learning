(() => {
  'use strict';
  const $ = id => document.getElementById(id), csrf = window.SQE_CSRF;
  const FRAME = 'http://127.0.0.1:32193';
  const localDate = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  let state = {books:[],plan:null,notes:[]}, activeTask = localStorage.getItem('sqe-study-task'), connected=false, busy=false;
  let sources=[], speech=[], currentTask=null, reviewTicket=null, audioContext, stream, processor, recording=false, recordTimer;
  let awaitingResponse=false, playbackActive=false, resumeNotBefore=0, reviewCancelled=false, captureFrames=[], preRoll=[], preRollLength=0, captureLength=0;
  const turnDetector=new VoiceTurnDetector();
  $('review-enabled').checked=localStorage.getItem('alex-review-enabled')==='true';
  $('continuous-enabled').checked=localStorage.getItem('alex-continuous-enabled')!=='false';
  let currentBook=null, sourceOffset=0, loading=false, initializedPlan=false;
  let activePlan=localStorage.getItem('alex-study-plan'), newCourse=false;
  // Keep the current explanation visible while the source pane scrolls.
  document.querySelector('.board-bottom').before($('spoken-section'));
  $('board-trail').hidden=true;
  const el = (tag, text, cls) => {const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e};
  const notice = text => {$('notice').textContent=text;$('notice').hidden=!text};
  function richText(parent, text) {
    for(const part of text.split(/(\*\*[^*]+\*\*)/g))parent.append(part.startsWith('**')?el('strong',part.slice(2,-2)):document.createTextNode(part));
  }
  function renderOutline(text) {
    const root=$('outline-text');root.replaceChildren();const lines=text.split('\n');
    for(let i=0;i<lines.length;i++){
      const line=lines[i].trim();if(!line)continue;
      if(line.startsWith('|')&&i+1<lines.length&&/^\|[\s:|\-]+\|$/.test(lines[i+1].trim())){
        const table=el('table'),head=el('thead'),body=el('tbody');
        const cells=l=>l.split('|').slice(1,-1).map(s=>s.trim());
        const row=(values,tag)=>{const r=el('tr');for(const v of values){const cell=el(tag);richText(cell,v);r.append(cell)}return r};
        head.append(row(cells(line),'th'));i+=2;
        while(i<lines.length&&lines[i].trim().startsWith('|')){body.append(row(cells(lines[i]),'td'));i++}i--;
        table.append(head,body);root.append(table);
      }else{
        const heading=line.match(/^(#{1,6})\s+(.+)/),bullet=line.match(/^[-*]\s+(.+)/);
        const node=el(heading?'h3':'p');if(bullet)node.className='outline-bullet';richText(node,heading?heading[2]:bullet?'• '+bullet[1]:line);root.append(node);
      }
    }
  }
  async function api(path, body) {
    const options = body === undefined ? {} : {method:'POST',headers:{'X-SQE-CSRF':csrf}};
    if(body instanceof FormData) options.body=body;
    else if(body!==undefined) {options.headers['Content-Type']='application/json';options.body=JSON.stringify(body)}
    const r=await fetch(path,options);let data;try{data=await r.json()}catch{throw Error('本地服务返回异常，请重新打开课堂。')}
    if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'操作未完成，请检查输入。');return data;
  }
  function action(fn) {return async e=>{e?.preventDefault();try{await fn(e)}catch(error){notice(error.message)}}}
  function post(action, fields={}) {
    if(!connected)throw Error('虚拟老师还未连接，请稍候或重新启动课堂。');
    $('teacher').contentWindow.postMessage({sqe:1,action,...fields},FRAME);
  }
  function context() {const game=window.extensionRoom?.gameMode;post('context',{task_id:game?null:activeTask,review:$('review-enabled').checked,companion:!!game,companion_context:game?window.extensionRoom.getPassage():''})}
  function view(name) {
    if(window.extensionRoom && window.extensionRoom.gameMode !== (name==='game') && (busy||recording||reviewTicket)){notice('请先结束录音或回答，再切换课堂与游戏伴读。');return}
    window.extensionRoom?.onView(name);
    document.querySelectorAll('.view').forEach(e=>e.hidden=e.id!=='view-'+name);
    document.querySelectorAll('.nav').forEach(e=>e.classList.toggle('active',e.dataset.view===name));
    $('page-title').textContent={classroom:'今天，学懂一点。',game:'边玩，边学英语。',library:'你的教材书架。',plan:'每天一小步。',notes:'理解，值得留下。',progress:'每一步，都算数。',review:'回忆，让知识留下。'}[name];
    window.scrollTo(0,0);if(['progress','review'].includes(name))window.dispatchEvent(new Event('learning-view'));
  }
  document.querySelectorAll('.nav').forEach(e=>e.onclick=()=>view(e.dataset.view));
  $('today-label').textContent=new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'short'});
  $('start-date').value=$('task-date').value=localDate();
  $('choose-lesson').onclick=()=>view('plan');$('go-library').onclick=()=>view('library');
  async function refresh() {
    if(loading)return;loading=true;
    try {state=await api('/study/state'+(activePlan?'?plan_id='+encodeURIComponent(activePlan):''));if(activePlan&&!state.plan){activePlan=null;localStorage.removeItem('alex-study-plan');state=await api('/study/state')}if(newCourse)state.plan=null;if(state.plan){activePlan=state.plan.id;localStorage.setItem('alex-study-plan',activePlan)}
      const picker=$('course-select');picker.replaceChildren(new Option('＋ 创建新课程',''));for(const course of state.courses||[])picker.append(new Option(course.config.subject,course.id));picker.value=state.plan?.id||'';
      if(state.plan&&!initializedPlan){const c=state.plan.config;$('subject').value=c.subject||'';$('mode').value=c.mode||'general';$('teaching-language').value=c.language||'zh';$('learner-level').value=c.level||'';$('start-date').value=c.start;$('target-date').value=c.target||'';$('daily-minutes').value=c.minutes;$('study-goals').value=c.goals||'';initializedPlan=true}
      renderBooks();renderPlan();renderNotes();importer.render();window.dispatchEvent(new Event('learning-state'));const label=$('subject-label');label.firstChild.textContent=state.plan?.config.subject||'你的学习空间';$('subject-caption').textContent=state.plan?`${{zh:'中文',en:'英语',bilingual:'中英结合'}[state.plan.config.language]} · 按所选教材学习`:'教材决定主题 · 自由选择学科'
    } finally {loading=false}
  }
  $('course-select').onchange=action(async()=>{
    if(busy||recording||reviewTicket){$('course-select').value=state.plan?.id||'';throw Error('请先结束当前对话或录音，再切换课程。')}
    activePlan=$('course-select').value||null;newCourse=!activePlan;initializedPlan=false;
    activeTask=null;currentTask=null;localStorage.removeItem('sqe-study-task');
    if(activePlan)localStorage.setItem('alex-study-plan',activePlan);else localStorage.removeItem('alex-study-plan');
    $('plan-books').replaceChildren();setBoard([]);$('board-clear').click();$('lesson-title').textContent='从一段教材，开始一场对话';if(connected)context();
    if(newCourse){$('subject').value='';$('mode').value='general';$('teaching-language').value='zh';$('learner-level').value='';$('study-goals').value='';$('start-date').value=localDate();$('target-date').value='';$('daily-minutes').value=30}
    await refresh();notice(newCourse?'选择新教材，填写主题后生成课程。旧课程与笔记仍然保留。':'已切换课程。请选择一节课开始学习。');
  });
  $('mode').onchange=()=>{if($('mode').value==='english')$('teaching-language').value='en'};
  function renderBooks() {
    $('book-count').textContent=state.books.filter(b=>b.status==='ready').length;
    const selected=new Set([...$('plan-books').querySelectorAll('input:checked')].map(e=>e.value));
    $('books').replaceChildren();$('plan-books').replaceChildren();
    for(const b of state.books) {
      const card=el('article',undefined,'book-card');card.append(el('div','▤','book-symbol'),el('h3',b.name));
      const description=b.status==='ready'?`${b.chunks} 个原文片段${b.ocr_chunks?` · ${b.ocr_chunks} 个由 OCR 识别`:''}`:b.status==='failed'?b.error:b.status==='queued'?'等待本机解析…':`正在本机解析${b.total?` · ${b.progress}/${b.total} 页`: '…'}`;
      card.append(el('p',description));
      if(b.source_path&&b.source_path!==b.name)card.append(el('small',b.source_path,'book-path'));
      if(b.status==='failed'){const retry=el('button','重试解析','secondary');retry.onclick=action(async()=>{retry.disabled=true;await api('/study/import/retry',{id:b.id});await refresh()});card.append(retry)}
      if(b.status==='processing'){const p=el('progress');if(b.total){p.max=b.total;p.value=b.progress}card.append(p)}
      if(b.status==='ready'){
        const button=el('button','浏览原文','secondary');button.onclick=action(()=>openBook(b));card.append(button);
        const label=el('label'),input=el('input');input.type='checkbox';input.value=b.id;input.checked=selected.size?selected.has(b.id):state.plan?.config.books.includes(b.id)??!newCourse;
        label.append(input,document.createTextNode(b.name));$('plan-books').append(label);
      }
      $('books').append(card);
    }
    if(!state.books.length)$('books').append(el('p','还没有教材。导入后，它们会保存在本机书架。','muted'));
  }
  const importer=ClassroomImport.install({api,refresh,getBooks:()=>state.books,notice});
  $('demo').onclick=action(async()=>{
    const sample=`# 功能演示：学习如何解释一个概念

这是一份自编功能样例，用于测试书架、计划与小黑板。

主题 1：主动回忆
主动回忆是尝试不看材料，自己说出刚学过的内容。举例：读完一小段，合上材料，再用自己的话解释一个概念，随后对照原文找出遗漏。
思考问题：如果你刚读了一段有关光合作用的教材，怎样检查自己真的理解了？先给出你的方法，再说明理由。

主题 2：用例子说明
解释一个概念时，可以先说明核心意思，再举出一个例子，最后指出例子和定义的关系。
练习：选一个你想学的概念，用两句话解释它。老师应先听你的回答，再一次只追问一个问题。

可选英语练习
如果选择英语练习模式，可以用 I understand it as... 和 One example is... 表达自己的理解。其他学科也可以直接用中文学习。

下一步：导入你自己的教材，选择主题、教学语言和每日时间。`;
    const form=new FormData();form.append('files',new File([sample],'功能演示-学习方法.md',{type:'text/markdown'}));await api('/study/import',form);notice('演示材料已导入。这是自编功能样例，之后可以换成你的真实教材。');await refresh();
  });
  async function openBook(book, offset=0) {
    const data=await api(`/study/book/${book.id}?offset=${offset}`);currentBook=book;sourceOffset=offset;
    $('source-title').textContent=book.name;$('source-location').textContent=`原文片段 ${offset+1}–${offset+data.sources.length} · ${book.chunks} 个片段`;
    $('source-text').textContent=data.sources.map(s=>`[${s.id}] ${s.location}${s.method==='ocr'?' · OCR，请核对':''}\n\n${s.text}`).join('\n\n────────────\n\n');
    $('source-prev').disabled=offset===0;$('source-next').disabled=offset+30>=book.chunks;
    if(!$('source-dialog').open)$('source-dialog').showModal();
  }
  $('source-prev').onclick=action(()=>openBook(currentBook,Math.max(0,sourceOffset-30)));
  $('source-next').onclick=action(()=>openBook(currentBook,sourceOffset+30));$('source-close').onclick=()=>$('source-dialog').close();
  $('search-form').onsubmit=action(async()=>{
    const data=await api('/study/search?q='+encodeURIComponent($('search').value));$('search-results').replaceChildren();
    if(!data.sources.length)$('search-results').append(el('p','未找到匹配原文。试试教材中的英文术语或更短的关键词。','muted'));
    for(const s of data.sources){const card=el('article',undefined,'result-card');card.append(el('small',`${s.book} · ${s.location} · [${s.id}]`),el('p',s.text));const b=el('button','投到小黑板','secondary');b.onclick=()=>{setBoard([s]);view('classroom');notice('已投放原文。需要教材对话时，请从每日计划选择任务。')};card.append(b);$('search-results').append(card)}
  });
  $('plan-form').onsubmit=action(async()=>{
    if(busy||recording||reviewTicket)throw Error('请先结束当前对话或录音，再调整计划。');
    const books=[...$('plan-books').querySelectorAll('input:checked')].map(e=>e.value);
    const planned=await api('/study/plan',{subject:$('subject').value,mode:$('mode').value,language:$('teaching-language').value,level:$('learner-level').value,start:$('start-date').value,target:$('target-date').value,minutes:Number($('daily-minutes').value),goals:$('study-goals').value,books});
    activePlan=planned.id;newCourse=false;localStorage.setItem('alex-study-plan',activePlan);activeTask=null;currentTask=null;localStorage.removeItem('sqe-study-task');setBoard([]);$('board-clear').click();$('lesson-title').textContent='从一段教材，开始一场对话';if(connected)context();await refresh();notice('每日计划已生成。选一节课，就可以带着教材与 Alex 对话。');
  });
  function renderPlan() {
    $('plan-summary').replaceChildren();$('tasks').replaceChildren();const plan=state.plan;
    $('outline').disabled=!plan;$('outline-section').hidden=!plan?.config.outline;
    if(plan?.config.outline)renderOutline(plan.config.outline);
    if(!plan){$('tasks').append(el('p','导入教材并设置每天的学习时间，即可排课。','muted'));return}
    const done=plan.tasks.filter(t=>t.kind==='lesson'&&t.status==='done').length,total=plan.tasks.filter(t=>t.kind==='lesson').length;
    $('plan-summary').append(el('div',`${plan.config.subject} · ${{general:"通用学习",english:"英语练习",sqe1:"SQE1",sqe2:"SQE2",sqe_both:"SQE1 + SQE2"}[plan.config.mode]} · 每天 ${plan.config.minutes} 分钟 · 首轮预计 ${plan.config.finish} · 已完成 ${done}/${total} 节`,'plan-summary'));
    for(const warning of plan.config.warnings||[])$('plan-summary').append(el('p',warning,'muted'));
    const day=$('task-date').value;
    const relevant=plan.tasks.filter(t=>t.due===day||(t.status==='pending'&&t.due<day));
    for(const t of relevant){
      const card=el('article',undefined,'task-card'+(t.id===activeTask?' current':'')+(t.status==='done'?' done':'')),info=el('div');
      info.append(el('span',t.kind==='review'?'RECALL / 间隔复习':'READ & DISCUSS / 阅读与对话','task-kind'),el('h3',t.title),el('p',`${t.due} · 约 ${t.minutes} 分钟${t.due<day?' · 待补学':''}${t.status==='done'?' · 已完成':''}`));
      const button=el('button',t.id===activeTask?'继续这节课':'进入课堂 ↗','secondary');button.onclick=action(()=>selectTask(t.id));card.append(info,button);$('tasks').append(card);
    }
    if(!relevant.length)$('tasks').append(el('p',`这一天没有待学任务。首轮从 ${plan.config.start} 开始，可切换日期查看。`,'muted'));
  }
  $('task-date').onchange=renderPlan;
  async function selectTask(id, silent=false) {
    if(busy||recording||reviewTicket)throw Error('请先结束当前回答或录音，再换课。');
    const data=await api('/study/task/'+id);if(currentTask&&currentTask.plan_id!==data.task.plan_id)$('board-clear').click();activeTask=id;currentTask=data.task;localStorage.setItem('sqe-study-task',id);
    $('lesson-title').textContent=data.task.title;setBoard(data.sources);if(connected)context();renderPlan();window.dispatchEvent(new Event('lesson-selected'));
    if(!silent){view('classroom');notice('教材已就位。点击「开始本节对话」，或直接说出你的问题。')}
  }
  function setBoard(data) {
    sources=data;const root=$('board-sources');root.replaceChildren();
    for(const s of data){const card=el('article',undefined,'board-source');card.dataset.source=s.id;
      const meta=el('div',undefined,'source-meta'),button=el('button',`${s.book} · ${s.location}${s.method==='ocr'?' · OCR':''} ↗`);
      button.onclick=action(()=>openBook(state.books.find(b=>b.id===s.book_id)));meta.append(button);card.append(meta,el('div',`SOURCE [${s.id}]`,'board-label'));
      const copy=el('div',undefined,'source-copy');
      for(const sentence of s.text.split(/(?<=[.!?。])\s+|\n+/).filter(Boolean))copy.append(el('span',sentence,'line'));
      card.append(copy);root.append(card);
    }
  }
  const STOP=new Set('the and that this with from your what have would could should about into when will you are was were for not but can one a an is to of in it'.split(' '));
  function spoken(text) {
    text=text.replace(/\[(joy|neutral|happy|sad|angry|surprise|surprised)\]/gi,'').trim();if(!text)return;
    if(!text.replace(/\[[a-f0-9]{10}-\d+\]/g,'').replace(/[.\s]/g,''))return;
    const ids=new Set(sources.map(s=>s.id));text=text.replace(/\[([a-f0-9]{10}-\d+)\]/g,(all,id)=>ids.has(id)?all:'[来源未核实]');
    const prev=$('spoken').textContent;if(prev&&prev!==text){const row=el('div',prev,'board-trail-entry');$('board-trail').prepend(row);while($('board-trail').children.length>6)$('board-trail').lastChild.remove()}
    $('spoken-section').hidden=false;$('spoken').textContent=text;speech.push(text);if(speech.length>200)speech.shift();
    document.querySelectorAll('.line').forEach(e=>e.classList.remove('pointed'));
    const words=[...new Set((text.toLowerCase().match(/[a-z]{3,}/g)||[]).filter(w=>!STOP.has(w)))];
    const cited=text.match(/\[([a-f0-9]{10}-\d+)\]/)?.[1];let best=null,score=1;
    const quotes=[...text.matchAll(/[“"]([^”"]{6,100})[”"]/g)].map(m=>m[1].toLowerCase().replace(/\.{3}|…/g,'').trim()).filter(q=>q.split(' ').length>1);
    for(const line of document.querySelectorAll('.source-copy .line')){
      const content=line.textContent.toLowerCase();const hits=words.filter(w=>new RegExp(`\\b${w}\\b`).test(content));
      const value=hits.length+(quotes.some(q=>content.includes(q))?20:0)+(cited===line.closest('[data-source]').dataset.source?.toString()?0.5:0);
      if(value>score){score=value;best=line}
    }
    if(best){best.classList.add('pointed');const pane=document.querySelector('.board-scroll');const r=best.getBoundingClientRect(),p=pane.getBoundingClientRect();pane.scrollTo({top:pane.scrollTop+r.top-p.top-50,behavior:'smooth'})}
  }
  $('board-clear').onclick=()=>{$('spoken-section').hidden=true;$('spoken').textContent='';$('board-trail').replaceChildren();speech=[];document.querySelectorAll('.pointed').forEach(e=>e.classList.remove('pointed'))};
  window.addEventListener('message',e=>{
    if(e.origin!==FRAME||e.source!==$('teacher').contentWindow||e.data?.sqe!==1)return;
    const d=e.data;
    window.extensionRoom?.onTeacher(d);
    if(d.event==='connected'){connected=true;$('connection').textContent='老师已连接';try{context()}catch(error){notice(error.message)}}
    if(d.event==='disconnected'){if(recording)stopRecording(false).catch(()=>{});connected=false;busy=false;$('connection').textContent='老师已断开';notice('老师连接断开；教材和学习进度仍在本机。请重新启动课堂。')}
    if(d.event==='board'){sources=d.board.sources;currentTask=d.board.task;setBoard(sources)}
    if(d.event==='speaking'){playbackActive=true;spoken(d.text)}
    if(d.event==='playback-finished'){playbackActive=false;resumeNotBefore=performance.now()+350;}
    if(d.event==='transcribing'){$('input-status').textContent='正在本机识别中英混合语音…';if(!recording)$('record').disabled=true}
    if(d.event==='review'){reviewTicket=d.request_id;$('review-text').value=d.text;$('review-dialog').showModal();$('review-text').focus();$('record').disabled=false;$('input-status').textContent=d.text?'转写已完成，请确认。':'没有识别到文字，可重录或用输入法填写。'}
    if(d.event==='review-closed'){reviewTicket=null;$('review-dialog').close();if(reviewCancelled){awaitingResponse=false;reviewCancelled=false;turnDetector.reset()}$('input-status').textContent='转写确认完毕。';$('record').disabled=false}
    if(d.event==='conversation-chain-start'){busy=true;$('connection').textContent='Alex 正在思考…';$('send').disabled=true;$('start-lesson').disabled=true}
    if(['conversation-chain-end','interrupted'].includes(d.event)){busy=false;awaitingResponse=false;playbackActive=false;resumeNotBefore=performance.now()+350;turnDetector.reset();$('input-status').textContent=recording?'继续听你说… 停顿后自动发送。':'可以直接开始语音对话。';$('connection').textContent='老师已连接';$('send').disabled=false;$('start-lesson').disabled=false}
    if(d.event==='error'){notice(d.message);awaitingResponse=false;playbackActive=false;turnDetector.reset();$('record').disabled=false}
  });
  $('review-enabled').onchange=action(()=>{localStorage.setItem('alex-review-enabled',String($('review-enabled').checked));context()});
  $('continuous-enabled').onchange=action(async()=>{localStorage.setItem('alex-continuous-enabled',String($('continuous-enabled').checked));if(recording)await stopRecording(false)});
  $('pause-delay').onchange=()=>{turnDetector.silenceMs=Number($('pause-delay').value)};
  $('review-dialog').addEventListener('cancel',e=>{e.preventDefault();$('review-cancel').click()});
  $('review-confirm').onclick=action(()=>{const text=$('review-text').value.trim();if(!text)throw Error('请填写转写内容，或取消后重录。');reviewCancelled=false;post('confirm',{request_id:reviewTicket,text})});
  $('review-cancel').onclick=action(()=>{reviewCancelled=true;post('confirm',{request_id:reviewTicket,cancel:true})});
  $('send').onclick=action(()=>{if(busy||recording||reviewTicket)throw Error('请先结束当前录音或回复。');const text=$('message').value.trim();if(!text)return;context();post('text',{text});window.extensionRoom?.learner(text);$('message').value='';notice('')});
  $('message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('send').click()}});
  $('interrupt').onclick=action(()=>post('interrupt'));
  $('start-lesson').onclick=action(()=>{if(!activeTask){view('plan');throw Error('请先在每日计划选择一节课。')}if(busy||recording||reviewTicket)throw Error('请先结束当前录音或回答。');post('text',{text:currentTask?.kind==='review'?'Start a recall review of this material. Ask me just one question in the selected teaching language, without explaining the answer or giving hints first. Wait for my answer.':'Start the current material-based lesson. Briefly introduce one key concept from the selected material on the blackboard, then ask me just one Socratic question in the selected teaching language. Wait for my answer.'});notice('')});
  window.learningRoom={api,notice,view,refresh,getState:()=>state,getTask:()=>activeTask,selectTask,context,sendText(text){$('message').value=text;$('send').click()},isBusy:()=>busy||recording||!!reviewTicket};
  $('complete-lesson').onclick=action(async()=>{
    if(!activeTask)throw Error('请先选择学习任务。');
    await api('/study/complete',{id:activeTask,date:localDate(),grade:$('review-grade').value});await refresh();notice('已保存完成记录。可以打开「课后整理与练习」，总结本节并开始回忆。');
  });
  $('save-conversation').onclick=action(async()=>{if(!activeTask||!speech.length)throw Error('先选择任务并与老师对话，再保存讲解。');await api('/study/note',{id:activeTask,text:'课堂讲解（AI 生成，请结合原文核对）：\n\n'+speech.slice(-20).join('\n\n')});await refresh();notice('当前讲解已保存到「我的笔记」。')});
  $('note-form').onsubmit=action(async()=>{if(!activeTask)throw Error('请先选择一节课，以便把笔记关联到教材。');await api('/study/note',{id:activeTask,text:$('note-text').value});$('note-text').value='';await refresh();notice('笔记已保存。')});
  function renderNotes(){$('notes').replaceChildren();for(const n of state.notes){const card=el('article',undefined,'note-card');card.append(el('strong',n.title),el('small',' · '+n.created),el('p',n.text));$('notes').append(card)}if(!state.notes.length)$('notes').append(el('p','还没有笔记。可以保存课堂讲解，也可以写下自己的理解。','muted'))}
  $('outline').onclick=action(async()=>{if(!state.plan)throw Error('请先生成计划。');$('outline').disabled=true;$('outline').textContent='AI 正在整理…';try{const r=await api('/study/outline',{id:state.plan.id});renderOutline(r.outline);$('outline-section').hidden=false;$('outline-section').open=true;await refresh();notice('课纲已保存：根据最多 20 段教材抽样整理，详细学习仍逐段引用原文。')}finally{$('outline').disabled=false;$('outline').textContent='AI 整理教材课纲'}});
  function clearCapture(){captureFrames=[];captureLength=0;preRoll=[];preRollLength=0;turnDetector.reset()}
  function submitCapturedTurn() {
    if(!captureLength||awaitingResponse||busy||reviewTicket)return false;
    // Chunk below the existing backend message and 2-minute audio limits.
    for(const frame of captureFrames)post('audio',{audio:Array.from(frame)});
    captureFrames=[];captureLength=0;preRoll=[];preRollLength=0;turnDetector.reset();
    context();awaitingResponse=true;post('audio-end');$('input-status').textContent='正在识别并发送…';return true;
  }
  async function stopRecording(submit=true) {
    if(!recording)return;
    const shouldSend=submit&&!busy&&!awaitingResponse&&!reviewTicket&&(turnDetector.active||!$('continuous-enabled').checked);
    recording=false;clearTimeout(recordTimer);processor?.disconnect();stream?.getTracks().forEach(t=>t.stop());
    if(shouldSend)submitCapturedTurn();else clearCapture();
    await audioContext?.close();audioContext=null;stream=null;processor=null;
    $('record').classList.remove('recording');$('record').disabled=false;$('record').setAttribute('aria-label','开始语音对话');$('record').textContent='●';
    if(!awaitingResponse)$('input-status').textContent='语音对话已结束。';
  }
  $('record').onclick=action(async()=>{
    if(recording){await stopRecording();return}
    if(!connected||busy||awaitingResponse||reviewTicket)throw Error('请等老师连接、结束回答或完成转写确认后再录音。');
    if(!navigator.mediaDevices?.getUserMedia)throw Error('此浏览器不支持录音，可使用系统输入法。');
    stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
    try{
      audioContext=new AudioContext();await audioContext.resume();const input=audioContext.createMediaStreamSource(stream);
      processor=audioContext.createScriptProcessor(4096,1,1);input.connect(processor);processor.connect(audioContext.destination);
      clearCapture();turnDetector.silenceMs=Number($('pause-delay').value);
      processor.onaudioprocess=e=>{
        if(!recording||busy||awaitingResponse||reviewTicket||playbackActive||performance.now()<resumeNotBefore)return;
        const raw=e.inputBuffer.getChannelData(0),ratio=audioContext.sampleRate/16000,out=new Float32Array(Math.floor(raw.length/ratio));let energy=0;
        for(let i=0;i<out.length;i++){const a=Math.floor(i*ratio),b=Math.min(raw.length,Math.floor((i+1)*ratio));let sum=0;for(let j=a;j<b;j++)sum+=raw[j];out[i]=sum/Math.max(1,b-a);energy+=out[i]*out[i]}
        try {
          if(!$('continuous-enabled').checked){captureFrames.push(out);captureLength+=out.length;return}
          const wasActive=turnDetector.active,result=turnDetector.feed(Math.sqrt(energy/Math.max(1,out.length)),out.length/16,performance.now());
          if(!wasActive&&result==='idle'){
            preRoll.push(out);preRollLength+=out.length;while(preRollLength>6400&&preRoll.length>1)preRollLength-=preRoll.shift().length;
          }else{
            if(!wasActive){captureFrames=preRoll;captureLength=preRollLength;preRoll=[];preRollLength=0}
            captureFrames.push(out);captureLength+=out.length;
            $('input-status').textContent='听你说… 停顿后自动发送。';
            if(result==='end'||captureLength>=16000*110)submitCapturedTurn();
          }
        }catch(error){notice(error.message);stopRecording(false).catch(()=>{})}
      };
      recording=true;$('record').classList.add('recording');$('record').textContent='■';$('record').setAttribute('aria-label','结束语音对话');
      $('input-status').textContent=$('continuous-enabled').checked?'正在听你说… 停顿后自动发送，老师说完继续听。再点麦克风退出。':'正在录音… 再点一次直接发送。';
      if(!$('continuous-enabled').checked)recordTimer=setTimeout(()=>stopRecording().catch(e=>notice(e.message)),110000);
    }catch(error){stream?.getTracks().forEach(t=>t.stop());await audioContext?.close();throw error}
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&recording)stopRecording(false).catch(()=>{})});
  window.addEventListener('pagehide',()=>stream?.getTracks().forEach(t=>t.stop()));
  refresh().then(async()=>{if(activeTask){try{await selectTask(activeTask,true)}catch{activeTask=null;localStorage.removeItem('sqe-study-task')}}}).catch(e=>notice(e.message));
  setInterval(()=>{if(state.books.some(b=>['queued','processing'].includes(b.status)))refresh().catch(e=>notice(e.message))},2500);
})();
