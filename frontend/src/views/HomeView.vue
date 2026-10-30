<template>
  <el-container class="app-shell">
    <el-header class="topbar">
      <div class="brand"><span class="brand-mark">S</span><span>审格式 <small>SmartFormat</small></span></div>
      <div class="workspace-picker"><span class="workspace-label">当前工作区</span><el-select :model-value="ws.currentId" placeholder="选择工作区" @update:model-value="onSwitchWorkspace"><el-option v-for="w in ws.workspaces" :key="w.id" :label="w.name" :value="w.id" /></el-select><el-button text class="new-workspace" @click="onNewWorkspace">＋ 新建</el-button></div>
      <div class="topbar-spacer" />
      <div class="user-area"><span class="avatar">{{ userInitial }}</span><el-dropdown><span class="user-name">{{ auth.user?.username }} <span class="chevron">⌄</span></span><template #dropdown><el-dropdown-menu><el-dropdown-item @click="logout">退出登录</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
    </el-header>

    <el-container class="workspace-body">
      <el-aside class="left-rail" width="300px">
        <el-card shadow="never" class="side-card documents-card"><DocumentsPanel :model-value="selectedDocId" :documents="documents" :uploading="uploading" @update:model-value="onSelectDocument" @upload="onUpload" @delete="onDeleteDoc" /></el-card>
        <el-card shadow="never" class="side-card"><RulesPanel :model-value="selectedRuleId" :rules="rules" :templates="templates" :generating="generating" @update:model-value="onSelectRule" @generate="onGenerate" @add-rule="onAddRule" @delete-template="onDeleteTemplate" @delete="onDeleteRule" /></el-card>
      </el-aside>

      <el-main class="content-main">
        <section class="hero-row">
          <div><p class="eyebrow">FORMAT REVIEW WORKSPACE</p><h1>文档格式审查台</h1><p class="hero-copy">选择文档与规则，一键发现格式偏差并回到对应段落。</p></div>
          <div class="stats"><div><b>{{ documents.length }}</b><span>份文档</span></div><div><b>{{ rules.length }}</b><span>条规则</span></div><div><b :class="check?.summary.compliant ? 'success-text' : 'warning-text'">{{ check ? check.summary.total : '—' }}</b><span>当前问题</span></div></div>
        </section>
        <section class="review-bar">
          <div class="selection"><span class="selection-icon doc">D</span><div><small>当前文档</small><b>{{ selectedDoc?.filename ?? '尚未选择文档' }}</b></div></div>
          <el-button class="revision-button" :disabled="!selectedDocId || selectedFixCount === 0 || selectedDoc?.file_type === 'pdf'" :loading="generatingCopy" @click="generateRevisedCopy">生成修订后副本<span v-if="selectedFixCount">（{{ selectedFixCount }}）</span></el-button>
        </section>
        <el-card shadow="never" class="main-card">
          <el-tabs v-model="tab" class="main-tabs">
            <el-tab-pane label="工作区概览" name="dashboard"><WorkspaceDashboard :documents="documents" :rules="rules" :checks="checks" @select="onSelectHistory" @batch="batchDialogVisible = true" /></el-tab-pane>
            <el-tab-pane label="文档预览" name="preview"><PdfPreview v-if="selectedDoc?.file_type === 'pdf'" :document-id="selectedDocId" :focus-page="focusPage" :active="tab === 'preview'" /><DocPreview v-else :document-id="selectedDocId" :focus-paragraph="focusParagraph" :focus-kind="focusKind" :active="tab === 'preview'" /></el-tab-pane>
            <el-tab-pane label="文本模板审查" name="text-template">
              <section class="text-template-review">
                <header class="text-template-head">
                  <div><h3>文本模板审查</h3><p>上传标准样例、确认候选样式并保存规则，再审查提交文档。可单独选择格式或内容审查，也可同时运行。</p></div>
                  <el-upload :show-file-list="false" :auto-upload="false" :disabled="extractingTemplate || combinedRunning" accept=".docx" :on-change="onPickTextTemplate">
                    <el-button type="primary" :loading="extractingTemplate" :disabled="combinedRunning">上传文本模板</el-button>
                  </el-upload>
                </header>
                <p class="text-template-hint">大标题与一级标题独立；同类段落的多种样式会列为候选，等待你确认，不自动取舍。</p>
                <div class="text-review-selection">
                  <label>提交文档<el-select :model-value="selectedDocId" :disabled="combinedRunning" placeholder="选择待审查文档" aria-label="文本模板审查文档" @update:model-value="onSelectDocument"><el-option v-for="doc in documents" :key="doc.id" :label="doc.filename" :value="doc.id" /></el-select></label>
                  <label>格式规则<el-select :model-value="selectedRuleId" :disabled="combinedRunning" placeholder="选择已保存规则（仅内容审查无需规则）" aria-label="文本模板格式规则" @update:model-value="onSelectRule"><el-option v-for="rule in rules" :key="rule.id" :label="rule.name" :value="rule.id" /></el-select></label>
                </div>
                <div class="text-review-actions">
                  <el-checkbox-group v-model="reviewTypes" :disabled="combinedRunning" class="review-types" aria-label="文本模板审查功能选择">
                    <el-checkbox-button value="format" :disabled="selectedDoc?.file_type === 'pdf'">格式审查</el-checkbox-button>
                    <el-checkbox-button value="content">内容审查</el-checkbox-button>
                  </el-checkbox-group>
                  <el-button class="batch-button" :disabled="!wordDocuments.length || !selectedRuleId || combinedRunning" @click="batchDialogVisible = true">批量格式审查</el-button>
                  <el-button type="primary" class="run-button" :disabled="!canRunSelectedReviews" :loading="combinedRunning || running" @click="runSelectedReviews">开始文本审查 <span>→</span></el-button>
                </div>
                <p v-if="reviewTypes.includes('content')" class="text-template-hint">内容审查会将正文和表格文字发送给 DeepSeek；较长文档会自动拆成多次请求，可在下方“内容审查”中设置重点和额外的跨段复核。</p>
                <p v-if="selectedDoc?.file_type === 'pdf'" class="text-template-hint">PDF 可进行内容审查并按页定位；Word 格式审查及修订副本仅适用于 .docx。</p>
                <p v-if="reviewTypes.includes('format') && (ruleDraft || ruleEditor?.isDirty)" class="text-template-hint">模板规则尚未保存，请先在“模板规则”中确认并保存，再执行格式审查。</p>
                <p v-if="combinedRunning" class="review-progress" role="status">格式审查：{{ formatProgress }} · 内容审查：{{ contentProgress }}</p>
                <el-tabs v-model="textReviewTab" class="text-review-tabs">
                  <el-tab-pane label="模板规则" name="editor"><RuleEditor ref="ruleEditor" :rule="selectedRule" :draft="ruleDraft" :saving="savingRule" @new="onNewRule" @save="onSaveRuleset" @save-template="onSaveTemplate" @versions="versionDialogVisible = true" /></el-tab-pane>
                  <el-tab-pane name="report"><template #label>格式审查 <span v-if="check && !check.summary.compliant" class="tab-count">{{ check.summary.total }}</span></template><ViolationReport :check="check" :accepted-indexes="selectedFormatIndexes" :exporting="exportingFormatId === check?.id" @locate="onLocate" @accept="onAcceptFormatFix" @export="exportFormatReport" /></el-tab-pane>
                  <el-tab-pane label="内容审查" name="content"><ContentReviewPanel ref="contentReviewPanel" :workspace-id="ws.currentId" :document="selectedDoc" :accepted-fixes="selectedContentFixes" @locate="onContentLocate" @accept="onAcceptContentFix" @reject="onRejectContentFix" @clear-review="onClearContentReview" /></el-tab-pane>
                  <el-tab-pane label="格式历史" name="history"><CheckHistory :checks="activeChecks" :active-id="check?.id ?? null" @select="onSelectHistory" @delete="onDeleteCheck" /></el-tab-pane>
                  <el-tab-pane label="规则 JSON" name="ruleset"><pre class="json">{{ rulesetPretty }}</pre></el-tab-pane>
                </el-tabs>
              </section>
            </el-tab-pane>
            <el-tab-pane label="表单模板审查" name="template"><TemplateAuditPanel :active="tab === 'template'" :workspace-id="ws.currentId" :documents="wordDocuments" :selected-document-id="selectedDoc?.file_type === 'pdf' ? null : selectedDocId" :accepted-fixes="selectedTemplateFixes" @select-document="onSelectDocument" @accept="onAcceptTemplateFix" @reject="onRejectTemplateFix" @clear-review="onClearTemplateReview" /></el-tab-pane>
            <el-tab-pane label="文档深度审查" name="analysis"><AnalysisPanel :workspace-id="ws.currentId" :documents="documents" :rules="rules" :selected-document-id="selectedDocId" @locate="onAnalysisLocate" /></el-tab-pane>
          </el-tabs>
        </el-card>
      </el-main>
      <el-aside class="right-rail" width="250px"><el-card shadow="never" class="history-card"><CheckHistory :checks="activeChecks" :active-id="check?.id ?? null" @select="onSelectHistory" @delete="onDeleteCheck" /></el-card></el-aside>
    </el-container>
    <BatchCheckDialog v-model="batchDialogVisible" :documents="wordDocuments" :rule="selectedRule" :running="batchRunning" @run="runBatchCheck" />
    <RuleVersionsDialog v-model="versionDialogVisible" :rule="selectedRule" @restored="onRuleRestored" />
    <TemplateCandidatesDialog :extraction="templateExtraction" @cancel="templateExtraction = null" @confirm="onConfirmCandidates" />
  </el-container>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, toRaw, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus/es/components/message/index";
