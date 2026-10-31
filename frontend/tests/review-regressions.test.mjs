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
    contentReviewApi:{list:empty},templateAuditApi:{current:async()=>({data:null}),versions:empty,reviews:empty},reportApi:{},downloads:[],
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
  if(name==='@/api')return dataModule('const m=globalThis.__reviewMocks;export const {ruleApi,documentApi,checkApi,contentReviewApi,templateAuditApi,reportApi}=m;');
  if(name==='@/api/http')return dataModule('export const errText=e=>String(e?.message||e);export default {};');
  if(name==='@/utils/download')return dataModule('export const downloadBlob=(blob,name)=>globalThis.__reviewMocks.downloads.push([blob,name]);export const downloadErrorText=async e=>String(e?.message||e);');
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

test('工作区问题分布与报告使用相同中文类别标签', async()=>{
  const source=await readFile(new URL('../src/utils/violationLabels.ts',import.meta.url),'utf8');
  const js=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
  const {categoryLabel}=await import(dataModule(js)+'#labels'+sequence++);
  assert.equal(categoryLabel('template_content'),'固定内容');
  assert.equal(categoryLabel('template_structure'),'模板结构');
  assert.equal(categoryLabel('paragraph'),'段落');
  const dashboard=await readFile(new URL('../src/components/WorkspaceDashboard.vue',import.meta.url),'utf8');
  const report=await readFile(new URL('../src/components/ViolationReport.vue',import.meta.url),'utf8');
  assert.match(dashboard,/import \{ categoryLabel \} from "@\/utils\/violationLabels"/);
  assert.match(report,/import \{ categoryLabel \} from "@\/utils\/violationLabels"/);
  assert.match(dashboard,/\.category-name \{[^}]*text-overflow: ellipsis/);
});

test('表单填写要求修改后旧规则不再被静默执行', async()=>{
  const {state}=await mount('components/TemplateAuditPanel.vue',{
    workspaceId:null,documents:[],selectedDocumentId:null,acceptedFixes:[],
  });
  const block=reactive({id:'people',label:'家庭人口数',mode:'variable',rules:[{kind:'exact_text',text:'6人'}],
    requirement_text:'人数要写6人',unsupported_requirements:[]});
  state.openRequirements(block);
  assert.equal(state.requirementText,'人数要写6人');
  state.onRequirementInput('人数填写数字即可');
  assert.deepEqual(block.rules,[]);
  assert.deepEqual(block.unsupported_requirements,['人数填写数字即可']);
  state.clearUnsupported();
  assert.deepEqual(block.unsupported_requirements,[]);
});

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

test('候选样式以可读摘要显示，不暴露原始样式 JSON',async()=>{
  const candidate={id:'body',scope:'body',count:1,examples:['原文'],paragraph_indexes:[0],style:{font:{name:'宋体',ascii_name:'Times New Roman',size:12,bold:false},paragraph:{alignment:'justify',line_spacing:1.5,line_spacing_kind:'multiple',space_before:0,space_after:0,first_line_indent_chars:2,numbered:false,bullet:false}}};
  const {state}=await mount('components/TemplateCandidatesDialog.vue',{extraction:{ruleset:{name:'规范'},warnings:[],candidates:{body:[candidate]}}});
  assert.match(state.describe(candidate),/宋体 · Times New Roman · 12pt · 不加粗 · 两端对齐 · 行距 1.5 倍/);
  assert.deepEqual(state.details(candidate),[{label:'段前',value:'0 磅'},{label:'段后',value:'0 磅'},{label:'首行缩进',value:'2 字符'}]);
  const source=await readFile(new URL('../src/components/TemplateCandidatesDialog.vue',import.meta.url),'utf8');
  assert.doesNotMatch(source,/JSON\.stringify\(candidate\.style\)/);
});

