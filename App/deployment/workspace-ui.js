/* MIT. Unified PDF.js reading, continuous classroom voice and source-linked review. */
(() => {
  'use strict';
  const room=window.learningRoom,reading=window.readingRoom,$=id=>document.getElementById(id);
  const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e};
  const run=fn=>async()=>{try{await fn()}catch(e){room.notice(e.message)}};
  const button=(text,fn,cls='secondary')=>{const b=el('button',text,cls);b.type='button';b.onclick=run(async()=>{b.disabled=true;try{await fn()}finally{b.disabled=false}});return b};
  const api=(p,b)=>room.api('/study/workspace/'+p,b);
  const desk=document.querySelector('.reading-desk'),host=document.querySelector('.reading-teacher-host');
  const setup=$('reading-title').closest('section'),setupDetails=el('details',undefined,'reading-book-settings');
  const setupSummary=el('summary','选择书籍 / 阅读目标');setup.before(setupDetails);setupDetails.append(setupSummary,setup);setupDetails.open=!reading.current;
  document.querySelector('.reading-grid').classList.add('unified-reading-grid');
  host.append($('reading-composer-host'),$('reading-transcript').closest('section'));
  const css=el('link');css.rel='stylesheet';css.href='/study/vendor/pdfjs/pdf_viewer.css?v=0.5.0.1';document.head.append(css);
  const panel=el('section',undefined,'pdf-reading-panel');panel.hidden=true;
  const toolbar=el('div',undefined,'pdf-toolbar'),pageInput=el('input');pageInput.type='number';pageInput.min='1';pageInput.setAttribute('aria-label','PDF 页码');
  const pageLabel=el('span'),status=el('p','选择文字后可高亮、批注或直接问老师。','muted');status.setAttribute('aria-live','polite');
  const stage=el('div',undefined,'pdf-stage'),surface=el('div',undefined,'pdf-surface');stage.append(surface);
  let pdf=null,module=null,sid='',bookId='',page=1,total=0,generation=0,pendingSelection=null,paintTask=null,textTask=null,loading=false;
  toolbar.append(button('上一页',()=>showPage(page-1)),pageInput,pageLabel,button('前往',()=>showPage(Number(pageInput.value))),button('下一页',()=>showPage(page+1)));
  pageInput.onkeydown=e=>{if(e.key==='Enter')run(()=>showPage(Number(pageInput.value)))()};
  const note=el('input');note.placeholder='批注（可选）';note.maxLength=4000;note.setAttribute('aria-label','PDF 批注');
  const actions=el('div',undefined,'pdf-toolbar');
  async function selectedContext(){if(!pendingSelection)throw Error('请先在当前 PDF 页中选择文字。');await reading.setPage(page,pendingSelection.quote)}
  actions.append(button('高亮 / 保存批注',async()=>{if(!pendingSelection)throw Error('请先选择文字。');await api('annotation',{session_id:sid,page,...pendingSelection,note:note.value});note.value='';await showPage(page,false);status.textContent='批注已保存，重开仍可查看。'}),
    button('解释选段',async()=>{await selectedContext();await reading.ask(/^[a-zA-Z][a-zA-Z-]{1,35}$/.test(pendingSelection.quote)?pendingSelection.quote+'是什么意思？':'请解释我选中的原文，先用简单语言说明，再给一个例子。')}),
    button('引导我理解',async()=>{await selectedContext();await reading.ask('请围绕我选中的原文进行苏格拉底式引导，一次只问一个问题，等我回答。')}),
    button('讲解本页',async()=>{await reading.setPage(page);await reading.ask('请简短讲解当前页最重要的一个概念，再让我用简单英语复述。')}),note);
  panel.append(el('h3','原文阅读 · 与老师同步'),toolbar,actions,status,stage);desk.prepend(panel);
  const mediaTools=el('div',undefined,'pdf-toolbar'),visualQuestion=el('input');visualQuestion.maxLength=2000;visualQuestion.placeholder='例如：这个图表的两个指标有什么关系？';visualQuestion.setAttribute('aria-label','本页图表问题');
  const visualReply=el('p',undefined,'learning-copy');visualReply.setAttribute('aria-live','polite');
  const annotatedPDF=el('input');annotatedPDF.type='file';annotatedPDF.accept='.pdf,application/pdf';annotatedPDF.setAttribute('aria-label','外部批注PDF');
  function paintOCR(regions){
    if(!regions.length)return;surface.querySelector('.textLayer')?.remove();surface.querySelector('.ocr-text-layer')?.remove();
    const layer=el('div',undefined,'ocr-text-layer'),ctx=document.createElement('canvas').getContext('2d'),width=parseFloat(surface.style.width),height=parseFloat(surface.style.height);
    for(const r of regions){const [x0,y0,x1,y1]=r.rect,h=(y1-y0)*height,w=(x1-x0)*width,size=Math.max(4,h*.85),span=el('span',r.text);ctx.font=size+'px sans-serif';const measured=ctx.measureText(r.text).width;span.style.cssText=`left:${x0*100}%;top:${y0*100}%;height:${h}px;font-size:${size}px;line-height:${h}px;transform:scaleX(${Math.max(.1,Math.min(10,w/Math.max(1,measured)))})`;layer.append(span)}surface.append(layer)
  }
  mediaTools.append(button('扫描页取词（本机）',async()=>{const current=sid,p=page;status.textContent='正在本机识别当前页文字…';const r=await room.runReadingAction(()=>api('media/ocr',{session_id:current,page:p}));if(sid!==current||page!==p)return;paintOCR(r.regions);status.textContent=r.regions.length?'OCR文字层已就绪，可划线、取词和提问；识别可能有错字，请核对页面。':'本页没有识别到文字，可尝试看图提问。'}),visualQuestion,
    button('发送本页给视觉模型',async()=>{if(!visualQuestion.value.trim())throw Error('先填写本页图表问题。');const current=sid,p=page;await reading.flushDraft();visualReply.textContent='正在向你配置的模型发送当前页图像并分析…';try{const r=await room.runReadingAction(()=>api('media/visual',{session_id:current,page:p,question:visualQuestion.value,send_page:true}));visualReply.textContent=r.answer+'\n\n'+r.label;await reading.reloadCurrent();await syncNotes()}catch(e){visualReply.textContent='看图未完成：'+e.message+'。原文和已有记录仍保留。';throw e}}),
    button('让老师继续讲解看图结果',async()=>{await reading.ask('请基于当前页最近一次看图解释，先说明可见事实与推测，再用简单语言解释我的问题。没有看图记录时请提示我先发送本页。')}));
  const importTools=el('div',undefined,'pdf-toolbar');importTools.append(annotatedPDF,button('导回外部PDF批注',async()=>{const file=annotatedPDF.files[0];if(!file)throw Error('请选择同一教材的批注PDF。');if(file.size>50*1024*1024)throw Error('批注PDF上限50MB。');const form=new FormData();form.append('session_id',sid);form.append('file',file);status.textContent='正在核对教材页面和批注…';const r=await room.runReadingAction(async()=>{const response=await fetch('/study/workspace/media/import-annotations',{method:'POST',headers:{'X-SQE-CSRF':window.SQE_CSRF},body:form});const data=await response.json();if(!response.ok)throw Error(data.detail||'批注导入失败。');return data});await showPage(page,false);status.textContent=`新增 ${r.added} 项，跳过 ${r.skipped} 项，冲突保留 ${r.conflicts} 项，未支持 ${r.unsupported} 项。`+r.message;annotatedPDF.value='';await syncNotes()}));
  stage.after(mediaTools,el('p','本机OCR不上传页面。看图按钮会发送当前页给已配置的模型，需模型支持图片；解释仍可能出错。外部批注导回会核对页面，保留冲突，不同步删除。','muted'),visualReply,importTools);
  function capture(){
    const selection=window.getSelection();
    if(!selection?.rangeCount||!surface.contains(selection.anchorNode)||!surface.contains(selection.focusNode))return;
    const quote=selection.toString().trim().slice(0,6000);if(!quote)return;
    const box=surface.getBoundingClientRect();
    const rects=[...selection.getRangeAt(0).getClientRects()].filter(r=>r.width>1&&r.height>1).map(r=>[
      Math.max(0,(r.left-box.left)/box.width),Math.max(0,(r.top-box.top)/box.height),
      Math.min(1,(r.right-box.left)/box.width),Math.min(1,(r.bottom-box.top)/box.height)]).filter(r=>r[2]>r[0]&&r[3]>r[1]);
    if(rects.length&&rects.length<=100){pendingSelection={quote,rects};status.textContent='已选：'+quote.slice(0,140)+'。直接语音提问也会带上这段原文。';}
  }
  surface.addEventListener('mouseup',capture);surface.addEventListener('keyup',capture);
  const originalBeforeSend=reading.beforeSend.bind(reading);
  reading.beforeSend=async()=>{await originalBeforeSend();if(panel.hidden||!pendingSelection)return;
    // The classroom marks a turn busy before preparing microphone audio. Save
    // context directly here, before audio-end starts actual inference.
    await api('position',{session_id:sid,page,selection:pendingSelection.quote});
  };
  async function showPage(next,sync=true){
    if(!pdf||loading)return;if(!room.canChangeReading())throw Error('请等老师回答结束后翻页，避免原文错位。');
    if(!Number.isInteger(next)||next<1||next>total)throw Error('页码超出范围。');
    loading=true;const ticket=++generation;
    try{
      page=next;pendingSelection=null;status.textContent='正在载入原文…';
      const data=sync?await reading.setPage(page):await api('page?session_id='+sid+'&page='+page);
      const p=await pdf.getPage(page);const base=p.getViewport({scale:1});const width=Math.max(220,Math.min(stage.clientWidth-20,920));
      const scale=width/base.width,viewport=p.getViewport({scale});
      if(ticket!==generation)return;paintTask?.cancel();textTask?.cancel();surface.replaceChildren();
      surface.style.width=viewport.width+'px';surface.style.height=viewport.height+'px';
      surface.style.setProperty('--scale-factor',scale);surface.style.setProperty('--total-scale-factor',scale);
      surface.style.setProperty('--scale-round-x','1px');surface.style.setProperty('--scale-round-y','1px');
      const canvas=el('canvas');const ratio=Math.min(window.devicePixelRatio||1,2);canvas.width=Math.floor(viewport.width*ratio);canvas.height=Math.floor(viewport.height*ratio);canvas.style.width=viewport.width+'px';canvas.style.height=viewport.height+'px';surface.append(canvas);
      paintTask=p.render({canvasContext:canvas.getContext('2d'),viewport,transform:ratio===1?null:[ratio,0,0,ratio,0,0]});await paintTask.promise;
      const marks=el('div',undefined,'pdf-marks');surface.append(marks);
      for(const mark of data.annotations)for(const r of mark.rects){const h=el('div',undefined,'pdf-highlight');h.title=mark.note||mark.quote;h.style.cssText=`left:${r[0]*100}%;top:${r[1]*100}%;width:${(r[2]-r[0])*100}%;height:${(r[3]-r[1])*100}%`;marks.append(h)}
      const textLayer=el('div',undefined,'textLayer');surface.append(textLayer);textTask=new module.TextLayer({textContentSource:await p.getTextContent(),container:textLayer,viewport});await textTask.render();
      const ocr=await api('media/ocr?session_id='+encodeURIComponent(sid)+'&page='+page);if(ticket===generation)paintOCR(ocr.regions);
      pageInput.value=String(page);pageInput.max=String(total);pageLabel.textContent='/ '+total+' 页';
      status.textContent='第 '+page+' 页已同步给老师。选中原文后，可直接说“解释这句话”。';
    }finally{loading=false}
  }
  async function loadDocument(){
    const data=reading.current;if(!data||sid===data.id)return;
    sid=data.id;bookId=data.book_id;pdf?.destroy();pdf=null;pendingSelection=null;panel.hidden=true;visualReply.textContent='';visualQuestion.value='';annotatedPDF.value='';
    const b=room.getState().books.find(b=>b.id===bookId);if(!b||!b.name.toLowerCase().endsWith('.pdf'))return;
    panel.hidden=false;status.textContent='正在打开 PDF…';
    try{
      module=module||await import('/study/vendor/pdfjs/pdf.mjs');module.GlobalWorkerOptions.workerSrc='/study/vendor/pdfjs/pdf.worker.mjs';
      const target=sid;pdf=await module.getDocument({url:'/study/workspace/pdf/'+encodeURIComponent(bookId),isEvalSupported:false}).promise;
      if(sid!==target)return;total=pdf.numPages;const saved=await api('position/'+sid);await showPage(Math.min(saved.page,total),data.status==='active');
    }catch(e){status.textContent='PDF 未打开：'+e.message+'。仍可使用下方文本伴读。';}
  }
  window.addEventListener('reading-selected',()=>{setupDetails.open=false;setupSummary.textContent='正在读：'+(reading.current?.title||'选择书籍')+' · 展开设置';loadDocument().catch(e=>room.notice(e.message));candidates.replaceChildren();semanticResults.replaceChildren();results.replaceChildren()});
  const workflow=el('section',undefined,'learning-panel workspace-workflow');workflow.append(el('h3','阅读 → 回忆 → 每日学习'));
  const candidates=el('div'),reviewState=el('p','先整理本次阅读，再选择核对过的问题与词句加入当前课程复习。','muted');
  workflow.append(reviewState,button('检查本次复习内容',async()=>{if(!reading.sessionId)throw Error('请先开始伴读。');const data=await api('review-candidates/'+reading.sessionId);candidates.replaceChildren();for(const item of data.items){const row=el('label',undefined,'workspace-review-item'),check=el('input');check.type='checkbox';check.value=item.key;check.disabled=item.added;check.checked=false;row.append(check,el('span',item.question+(item.added?' · 已加入':'')),el('small',item.answer+'\n'+item.label));candidates.append(row)}if(!data.items.length)candidates.append(el('p','这次整理没有可用复习内容。'))}),candidates,
    button('把已核对内容加入当前课程',async()=>{const taskId=room.getTask();if(!taskId)throw Error('先在每日计划选择当前课次，再回来加入复习。');const keys=[...candidates.querySelectorAll('input:checked:not(:disabled)')].map(c=>c.value);const result=await api('reviews',{session_id:reading.sessionId,task_id:taskId,keys});reviewState.textContent='已加入 '+result.added+' 项。可在「今日60分钟」或「间隔复习」练习，不会自动标记课程完成。';window.dispatchEvent(new Event('learning-state'))}));
  workflow.prepend(button('直接整理原始记录（无需模型）',async()=>{await api('organize-local',{session_id:reading.sessionId});await reading.reloadCurrent();reviewState.textContent='已按真实问题与原回答整理，没有调用模型概括。核对后可加入复习。';await syncNotes()}));
  $('reading-report').parentElement.after(workflow);
  const assessment=el('section',undefined,'learning-panel');assessment.append(el('h3','试着复述，分别检查内容与英语'));
  const question=el('textarea');question.rows=2;question.placeholder='你要回答的问题 / 本次复述的主题';question.maxLength=2000;question.setAttribute('aria-label','双重评估问题');
  const answer=el('textarea');answer.rows=4;answer.placeholder='先用自己的英语解释，再获取反馈。';answer.maxLength=8000;answer.setAttribute('aria-label','我的英文复述');
  const feedback=el('p',undefined,'learning-copy');feedback.setAttribute('aria-live','polite');
  assessment.append(question,answer,button('分别检查内容和英语',async()=>{await reading.flushDraft();feedback.textContent='正在结合当前原文检查…';try{const result=await api('assessment',{session_id:reading.sessionId,question:question.value,answer:answer.value});feedback.textContent=result.feedback+'\n\n'+result.label}catch(e){feedback.textContent='反馈未完成，你输入的内容仍在这里。';throw e}}),feedback);workflow.after(assessment);
  const notes=el('section',undefined,'learning-panel');notes.append(el('h3','我的学习记忆与 Obsidian'));
  const vault=el('input');vault.setAttribute('aria-label','学习笔记仓库路径');vault.style.width='100%';
  const notesStatus=el('p',undefined,'muted'),results=el('div'),query=el('input');query.placeholder='搜索我的笔记与交流';query.setAttribute('aria-label','检索学习笔记');
  const backup=el('a','下载私人学习备份 ZIP','secondary');backup.href='/study/workspace/backup';backup.download='Alex-private-study-backup.zip';
  let syncing=false;
  async function syncNotes(){if(syncing)return;syncing=true;try{const r=await api('sync',{});notesStatus.textContent='已同步 '+r.sessions+' 次伴读至 '+r.vault+(r.conflicts.length?'；有 '+r.conflicts.length+' 份更新副本待合并。':'；个人补充已保留。')}finally{syncing=false}}
  const autoSync=el('input');autoSync.type='checkbox';autoSync.checked=localStorage.getItem('alex-reading-autosync')!=='false';autoSync.onchange=()=>localStorage.setItem('alex-reading-autosync',String(autoSync.checked));const autoLabel=el('label');autoLabel.append(autoSync,document.createTextNode('每次回答结束后自动保存到笔记库'));
  notes.append(vault,button('使用这个学习笔记仓库',async()=>{await api('vault',{path:vault.value});notesStatus.textContent='仓库已连接并建立本机关键词索引。'}),button('立即同步笔记',syncNotes),button('重新索引我修改的笔记',async()=>{const r=await api('index',{});notesStatus.textContent='已索引 '+r.indexed_notes+' 篇笔记。'}),autoLabel,notesStatus,query,
    button('查找',async()=>{const r=await api('search?q='+encodeURIComponent(query.value)+'&book_id='+encodeURIComponent(reading.current?.book_id||''));results.replaceChildren();for(const n of r.notes){const p=el('article');p.append(el('strong',n.note),el('p',n.text,'learning-copy'),el('small',n.label));results.append(p)}if(!r.notes.length)results.append(el('p','没有匹配笔记，试试原文关键词。'))}),results,backup,el('p','备份包含私人教材和学习记录，仅供自己保存；不会包含模型凭据。','muted'));
  assessment.after(notes);
  const knowledge=el('section',undefined,'learning-panel');knowledge.append(el('h3','本机语义知识库 · 中英互查'));
  const knowledgeStatus=el('p','正在检查本机索引…','muted'),semanticQuery=el('input'),semanticResults=el('div');semanticQuery.setAttribute('aria-label','语义知识库问题');semanticQuery.placeholder='可以用中文查英文教材，例如：承诺何时生效';
  async function semanticStatus(){const s=await room.api('/study/semantic/status'),j=s.job;knowledgeStatus.textContent=s.model+' · 教材向量 '+(s.vectors.material||0)+'，笔记向量 '+(s.vectors.note||0)+'。'+({idle:'尚未建立索引。',starting:'正在准备…',downloading:'正在下载并校验约135MB模型…',indexing:`后台建立索引 ${j.done||0}/${j.total||0}；已有部分可查询。`,ready:'索引已就绪。',paused:'任务已暂停，下次复用已完成部分。',error:'索引未完成：'+j.error}[j.state]||j.state);return s}
  async function startSemantic(scope){const r=await room.api('/study/semantic/index',{scope,book_id:reading.current?.book_id||''});await semanticStatus();room.notice(r.started?'语义索引已在后台开始；教材在本机处理。':'已有本机索引任务正在进行，继续复用。')}
  knowledge.append(knowledgeStatus,button('索引当前教材和笔记',()=>startSemantic('selected')),button('索引全部书架',()=>startSemantic('all')),button('刷新索引状态',semanticStatus),el('p','首次下载公共模型，随后本机计算；关键词与语义结合。修改笔记后重新索引。检索结果是相关材料，不代表答案正确。','muted'),semanticQuery,
    button('按意思查找教材',async()=>{const r=await room.api('/study/semantic/search?q='+encodeURIComponent(semanticQuery.value)+'&book_id='+encodeURIComponent(reading.current?.book_id||''));semanticResults.replaceChildren(el('p','检索用时 '+r.elapsed_ms+' ms；范围为当前关联教材。','muted'));for(const s of r.sources){const row=el('article',undefined,'reading-source');row.append(el('strong',s.book+' · '+s.location),el('p',s.text),el('small',(s.retrieval==='semantic'?'语义匹配':'关键词匹配')+' · ['+s.id+']'));semanticResults.append(row)}if(!r.sources.length)semanticResults.append(el('p','没有找到相关原文；可以换一种说法或建立索引。'))}),semanticResults);
  notes.after(knowledge);semanticStatus().catch(e=>{knowledgeStatus.textContent=e.message});
  setInterval(()=>{if(reading.active)semanticStatus().catch(()=>{})},5000);
  const previousTeacher=reading.onTeacher.bind(reading);
  reading.onTeacher=d=>{previousTeacher(d);if(reading.active&&autoSync.checked&&['conversation-chain-end','interrupted'].includes(d.event))setTimeout(()=>syncNotes().catch(e=>{notesStatus.textContent='自动同步未完成：'+e.message+'。原始对话仍保存在课堂。'}),900)};
  api('status').then(s=>{vault.value=s.vault;notesStatus.textContent='本机已索引 '+s.indexed_notes+' 篇笔记。'}).catch(e=>room.notice(e.message));
  let todayGeneration=0;
  async function today(){const ticket=++todayGeneration,pid=room.getState().plan?.id;if(!pid)return;
    const data=await api('today?plan_id='+encodeURIComponent(pid));if(ticket!==todayGeneration)return;
    const target=$('view-daily');target.querySelector('.workspace-today')?.remove();const card=el('section',undefined,'workspace-today');
    card.append(el('h3','把阅读带进今天的学习'),el('p','本课程有 '+data.due_count+' 项伴读内容到期。'+data.budget_notice),button('练习到期内容',()=>room.view('review')));
    for(const item of data.cards.slice(0,5))card.append(el('p','• '+item.question));
    if(data.reading)card.append(button('继续阅读：'+data.reading.title,()=>reading.openSession(data.reading.id)));
    target.prepend(card);
  }
  window.addEventListener('daily-ready',()=>today().catch(e=>room.notice(e.message)));
  today().catch(e=>room.notice(e.message));
  if(reading.current)loadDocument().catch(e=>room.notice(e.message));
})();
