(() => {
  'use strict';
  const $=id=>document.getElementById(id), room=window.learningRoom;
  const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e};
  const button=(text,fn,cls='secondary')=>{const e=node('button',text,cls);e.onclick=async()=>{e.disabled=true;try{await fn()}catch(err){room.notice(err.message)}finally{e.disabled=false}};return e};
  let planId=null, requestVersion=0, lastPlan=null, resultVersion=0;
  const currentPlan=()=>room.getState().plan;
  function renderTaskPicker(){
    const plan=currentPlan(), old=$('result-task').value;
    $('result-task').replaceChildren(new Option('选择一节课',''));
    for(const t of plan?.tasks||[])if(t.kind==='lesson')$('result-task').append(new Option((t.status==='done'?'✓ ':'')+t.title,t.id));
    if([...$('result-task').options].some(o=>o.value===old))$('result-task').value=old;
    $('generate-pack').disabled=!plan;
  }
  async function loadResult(){
    const tid=$('result-task').value, version=++resultVersion;
    $('lesson-summary').textContent='';$('lesson-transcript').textContent='';
    if(!tid)return;
    const r=await room.api('/study/lesson-result/'+encodeURIComponent(tid));if(version!==resultVersion)return;
    $('lesson-summary').textContent=r.pack?r.pack.summary:'本节还没有课后整理。学完后点击生成，也可以先生成教材预习。';
    $('lesson-transcript').textContent=r.turns.length?r.turns.map(t=>(t.role==='user'?'我：':'Alex：')+t.text).join('\n\n'):'还没有保存的本节对话。新版本会自动记录所选任务下的课堂对话。';
    $('generate-pack').textContent=r.pack?'查看已保存的课后整理':'生成课后总结与练习';
  }
  async function progress(){
    const pid=currentPlan()?.id;planId=pid||null;
    const p=pid?await room.api('/study/progress?plan_id='+encodeURIComponent(pid)):null;
    if(pid!==currentPlan()?.id)return;
    $('progress-metrics').replaceChildren();$('activity-grid').replaceChildren();$('review-history').replaceChildren();
    $('progress-course').textContent=currentPlan()?.config.subject||'先在每日学习计划中选择课程。';
    $('review-count').textContent=p?.cards_due||0;
    $('learning-export').hidden=!pid;$('learning-export').href=pid?'/study/learning-export?plan_id='+encodeURIComponent(pid):'#';
    if(!p){$('next-step').textContent='先导入教材并生成一个学习计划。';return}
    for(const [value,label] of [[`${p.lessons_done}/${p.lessons_total}`,'已学课次'],[p.packs,'课后整理'],[p.cards_due,'到期卡片'],[p.weak,'薄弱点'],[p.recent_recall_rate===null?'—':p.recent_recall_rate+'%','7 天顺利回忆率（自评）'],[p.streak+' 天','连续学习']]){
      const card=node('div',undefined,'metric-card');card.append(node('strong',String(value)),node('span',label));$('progress-metrics').append(card);
    }
    for(const d of p.days){const cell=node('div',undefined,'activity-day');cell.dataset.active=d.count>0?'true':'false';cell.title=d.date+' · '+d.count+' 项';cell.append(node('strong',String(d.count)),node('small',d.date.slice(5)));$('activity-grid').append(cell)}
    $('next-step').textContent=p.cards_due?`先做 ${p.cards_due} 张到期卡片，再开始新课。${p.unreviewed?`其中 ${p.unreviewed} 张还没有作答记录。`:''}`:p.lessons_done>p.packs?'已有学完的课程还没整理，去生成课后总结与练习。':'今天没有到期卡片，可以继续每日计划中的下一节课。';
    if(p.history.length){$('review-history').append(node('h3','最近作答记录'));for(const item of p.history){const detail=node('details',undefined,'learning-panel');detail.append(node('summary',item.question+' · '+['','忘记','困难','记得','轻松'][item.rating]),node('p',item.title+' · '+new Date(item.created).toLocaleString()),node('p','我的答案：'+item.answer,'learning-copy'));if(item.feedback)detail.append(node('p',item.feedback,'learning-copy'));$('review-history').append(detail)}}
  }
  async function loadCards(){
    const pid=currentPlan()?.id, version=++requestVersion, root=$('review-cards');
    root.replaceChildren();if(!pid){root.append(node('p','请先选择课程。'));return}
    const data=await room.api('/study/cards?plan_id='+encodeURIComponent(pid)+'&scope='+$('review-scope').value);
    if(version!==requestVersion||pid!==currentPlan()?.id)return;
    if(!data.cards.length){root.append(node('p','这个范围还没有卡片。先生成课后整理；到期卡片会在这里出现。','muted'));return}
    for(const card of data.cards){
      const article=node('article',undefined,'recall-card'), answer=node('textarea'), response=node('div',undefined,'learning-copy'), feedback=node('div',undefined,'learning-copy'), ratings=node('div',undefined,'rating-row');
      answer.rows=3;answer.maxLength=8000;answer.placeholder='先用自己的话作答，想不起来就写「暂时想不起来」。';answer.setAttribute('aria-label','我的答案：'+card.question);
      article.append(node('small',(card.kind==='exercise'?'应用练习':'主动回忆')+' · '+card.title),node('h3',card.question),node('small','下次复习：'+new Date(card.due).toLocaleString()),answer);
      let snapshot='', due=null, feedbackText='';
      const aiButton=button('让 AI 点评答案',async()=>{aiButton.textContent='正在点评…';try{const result=await room.api('/study/card-feedback',{id:card.id,answer:snapshot});feedbackText=result.feedback;feedback.textContent='AI 反馈（请结合原文核对）：\n'+feedbackText}finally{aiButton.textContent='让 AI 点评答案'}});aiButton.hidden=true;
      const reveal=button('查看参考答案，再评价回忆',async()=>{
        const result=await room.api('/study/card-answer',{id:card.id,answer:answer.value});snapshot=answer.value;due=result.due;answer.readOnly=true;
        response.replaceChildren(node('p','参考答案（AI 生成）：\n'+result.answer));
        for(const s of result.sources){const d=node('details');d.append(node('summary',s.book+' · '+s.location+' · ['+s.id+']'),node('p',s.text));response.append(d)}
        reveal.hidden=true;aiButton.hidden=false;ratings.hidden=false;
      });
      for(const [rating,label] of [[1,'忘记'],[2,'困难'],[3,'记得'],[4,'轻松']])ratings.append(button(label,async()=>{
        [...ratings.children].forEach(b=>b.disabled=true);
        try{const result=await room.api('/study/card-review',{id:card.id,rating,answer:snapshot,feedback:feedbackText,due});article.replaceChildren(node('p',`已记录「${label}」 · 下次复习 ${new Date(result.due).toLocaleString()}`));await progress()}catch(e){[...ratings.children].forEach(b=>b.disabled=false);throw e}
      }));
      ratings.hidden=true;
      article.append(reveal,response,aiButton,feedback,ratings);root.append(article);
    }
  }
  async function refresh(){renderTaskPicker();await Promise.all([progress(),loadCards()])}
  const safe=fn=>async()=>{try{await fn()}catch(e){room.notice(e.message)}};
  $('progress-refresh').onclick=safe(progress);
  $('review-scope').onchange=safe(loadCards);
  $('result-task').onchange=safe(loadResult);
  $('load-result').onclick=safe(loadResult);
  $('go-review').onclick=()=>room.view('review');
  $('generate-pack').onclick=safe(async()=>{
    const id=$('result-task').value;if(!id)throw Error('先选择要整理的课次。');
    $('generate-pack').disabled=true;$('generate-pack').textContent='正在整理教材和对话…';
    try{await room.api('/study/lesson-pack',{id});await loadResult();await Promise.all([progress(),loadCards()]);room.notice('课后整理已保存。卡片先作答，再看答案，最后评价回忆情况，作答记录会一起保存。')}
    finally{$('generate-pack').disabled=false;$('generate-pack').textContent='生成 / 查看课后总结与练习'}
  });
  const updateSummary=button('更新总结（保留卡片进度）',async()=>{const id=$('result-task').value;if(!id)throw Error('请先选择课次。');updateSummary.textContent='正在更新…';try{await room.api('/study/lesson-pack',{id,update_summary:true});await loadResult();await progress();room.notice('总结已按最新对话更新，已有卡片与复习记录保留。')}finally{updateSummary.textContent='更新总结（保留卡片进度）'}});
  $('generate-pack').parentElement.append(updateSummary);
  $('open-afterclass').onclick=safe(async()=>{room.view('review');renderTaskPicker();const id=room.getTask();if([...$('result-task').options].some(o=>o.value===id))$('result-task').value=id;await loadResult()});
  window.addEventListener('learning-state',safe(async()=>{renderTaskPicker();const id=currentPlan()?.id;if(id!==lastPlan){lastPlan=id;++resultVersion;$('lesson-summary').textContent='';$('lesson-transcript').textContent='';await refresh()}else await progress()}));
  window.addEventListener('learning-view',safe(refresh));
  safe(refresh)();
})();
