const test=require('node:test');
const assert=require('node:assert/strict');
const {Queue,collectDrop}=require('./import-queue.js');
const file=(name)=>({name,size:100});
test('large batch stays serial, skips unsupported files, continues and retries failures',async()=>{
  let active=0,max=0,fail=true;
  const queue=new Queue(async item=>{
    max=Math.max(max,++active);await new Promise(r=>setTimeout(r,1));active--;
    if(item.file.name==='7.md'&&fail)throw Error('Network interrupted');
    return {id:item.file.name,duplicate:item.file.name==='8.md'};
  });
  await queue.add([...Array.from({length:120},(_,i)=>({file:file(i+'.md')})),{file:file('image.png')}]);
  assert.equal(max,1);assert.equal(queue.items.filter(i=>i.state==='uploaded').length,118);
  assert.equal(queue.items[7].state,'failed');assert.equal(queue.items[8].state,'duplicate');
  assert.equal(queue.items[120].state,'skipped');fail=false;await queue.retry();
  assert.equal(queue.items[7].state,'uploaded');
});
test('pause finishes current upload, resume includes files added while paused',async()=>{
  let release;const gate=new Promise(r=>release=r);
  const q=new Queue(async item=>{await gate;return {id:item.file.name}});
  const run=q.add([{file:file('first.txt')},{file:file('second.txt')}]);q.pause();
  await q.add([{file:file('third.txt')}]);release();await run;
  assert.deepEqual(q.items.map(i=>i.state),['uploaded','pending','pending']);
  await q.resume();assert.ok(q.items.every(i=>i.state==='uploaded'));
});
test('recursive folder drop reads every directory batch beyond 100 entries',async()=>{
  const entry=name=>({name,isFile:true,file:resolve=>resolve(file(name))});
  const directory=(name,batches)=>({name,isDirectory:true,createReader:()=>{let n=0;return {readEntries:r=>r(batches[n++]||[])}}});
  const root=directory('教材',[
    Array.from({length:100},(_,i)=>entry(i+'.pdf')),
    [directory('子目录',[[entry('chapter.md')]]),entry('last.txt')]
  ]);
  const result=await collectDrop([{kind:'file',webkitGetAsEntry:()=>root}]);
  assert.equal(result.files.length,102);assert.equal(result.errors.length,0);
  assert.ok(result.files.some(i=>i.path==='教材/子目录/chapter.md'));
});