import { ElMessageBox } from "element-plus/es/components/message-box/index";
import DocumentsPanel from "@/components/DocumentsPanel.vue";
import RulesPanel from "@/components/RulesPanel.vue";
import DocPreview from "@/components/DocPreview.vue";
import PdfPreview from "@/components/PdfPreview.vue";
import AnalysisPanel from "@/components/AnalysisPanel.vue";
import ContentReviewPanel from "@/components/ContentReviewPanel.vue";
import TemplateAuditPanel from "@/components/TemplateAuditPanel.vue";
import ViolationReport from "@/components/ViolationReport.vue";
import RuleEditor from "@/components/RuleEditor.vue";
import CheckHistory from "@/components/CheckHistory.vue";
import BatchCheckDialog from "@/components/BatchCheckDialog.vue";
import WorkspaceDashboard from "@/components/WorkspaceDashboard.vue";
import RuleVersionsDialog from "@/components/RuleVersionsDialog.vue";
import TemplateCandidatesDialog from "@/components/TemplateCandidatesDialog.vue";
import { checkApi, documentApi, reportApi, ruleApi } from "@/api";
import { errText } from "@/api/http";
import { downloadBlob, downloadErrorText } from "@/utils/download";
import { useAuthStore } from "@/stores/auth";
import { useWorkspaceStore } from "@/stores/workspace";
import type { AnalysisSource, CheckItem, ContentRepairFix, DocumentItem, RuleItem, RuleSet, RuleTemplate, TemplateRepairFix, TemplateExtraction } from "@/types";

