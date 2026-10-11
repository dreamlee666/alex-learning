(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.ClassroomImport=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const MAX_BYTES=50*1024*1024;
  function validate(file){if(!/\.(pdf|docx|txt|md)$/i.test(file.name))return '不支持的格式，已跳过';if(!file.size)return '空文件，已跳过';if(file.size>MAX_BYTES)return '超过单本 50 MB，已跳过';return '';}
  async function collectDrop(items, fallback=[]){
    // Capture entry handles synchronously while the drop event is still valid.
    const roots=Array.from(items||[]).filter(i=>i.kind==='file').map(i=>({entry:i.webkitGetAsEntry?.(),file:i.getAsFile?.()}));
    const files=[],errors=[];
    async function walk(entry,path=''){
      const relative=path+entry.name;
      try{
        if(entry.isFile){const file=await new Promise((resolve,reject)=>entry.file(resolve,reject));files.push({file,path:relative});}
        else if(entry.isDirectory){const reader=entry.createReader();for(;;){const batch=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject));if(!batch.length)break;for(const child of batch)await walk(child,relative+'/');}}
      }catch(error){errors.push({path:relative,error:'无法读取，请重新选择：'+error.message});}
    }
    if(roots.length){for(const item of roots){if(item.entry)await walk(item.entry);else if(item.file)files.push({file:item.file,path:item.file.name});}}
    else for(const file of Array.from(fallback))files.push({file,path:file.webkitRelativePath||file.name});
    return {files,errors};
  }
  class Queue{
    constructor(upload,changed=()=>{}){this.upload=upload;this.changed=changed;this.items=[];this.running=false;this.paused=false;}
    add(files,errors=[]){for(const item of files){const error=validate(item.file);this.items.push({...item,state:error?'skipped':'pending',error});}for(const e of errors)this.items.push({...e,state:'skipped'});this.changed();return this.run();}
    pause(){this.paused=true;this.changed();}
    resume(){this.paused=false;return this.run();}
    retry(){for(const item of this.items)if(item.state==='failed'){item.state='pending';item.error='';}return this.resume();}
    async run(){
      if(this.running)return;this.running=true;this.changed();
      try{while(!this.paused){const item=this.items.find(i=>i.state==='pending');if(!item)break;item.state='uploading';this.changed();try{const result=await this.upload(item);item.id=result.id;item.state=result.duplicate?'duplicate':'uploaded';}catch(error){item.state='failed';item.error=error.message;}this.changed();}}
      finally{this.running=false;this.changed();}
    }
  }
  function install({api,refresh,getBooks,notice}){
    const $=id=>document.getElementById(id), zone=$('import-drop');
    const line=(text)=>{const p=document.createElement('li');p.textContent=text;return p;};
    const queue=new Queue(async item=>{const form=new FormData();form.append('files',item.file,item.path||item.file.name);const result=await api('/study/import',form);const detail=result.results?.[0]||{id:result.ids[0]};if(detail.error)throw Error(detail.error);await refresh();return detail;},render);
    function render(){
      if(!queue.items.length)return;$('import-status-panel').hidden=false;
      const books=new Map(getBooks().map(b=>[b.id,b]));
      const count=state=>queue.items.filter(i=>i.state===state).length;
      const pending=count('pending'),uploading=count('uploading'),failed=count('failed'),skipped=count('skipped'),duplicate=count('duplicate');
      let ready=0,parsing=0,parseFailed=0;
      for(const item of queue.items)if(item.state==='uploaded'){const state=books.get(item.id)?.status;if(state==='ready')ready++;else if(state==='failed')parseFailed++;else parsing++;}
      $('import-status').textContent=`共 ${queue.items.length} 项 · 待传输 ${pending} · 传输中 ${uploading} · 排队/解析 ${parsing} · 已入库 ${ready} · 重复 ${duplicate} · 跳过 ${skipped} · 失败 ${failed+parseFailed}${queue.paused?' · 已暂停传输':''}`;
      $('import-progress').max=queue.items.length;$('import-progress').value=queue.items.length-pending-uploading;
      $('import-pause').textContent=queue.paused?'继续传输':'暂停传输';$('import-pause').disabled=!pending&&!uploading;
      $('import-retry').hidden=!failed;
      const list=$('import-log');list.replaceChildren();
      // Show active/problem items first; keep the DOM bounded for large folders.
      const ordered=[...queue.items].sort((a,b)=>Number(['pending','uploaded','duplicate'].includes(a.state))-Number(['pending','uploaded','duplicate'].includes(b.state)));
      for(const item of ordered.slice(0,100)){
        const b=books.get(item.id),labels={pending:'等待传输',uploading:'正在传输',duplicate:'内容已在书架，未重复导入',uploaded:b?.status==='ready'?'已入库':b?.status==='failed'?'解析失败：'+b.error:b?.status==='processing'?'正在解析':'等待解析',failed:'传输失败：'+item.error,skipped:item.error};
        list.append(line((item.path||item.file?.name||'文件')+' — '+labels[item.state]));
      }
      if(queue.items.length>100)list.append(line(`此处显示 100 项，全部 ${queue.items.length} 项都已加入队列；入库结果在下方书架查看。`));
    }
    function choose(input){const files=Array.from(input.files||[]).map(file=>({file,path:file.webkitRelativePath||file.name}));input.value='';if(files.length){notice('已加入导入队列。上传完的教材会继续在本机解析；传输结束前请保留此页面。');queue.add(files);}}
    $('files').onchange=()=>choose($('files'));
    $('folder-files').onchange=()=>choose($('folder-files'));
    $('import-pause').onclick=()=>queue.paused?queue.resume():queue.pause();
    $('import-retry').onclick=()=>queue.retry();
    for(const type of ['dragenter','dragover'])zone.addEventListener(type,e=>{e.preventDefault();e.stopPropagation();zone.classList.add('drag-active');if(e.dataTransfer)e.dataTransfer.dropEffect='copy';});
    zone.addEventListener('dragleave',e=>{if(!zone.contains(e.relatedTarget))zone.classList.remove('drag-active');});
    zone.addEventListener('drop',async e=>{e.preventDefault();e.stopPropagation();zone.classList.remove('drag-active');const pending=collectDrop(e.dataTransfer.items,e.dataTransfer.files);notice('正在读取拖入的文件与子文件夹…');try{const result=await pending;if(!result.files.length&&!result.errors.length)throw Error('未读到教材；可使用「导入文件夹」按钮。');queue.add(result.files,result.errors);notice('已加入导入队列，支持继续添加文件。')}catch(error){notice(error.message)}});
    // Avoid navigating away when a file is dropped elsewhere on the library page.
    document.addEventListener('dragover',e=>{if(Array.from(e.dataTransfer?.types||[]).includes('Files'))e.preventDefault();});
    document.addEventListener('drop',e=>{if(Array.from(e.dataTransfer?.types||[]).includes('Files')){e.preventDefault();notice('请把文件或文件夹拖到书架的导入区域。');}});
    window.addEventListener('beforeunload',e=>{if(queue.items.some(i=>['pending','uploading'].includes(i.state))){e.preventDefault();e.returnValue='';}});
    return {render,queue};
  }
  return {Queue,collectDrop,validate,install};
});
