<template>
  <section class="analysis-panel">
    <header><h3>文档深度审查</h3><p>对比修订稿、检查章节和图表引用，或核对多份材料中的同一字段。点击原文可回到文档预览。</p></header>
    <el-tabs v-model="mode">
      <el-tab-pane label="版本对比与复审" name="versions">
        <div class="controls">
          <label>原稿<el-select v-model="originalId" placeholder="选择原稿"><el-option v-for="doc in wordDocuments" :key="doc.id" :value="doc.id" :label="doc.filename" /></el-select></label>
          <label>修改稿<el-select v-model="revisedId" placeholder="选择修改稿"><el-option v-for="doc in wordDocuments" :key="doc.id" :value="doc.id" :label="doc.filename" /></el-select></label>
          <label>同一格式规则<el-select v-model="ruleId" placeholder="选择规则"><el-option v-for="rule in rules" :key="rule.id" :value="rule.id" :label="rule.name" /></el-select></label>
        </div>
        <el-button type="primary" :disabled="!originalId || !revisedId || originalId===revisedId || !ruleId || busy" :loading="busy==='versions'" @click="runVersions">对比并复审</el-button>
        <p class="hint">两份文件使用同一套当前规则。段落移动或无法可靠对应时列为“待确认”。</p>
        <div v-if="versionResult" class="result"><h4>原稿 {{ versionResult.original_issue_count }} 项格式问题 · 修改稿 {{ versionResult.revised_issue_count }} 项</h4><FindingList :items="versionResult.findings" :documents="documents" @locate="(source) => locate(source, 'format')" /></div>
      </el-tab-pane>
      <el-tab-pane label="章节与图表完整性" name="structure">
        <div class="controls"><label>待审 Word 文档<el-select v-model="structureId" placeholder="选择文档"><el-option v-for="doc in wordDocuments" :key="doc.id" :value="doc.id" :label="doc.filename" /></el-select></label></div>
        <label class="full-label">必需章节（每行一项，按期望顺序）<el-input v-model="requiredText" type="textarea" :rows="4" placeholder="摘要&#10;研究方法&#10;结论&#10;参考文献" /></label>
        <el-checkbox v-model="requireOrder">检查章节顺序</el-checkbox>
        <div class="action"><el-button type="primary" :disabled="!structureId || busy" :loading="busy==='structure'" @click="runStructure">检查完整性</el-button></div>
        <p class="hint">图表题注、重复编号和正文引用一并检查；章节名称按标题原文匹配。</p>
        <div v-if="structureResult" class="result"><h4>识别到 {{ structureResult.headings_found.length }} 个标题</h4><FindingList :items="structureResult.findings" :documents="documents" @locate="(source) => locate(source, 'format')" /></div>
      </el-tab-pane>
      <el-tab-pane label="跨文档数据核对" name="cross">
        <div class="controls"><label>核对材料（2–10 份）<el-select v-model="crossIds" multiple collapse-tags placeholder="选择材料"><el-option v-for="doc in documents" :key="doc.id" :value="doc.id" :label="doc.filename" /></el-select></label>
          <label>基准文档<el-select v-model="baselineId" placeholder="选择基准"><el-option v-for="doc in selectedCrossDocs" :key="doc.id" :value="doc.id" :label="doc.filename" /></el-select></label></div>
        <div class="field-list"><div class="field-row" v-for="(field,index) in fieldRows" :key="field.key">
          <el-input v-model="field.name" maxlength="40" placeholder="字段名，如预算金额" aria-label="核对字段名" />
          <el-select v-model="field.value_type" aria-label="字段类型"><el-option label="文字" value="text" /><el-option label="金额／数值" value="number" /><el-option label="日期" value="date" /></el-select>
          <el-input v-model="field.aliasesText" placeholder="其他标签，逗号分隔" aria-label="字段别名" />
          <el-button link type="danger" :disabled="fieldRows.length===1" @click="fieldRows.splice(index,1)">移除</el-button>
        </div></div>
        <el-button :disabled="fieldRows.length>=20" @click="addField">＋ 添加字段</el-button>
        <el-button type="primary" :disabled="crossIds.length<2 || !baselineId || !crossIds.includes(baselineId) || !validFields || busy" :loading="busy==='cross'" @click="runCross">核对字段</el-button>
        <p class="hint">识别“字段名：值”及你填写的别名。缺失、多处候选和无法规范化的值会标为待确认；不会自动选一个值。</p>
        <div v-if="crossResult" class="result"><article v-for="field in crossResult.fields" :key="field.name" class="field-result"><h4>{{ field.name }} <small>基准：{{ field.baseline_value ?? '未确定' }}</small></h4>
          <div v-for="item in field.values" :key="item.document_id" class="field-value"><b>{{ nameOf(item.document_id) }}</b><span :class="'status-'+item.status">{{ statusLabel(item.status) }}</span><span>{{ item.value ?? '—' }}</span>
            <button v-if="item.source" type="button" class="source" @click="locate(item.source,'content')">{{ item.source.quote }} ↗</button>
            <button v-for="(candidate,index) in item.candidates" :key="index" type="button" class="source" @click="locate(candidate,'content')">候选 {{ index+1 }}：{{ candidate.quote }} ↗</button>
          </div></article></div>
      </el-tab-pane>
    </el-tabs>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { analysisApi } from "@/api";