const router = useRouter(); const auth = useAuthStore(); const ws = useWorkspaceStore();
const documents = ref<DocumentItem[]>([]); const rules = ref<RuleItem[]>([]); const checks = ref<CheckItem[]>([]); const templates = ref<RuleTemplate[]>([]);
const selectedDocId = ref<number | null>(null); const selectedRuleId = ref<number | null>(null); const check = ref<CheckItem | null>(null);
const ruleDraft = ref<RuleSet | null>(null);
const templateExtraction = ref<TemplateExtraction | null>(null);
const ruleEditor = ref<{ isDirty: boolean } | null>(null);
let workspaceEpoch = 0;
let checkReadEpoch = 0;
watch(() => ws.currentId, () => { workspaceEpoch++; templateExtraction.value = null; }, { flush: 'sync' });
function context(documentId?: number | null, ruleId?: number | null) {
  const epoch = workspaceEpoch;
  return () => epoch === workspaceEpoch && (documentId === undefined || documentId === selectedDocId.value) && (ruleId === undefined || ruleId === selectedRuleId.value);
}
async function mayDiscard() {
  if (!ruleEditor.value?.isDirty) return true;
  try { await ElMessageBox.confirm('当前规则有未保存的修改，确认离开？', '未保存规则'); return true; } catch { return false; }
}
const focusKind = ref<"format" | "content">("format");
const focusPage = ref<number | null>(null);
type ReviewType = "format" | "content";
const reviewTypes = ref<ReviewType[]>(["format"]);
const formatProgress=ref('未选择'); const contentProgress=ref('未选择');
const contentReviewPanel = ref<{ run: () => Promise<boolean>; running: boolean } | null>(null);
const textReviewTab = ref('editor');
function openTextReview(section: string) { textReviewTab.value = section; tab.value = 'text-template'; }
const tab = ref("dashboard"); const focusParagraph = ref<number | null>(null); const uploading = ref(false); const generating = ref(false); const extractingTemplate = ref(false); const running = ref(false); const combinedRunning = ref(false); const savingRule = ref(false); const batchRunning = ref(false); const batchDialogVisible = ref(false); const versionDialogVisible = ref(false); const generatingCopy = ref(false);
const exportingFormatId = ref<number | null>(null);
const acceptedFormat = ref<Record<number, number[]>>({});
const acceptedContent = ref<Record<string, { documentId: number; fix: ContentRepairFix }>>({});
const acceptedTemplate = ref<Record<string, { documentId: number; fix: TemplateRepairFix }>>({});
const selectedDoc = computed(() => documents.value.find((d) => d.id === selectedDocId.value) ?? null);
const wordDocuments = computed(() => documents.value.filter(d => d.file_type !== 'pdf'));
const selectedRule = computed(() => rules.value.find((r) => r.id === selectedRuleId.value) ?? null);
const activeChecks = computed(() => selectedDocId.value == null ? [] : checks.value.filter(item => item.document_id === selectedDocId.value));
const selectedFormatIndexes = computed(() => check.value ? acceptedFormat.value[check.value.id] ?? [] : []);
const selectedContentFixes = computed(() => selectedDocId.value == null ? [] : Object.values(acceptedContent.value).filter(item => item.documentId === selectedDocId.value).map(item => item.fix));
const selectedTemplateFixes = computed(() => selectedDocId.value == null ? [] : Object.values(acceptedTemplate.value).filter(item => item.documentId === selectedDocId.value).map(item => item.fix));
const selectedFixCount = computed(() => selectedFormatIndexes.value.length + selectedContentFixes.value.length + selectedTemplateFixes.value.length);
const canRunSelectedReviews = computed(() => {
  if (selectedDocId.value == null || reviewTypes.value.length === 0 || running.value || extractingTemplate.value) return false;
  if (reviewTypes.value.includes('format') && (ruleEditor.value?.isDirty || selectedDoc.value?.file_type === 'pdf')) return false;
  if (reviewTypes.value.includes('content') && contentReviewPanel.value?.running) return false;
  return !reviewTypes.value.includes("format") || selectedRuleId.value != null;
});
const rulesetPretty = computed(() => selectedRule.value ? JSON.stringify(selectedRule.value.ruleset, null, 2) : "（尚未选择规则）");
const userInitial = computed(() => auth.user?.username?.trim().slice(0, 1).toUpperCase() || "U");
async function loadDocuments() { if (ws.currentId == null) return; const valid = context(); const resp = await documentApi.list(ws.currentId); if (!valid()) return; documents.value = resp.data; if (!documents.value.some((d) => d.id === selectedDocId.value)) selectedDocId.value = documents.value[0]?.id ?? null; }
async function loadRules() { if (ws.currentId == null) return; const valid = context(); const resp = await ruleApi.list(ws.currentId); if (!valid()) return; rules.value = resp.data; if (!rules.value.some((r) => r.id === selectedRuleId.value)) selectedRuleId.value = rules.value[0]?.id ?? null; }
async function loadChecks() { if (ws.currentId == null) return; const valid = context(); const request=++checkReadEpoch; const resp = await checkApi.list(ws.currentId); if (!valid() || request!==checkReadEpoch) return; checks.value = resp.data; await loadDocumentHistory(); if(valid() && request===checkReadEpoch && check.value && !checks.value.some((item) => item.id === check.value?.id)) check.value = null; }
async function loadDocumentHistory() { if(ws.currentId==null || selectedDocId.value==null)return; const request=checkReadEpoch;const valid=context(selectedDocId.value);const response=await checkApi.list(ws.currentId,selectedDocId.value);if(!valid() || request!==checkReadEpoch)return;const ids=new Set(response.data.map(item=>item.id));checks.value=[...response.data,...checks.value.filter(item=>!ids.has(item.id))];syncCurrentCheck(); }
watch(selectedDocId,()=>{void loadDocumentHistory().catch(error=>ElMessage.error(errText(error)));});
async function loadTemplates() { if (ws.currentId == null) { templates.value = []; return; } const valid = context(); const response = await ruleApi.templates(ws.currentId); if(valid()) templates.value = response.data; }
function syncCurrentCheck() { check.value = activeChecks.value[0] ?? null; }
async function loadAll() { await ws.load(); await Promise.all([loadDocuments(), loadRules(), loadChecks(), loadTemplates()]); syncCurrentCheck(); }
async function onSwitchWorkspace(id: number) { if (!(await mayDiscard())) return; ws.currentId = id; documents.value=[]; rules.value=[]; checks.value=[]; templates.value=[]; selectedDocId.value = null; selectedRuleId.value = null; ruleDraft.value = null; check.value = null; focusParagraph.value = null; acceptedFormat.value = {}; acceptedContent.value = {}; acceptedTemplate.value = {}; const valid=context(); try { await Promise.all([loadDocuments(), loadRules(), loadChecks(), loadTemplates()]); if(valid()) syncCurrentCheck(); } catch (e) { if(valid()) ElMessage.error(errText(e)); } }
async function onNewWorkspace() { if(!(await mayDiscard()))return; const valid=context(); try { const { value } = await ElMessageBox.prompt("请输入工作区名称", "新建工作区", { confirmButtonText: "创建", cancelButtonText: "取消", inputPattern: /\S+/, inputErrorMessage: "工作区名称不能为空" }); if(!valid())return; await ws.create(value.trim()); documents.value = []; rules.value = []; checks.value = []; templates.value = []; selectedDocId.value=null; selectedRuleId.value=null; ruleDraft.value = null; check.value = null; acceptedFormat.value = {}; acceptedContent.value = {}; acceptedTemplate.value = {}; await Promise.all([loadDocuments(), loadRules(), loadChecks(), loadTemplates()]); syncCurrentCheck(); } catch(e) { if(e!=='cancel' && e!=='close') ElMessage.error(errText(e)); } }
function onSelectDocument(id: number | null) { selectedDocId.value = id; focusParagraph.value = null; focusPage.value=null; if(documents.value.find(doc=>doc.id===id)?.file_type==='pdf')reviewTypes.value=['content']; syncCurrentCheck(); }
async function onUpload(file: File) { if (ws.currentId == null) return; const valid=context(); uploading.value = true; try { const resp = await documentApi.upload(ws.currentId, file); if(!valid()) return; await loadDocuments(); if(!valid())return; onSelectDocument(resp.data.id); tab.value = "preview"; ElMessage.success("文档已上传并完成解析"); } catch (e) { if(valid()) ElMessage.error(errText(e)); } finally { uploading.value = false; } }
async function onDeleteDoc(doc: DocumentItem) { const valid=context(); try { await ElMessageBox.confirm(`删除文档「${doc.filename}」及其全部格式、内容和表单审查历史？此操作无法恢复。`, "删除文档", { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }); } catch { return; } if(!valid())return; try { await documentApi.remove(doc.id); if(!valid())return; for(const item of checks.value.filter(c=>c.document_id===doc.id)) delete acceptedFormat.value[item.id]; acceptedContent.value=Object.fromEntries(Object.entries(acceptedContent.value).filter(([,item])=>item.documentId!==doc.id)); acceptedTemplate.value=Object.fromEntries(Object.entries(acceptedTemplate.value).filter(([,item])=>item.documentId!==doc.id)); await Promise.all([loadDocuments(),loadChecks()]); if(!valid())return; syncCurrentCheck(); ElMessage.success("文档及全部审查历史已删除"); } catch (e) { if(valid())ElMessage.error(errText(e)); } }
async function onGenerate(text: string) { if (ws.currentId == null || !(await mayDiscard())) return; const valid=context(); generating.value = true; try { const resp = await ruleApi.generate(ws.currentId, text); if(!valid())return; await loadRules(); if(!valid())return; ruleDraft.value = null; selectedRuleId.value = resp.data.id; openTextReview('editor'); ElMessage.success("AI 已提取规则，可在编辑器中微调"); } catch (e) { if(valid())ElMessage.error(errText(e)); } finally { generating.value = false; } }
async function onExtractTemplate(file: File) {
  if (ws.currentId == null || extractingTemplate.value) return;
  if (!(await mayDiscard())) return;
  const valid=context();
  extractingTemplate.value = true;
  openTextReview('editor');
  try {
    const response = await ruleApi.extractCandidates(ws.currentId, file);
    if(!valid())return;
    templateExtraction.value = response.data;
  } catch (e) {
    if(valid()) ElMessage.error(errText(e));
  } finally {
    extractingTemplate.value = false;
  }
}
function onPickTextTemplate(uploadFile: { raw?: File }) { if(uploadFile.raw) void onExtractTemplate(uploadFile.raw); }
async function onSelectRule(id: number) { if (!(await mayDiscard())) return; ruleDraft.value = null; selectedRuleId.value = id; openTextReview('editor'); }
function onConfirmCandidates(ruleset: RuleSet) { ruleDraft.value=ruleset; selectedRuleId.value=null; templateExtraction.value=null; openTextReview('editor'); }
async function onAddRule(template: RuleTemplate | null) {
  if (!(await mayDiscard())) return;
  selectedRuleId.value = null;
  versionDialogVisible.value = false;
  ruleDraft.value = structuredClone(toRaw(template?.ruleset ?? { name: "自定义格式规则" }));
  openTextReview('editor');
}
async function onSaveTemplate(ruleset: RuleSet) { if (ws.currentId == null || !selectedRule.value) return; const workspaceId=ws.currentId;const valid=context(undefined,selectedRuleId.value);const description=ruleset.description ?? `来自规则「${selectedRule.value.name}」`;try { const { value } = await ElMessageBox.prompt("为此模板命名", "保存为自定义模板", { confirmButtonText: "保存", cancelButtonText: "取消", inputPattern: /\S+/, inputErrorMessage: "模板名称不能为空" }); if(!valid())return;await ruleApi.createTemplate(workspaceId, value.trim(), description, ruleset); if(!valid())return;await loadTemplates(); ElMessage.success("自定义模板已保存到当前工作区"); } catch (e) { if (valid() && e !== "cancel" && e !== "close") ElMessage.error(errText(e)); } }
async function onDeleteTemplate(template: RuleTemplate) { if (template.source !== "workspace") return; const templateId = Number(template.id.replace(/^workspace:/, "")); if (!Number.isInteger(templateId)) return; try { await ElMessageBox.confirm(`确认删除自定义模板「${template.name}」？`, "删除模板", { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }); } catch { return; } try { await ruleApi.removeTemplate(templateId); await loadTemplates(); ElMessage.success("自定义模板已删除"); } catch (e) { ElMessage.error(errText(e)); } }
async function onDeleteRule(rule: RuleItem) { try { await ElMessageBox.confirm(`确认删除规则「${rule.name}」？`, "删除规则", { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }); } catch { return; } try { await ruleApi.remove(rule.id); await loadRules(); await loadChecks(); syncCurrentCheck(); ElMessage.success("规则已删除"); } catch (e) { ElMessage.error(errText(e)); } }
function onNewRule() { onAddRule(null); }
async function onSaveRuleset(ruleset: RuleSet) { if (ws.currentId == null || savingRule.value) return; const valid=context(undefined,selectedRuleId.value); const ruleId=selectedRuleId.value; savingRule.value = true; try { const resp=ruleId==null?await ruleApi.createManual(ws.currentId,ruleset):await ruleApi.updateRuleset(ruleId,ruleset); if(!valid())return; const index=rules.value.findIndex(item=>item.id===resp.data.id); if(index<0)rules.value.unshift(resp.data);else rules.value[index]=resp.data; ruleDraft.value=null;selectedRuleId.value=resp.data.id;ElMessage.success('规则已保存'); } catch (e) { if(valid())ElMessage.error(errText(e)); } finally { savingRule.value = false; } }
async function runFormatCheck(): Promise<boolean> {
  if (ws.currentId == null || !selectedDocId.value || !selectedRuleId.value || running.value) return false;
  const valid=context(selectedDocId.value, selectedRuleId.value);
  ++checkReadEpoch;
  running.value = true; check.value = null; focusParagraph.value = null;
  try {
    const resp = await checkApi.run(ws.currentId, selectedDocId.value, selectedRuleId.value);
    if(!valid())return false;
    check.value = resp.data;
    checks.value = [resp.data, ...checks.value.filter((item) => item.id !== resp.data.id)];
    return true;
  } catch (e) {
    ElMessage.error(errText(e));
    return false;
  } finally {
    running.value = false;
  }
}
async function runSelectedReviews() {
  if (!canRunSelectedReviews.value || combinedRunning.value) return;
  const valid=context(selectedDocId.value);
  const withFormat = reviewTypes.value.includes("format");
  const withContent = reviewTypes.value.includes("content");
  combinedRunning.value = true;
  formatProgress.value=withFormat?'进行中':'未选择';contentProgress.value=withContent?'进行中':'未选择';
  openTextReview(withFormat?'report':'content');
  try {
    const [formatOk, contentOk] = await Promise.all([
      withFormat ? runFormatCheck().then(ok=>{if(valid())formatProgress.value=ok?'已完成':'未完成';return ok;}) : Promise.resolve(false),
      withContent ? (contentReviewPanel.value?.run() ?? Promise.resolve(false)).then(ok=>{if(valid())contentProgress.value=ok?'已完成':'未完成';return ok;}) : Promise.resolve(false),
    ]);
    if(!valid())return;
    if (withFormat && formatOk) openTextReview('report');
    else if (withContent) openTextReview('content');

    if ((!withFormat || formatOk) && (!withContent || contentOk)) {
      const formatText = withFormat && check.value
        ? (check.value.summary.compliant ? "格式合规" : `格式发现 ${check.value.summary.total} 项问题`)
        : "";
      const contentText = withContent ? "内容审查已完成" : "";
      ElMessage.success([formatText, contentText].filter(Boolean).join("；"));
    } else if (withFormat && withContent && (formatOk || contentOk)) {
      ElMessage.warning("部分审查已完成，另一项失败，请查看对应页签的提示");
    }
  } finally {
    combinedRunning.value = false;
  }
}
async function runBatchCheck(documentIds: number[]) { if (ws.currentId == null || !selectedRuleId.value || !documentIds.length) return; const valid=context(undefined,selectedRuleId.value); batchRunning.value = true; try { const resp = await checkApi.runBatch(ws.currentId, documentIds, selectedRuleId.value); if(!valid())return; const newIds = new Set(resp.data.checks.map((item) => item.id)); checks.value = [...resp.data.checks, ...checks.value.filter((item) => !newIds.has(item.id))]; syncCurrentCheck(); batchDialogVisible.value = false; tab.value = "dashboard"; ElMessage.success(`批量审查完成：${resp.data.compliant_documents}/${resp.data.total_documents} 份通过，共发现 ${resp.data.violation_total} 项问题`); } catch (e) { if(valid())ElMessage.error(errText(e)); } finally { batchRunning.value = false; } }
async function onSelectHistory(item: CheckItem) { if(!(await mayDiscard()))return;ruleDraft.value=null;check.value = item; selectedDocId.value = item.document_id; selectedRuleId.value = item.rule_id; focusParagraph.value = null; openTextReview('report'); }
function onAcceptFormatFix(violationIndex: number, accepted: boolean) { if (!check.value) return; const selected = new Set(acceptedFormat.value[check.value.id] ?? []); if (accepted) selected.add(violationIndex); else selected.delete(violationIndex); acceptedFormat.value = { ...acceptedFormat.value, [check.value.id]: [...selected].sort((a, b) => a - b) }; }
function contentKey(documentId: number, fix: ContentRepairFix) { return `${documentId}:${fix.review_id}:${fix.issue_index}`; }
function onAcceptContentFix(fix: ContentRepairFix) { if (selectedDocId.value == null) return; acceptedContent.value = { ...acceptedContent.value, [contentKey(selectedDocId.value, fix)]: { documentId: selectedDocId.value, fix } }; }
function onRejectContentFix(reviewId: number, issueIndex: number) { if (selectedDocId.value == null) return; const next = { ...acceptedContent.value }; delete next[`${selectedDocId.value}:${reviewId}:${issueIndex}`]; acceptedContent.value = next; }
function onClearContentReview(reviewId: number) { const next = { ...acceptedContent.value }; for (const [key, item] of Object.entries(next)) if (item.fix.review_id === reviewId) delete next[key]; acceptedContent.value = next; }
function templateKey(documentId: number, fix: TemplateRepairFix) { return `${documentId}:${fix.review_id}:${fix.issue_index}`; }
function onAcceptTemplateFix(fix: TemplateRepairFix) { if (selectedDocId.value == null) return; acceptedTemplate.value = { ...acceptedTemplate.value, [templateKey(selectedDocId.value, fix)]: { documentId: selectedDocId.value, fix } }; }
function onRejectTemplateFix(reviewId: number, issueIndex: number) { if (selectedDocId.value == null) return; const next = { ...acceptedTemplate.value }; delete next[`${selectedDocId.value}:${reviewId}:${issueIndex}`]; acceptedTemplate.value = next; }
function onClearTemplateReview(reviewId: number) { const next = { ...acceptedTemplate.value }; for (const [key, item] of Object.entries(next)) if (item.fix.review_id === reviewId) delete next[key]; acceptedTemplate.value = next; }
async function generateRevisedCopy() { if (ws.currentId == null || selectedDocId.value == null || selectedFixCount.value === 0) return; const valid=context(selectedDocId.value);const filename=`${(selectedDoc.value?.filename ?? "文档.docx").replace(/\.docx$/i, "")}_修订后副本.docx`;generatingCopy.value = true; try { const response = await documentApi.revisedCopy(selectedDocId.value, { workspace_id: ws.currentId, check_id: selectedFormatIndexes.value.length ? check.value?.id : null, format_violation_indexes: selectedFormatIndexes.value, content_fixes: selectedContentFixes.value, template_fixes: selectedTemplateFixes.value }); if(!valid())return;const blob = response.data as Blob; if (!blob.size) throw new Error("生成的副本为空"); downloadBlob(blob, filename); ElMessage.success("已生成修订后副本，原始文件未修改"); } catch (e) { if(valid())ElMessage.error(await copyErrorText(e)); } finally { generatingCopy.value = false; } }
async function exportFormatReport() {
  const current = check.value;
  if (!current || exportingFormatId.value != null) return;
  const valid = context(current.document_id);
  exportingFormatId.value = current.id;
  try {
    const response = await reportApi.format(current.id);
    if (!valid() || check.value?.id !== current.id) return;
    const source = documents.value.find(doc => doc.id === current.document_id);
    downloadBlob(response.data, `${(source?.filename ?? "文档.docx").replace(/\.docx$/i, "")}_格式审查报告.docx`);
  } catch (error) { if (valid()) ElMessage.error(await downloadErrorText(error)); }
  finally { exportingFormatId.value = null; }
}
async function copyErrorText(error: unknown): Promise<string> { return downloadErrorText(error); }
async function onDeleteCheck(item: CheckItem) { try { await ElMessageBox.confirm("删除后无法恢复，确认删除这条格式审查记录？", "删除审查记录", { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }); } catch { return; } try { await checkApi.remove(item.id); checks.value = checks.value.filter(checkItem => checkItem.id !== item.id); const next = { ...acceptedFormat.value }; delete next[item.id]; acceptedFormat.value = next; if (check.value?.id === item.id) syncCurrentCheck(); ElMessage.success("格式审查记录已删除"); } catch (e) { ElMessage.error(errText(e)); } }
function onRuleRestored(rule: RuleItem) { const index = rules.value.findIndex((item) => item.id === rule.id); if (index >= 0) rules.value[index] = rule; ruleDraft.value = null; selectedRuleId.value = rule.id; openTextReview('editor'); }
async function onLocate(index: number) {
  // 即使连续点击同一条问题，也要重新触发子组件的定位监听。
  focusParagraph.value = null;
  focusKind.value = "format";
  if (check.value) selectedDocId.value = check.value.document_id;
  tab.value = "preview";
  await nextTick();
  focusParagraph.value = index;
}
async function onContentLocate(documentId: number, index: number) {
  focusParagraph.value = null;
  focusKind.value = "content";
  selectedDocId.value = documentId;
  const document = documents.value.find(item=>item.id===documentId);
  if (document?.file_type === 'pdf') {
    focusPage.value = null;
    tab.value = 'preview';
    await nextTick();
    focusPage.value = document.pdf_page_map?.[index] ?? 1;
    return;
  }
  tab.value = "preview";
  await nextTick();
  focusParagraph.value = index;
}
async function onAnalysisLocate(source: AnalysisSource, kind: "format" | "content") {
  const document = documents.value.find(item=>item.id===source.document_id);
  if (!document) return;
  if (document?.file_type === 'pdf') {
    selectedDocId.value = source.document_id;
    focusPage.value = null;
    tab.value = 'preview';
    await nextTick();
    focusPage.value = source.page_number ?? document.pdf_page_map?.[source.paragraph_index ?? 0] ?? 1;
    return;
  }
  focusParagraph.value = null;
  focusKind.value = kind;
  selectedDocId.value = source.document_id;
  tab.value = 'preview';
  await nextTick();
  focusParagraph.value = source.paragraph_index;
}
function logout() { auth.logout(); ws.reset(); router.push("/login"); }
onMounted(async () => { try { await loadAll(); } catch (e) { ElMessage.error(errText(e)); } });
</script>

