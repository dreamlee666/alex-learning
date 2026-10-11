const test=require('node:test'),assert=require('node:assert/strict');
const Detector=require('./voice-turn.js');

test('silence and keyboard-sized bursts never submit a turn',()=>{
  const d=new Detector();let events=[];
  for(let t=0;t<5000;t+=80)events.push(d.feed(t===800?.2:.001,80,t));
  assert(!events.includes('end'));assert(!d.active);
});
test('speech plus a full pause submits once and preserves thinking pauses',()=>{
  const d=new Detector({silenceMs:2000});
  for(let t=0;t<800;t+=80)d.feed(.03,80,t);
  assert(d.active);
  for(let t=800;t<1600;t+=80)assert.notEqual(d.feed(.001,80,t),'end');
  for(let t=1600;t<1920;t+=80)d.feed(.03,80,t);
  for(let t=1920;t<3840;t+=80)assert.notEqual(d.feed(.001,80,t),'end');
  assert.equal(d.feed(.001,80,3840),'end');
  assert.equal(d.feed(.001,80,3920),'idle');
});
test('a new turn can start after reset and a long turn is bounded',()=>{
  const d=new Detector({maxTurnMs:1200});
  let ended=false;
  for(let t=0;t<2000;t+=80)if(d.feed(.04,80,t)==='end'){ended=true;break}
  assert(ended);d.reset();assert(!d.active);
  for(let t=3000;t<3400;t+=80)d.feed(.04,80,t);
  assert(d.active);
});
test('pause choice changes when a turn is sent',()=>{
  const d=new Detector({silenceMs:3500});
  for(let t=0;t<480;t+=80)d.feed(.04,80,t);
  assert.notEqual(d.feed(.001,80,2500),'end');
  assert.equal(d.feed(.001,80,4000),'end');
});
test('a short yes or no is long enough to submit a turn',()=>{
  const d=new Detector();
  d.feed(.04,80,0);d.feed(.04,80,80);
  assert(d.active);
  assert.equal(d.feed(.001,80,2080),'end');
});
