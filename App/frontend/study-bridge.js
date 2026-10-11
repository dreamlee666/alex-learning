/* SQE workspace bridge: public WebSocket protocol + same-device parent only.
 * Kept outside the upstream compiled bundle so upgrades remain reviewable.
 */
(() => {
  const PARENT = 'http://127.0.0.1:32194';
  const NativeWS = window.WebSocket;
  let socket, taskId = null, review = false;
  const embedded = window.parent !== window;
  if (!embedded) {
    // Upgrade the full teacher page to turn-taking without auto-starting the mic.
    if (localStorage.getItem('alex-direct-voice-version') !== '2') {
      localStorage.setItem('autoStopMic', 'true');
      localStorage.setItem('autoStartMicOnConvEnd', 'true');
      localStorage.setItem('alex-direct-voice-version', '2');
    }
    document.addEventListener('DOMContentLoaded', () => {
      const panel=document.createElement('label');panel.id='alex-direct-voice';
      panel.style.cssText='position:fixed;right:16px;top:16px;z-index:9999;background:#173932e8;color:white;padding:10px 14px;border-radius:12px;font:13px sans-serif';
      const state=document.createElement('span');state.textContent='直接发送 · 停顿分句 · 回复后继续听';
      const input=document.createElement('input');input.type='checkbox';input.style.marginLeft='12px';input.setAttribute('aria-label','发送前校对转写（可选）');
      input.onchange=()=>{review=input.checked;state.textContent=review?'转写校对已开启':'直接发送 · 停顿分句 · 回复后继续听';if(socket?.readyState===NativeWS.OPEN)send({type:'study-settings',review,task_id:taskId})};
      panel.append(state,input,document.createTextNode(' 校对（可选）'));document.body.append(panel);
    });
  }
  if (embedded) {
    // These upstream containers were inspected in the installed v1.2.1 build.
    // The full teacher page retains its own controls when opened independently.
    const style = document.createElement('style');
    style.textContent = '.css-5ksl0p,.css-agdotf,.css-bgvbkp,.css-1x920na{display:none!important}.css-3yulw9{left:0!important;width:100%!important}.css-128zb0j{width:100%!important}.css-1f0fqlc{height:100%!important}';
    document.head.append(style);
  }
  const notify = (event, data = {}) => {
    if (embedded) window.parent.postMessage({sqe: 1, event, ...data}, PARENT);
  };
  function send(data) {
    if (!socket || socket.readyState !== NativeWS.OPEN) throw Error('虚拟老师尚未连接。');
    socket.send(JSON.stringify(data));
  }
  function standaloneReview(data) {
    let panel = document.getElementById('sqe-review');
    if (!panel) {
      panel = document.createElement('section'); panel.id = 'sqe-review';
      Object.assign(panel.style, {position:'fixed',bottom:'90px',left:'5%',right:'5%',zIndex:99999,padding:'20px',background:'#fff',color:'#172d30',borderRadius:'16px',boxShadow:'0 12px 50px #0006'});
      const label = document.createElement('strong'); label.textContent='确认转写后发送 · 可用系统输入法修改';
      const input = document.createElement('textarea'); input.rows=3; input.style.cssText='display:block;width:100%;margin:12px 0;color:#172d30';
      input.id='sqe-review-text'; input.setAttribute('aria-label','确认转写文本');
      const ok=document.createElement('button');ok.textContent='确认发送';
      const cancel=document.createElement('button');cancel.textContent='取消';cancel.style.marginLeft='16px';
      ok.onclick=()=>{try{send({type:'transcription-confirm',request_id:panel.dataset.ticket,text:input.value});}catch(e){label.textContent=e.message}};
      cancel.onclick=()=>send({type:'transcription-confirm',request_id:panel.dataset.ticket,cancel:true});
      panel.append(label,input,ok,cancel);document.body.append(panel);
    }
    panel.hidden=false;panel.dataset.ticket=data.request_id;
    panel.querySelector('textarea').value=data.text;panel.querySelector('textarea').focus();
  }
  window.WebSocket = class extends NativeWS {
    constructor(...args) {
      super(...args);
      const url = new URL(String(args[0]), location.href);
      if (url.host !== location.host || !url.pathname.endsWith('/client-ws')) return;
      socket=this;
      this.addEventListener('open',()=>{
        this.send(JSON.stringify({type:'study-settings',review,task_id:taskId}));notify('connected');
      });
      this.addEventListener('close',()=>notify('disconnected'));
      this.addEventListener('message',e=>{
        let d;try{d=JSON.parse(e.data)}catch{return}
        if(embedded && d.type==='control' && d.text==='start-mic') {
          // Recording belongs to the workspace's explicit push-to-talk button.
          // Do not let the embedded upstream UI auto-request a second microphone.
          e.stopImmediatePropagation();return;
        }
        if (d.type==='set-model-and-conf') notify('connected');
        if (d.type==='study-board') notify('board',{board:d});
        if (d.type==='user-input-transcription') notify('learner-text',{text:d.text});
        if (d.type==='study-ready') notify('ready',{task_id:d.task_id});
        if (d.type==='transcription-processing') notify('transcribing');
        if (d.type==='transcription-review') {
          if (embedded) notify('review',{request_id:d.request_id,text:d.text});
          else if (review) standaloneReview(d);
          else send({type:'transcription-confirm',request_id:d.request_id,text:d.text,cancel:!String(d.text||'').trim()});
        }
        if (d.type==='transcription-closed') {
          document.getElementById('sqe-review')?.setAttribute('hidden','');notify('review-closed');
        }
        if (d.type==='control' && ['conversation-chain-start','conversation-chain-end'].includes(d.text)) notify(d.text);
        if (d.type==='error') notify('error',{message:d.message});
      });
    }
    send(raw) {
      try {
        const d=JSON.parse(raw);
        // Reassert the selected input mode before each standalone voice turn.
        // This also corrects older sessions that were initialized with review on.
        if (!embedded && d.type==='mic-audio-end') {
          super.send(JSON.stringify({type:'study-settings',review,task_id:taskId}));
        }
        // This event is emitted when a queued sentence actually starts playback.
        if(d.type==='audio-play-start') notify('speaking',{text:d.display_text?.text || ''});
        if(d.type==='frontend-playback-complete') notify('playback-finished');
        if(d.type==='interrupt-signal') notify('interrupted');
      } catch {}
      return super.send(raw);
    }
  };
  window.addEventListener('message',e=>{
    if(e.origin!==PARENT || e.source!==window.parent || e.data?.sqe!==1) return;
    const d=e.data;
    try {
      if(d.action==='context') {taskId=d.task_id || null;review=d.review===true;send({type:'study-settings',review,task_id:taskId,companion:d.companion===true,companion_context:d.companion_context||''})}
      else if(d.action==='text') send({type:'text-input',text:String(d.text).slice(0,8000)});
      else if(d.action==='confirm') send({type:'transcription-confirm',request_id:d.request_id,text:d.text,cancel:d.cancel===true});
      else if(d.action==='audio') send({type:'mic-audio-data',audio:d.audio});
      else if(d.action==='audio-end') send({type:'mic-audio-end'});
      else if(d.action==='interrupt') send({type:'interrupt-signal',text:''});
    } catch(error) {notify('error',{message:error.message})}
  });
})();