<style scoped>
.text-template-head{display:flex;align-items:center;justify-content:space-between;gap:16px}.text-template-head h3{margin:0;color:#22324f}.text-template-head p,.text-template-hint{color:#8995a8;font-size:12px;line-height:1.6}.text-template-head p{margin:6px 0}.text-template-hint{margin:10px 0}.text-review-selection{display:flex;flex-wrap:wrap;gap:14px;margin:18px 0}.text-review-selection label{display:grid;flex:1;min-width:200px;gap:7px;color:#657590;font-size:12px}.text-review-selection .el-select{width:100%}.text-review-actions{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin:12px 0}.text-review-actions .review-types{margin-left:0}.text-review-tabs{margin-top:20px}.review-progress{color:#526ed9;font-size:12px}.review-bar .revision-button{margin-left:auto}@media(max-width:700px){.text-template-head{align-items:flex-start;flex-direction:column}.text-review-actions{align-items:stretch;flex-direction:column}.text-review-actions .el-button{margin-left:0}.review-bar .revision-button{margin-left:0}}
.app-shell{min-width:0;height:100vh;color:#273653;background:#f5f7fb}.topbar{z-index:2;display:flex;align-items:center;height:66px;padding:0 26px;border-bottom:1px solid #e7ebf3;background:rgba(255,255,255,.95);box-shadow:0 2px 12px rgba(33,48,80,.03)}.brand{display:flex;align-items:center;gap:10px;color:#172442;font-size:17px;font-weight:800;letter-spacing:.02em;white-space:nowrap}.brand small{display:block;margin-top:-1px;color:#8c9ab2;font-size:9px;font-weight:700;letter-spacing:.1em}.brand-mark{display:grid;place-items:center;width:31px;height:31px;color:#fff;border-radius:9px;background:linear-gradient(135deg,#5b77f4,#314fd4);box-shadow:0 5px 12px rgba(59,82,205,.3);font-family:Georgia,serif;font-size:19px}.workspace-picker{display:flex;align-items:center;gap:8px;margin-left:52px}.workspace-picker :deep(.el-select){width:178px}.workspace-picker :deep(.el-input__wrapper){background:#f6f8fc;box-shadow:0 0 0 1px #edf0f5 inset}.workspace-label{color:#8c99ad;font-size:12px}.new-workspace{font-size:12px}.topbar-spacer{flex:1}.user-area{display:flex;align-items:center;gap:8px}.avatar{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;color:#526ed9;background:#e9eeff;font-size:12px;font-weight:800}.user-name{color:#53617a;font-size:13px;cursor:pointer}.chevron{margin-left:3px;color:#96a1b3}.workspace-body{min-height:0}.left-rail,.right-rail{overflow-y:auto;padding:18px 14px;background:#fbfcfe}.left-rail{border-right:1px solid #e8ecf3}.right-rail{border-left:1px solid #e8ecf3}.side-card,.history-card,.main-card{border:1px solid #e7ebf3;border-radius:12px}.side-card{margin-bottom:13px}.side-card :deep(.el-card__body){padding:15px}.content-main{overflow-y:auto;padding:24px}.hero-row{display:flex;align-items:center;justify-content:space-between;gap:20px;max-width:1260px;margin:0 auto 20px}.eyebrow{margin:0 0 5px;color:#6d80a6;font-size:10px;font-weight:800;letter-spacing:.13em}h1{margin:0;color:#172541;font-size:25px;letter-spacing:-.03em}.hero-copy{margin:7px 0 0;color:#8995a8;font-size:13px}.stats{display:flex;overflow:hidden;border:1px solid #e6ebf4;border-radius:10px;background:#fff}.stats div{display:grid;min-width:75px;padding:9px 14px;border-right:1px solid #edf0f5;text-align:center}.stats div:last-child{border:0}.stats b{color:#344767;font-size:17px}.stats span{margin-top:2px;color:#98a3b5;font-size:10px}.success-text{color:#169167!important}.warning-text{color:#dc6645!important}.review-bar{display:flex;align-items:center;gap:12px;max-width:1260px;padding:13px 16px;margin:0 auto 17px;border:1px solid #e5eaf4;border-radius:12px;background:#fff;box-shadow:0 5px 20px rgba(39,58,94,.035)}.selection{display:flex;align-items:center;min-width:0;gap:9px}.selection-icon{display:grid;place-items:center;width:31px;height:31px;flex:0 0 auto;border-radius:8px;font-size:11px;font-weight:800}.selection-icon.doc{color:#4e69ca;background:#e9efff}.selection-icon.rule{color:#9a63cc;background:#f3eaff}.selection div{display:grid;min-width:0;gap:2px}.selection small{color:#9aa5b7;font-size:10px}.selection b{display:block;max-width:190px;overflow:hidden;color:#384762;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.flow-line{color:#b0bbcf}.review-types{display:flex;margin-left:auto;white-space:nowrap}.review-types :deep(.el-checkbox-button__inner){padding:8px 9px;font-size:11px}.batch-button{margin-left:0}.run-button{margin-left:0;padding-right:16px;padding-left:16px;border:0;background:linear-gradient(135deg,#5f7bf5,#4160dc);box-shadow:0 5px 12px rgba(65,96,220,.22)}.run-button span{margin-left:6px}.main-card{max-width:1260px;min-height:575px;margin:0 auto 22px}.main-card :deep(.el-card__body){padding:0 20px 20px}.main-tabs :deep(.el-tabs__header){margin-bottom:20px}.main-tabs :deep(.el-tabs__nav-wrap::after){height:1px;background:#edf0f5}.main-tabs :deep(.el-tabs__item){height:55px;padding:0 18px;color:#77849b;font-size:13px}.main-tabs :deep(.el-tabs__item.is-active){color:#4766dc;font-weight:700}.tab-count{display:inline-grid;place-items:center;min-width:16px;height:16px;margin-left:3px;border-radius:8px;color:#fff;background:#ec7857;font-size:10px;line-height:1}.json{max-height:500px;padding:18px;overflow:auto;border:1px solid #e8edf5;border-radius:10px;color:#3e4c68;background:#f7f9fc;font-size:12px;line-height:1.6}.history-card{min-height:250px}.history-card :deep(.el-card__body){padding:15px 11px}@media(max-width:1180px){.right-rail{display:none}.review-bar{flex-wrap:wrap}.review-types{margin-left:0}}@media(max-width:900px){.left-rail{width:248px!important}.content-main{padding:18px}.workspace-picker{margin-left:22px}.workspace-label{display:none}}@media(max-width:700px){.topbar{height:58px;padding:0 14px}.brand small,.workspace-picker,.user-name{display:none}.user-area{margin-left:auto}.left-rail{display:none}.content-main{padding:15px}.hero-row{display:block}.stats{width:max-content;margin-top:14px}.review-bar{align-items:stretch;flex-direction:column;gap:9px}.flow-line{display:none}.selection b{max-width:none}.review-types{width:100%}.review-types :deep(.el-checkbox-button){flex:1}.review-types :deep(.el-checkbox-button__inner){width:100%}.batch-button,.revision-button,.run-button{width:100%;margin-top:4px}.main-card :deep(.el-card__body){padding:0 12px 14px}.main-tabs :deep(.el-tabs__item){padding:0 10px;font-size:12px}}
@media(max-width:700px){.app-shell{height:auto;min-height:100vh}.workspace-body{flex-direction:column}.left-rail{display:grid;width:100%!important;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px;overflow:visible;box-sizing:border-box}.workspace-picker{display:flex;margin-left:0;flex-wrap:wrap}.topbar{height:auto;min-height:58px;gap:12px;flex-wrap:wrap;padding:12px}.workspace-picker :deep(.el-select){width:140px}.content-main{overflow:visible}}
</style>
