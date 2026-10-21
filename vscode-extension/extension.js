'use strict';
// Rhino Gamepad Agent Link v0.5.5: local, authenticated, explicitly bound terminal.
const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const http = require('http');

const LINK_FILE = path.join(os.homedir(), 'Library', 'Application Support', 'RhinoGamepad', 'agent-link.json');
const HISTORY_TTL_MS = 20 * 60 * 1000;
const HISTORY_MAX = 512;
let server = null, registeredTerminal = null, pending = null, secret = null, address = null;
let statusBar = null, output = null;
let autoSubmitSession = false;
const history = new Map();

function settings() {
  const c = vscode.workspace.getConfiguration('rhinoGamepad');
  return {
    autoSend: Boolean(c.get('autoSend', false)),
    autoSubmit: Boolean(c.get('autoSubmit', false)) || autoSubmitSession,
    ttlMs: Math.min(600, Math.max(15, Number(c.get('draftTTLSeconds', 60)) || 60)) * 1000
  };
}
function cleanText(str) {
  // Input is destined for a PTY: strip control bytes, CR, LF, OSC, CSI, and C1.
  if (typeof str !== 'string') return '';
  return str.replace(/[\x00-\x1f\x7f-\x9f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 24000);
}
function hash(str) { return crypto.createHash('sha256').update(str).digest('hex'); }
function ensureLinkDirectory() { fs.mkdirSync(path.dirname(LINK_FILE), {recursive:true, mode:0o700}); }
function writeLink() {
  if (!address || !secret) return;
  ensureLinkDirectory();
  const tmp = `${LINK_FILE}.${process.pid}.tmp`;
  const config = settings();
  fs.writeFileSync(tmp, JSON.stringify({host:'127.0.0.1',port:address.port,token:secret,
    version:'0.5.5', autoSend:config.autoSend,autoSubmit:config.autoSubmit}),
    {mode:0o600, flag:'w'});
  fs.chmodSync(tmp,0o600);
  fs.renameSync(tmp,LINK_FILE);
}
function cleanupLink() {
  try { const data=JSON.parse(fs.readFileSync(LINK_FILE,'utf8'));
    if(data.token === secret)fs.unlinkSync(LINK_FILE); }catch(_){}
}
function terminalReady() {
  return Boolean(registeredTerminal && vscode.window.terminals.includes(registeredTerminal));
}
function remember(id, state, digest, now=Date.now()) {
  history.set(id,{state,digest,at:now});
  prune(now);
}
function prune(now=Date.now()) {
  for(const [id,entry] of history) {
    if(now-entry.at>HISTORY_TTL_MS)history.delete(id);
  }
  while(history.size>HISTORY_MAX)history.delete(history.keys().next().value);
}
function expire(now=Date.now()) {
  prune(now);
  if(pending && now-pending.at >= settings().ttlMs) {
    remember(pending.id,'expired',pending.digest,now);
    output?.appendLine('Expired unsubmitted voice draft '+pending.id.slice(0,8));
    pending=null;
    updateStatus();
  }
}
function updateStatus() {
  if(!statusBar)return;
  if(!terminalReady() || !server)statusBar.text='$(debug-disconnect) Rhino agent: not bound';
  else if(pending)statusBar.text='$(mic) Rhino agent: draft ready';
  else statusBar.text='$(terminal) Rhino agent: '+registeredTerminal.name;
  const s=settings();
  statusBar.tooltip='Click to bind a terminal. Auto-send: '+(s.autoSend?'ON':'OFF')+
    '; auto-submit: '+(s.autoSubmit?'ON (executes terminal input)':'OFF');
  statusBar.show();
}
function respond(res,code,obj) {
  res.writeHead(code,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
  res.end(JSON.stringify(obj));
}
function processRoute(route,body) {
  expire();
  if(!terminalReady())return {code:409,body:{ok:false,error:'terminal not bound or closed'}};
  const config=settings();
  if(route==='/status')return {code:200,body:{ok:true,terminal:registeredTerminal.name,
    autoSubmit:config.autoSubmit,autoSend:config.autoSend,pending:pending!==null,
    pendingId:pending?.id||null}};
  const id=body && body.id;
  if(typeof id !=='string'|| !/^[0-9a-f]{32}$/.test(id))
    return {code:400,body:{ok:false,error:'invalid request ID'}};
  const prior=history.get(id);
  if(route==='/draft') {
    if(typeof body.prompt!=='string'||!body.prompt.trim()||body.prompt.length>24000 ||!cleanText(body.prompt))
      return {code:400,body:{ok:false,error:'invalid draft'}};
    const digest=hash(body.prompt);
    if(prior) {
      if(prior.digest !== digest)return {code:409,body:{ok:false,error:'request ID already used with different content'}};
      return {code:200,body:{ok:true,state:prior.state,previous:true}};
    }
    if(pending && pending.id===id) {
      if(pending.digest!==digest)return {code:409,body:{ok:false,error:'request ID already staged with different content'}};
      return {code:200,body:{ok:true,state:'ready',previous:true}};
    }
    if(pending) {
      remember(pending.id,'replaced',pending.digest);
      output.appendLine('Replacing unsubmitted draft '+pending.id.slice(0,8));
    }
    pending={id,prompt:body.prompt,digest,at:Date.now()};
    output.appendLine('Voice draft staged ('+pending.prompt.length+' chars) for '+registeredTerminal.name);
    updateStatus(); // No global notification: can steal Rhino focus.
    return {code:200,body:{ok:true,state:'ready'}};
  }
  if(route==='/send') {
    if(prior)return {code:200,body:{ok:prior.state==='sent',state:prior.state,alreadyProcessed:true,
      submitted:prior.state==='sent'?prior.submitted:undefined}};
    if(!pending||pending.id!==id)return {code:409,body:{ok:false,error:'no matching draft'}};
    const msg=cleanText(pending.prompt);
    if(!msg)return {code:400,body:{ok:false,error:'empty prompt'}};
    try {
      registeredTerminal.sendText(msg,config.autoSubmit);
      // This acknowledges VS Code's sendText invocation, not agent execution.
      const digest=pending.digest;
      pending=null;
      remember(id,'sent',digest);
      history.get(id).submitted=config.autoSubmit;
      output.appendLine('Sent text to bound terminal '+registeredTerminal.name+
        (config.autoSubmit?' with newline (agent readiness unverified)':' without newline'));
      updateStatus();
      return {code:200,body:{ok:true,state:'sent',submitted:config.autoSubmit}};
    }catch(e) {
      output.appendLine('Terminal sendText failed: '+String(e));
      return {code:500,body:{ok:false,error:'terminal send failed'}};
    }
  }
  if(route==='/cancel') {
    if(prior)return {code:200,body:{ok:true,state:prior.state,alreadyProcessed:true}};
    if(!pending||pending.id!==id)return {code:409,body:{ok:false,error:'no matching draft'}};
    remember(id,'cancelled',pending.digest);
    pending=null;
    updateStatus();
    return {code:200,body:{ok:true,state:'cancelled'}};
  }
  return {code:404,body:{ok:false,error:'unknown route'}};
}
function startListener() {
  if(server){writeLink();return Promise.resolve();}
  return new Promise((resolve,reject)=>{
    secret=crypto.randomBytes(32).toString('hex');
    server=http.createServer((req,res)=>{
      if(!['127.0.0.1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress))
        return respond(res,403,{ok:false,error:'loopback only'});
      if(req.method!=='POST'||req.headers.authorization!=='Bearer '+secret)
        return respond(res,403,{ok:false,error:'unauthorized'});
      let buf='',tooLarge=false;
      req.on('data', chunk=>{
        buf+=chunk;
        if(buf.length>64000){tooLarge=true;respond(res,413,{ok:false,error:'request too large'});req.destroy();}
      });
      req.on('end',()=>{
        if(tooLarge)return;
        let body;
        try{body=JSON.parse(buf);}catch(_){return respond(res,400,{ok:false,error:'invalid JSON'});}
        const result=processRoute(req.url,body);
        respond(res,result.code,result.body);
      });
    });
    server.once('error',err=>{server=null;reject(err);});
    server.listen(0,'127.0.0.1',()=>{
      address=server.address();
      try{writeLink();updateStatus();resolve();}
      catch(err){server.close();server=null;reject(err);}
    });
  });
}
function stop() {
  pending=null;registeredTerminal=null;cleanupLink();
  if(server)server.close();server=null;secret=null;address=null;
  autoSubmitSession=false;history.clear();updateStatus();
}
async function bindTerminal() {
  const terminals=vscode.window.terminals;
  if(!terminals.length)return vscode.window.showWarningMessage('Start your AI CLI in a VS Code terminal first.');
  const choices=terminals.map(t=>({label:t.name,
    description:t===vscode.window.activeTerminal?'active terminal':'',term:t}));
  const chosen=await vscode.window.showQuickPick(choices,{title:'Choose the CLI agent terminal, not a shell'});
  if(!chosen)return;
  registeredTerminal=chosen.term;
  try{await startListener();writeLink();updateStatus();
    vscode.window.showInformationMessage('Rhino Agent linked to '+chosen.term.name+'.');
  }catch(err){registeredTerminal=null;vscode.window.showErrorMessage('Rhino Agent link failed: '+err.message);}
}
async function reviewDraft() {
  expire();
  if(!pending)return vscode.window.showInformationMessage('No Rhino voice draft waiting.');
  const edit=await vscode.window.showInputBox({title:'Review Rhino voice draft',
    value:pending.prompt,ignoreFocusOut:true});
  if(typeof edit==='string') {
    if(!edit.trim())return vscode.window.showWarningMessage('Draft cannot be empty.');
    pending.prompt=edit;pending.digest=hash(edit);pending.at=Date.now();
    output.appendLine('Pending draft edited');
    updateStatus();
  }
}
async function toggleSubmit() {
  if(!terminalReady())return vscode.window.showWarningMessage('Bind an agent terminal first.');
  if(autoSubmitSession){autoSubmitSession=false;writeLink();updateStatus();return;}
  const result=await vscode.window.showWarningMessage(
    'WARNING: Auto-submit sends Enter to the bound terminal. If your agent exited, the dictated command can execute in the shell. Enable for this session?',
    {modal:true},'Enable for session');
  if(result==='Enable for session'){autoSubmitSession=true;writeLink();updateStatus();}
}
function activate(context) {
  output=vscode.window.createOutputChannel('Rhino Gamepad Agent');
  statusBar=vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left,100);
  statusBar.command='rhinoGamepad.bindTerminal';updateStatus();
  const commands=[
    vscode.commands.registerCommand('rhinoGamepad.bindTerminal',bindTerminal),
    vscode.commands.registerCommand('rhinoGamepad.preview',reviewDraft),
    vscode.commands.registerCommand('rhinoGamepad.toggleSubmit',toggleSubmit),
    vscode.commands.registerCommand('rhinoGamepad.disconnect',()=>{stop();vscode.window.showInformationMessage('Rhino Agent disconnected.');}),
    vscode.window.onDidCloseTerminal(t=>{if(t===registeredTerminal){stop();vscode.window.showWarningMessage('Bound agent terminal closed; disconnected.');}})
  ];
  if(vscode.workspace.onDidChangeConfiguration)commands.push(vscode.workspace.onDidChangeConfiguration(e=>{
    if(e.affectsConfiguration('rhinoGamepad')){writeLink();updateStatus();}
  }));
  context.subscriptions.push(...commands,statusBar,output,{dispose:stop});
}
function deactivate(){stop();}
module.exports={activate,deactivate};