test('结构模板可配置固定、可变和忽略章节并写入规则草稿',async()=>{
  const regions=[
    {id:'chapter-1',label:'第1章 概述',anchor:'第1章 概述',level:1,mode:'fixed',required:true,check_format:true,template_paragraph_index:0,heading_style:{font:{size:18}},body_style:{font:{size:12}}},
    {id:'chapter-2',label:'第2章 实现',anchor:'第2章 实现',level:1,mode:'fixed',required:true,check_format:true,template_paragraph_index:2,heading_style:{font:{size:18}},body_style:{font:{size:12}}},
  ];
  const checks={check_toc:true,toc_entries:['第1章 概述'],check_figure_numbering:true,check_table_numbering:false,check_code_style:true,code_style:{font:{size:10}}};
  const {state,events}=await mount('components/TemplateCandidatesDialog.vue',{extraction:{ruleset:{name:'结构规范',template_checks:checks},warnings:[],candidates:{},regions}});
  assert.equal(state.hasRegions,true);assert.equal(state.complete,true);
  state.regionDrafts[1].mode='variable';state.regionDrafts[0].check_format=false;state.documentChecks.check_code_style=false;state.confirm();
  const result=events.find(([name])=>name==='confirm')?.[1];
  assert.equal(result.template_regions[1].mode,'variable');assert.equal(result.template_regions[0].check_format,false);
  assert.equal(result.template_checks.check_code_style,false);assert.equal(checks.check_code_style,true);assert.equal(regions[1].mode,'fixed');
});

test('规则历史展示模板章节和文档级检查的版本差异',async()=>{
  const rule={id:1,name:'模板规则',ruleset:{name:'模板规则'}};
  const {state}=await mount('components/RuleVersionsDialog.vue',{modelValue:false,rule});
  state.versions=[
    {id:2,version:2,name:'模板规则',natural_language:'',created_at:'2026-01-02',ruleset:{name:'模板规则',template_regions:[{id:'a',label:'第一章',anchor:'第一章',level:1,mode:'variable',required:true,check_format:true,template_paragraph_index:0}],template_checks:{check_toc:true,toc_entries:['第一章'],check_figure_numbering:true,check_table_numbering:false,check_code_style:false}}},
    {id:1,version:1,name:'模板规则',natural_language:'',created_at:'2026-01-01',ruleset:{name:'模板规则',template_regions:[{id:'a',label:'第一章',anchor:'第一章',level:1,mode:'fixed',required:true,check_format:true,template_paragraph_index:0}],template_checks:{check_toc:false,toc_entries:[],check_figure_numbering:false,check_table_numbering:false,check_code_style:false}}},
  ];
  assert.deepEqual(state.changes(0),['调整模板章节：第一章','启用目录校验','启用图片题注编号']);
  assert.match(state.summary(state.versions[0]),/1 个模板章节.*目录图表与代码/);
});

test('工作区切换后迟到的列表不能覆盖当前页面',async()=>{
  const {state}=await mount('views/HomeView.vue');const m=globalThis.__reviewMocks;
  const pending=deferred();m.documentApi.list=()=>pending.promise;
  m.workspace.currentId=1;const load=state.loadDocuments();m.workspace.currentId=2;
  pending.resolve({data:[{id:1,filename:'旧工作区',workspace_id:1}]});await load;
  assert.deepEqual(state.documents,[]);
});

test('删除当前工作区后清空页面状态和选择',async()=>{
  const m=globalThis.__reviewMocks;
  m.auth.user.id=7;
  m.workspace.currentId=1;
  m.workspace.workspaces=[{id:1,name:'待删除',owner_id:7,role:'owner'}];
  const removed=[];
  m.workspace.remove=async id=>{removed.push(id);m.workspace.workspaces=[];m.workspace.currentId=null;};
  const {state}=await mount('views/HomeView.vue');
  await flush();
  state.documents=[{id:3,filename:'旧文件.docx'}];
  await state.onDeleteWorkspace();
  assert.deepEqual(removed,[1]);
  assert.equal(m.workspace.currentId,null);
  assert.deepEqual(state.documents,[]);
  assert.equal(state.selectedDocId,null);
});

