// 在本机浏览器中运行合成 DOCX 定位回归，无下载、无真实 API 或用户文档。
import { spawn } from 'node:child_process';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer } from 'node:net';
const reservation=createServer();
await new Promise(resolve=>reservation.listen(0,'127.0.0.1',resolve));
const port=reservation.address().port;
await new Promise(resolve=>reservation.close(resolve));
const profile=await mkdtemp(join(tmpdir(),'format-review-browser-'));
const browser=spawn(process.env.BROWSER_BIN || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',[
  '--headless=new','--disable-gpu','--no-first-run',`--user-data-dir=${profile}`,`--remote-debugging-port=${port}`,'--remote-debugging-address=127.0.0.1','about:blank',
],{windowsHide:true,stdio:['ignore','ignore','pipe']});
let browserLog='';browser.stderr.on('data',data=>{browserLog=(browserLog+data).slice(-2500);});
let socket;let error;
browser.on('error',value=>{error=value;});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
try{
  let tabs;
  for(let i=0;i<100;i++){
    if(error)throw error;
    try{tabs=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(tabs.some(t=>t.type==='page'))break;}catch{}
    await delay(100);
  }
  const tab=tabs?.find(t=>t.type==='page');if(!tab)throw new Error('无法连接本机浏览器调试端口');
  socket=new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
  const pending=new Map();let id=0;const diagnostics=[];
  socket.addEventListener('message',event=>{const value=JSON.parse(event.data);if(value.id){pending.get(value.id)?.(value);pending.delete(value.id);}else if(value.method==='Runtime.exceptionThrown')diagnostics.push(value.params.exceptionDetails.exception?.description || value.params.exceptionDetails.text);else if(value.method==='Network.loadingFailed')diagnostics.push(value.params.errorText);});
  socket.addEventListener('close',()=>{for(const done of pending.values())done({error:{message:'浏览器调试连接已断开'}});pending.clear();});
  const send=(method,params={})=>new Promise((resolve,reject)=>{const key=++id;const timer=setTimeout(()=>{pending.delete(key);reject(Error('浏览器命令超时：'+method));},10000);pending.set(key,value=>{clearTimeout(timer);value.error?reject(Error(value.error.message)):resolve(value.result);});socket.send(JSON.stringify({id:key,method,params}));});
  await send('Runtime.enable');await send('Network.enable');
  for(const page of ['/tests/content-review.browser.html','/tests/workflow.browser.html']){
  await send('Emulation.setDeviceMetricsOverride',{width:page.includes('workflow')?600:1280,height:900,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:(process.env.TEST_BASE_URL || 'http://127.0.0.1:5189')+page});
  let result='RUNNING';
  for(let i=0;i<300;i++){
    const value=await send('Runtime.evaluate',{expression:`location.pathname === ${JSON.stringify(page)} ? (document.querySelector("#result")?.textContent || "RUNNING") : "RUNNING"`,returnByValue:true});
    result=value.result?.value || 'RUNNING';if(result!=='RUNNING')break;await delay(100);
  }
  if(!result.startsWith('PASS:')){
    const detail=await send('Runtime.evaluate',{expression:'JSON.stringify({url:location.href,text:document.body?.innerText?.slice(0,500)})',returnByValue:true});
    throw new Error(page+'\n'+result+'\n'+detail.result?.value+'\n'+diagnostics.join('\n'));
  }
  console.log(result);
  }
  await send('Browser.close').catch(()=>{});
}catch(error){console.error(browserLog);throw error;}finally{socket?.close();browser.kill();}