import { errText } from "@/api/http";
import FindingList from "./FindingList.vue";
import type { AnalysisSource, CrossDocumentResult, CrossFieldSpec, DocumentItem, RuleItem, StructureCheckResult, VersionCompareResult } from "@/types";

const props = defineProps<{ workspaceId: number | null; documents: DocumentItem[]; rules: RuleItem[]; selectedDocumentId: number | null }>();
const emit = defineEmits<{ (e:"locate", source:AnalysisSource, kind:"format"|"content"):void }>();
const mode=ref("versions");const busy=ref<"versions"|"structure"|"cross"|null>(null);const error=ref("");
const originalId=ref<number|null>(null);const revisedId=ref<number|null>(null);const ruleId=ref<number|null>(null);
const structureId=ref<number|null>(null);const requiredText=ref("摘要\n结论\n参考文献");const requireOrder=ref(true);
const crossIds=ref<number[]>([]);const baselineId=ref<number|null>(null);let nextKey=0;
type FieldRow=CrossFieldSpec & { key:number; aliasesText:string };
const fieldRows=ref<FieldRow[]>([{key:nextKey++,name:"预算金额",value_type:"number",aliases:[],aliasesText:"总预算"}]);
const versionResult=ref<VersionCompareResult|null>(null);const structureResult=ref<StructureCheckResult|null>(null);const crossResult=ref<CrossDocumentResult|null>(null);
const wordDocuments=computed(()=>props.documents.filter(doc=>doc.file_type!=="pdf"));
const selectedCrossDocs=computed(()=>props.documents.filter(doc=>crossIds.value.includes(doc.id)));
const validFields=computed(()=>fieldRows.value.length>0 && fieldRows.value.every(field=>field.name.trim()) && new Set(fieldRows.value.map(field=>field.name.trim().toLowerCase())).size===fieldRows.value.length);
let generation=0;
watch(()=>props.workspaceId,()=>{generation++;originalId.value=null;revisedId.value=null;ruleId.value=null;structureId.value=null;crossIds.value=[];baselineId.value=null;versionResult.value=null;structureResult.value=null;crossResult.value=null;error.value="";busy.value=null;});
watch(()=>props.documents.map(doc=>doc.id).join(","),()=>{const present=new Set(props.documents.map(doc=>doc.id));if(originalId.value&&!present.has(originalId.value))originalId.value=null;if(revisedId.value&&!present.has(revisedId.value))revisedId.value=null;if(structureId.value&&!present.has(structureId.value))structureId.value=null;crossIds.value=crossIds.value.filter(id=>present.has(id));if(versionResult.value&&(!present.has(versionResult.value.original_id)||!present.has(versionResult.value.revised_id)))versionResult.value=null;if(structureResult.value&&!present.has(structureResult.value.document_id))structureResult.value=null;if(crossResult.value&&crossResult.value.fields.some(field=>field.values.some(value=>!present.has(value.document_id))))crossResult.value=null;});
watch(()=>props.selectedDocumentId,(id)=>{if(id && props.documents.find(doc=>doc.id===id)?.file_type!=="pdf")structureId.value=id;});
watch(crossIds, ids=>{if(baselineId.value && !ids.includes(baselineId.value))baselineId.value=null;});
function addField(){fieldRows.value.push({key:nextKey++,name:"",value_type:"text",aliases:[],aliasesText:""});}
function nameOf(id:number){return props.documents.find(doc=>doc.id===id)?.filename??`文档 ${id}`;}
function statusLabel(status:string){return ({match:"一致",different:"不一致",missing:"未找到",ambiguous:"待确认",baseline:"基准",resolved:"已解决",remaining:"仍存在",new:"新增",uncertain:"待确认",changed:"已变化",replace:"已修改",insert:"新增",delete:"删除",duplicate:"重复",gap:"缺号",out_of_order:"顺序不符"} as Record<string,string>)[status]??status;}
function locate(source:AnalysisSource,kind:"format"|"content"){emit("locate",source,kind);}
async function runVersions(){if(props.workspaceId==null||!originalId.value||!revisedId.value||!ruleId.value||busy.value)return;const request=generation;busy.value="versions";error.value="";versionResult.value=null;try{const response=await analysisApi.compareVersions(props.workspaceId,originalId.value,revisedId.value,ruleId.value);if(request===generation)versionResult.value=response.data;}catch(e){if(request===generation)error.value=errText(e);}finally{if(request===generation)busy.value=null;}}
async function runStructure(){if(props.workspaceId==null||!structureId.value||busy.value)return;const request=generation;busy.value="structure";error.value="";structureResult.value=null;try{const required=requiredText.value.split(/[\r\n]+/).map(text=>text.trim()).filter(Boolean);const response=await analysisApi.checkStructure(props.workspaceId,structureId.value,required,requireOrder.value);if(request===generation)structureResult.value=response.data;}catch(e){if(request===generation)error.value=errText(e);}finally{if(request===generation)busy.value=null;}}
async function runCross(){if(props.workspaceId==null||!baselineId.value||crossIds.value.length<2||!validFields.value||busy.value)return;const request=generation;busy.value="cross";error.value="";crossResult.value=null;try{const fields=fieldRows.value.map(field=>({name:field.name.trim(),value_type:field.value_type,aliases:field.aliasesText.split(/[,，]/).map(item=>item.trim()).filter(Boolean).slice(0,5)}));const response=await analysisApi.compareDocuments(props.workspaceId,crossIds.value,baselineId.value,fields);if(request===generation)crossResult.value=response.data;}catch(e){if(request===generation)error.value=errText(e);}finally{if(request===generation)busy.value=null;}}
</script>

