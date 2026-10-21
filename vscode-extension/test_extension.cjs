'use strict';
// Integration tests using the real HTTP server and mocked VS Code API.
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert'),http=require('http');
const Module=require('module');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'rhino-v055-'));
const prior=process.env.HOME;process.env.HOME=dir;
const commands={};const sent=[];
const setting={autoSend:false,autoSubmit:false,draftTTLSeconds:60};
const terminal={name:'Test AI Agent',sendText:(s,enter)=>sent.push({s,enter})};
let changeCallback=null,closedCallback=null;
const vscode={
  StatusBarAlignment:{Left:1},
  workspace:{getConfiguration:()=>({get:(name,defaultValue)=>name in setting?setting[name]:defaultValue}),
    onDidChangeConfiguration:(cb)=>{changeCallback=cb;return {dispose(){}};}},
  window:{terminals:[terminal],activeTerminal:terminal,
    createStatusBarItem:()=>({show(){},dispose(){}}),
    createOutputChannel:()=>({appendLine(){},dispose(){}}),
    showQuickPick:async opts=>opts[0],showInformationMessage:async()=>null,
    showWarningMessage:async(_message,options,action)=>action||null,
    showInputBox:async o=>o.value,
    onDidCloseTerminal:cb=>{closedCallback=cb;return {dispose(){}};}
  },
  commands:{registerCommand:(n,cb)=>{commands[n]=cb;return {dispose(){}};}}
};
const orig=Module._load;Module._load=function(req,parent,isMain){if(req==='vscode')return vscode;return orig.apply(this,arguments);};
const extension=require('./extension.js');Module._load=orig;
function link(){return JSON.parse(fs.readFileSync(path.join(dir,'Library','Application Support','RhinoGamepad','agent-link.json'),'utf8'));}
async function post(info,route,body={},token=info.token){
  return new Promise((resolve,reject)=>{
    const data=JSON.stringify(body);
    const req=http.request({host:'127.0.0.1',port:info.port,path:'/'+route,method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json','Content-Length':Buffer.byteLength(data)}},res=>{
      let str='';res.on('data',v=>str+=v);res.on('end',()=>resolve({code:res.statusCode,body:JSON.parse(str)}));
    });
    req.on('error',reject);req.end(data);
  });
}
(async()=>{
  extension.activate({subscriptions:[]});
  await commands['rhinoGamepad.bindTerminal']();
  const info=link(), a='a'.repeat(32),b='b'.repeat(32),c='c'.repeat(32),d='d'.repeat(32);
  assert.equal(info.version,'0.5.5');
  assert.equal((await post(info,'status',{},'bad')).code,403);
  assert.equal((await post(info,'status')).body.autoSend,false);
  assert.equal((await post(info,'draft',{id:a,prompt:'Review\nthis; rm -rf /\x1b[31m'})).code,200);
  // Idempotent duplicate stage; changed prompt with same ID fails
  assert.equal((await post(info,'draft',{id:a,prompt:'Review\nthis; rm -rf /\x1b[31m'})).body.previous,true);
  assert.equal((await post(info,'draft',{id:a,prompt:'different'})).code,409);
  // New draft replaces stale unsubmitted one, old cannot send
  assert.equal((await post(info,'draft',{id:b,prompt:'inspect geometry'})).body.state,'ready');
  assert.equal((await post(info,'send',{id:a})).body.state,'replaced');
  assert.equal(sent.length,0);
  assert.equal((await post(info,'send',{id:b})).body.state,'sent');
  assert.equal(sent.length,1);
  assert.equal(sent[0].enter,false);
  assert.equal((await post(info,'send',{id:b})).body.alreadyProcessed,true);
  assert.equal(sent.length,1); // NEVER double send
  assert.equal((await post(info,'draft',{id:b,prompt:'inspect geometry'})).body.state,'sent');
  assert.equal(sent.length,1);
  assert.equal((await post(info,'cancel',{id:b})).body.state,'sent');
  assert.equal(sent.length,1);
  // Expiration after configurable TTL, using a clock offset instead of sleeping.
  let fakeNow=Date.now(),origNow=Date.now;Date.now=()=>fakeNow;
  try {
    await post(info,'draft',{id:c,prompt:'expires'});
    fakeNow+=61000;
    assert.equal((await post(info,'status')).body.pending,false);
    assert.equal((await post(info,'send',{id:c})).body.state,'expired');
  } finally {Date.now=origNow;}
  // Configured hands-free mode exposed through link file.
  setting.autoSend=true;setting.autoSubmit=true;
  changeCallback({affectsConfiguration:(key)=>key==='rhinoGamepad'});
  assert.equal(link().autoSend,true);
  assert.equal(link().autoSubmit,true);
  assert.equal((await post(info,'status')).body.autoSubmit,true);
  await post(info,'draft',{id:d,prompt:'Describe these surfaces\n\x1b[2J'});
  await post(info,'send',{id:d});
  assert.equal(sent.length,2);assert.equal(sent[1].enter,true);
  assert(!/[\r\n\x1b]/.test(sent[1].s));
  // Cancel is idempotent; status of old cancels is remembered
  const e='e'.repeat(32);
  await post(info,'draft',{id:e,prompt:'Never submit'});
  assert.equal((await post(info,'cancel',{id:e})).body.state,'cancelled');
  assert.equal((await post(info,'cancel',{id:e})).body.alreadyProcessed,true);
  assert.equal((await post(info,'send',{id:e})).body.ok,false);
  assert.equal(sent.length,2);
  closedCallback(terminal);
  assert(!fs.existsSync(path.join(dir,'Library','Application Support','RhinoGamepad','agent-link.json')));
  extension.deactivate();
  fs.rmSync(dir,{recursive:true,force:true});
  if(prior===undefined)delete process.env.HOME;else process.env.HOME=prior;
  console.log('v0.5.5 extension integration tests PASS: auth, draft replacement, expiry, idempotence, cancellation, config, safe terminal insert.');
})().catch(e=>{console.error(e);process.exitCode=1;extension.deactivate();});
