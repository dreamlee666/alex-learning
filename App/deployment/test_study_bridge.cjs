const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fullPage(){
  const events={},storage=new Map(),elements=new Map();let controls;
  class Socket{
    static OPEN=1;constructor(){this.readyState=1;this.events={};this.messages=[]}
    addEventListener(name,fn){this.events[name]=fn}
    send(raw){this.messages.push(JSON.parse(raw))}
  }
  const window={WebSocket:Socket,addEventListener:(name,fn)=>events[name]=fn};window.parent=window;
  const document={addEventListener:(name,fn)=>events[name]=fn,getElementById:id=>elements.get(id),
    createTextNode:text=>({textContent:text}),createElement:tag=>({tag,style:{},append(...children){this.children=children},setAttribute(){}}),
    body:{append(node){elements.set(node.id,node);controls=node.children}}};
  const context={window,document,URL,location:{href:'http://127.0.0.1:32193/',host:'127.0.0.1:32193'},localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)}};
  vm.runInNewContext(fs.readFileSync('frontend/study-bridge.js','utf8'),context);
  events.DOMContentLoaded();const socket=new window.WebSocket('ws://127.0.0.1:32193/client-ws');socket.events.open();
  return {socket,storage,controls};
}
test('full page configures reply-following turns and starts without confirmation',()=>{
  const {socket,storage}=fullPage();assert.equal(storage.get('autoStopMic'),'true');assert.equal(storage.get('autoStartMicOnConvEnd'),'true');
  assert.equal(socket.messages[0].review,false);assert.equal(storage.get('autoStartMicOn'),undefined);
});
test('full page reasserts direct mode before submitting voice',()=>{
  const {socket}=fullPage();socket.messages=[];socket.send(JSON.stringify({type:'mic-audio-end'}));
  assert.deepEqual(socket.messages,[{type:'study-settings',review:false,task_id:null},{type:'mic-audio-end'}]);
});
test('stale review tickets are forwarded without prompting in direct mode',()=>{
  const {socket}=fullPage();socket.events.message({data:JSON.stringify({type:'transcription-review',request_id:'old',text:'Hello'})});
  assert.deepEqual(socket.messages.at(-1),{type:'transcription-confirm',request_id:'old',text:'Hello',cancel:false});
});
test('explicit optional review remains available for correcting difficult words',()=>{
  const {socket,controls}=fullPage();controls[1].checked=true;controls[1].onchange();
  socket.send(JSON.stringify({type:'mic-audio-end'}));assert.equal(socket.messages.at(-2).review,true);
});
