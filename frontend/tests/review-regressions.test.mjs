import test, { beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { parse, compileScript } from '@vue/compiler-sfc';
import ts from 'typescript';
import { createRenderer, h, reactive, nextTick } from 'vue';

const require = createRequire(import.meta.url);
const mounted = [];
globalThis.window = new EventTarget();
window.setTimeout = setTimeout;
let sequence=0;
const empty = async () => ({data:[]});
beforeEach(() => {
  globalThis.__reviewMocks = {
    ruleApi:{list:empty,templates:empty},documentApi:{list:empty},checkApi:{list:empty},
    contentReviewApi:{list:empty},templateAuditApi:{current:async()=>({data:null}),versions:empty,reviews:empty},
    workspace:reactive({currentId:null,workspaces:[],load:async()=>{}}),auth:reactive({user:{username:'test'}}),
    box:{confirm:async()=>{},prompt:async()=>({value:'确认'})},message:Object.assign(()=>{},{success(){},error(){},warning(){}}),
  };
});
afterEach(()=>{for(const app of mounted.splice(0))app.unmount();});

function dataModule(source){return 'data:text/javascript;base64,'+Buffer.from(source+'\n// module '+sequence).toString('base64');}
function resolveImport(name){
  if(name==='vue')return pathToFileURL(require.resolve('vue')).href;
  if(name.startsWith('element-plus'))return dataModule('export const ElMessage=globalThis.__reviewMocks.message;export const ElMessageBox=globalThis.__reviewMocks.box;');
  if(name==='vue-router')return dataModule('export const useRouter=()=>({push(){}});');
  if(name==='@/api')return dataModule('const m=globalThis.__reviewMocks;export const {ruleApi,documentApi,checkApi,contentReviewApi,templateAuditApi}=m;');
  if(name==='@/api/http')return dataModule('export const errText=e=>String(e?.message||e);export default {};');
  if(name.includes('stores/workspace'))return dataModule('export const useWorkspaceStore=()=>globalThis.__reviewMocks.workspace;');
  if(name.includes('stores/auth'))return dataModule('export const useAuthStore=()=>globalThis.__reviewMocks.auth;');
  if(name.endsWith('.vue'))return dataModule('export default {};');
  throw new Error('Unexpected import '+name);
}
async function mount(file, props={}){
  const source=await readFile(new URL('../src/'+file,import.meta.url),'utf8');
  const {descriptor}=parse(source);
  const script=compileScript(descriptor,{id:'test'+sequence++});
  let js=ts.transpileModule(script.content,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
  js=js.replace(/(from\s*|import\s*\()(['"])([^'"]+)\2/g,(_m,start,_quote,name)=>start+JSON.stringify(resolveImport(name)));
  const component=(await import(dataModule(js)+'#'+sequence)).default;
  component.render=()=>h('div');
  const renderer=createRenderer({
    createElement:type=>({type,children:[]}),createText:text=>({text}),createComment:text=>({text}),
    setText(node,text){node.text=text;},setElementText(node,text){node.text=text;},
    insert(node,parent){parent.children??=[];parent.children.push(node);},remove(){},patchProp(){},parentNode(){return null;},nextSibling(){return null;},
  });
  const events=[];const reactiveProps=reactive(props);
  const app=renderer.createApp({...component,emits:component.emits},reactiveProps);
  // 记录真实 setup 发出的事件，不需要浏览器或真实网络。
  for(const event of component.emits??[])reactiveProps['on'+event.split('-').map(s=>s[0].toUpperCase()+s.slice(1)).join('')]=(...args)=>events.push([event,...args]);
  const vm=app.mount({children:[]});mounted.push(app);
  await nextTick();
  return {state:vm.$.setupState,props:reactiveProps,events,instance:vm.$};
}
const flush=async()=>{await new Promise(resolve=>setTimeout(resolve,0));await nextTick();};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};

test('预设模板解除 Vue 代理后可创建独立草稿',async()=>{
  const {state}=await mount('views/HomeView.vue');
  const template=reactive({id:'system',name:'规范',ruleset:{name:'规范',body:{font:{size:12}}}});
  await state.onAddRule(template);
  assert.equal(state.ruleDraft.body.font.size,12);
  state.ruleDraft.body.font.size=18;
  assert.equal(template.ruleset.body.font.size,12);
});

test('候选必须明确选择，大标题与一级标题写入不同作用域',async()=>{
  const candidate=(id,scope,size)=>({id,scope,count:1,examples:['原文'],paragraph_indexes:[0],style:{font:{size}}});
  const {state,events}=await mount('components/TemplateCandidatesDialog.vue',{extraction:{ruleset:{name:'规范'},warnings:[],candidates:{title:[candidate('title','title',28)],h1:[candidate('a','h1',18),candidate('b','h1',16)]}}});
  assert.equal(state.complete,false);
  state.choices.title='title';state.choices.h1='b';await nextTick();state.confirm();
  const result=events.find(([name])=>name==='confirm')?.[1];
  assert.equal(result.title.font.size,28);assert.equal(result.headings.h1.font.size,16);
});

test('工作区切换后迟到的列表不能覆盖当前页面',async()=>{
  const {state}=await mount('views/HomeView.vue');const m=globalThis.__reviewMocks;
  const pending=deferred();m.documentApi.list=()=>pending.promise;
  m.workspace.currentId=1;const load=state.loadDocuments();m.workspace.currentId=2;
  pending.resolve({data:[{id:1,filename:'旧工作区',workspace_id:1}]});await load;
  assert.deepEqual(state.documents,[]);
});

test('迟到的内容历史不能覆盖刚完成的新审查',async()=>{
  const m=globalThis.__reviewMocks;const old=deferred();m.contentReviewApi.list=()=>old.promise;
  m.contentReviewApi.run=async()=>({data:{id:2,document_id:1,summary:'NEW',issues:[]}});
  const {state}=await mount('components/ContentReviewPanel.vue',{workspaceId:1,document:{id:1,filename:'sample.docx'}});
  assert.equal(await state.run(),true);
  old.resolve({data:[{id:1,summary:'OLD',issues:[]}]});await flush();
  assert.equal(state.current.id,2);assert.equal(state.history.length,2);
});

test('规则编辑保留独立标题和可恢复的不限制状态',async()=>{
  const {state,events}=await mount('components/RuleEditor.vue',{rule:null,draft:{name:'规范',title:{font:{size:28}},headings:{h1:{font:{size:18,bold:true}}}}});
  state.form.headings.h1.font.bold=null;
  assert.equal(state.isDirty,true);
  const result=state.cleaned();assert.equal(result.title.font.size,28);assert.equal(result.headings.h1.font.bold,null);
});

test('历史表单报告按保存的模板快照展示',async()=>{
  const {state}=await mount('components/TemplateAuditPanel.vue',{workspaceId:null,documents:[],selectedDocumentId:null,acceptedFixes:[]});
  state.current={id:2,version:2,config:{blocks:[]}};
  state.review={id:1,template_id:1,template_version:1,template_snapshot:{id:1,version:1,config:{blocks:[]}}};
  assert.equal(state.comparisonTemplate.id,1);
});

test('迟到的格式历史不能覆盖刚完成的格式审查',async()=>{
  const {state}=await mount('views/HomeView.vue');const m=globalThis.__reviewMocks;
  const pending=deferred();m.checkApi.list=()=>pending.promise;
  m.checkApi.run=async()=>({data:{id:9,document_id:1,rule_id:2,summary:{total:1,compliant:false,by_category:{font:1}},violations:[]}});
  m.workspace.currentId=1;state.selectedDocId=1;state.selectedRuleId=2;
  await nextTick();const loading=state.loadChecks();assert.equal(await state.runFormatCheck(),true);
  pending.resolve({data:[]});await loading;await flush();
  assert.equal(state.check.id,9);assert.equal(state.checks[0].id,9);
});

test('预设、候选确认和历史入口均进入文本模板审查内部',async()=>{
  const {state}=await mount('views/HomeView.vue');
  await state.onAddRule(null);
  assert.equal(state.tab,'text-template');assert.equal(state.textReviewTab,'editor');
  state.onConfirmCandidates({name:'候选规则',title:{font:{size:28}}});
  assert.equal(state.tab,'text-template');assert.equal(state.textReviewTab,'editor');
  assert.equal(state.ruleDraft.title.font.size,28);
  await state.onSelectHistory({id:5,document_id:1,rule_id:2});
  assert.equal(state.tab,'text-template');assert.equal(state.textReviewTab,'report');
  state.onRuleRestored({id:2,ruleset:{name:'恢复规则'}});
  assert.equal(state.tab,'text-template');assert.equal(state.textReviewTab,'editor');
});

test('文本模板内可仅审内容，无格式规则时不调用格式引擎',async()=>{
  const {state}=await mount('views/HomeView.vue');const m=globalThis.__reviewMocks;
  m.workspace.currentId=1;state.selectedDocId=1;state.selectedRuleId=null;
  state.reviewTypes=['content'];let contentCalls=0;
  state.contentReviewPanel={running:false,run:async()=>{contentCalls++;return true;}};
  m.checkApi.run=()=>{throw Error('内容审查不应执行格式检查');};
  assert.equal(state.canRunSelectedReviews,true);
  await state.runSelectedReviews();
  assert.equal(contentCalls,1);assert.equal(state.tab,'text-template');assert.equal(state.textReviewTab,'content');
});

test('格式和内容可同时执行且结果仍在文本模板内部独立展示',async()=>{
  const {state}=await mount('views/HomeView.vue');const m=globalThis.__reviewMocks;
  m.workspace.currentId=1;state.selectedDocId=1;state.selectedRuleId=2;state.reviewTypes=['format','content'];
  let formatCalls=0;let contentCalls=0;
  m.checkApi.run=async()=>{formatCalls++;return {data:{id:1,document_id:1,rule_id:2,summary:{total:0,compliant:true},violations:[]}};};
  state.contentReviewPanel={running:false,run:async()=>{contentCalls++;return true;}};
  await state.runSelectedReviews();
  assert.equal(formatCalls,1);assert.equal(contentCalls,1);
  assert.equal(state.tab,'text-template');assert.equal(state.textReviewTab,'report');
  assert.equal(state.formatProgress,'已完成');assert.equal(state.contentProgress,'已完成');
});

test('未保存的规则不可按旧配置执行格式审查，内容审查不受影响',async()=>{
  const {state}=await mount('views/HomeView.vue');
  state.selectedDocId=1;state.selectedRuleId=2;state.ruleEditor={isDirty:true};
  assert.equal(state.canRunSelectedReviews,false);
  state.reviewTypes=['content'];assert.equal(state.canRunSelectedReviews,true);
});