<style scoped>
.analysis-panel{min-height:500px;padding:3px;color:#31415f}.analysis-panel header h3{margin:0 0 8px}.analysis-panel header p,.hint{color:#8290a8;font-size:12px;line-height:1.7}.controls{display:flex;flex-wrap:wrap;gap:12px;margin:15px 0}.controls label,.full-label{display:grid;flex:1;min-width:190px;gap:7px;font-size:12px}.controls .el-select{width:100%}.full-label{margin:14px 0}.action{margin-top:14px}.result{margin:20px 0}.result h4{font-size:14px}.field-list{display:grid;gap:9px;margin:16px 0}.field-row{display:grid;grid-template-columns:1fr 140px 1fr auto;gap:9px}.field-result{padding:12px 0;border-bottom:1px solid #e8edf5}.field-result small{margin-left:10px;color:#8290a8;font-weight:400}.field-value{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:7px 0;font-size:12px}.field-value b{min-width:110px}.source{border:0;background:#f1f5ff;color:#4565c3;cursor:pointer;text-align:left}.status-different,.status-missing{color:#d46345}.status-ambiguous{color:#b67830}.status-match,.status-baseline{color:#188564}@media(max-width:800px){.field-row{grid-template-columns:1fr 1fr}.field-row :first-child{grid-column:1/-1}}
</style>