test('删除表单模板版本后刷新版本和历史并清除待应用修订',async()=>{
  const m=globalThis.__reviewMocks;
  const template={id:3,workspace_id:1,version:2,name:'旧模板',filename:'template.docx',is_active:true,is_published:true,
    is_review_active:true,config:{check_page:true,blocks:[]}};
  let exists=true;
  m.templateAuditApi.current=async()=>({data:exists?template:null});
  m.templateAuditApi.versions=async()=>({data:exists?[template]:[]});
  m.templateAuditApi.reviews=async()=>({data:exists?[{id:9,template_id:3,document_id:5,template_version:2,template_snapshot:template}]:[]});
  m.templateAuditApi.removeVersion=async(_workspaceId,id)=>{assert.equal(id,3);exists=false;};
  const {state,events}=await mount('components/TemplateAuditPanel.vue',{
    workspaceId:1,documents:[],selectedDocumentId:5,acceptedFixes:[],
  });
  await flush();
  assert.equal(state.current.id,3);
  await state.deleteCurrentVersion();
  assert.equal(state.current,null);
  assert.deepEqual(state.versions,[]);
  assert.deepEqual(state.reviews,[]);
  assert.ok(events.some(([name])=>name==='clear-fixes'));
  assert.ok(events.some(([name,id])=>name==='clear-review'&&id===9));
});

test('迟到的内容历史不能覆盖刚完成的新审查',async()=>{
  const m=globalThis.__reviewMocks;const old=deferred();m.contentReviewApi.list=()=>old.promise;
  m.contentReviewApi.run=async()=>({data:{id:2,document_id:1,summary:'NEW',issues:[]}});
  const {state}=await mount('components/ContentReviewPanel.vue',{workspaceId:1,document:{id:1,filename:'sample.docx'}});
  assert.equal(await state.run(),true);
  old.resolve({data:[{id:1,summary:'OLD',issues:[]}]});await flush();
  assert.equal(state.current.id,2);assert.equal(state.history.length,2);
});

test('内容报告只下载当前选中记录，切换记录后丢弃迟到的下载',async()=>{
  const m=globalThis.__reviewMocks;
  m.contentReviewApi.list=async()=>({data:[{id:2,document_id:1,summary:'新',issues:[]},{id:1,document_id:1,summary:'旧',issues:[]}]});
  const pending=deferred();const requested=[];
  m.reportApi.content=id=>{requested.push(id);return pending.promise;};
  const {state}=await mount('components/ContentReviewPanel.vue',{workspaceId:1,document:{id:1,filename:'sample.docx'}});
  await flush();state.selectedId=1;
  const exporting=state.exportCurrent();
  assert.deepEqual(requested,[1]);
  state.selectedId=2;
  pending.resolve({data:new Blob(['docx'])});await exporting;
  assert.deepEqual(m.downloads,[]);
});

test('规则编辑保留独立标题和可恢复的不限制状态',async()=>{
  const {state,events}=await mount('components/RuleEditor.vue',{rule:null,draft:{name:'规范',title:{font:{size:28}},headings:{h1:{font:{size:18,bold:true}}}}});
  state.form.headings.h1.font.bold=null;
  assert.equal(state.isDirty,true);
  const result=state.cleaned();assert.equal(result.title.font.size,28);assert.equal(result.headings.h1.font.bold,null);
});

test('数值规则明确清空为不限制，保存时仍为 null',async()=>{
  const {state}=await mount('components/RuleEditor.vue',{rule:null,draft:{name:'间距规则',body:{paragraph:{space_after:0,space_before:12}}}});
  state.form.body.paragraph.space_after=null;
  assert.equal(state.cleaned().body.paragraph.space_after,null);
  assert.equal(state.cleaned().body.paragraph.space_before,12);
  const source=await readFile(new URL('../src/components/ScopeFields.vue',import.meta.url),'utf8');
  assert.match(source,/设为不限制/);
  assert.match(source,/:value-on-clear="null"/);
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
