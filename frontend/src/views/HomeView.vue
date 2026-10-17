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
          <div class="selection"><span class="selection-icon doc">D</span><div><small>审查文档</small><b>{{ selectedDoc?.filename ?? '尚未选择文档' }}</b></div></div><span class="flow-line">→</span>
          <div class="selection"><span class="selection-icon rule">R</span><div><small>应用规则</small><b>{{ selectedRule?.name ?? '尚未选择规则' }}</b></div></div>
          <el-button class="batch-button" :disabled="!documents.length || !selectedRuleId" @click="batchDialogVisible = true">批量审查</el-button>
          <el-button class="revision-button" :disabled="!selectedDocId || selectedFixCount === 0" :loading="generatingCopy" @click="generateRevisedCopy">生成修订后副本<span v-if="selectedFixCount">（{{ selectedFixCount }}）</span></el-button>
          <el-button type="primary" class="run-button" :disabled="!selectedDocId || !selectedRuleId" :loading="running" @click="runCheck">开始审查 <span>→</span></el-button>
        </section>
        <el-card shadow="never" class="main-card">
          <el-tabs v-model="tab" class="main-tabs">
            <el-tab-pane label="工作区概览" name="dashboard"><WorkspaceDashboard :documents="documents" :rules="rules" :checks="checks" @select="onSelectHistory" @batch="batchDialogVisible = true" /></el-tab-pane>
            <el-tab-pane label="文档预览" name="preview"><DocPreview :document-id="selectedDocId" :focus-paragraph="focusParagraph" :focus-kind="focusKind" :active="tab === 'preview'" /></el-tab-pane>
            <el-tab-pane label="内容审查" name="content"><ContentReviewPanel :workspace-id="ws.currentId" :document="selectedDoc" :accepted-fixes="selectedContentFixes" @locate="onContentLocate" @accept="onAcceptContentFix" @reject="onRejectContentFix" @clear-review="onClearContentReview" /></el-tab-pane>
            <el-tab-pane label="表单模板审查" name="template"><TemplateAuditPanel :workspace-id="ws.currentId" :documents="documents" :selected-document-id="selectedDocId" :accepted-fixes="selectedTemplateFixes" @select-document="onSelectDocument" @accept="onAcceptTemplateFix" @reject="onRejectTemplateFix" @clear-review="onClearTemplateReview" /></el-tab-pane>
            <el-tab-pane name="report"><template #label>格式审查 <span v-if="check && !check.summary.compliant" class="tab-count">{{ check.summary.total }}</span></template><ViolationReport :check="check" :accepted-indexes="selectedFormatIndexes" @locate="onLocate" @accept="onAcceptFormatFix" /></el-tab-pane>
            <el-tab-pane label="编辑规则" name="editor"><RuleEditor :rule="selectedRule" :draft="ruleDraft" :saving="savingRule" @new="onNewRule" @save="onSaveRuleset" @save-template="onSaveTemplate" @versions="versionDialogVisible = true" /></el-tab-pane>
            <el-tab-pane label="规则 JSON" name="ruleset"><pre class="json">{{ rulesetPretty }}</pre></el-tab-pane>
          </el-tabs>
        </el-card>
      </el-main>
      <el-aside class="right-rail" width="250px"><el-card shadow="never" class="history-card"><CheckHistory :checks="activeChecks" :active-id="check?.id ?? null" @select="onSelectHistory" @delete="onDeleteCheck" /></el-card></el-aside>
    </el-container>
    <BatchCheckDialog v-model="batchDialogVisible" :documents="documents" :rule="selectedRule" :running="batchRunning" @run="runBatchCheck" />
    <RuleVersionsDialog v-model="versionDialogVisible" :rule="selectedRule" @restored="onRuleRestored" />
  </el-container>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import DocumentsPanel from "@/components/DocumentsPanel.vue";
import RulesPanel from "@/components/RulesPanel.vue";
import DocPreview from "@/components/DocPreview.vue";
import ContentReviewPanel from "@/components/ContentReviewPanel.vue";
import TemplateAuditPanel from "@/components/TemplateAuditPanel.vue";
import ViolationReport from "@/components/ViolationReport.vue";
import RuleEditor from "@/components/RuleEditor.vue";
import CheckHistory from "@/components/CheckHistory.vue";
import BatchCheckDialog from "@/components/BatchCheckDialog.vue";
import WorkspaceDashboard from "@/components/WorkspaceDashboard.vue";
import RuleVersionsDialog from "@/components/RuleVersionsDialog.vue";
import { checkApi, documentApi, ruleApi } from "@/api";
import { errText } from "@/api/http";
import { useAuthStore } from "@/stores/auth";
import { useWorkspaceStore } from "@/stores/workspace";
import type { CheckItem, ContentRepairFix, DocumentItem, RuleItem, RuleSet, RuleTemplate, TemplateRepairFix } from "@/types";

const router = useRouter(); const auth = useAuthStore(); const ws = useWorkspaceStore();
const documents = ref<DocumentItem[]>([]); const rules = ref<RuleItem[]>([]); const checks = ref<CheckItem[]>([]); const templates = ref<RuleTemplate[]>([]);
const selectedDocId = ref<number | null>(null); const selectedRuleId = ref<number | null>(null); const check = ref<CheckItem | null>(null);
const ruleDraft = ref<RuleSet | null>(null);
const focusKind = ref<"format" | "content">("format");
const tab = ref("dashboard"); const focusParagraph = ref<number | null>(null); const uploading = ref(false); const generating = ref(false); const running = ref(false); const savingRule = ref(false); const batchRunning = ref(false); const batchDialogVisible = ref(false); const versionDialogVisible = ref(false); const generatingCopy = ref(false);
const acceptedFormat = ref<Record<number, number[]>>({});
const acceptedContent = ref<Record<string, { documentId: number; fix: ContentRepairFix }>>({});
const acceptedTemplate = ref<Record<string, { documentId: number; fix: TemplateRepairFix }>>({});
const selectedDoc = computed(() => documents.value.find((d) => d.id === selectedDocId.value) ?? null);
const selectedRule = computed(() => rules.value.find((r) => r.id === selectedRuleId.value) ?? null);
const activeChecks = computed(() => selectedDocId.value == null ? [] : checks.value.filter(item => item.document_id === selectedDocId.value));
const selectedFormatIndexes = computed(() => check.value ? acceptedFormat.value[check.value.id] ?? [] : []);
const selectedContentFixes = computed(() => selectedDocId.value == null ? [] : Object.values(acceptedContent.value).filter(item => item.documentId === selectedDocId.value).map(item => item.fix));
const selectedTemplateFixes = computed(() => selectedDocId.value == null ? [] : Object.values(acceptedTemplate.value).filter(item => item.documentId === selectedDocId.value).map(item => item.fix));
const selectedFixCount = computed(() => selectedFormatIndexes.value.length + selectedContentFixes.value.length + selectedTemplateFixes.value.length);
const rulesetPretty = computed(() => selectedRule.value ? JSON.stringify(selectedRule.value.ruleset, null, 2) : "（尚未选择规则）");
const userInitial = computed(() => auth.user?.username?.trim().slice(0, 1).toUpperCase() || "U");
async function loadDocuments() { if (ws.currentId == null) return; const resp = await documentApi.list(ws.currentId); documents.value = resp.data; if (!documents.value.some((d) => d.id === selectedDocId.value)) selectedDocId.value = documents.value[0]?.id ?? null; }
async function loadRules() { if (ws.currentId == null) return; const resp = await ruleApi.list(ws.currentId); rules.value = resp.data; if (!rules.value.some((r) => r.id === selectedRuleId.value)) selectedRuleId.value = rules.value[0]?.id ?? null; }
async function loadChecks() { if (ws.currentId == null) return; const resp = await checkApi.list(ws.currentId); checks.value = resp.data; if (check.value && !checks.value.some((item) => item.id === check.value?.id)) check.value = null; }
async function loadTemplates() { if (ws.currentId == null) { templates.value = []; return; } templates.value = (await ruleApi.templates(ws.currentId)).data; }
function syncCurrentCheck() { check.value = activeChecks.value[0] ?? null; }
async function loadAll() { await ws.load(); await Promise.all([loadDocuments(), loadRules(), loadChecks(), loadTemplates()]); syncCurrentCheck(); }
async function onSwitchWorkspace(id: number) { ws.currentId = id; selectedDocId.value = null; selectedRuleId.value = null; ruleDraft.value = null; check.value = null; focusParagraph.value = null; acceptedFormat.value = {}; acceptedContent.value = {}; acceptedTemplate.value = {}; try { await Promise.all([loadDocuments(), loadRules(), loadChecks(), loadTemplates()]); syncCurrentCheck(); } catch (e) { ElMessage.error(errText(e)); } }
async function onNewWorkspace() { try { const { value } = await ElMessageBox.prompt("请输入工作区名称", "新建工作区", { confirmButtonText: "创建", cancelButtonText: "取消", inputPattern: /\S+/, inputErrorMessage: "工作区名称不能为空" }); await ws.create(value.trim()); documents.value = []; rules.value = []; checks.value = []; templates.value = []; ruleDraft.value = null; check.value = null; acceptedFormat.value = {}; acceptedContent.value = {}; acceptedTemplate.value = {}; await Promise.all([loadDocuments(), loadRules(), loadChecks(), loadTemplates()]); syncCurrentCheck(); } catch { /* 用户取消 */ } }
function onSelectDocument(id: number | null) { selectedDocId.value = id; focusParagraph.value = null; syncCurrentCheck(); }
async function onUpload(file: File) { if (ws.currentId == null) return; uploading.value = true; try { const resp = await documentApi.upload(ws.currentId, file); await loadDocuments(); onSelectDocument(resp.data.id); tab.value = "preview"; ElMessage.success("文档已上传并完成解析"); } catch (e) { ElMessage.error(errText(e)); } finally { uploading.value = false; } }
async function onDeleteDoc(doc: DocumentItem) { try { await ElMessageBox.confirm(`确认删除文档「${doc.filename}」？`, "删除文档", { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }); } catch { return; } try { await documentApi.remove(doc.id); await loadDocuments(); await loadChecks(); syncCurrentCheck(); ElMessage.success("文档已删除"); } catch (e) { ElMessage.error(errText(e)); } }
async function onGenerate(text: string) { if (ws.currentId == null) return; generating.value = true; try { const resp = await ruleApi.generate(ws.currentId, text); await loadRules(); ruleDraft.value = null; selectedRuleId.value = resp.data.id; tab.value = "editor"; ElMessage.success("AI 已提取规则，可在编辑器中微调"); } catch (e) { ElMessage.error(errText(e)); } finally { generating.value = false; } }
function onSelectRule(id: number) { ruleDraft.value = null; selectedRuleId.value = id; tab.value = "editor"; }
function onAddRule(template: RuleTemplate | null) {
  selectedRuleId.value = null;
  versionDialogVisible.value = false;
  ruleDraft.value = structuredClone(template?.ruleset ?? { name: "自定义格式规则" });
  tab.value = "editor";
}
async function onSaveTemplate(ruleset: RuleSet) { if (ws.currentId == null || !selectedRule.value) return; try { const { value } = await ElMessageBox.prompt("为此模板命名", "保存为自定义模板", { confirmButtonText: "保存", cancelButtonText: "取消", inputPattern: /\S+/, inputErrorMessage: "模板名称不能为空" }); const name = value.trim(); const description = ruleset.description ?? `来自规则「${selectedRule.value.name}」`; await ruleApi.createTemplate(ws.currentId, name, description, ruleset); await loadTemplates(); ElMessage.success("自定义模板已保存到当前工作区"); } catch (e) { if (e !== "cancel" && e !== "close") ElMessage.error(errText(e)); } }
async function onDeleteTemplate(template: RuleTemplate) { if (template.source !== "workspace") return; const templateId = Number(template.id.replace(/^workspace:/, "")); if (!Number.isInteger(templateId)) return; try { await ElMessageBox.confirm(`确认删除自定义模板「${template.name}」？`, "删除模板", { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }); } catch { return; } try { await ruleApi.removeTemplate(templateId); await loadTemplates(); ElMessage.success("自定义模板已删除"); } catch (e) { ElMessage.error(errText(e)); } }
async function onDeleteRule(rule: RuleItem) { try { await ElMessageBox.confirm(`确认删除规则「${rule.name}」？`, "删除规则", { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }); } catch { return; } try { await ruleApi.remove(rule.id); await loadRules(); await loadChecks(); syncCurrentCheck(); ElMessage.success("规则已删除"); } catch (e) { ElMessage.error(errText(e)); } }
function onNewRule() { onAddRule(null); }
async function onSaveRuleset(ruleset: RuleSet) { if (ws.currentId == null) return; savingRule.value = true; try { if (!selectedRule.value) { const resp = await ruleApi.createManual(ws.currentId, ruleset); rules.value = [resp.data, ...rules.value]; ruleDraft.value = null; selectedRuleId.value = resp.data.id; ElMessage.success("规则已创建，可直接用于格式审查"); return; } const resp = await ruleApi.updateRuleset(selectedRule.value.id, ruleset); const index = rules.value.findIndex((item) => item.id === resp.data.id); if (index >= 0) rules.value[index] = resp.data; ElMessage.success("规则已保存，后续审查将使用新规则"); } catch (e) { ElMessage.error(errText(e)); } finally { savingRule.value = false; } }
async function runCheck() { if (ws.currentId == null || !selectedDocId.value || !selectedRuleId.value) return; running.value = true; check.value = null; focusParagraph.value = null; try { const resp = await checkApi.run(ws.currentId, selectedDocId.value, selectedRuleId.value); check.value = resp.data; checks.value = [resp.data, ...checks.value.filter((item) => item.id !== resp.data.id)]; tab.value = "report"; ElMessage.success(resp.data.summary.compliant ? "审查完成：全部合规" : `审查完成：发现 ${resp.data.summary.total} 处问题`); } catch (e) { ElMessage.error(errText(e)); } finally { running.value = false; } }
async function runBatchCheck(documentIds: number[]) { if (ws.currentId == null || !selectedRuleId.value || !documentIds.length) return; batchRunning.value = true; try { const resp = await checkApi.runBatch(ws.currentId, documentIds, selectedRuleId.value); const newIds = new Set(resp.data.checks.map((item) => item.id)); checks.value = [...resp.data.checks, ...checks.value.filter((item) => !newIds.has(item.id))]; check.value = resp.data.checks.find((item) => item.document_id === selectedDocId.value) ?? resp.data.checks[0] ?? null; if (check.value) { selectedDocId.value = check.value.document_id; selectedRuleId.value = check.value.rule_id; } batchDialogVisible.value = false; tab.value = "dashboard"; ElMessage.success(`批量审查完成：${resp.data.compliant_documents}/${resp.data.total_documents} 份通过，共发现 ${resp.data.violation_total} 项问题`); } catch (e) { ElMessage.error(errText(e)); } finally { batchRunning.value = false; } }
function onSelectHistory(item: CheckItem) { check.value = item; selectedDocId.value = item.document_id; selectedRuleId.value = item.rule_id; focusParagraph.value = null; tab.value = "report"; }
function onAcceptFormatFix(violationIndex: number, accepted: boolean) { if (!check.value) return; const selected = new Set(acceptedFormat.value[check.value.id] ?? []); if (accepted) selected.add(violationIndex); else selected.delete(violationIndex); acceptedFormat.value = { ...acceptedFormat.value, [check.value.id]: [...selected].sort((a, b) => a - b) }; }
function contentKey(documentId: number, fix: ContentRepairFix) { return `${documentId}:${fix.review_id}:${fix.issue_index}`; }
function onAcceptContentFix(fix: ContentRepairFix) { if (selectedDocId.value == null) return; acceptedContent.value = { ...acceptedContent.value, [contentKey(selectedDocId.value, fix)]: { documentId: selectedDocId.value, fix } }; }
function onRejectContentFix(reviewId: number, issueIndex: number) { if (selectedDocId.value == null) return; const next = { ...acceptedContent.value }; delete next[`${selectedDocId.value}:${reviewId}:${issueIndex}`]; acceptedContent.value = next; }
function onClearContentReview(reviewId: number) { const next = { ...acceptedContent.value }; for (const [key, item] of Object.entries(next)) if (item.fix.review_id === reviewId) delete next[key]; acceptedContent.value = next; }
function templateKey(documentId: number, fix: TemplateRepairFix) { return `${documentId}:${fix.review_id}:${fix.issue_index}`; }
function onAcceptTemplateFix(fix: TemplateRepairFix) { if (selectedDocId.value == null) return; acceptedTemplate.value = { ...acceptedTemplate.value, [templateKey(selectedDocId.value, fix)]: { documentId: selectedDocId.value, fix } }; }
function onRejectTemplateFix(reviewId: number, issueIndex: number) { if (selectedDocId.value == null) return; const next = { ...acceptedTemplate.value }; delete next[`${selectedDocId.value}:${reviewId}:${issueIndex}`]; acceptedTemplate.value = next; }
function onClearTemplateReview(reviewId: number) { const next = { ...acceptedTemplate.value }; for (const [key, item] of Object.entries(next)) if (item.fix.review_id === reviewId) delete next[key]; acceptedTemplate.value = next; }
async function generateRevisedCopy() { if (ws.currentId == null || selectedDocId.value == null || selectedFixCount.value === 0) return; generatingCopy.value = true; try { const response = await documentApi.revisedCopy(selectedDocId.value, { workspace_id: ws.currentId, check_id: selectedFormatIndexes.value.length ? check.value?.id : null, format_violation_indexes: selectedFormatIndexes.value, content_fixes: selectedContentFixes.value, template_fixes: selectedTemplateFixes.value }); const blob = response.data as Blob; if (!blob.size) throw new Error("生成的副本为空"); downloadBlob(blob, `${(selectedDoc.value?.filename ?? "文档.docx").replace(/\.docx$/i, "")}_修订后副本.docx`); ElMessage.success("已生成修订后副本，原始文件未修改"); } catch (e) { ElMessage.error(await copyErrorText(e)); } finally { generatingCopy.value = false; } }
function downloadBlob(blob: Blob, filename: string) { const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = filename; link.style.display = "none"; document.body.appendChild(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); }
async function copyErrorText(error: unknown): Promise<string> { const blob = (error as { response?: { data?: unknown } }).response?.data; if (blob instanceof Blob) { try { const data = JSON.parse(await blob.text()) as { detail?: unknown }; if (typeof data.detail === "string") return data.detail; } catch { /* 保留通用错误 */ } } return errText(error); }
async function onDeleteCheck(item: CheckItem) { try { await ElMessageBox.confirm("删除后无法恢复，确认删除这条格式审查记录？", "删除审查记录", { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }); } catch { return; } try { await checkApi.remove(item.id); checks.value = checks.value.filter(checkItem => checkItem.id !== item.id); const next = { ...acceptedFormat.value }; delete next[item.id]; acceptedFormat.value = next; if (check.value?.id === item.id) syncCurrentCheck(); ElMessage.success("格式审查记录已删除"); } catch (e) { ElMessage.error(errText(e)); } }
function onRuleRestored(rule: RuleItem) { const index = rules.value.findIndex((item) => item.id === rule.id); if (index >= 0) rules.value[index] = rule; ruleDraft.value = null; selectedRuleId.value = rule.id; tab.value = "editor"; }
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
  tab.value = "preview";
  await nextTick();
  focusParagraph.value = index;
}
function logout() { auth.logout(); ws.reset(); router.push("/login"); }
onMounted(async () => { try { await loadAll(); } catch (e) { ElMessage.error(errText(e)); } });
</script>

<style scoped>
.app-shell{min-width:0;height:100vh;color:#273653;background:#f5f7fb}.topbar{z-index:2;display:flex;align-items:center;height:66px;padding:0 26px;border-bottom:1px solid #e7ebf3;background:rgba(255,255,255,.95);box-shadow:0 2px 12px rgba(33,48,80,.03)}.brand{display:flex;align-items:center;gap:10px;color:#172442;font-size:17px;font-weight:800;letter-spacing:.02em;white-space:nowrap}.brand small{display:block;margin-top:-1px;color:#8c9ab2;font-size:9px;font-weight:700;letter-spacing:.1em}.brand-mark{display:grid;place-items:center;width:31px;height:31px;color:#fff;border-radius:9px;background:linear-gradient(135deg,#5b77f4,#314fd4);box-shadow:0 5px 12px rgba(59,82,205,.3);font-family:Georgia,serif;font-size:19px}.workspace-picker{display:flex;align-items:center;gap:8px;margin-left:52px}.workspace-picker :deep(.el-select){width:178px}.workspace-picker :deep(.el-input__wrapper){background:#f6f8fc;box-shadow:0 0 0 1px #edf0f5 inset}.workspace-label{color:#8c99ad;font-size:12px}.new-workspace{font-size:12px}.topbar-spacer{flex:1}.user-area{display:flex;align-items:center;gap:8px}.avatar{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;color:#526ed9;background:#e9eeff;font-size:12px;font-weight:800}.user-name{color:#53617a;font-size:13px;cursor:pointer}.chevron{margin-left:3px;color:#96a1b3}.workspace-body{min-height:0}.left-rail,.right-rail{overflow-y:auto;padding:18px 14px;background:#fbfcfe}.left-rail{border-right:1px solid #e8ecf3}.right-rail{border-left:1px solid #e8ecf3}.side-card,.history-card,.main-card{border:1px solid #e7ebf3;border-radius:12px}.side-card{margin-bottom:13px}.side-card :deep(.el-card__body){padding:15px}.content-main{overflow-y:auto;padding:24px}.hero-row{display:flex;align-items:center;justify-content:space-between;gap:20px;max-width:1260px;margin:0 auto 20px}.eyebrow{margin:0 0 5px;color:#6d80a6;font-size:10px;font-weight:800;letter-spacing:.13em}h1{margin:0;color:#172541;font-size:25px;letter-spacing:-.03em}.hero-copy{margin:7px 0 0;color:#8995a8;font-size:13px}.stats{display:flex;overflow:hidden;border:1px solid #e6ebf4;border-radius:10px;background:#fff}.stats div{display:grid;min-width:75px;padding:9px 14px;border-right:1px solid #edf0f5;text-align:center}.stats div:last-child{border:0}.stats b{color:#344767;font-size:17px}.stats span{margin-top:2px;color:#98a3b5;font-size:10px}.success-text{color:#169167!important}.warning-text{color:#dc6645!important}.review-bar{display:flex;align-items:center;gap:15px;max-width:1260px;padding:13px 16px;margin:0 auto 17px;border:1px solid #e5eaf4;border-radius:12px;background:#fff;box-shadow:0 5px 20px rgba(39,58,94,.035)}.selection{display:flex;align-items:center;min-width:0;gap:9px}.selection-icon{display:grid;place-items:center;width:31px;height:31px;flex:0 0 auto;border-radius:8px;font-size:11px;font-weight:800}.selection-icon.doc{color:#4e69ca;background:#e9efff}.selection-icon.rule{color:#9a63cc;background:#f3eaff}.selection div{display:grid;min-width:0;gap:2px}.selection small{color:#9aa5b7;font-size:10px}.selection b{display:block;max-width:235px;overflow:hidden;color:#384762;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.flow-line{color:#b0bbcf}.batch-button{margin-left:auto}.run-button{margin-left:0;padding-right:16px;padding-left:16px;border:0;background:linear-gradient(135deg,#5f7bf5,#4160dc);box-shadow:0 5px 12px rgba(65,96,220,.22)}.run-button span{margin-left:6px}.main-card{max-width:1260px;min-height:575px;margin:0 auto 22px}.main-card :deep(.el-card__body){padding:0 20px 20px}.main-tabs :deep(.el-tabs__header){margin-bottom:20px}.main-tabs :deep(.el-tabs__nav-wrap::after){height:1px;background:#edf0f5}.main-tabs :deep(.el-tabs__item){height:55px;padding:0 18px;color:#77849b;font-size:13px}.main-tabs :deep(.el-tabs__item.is-active){color:#4766dc;font-weight:700}.tab-count{display:inline-grid;place-items:center;min-width:16px;height:16px;margin-left:3px;border-radius:8px;color:#fff;background:#ec7857;font-size:10px;line-height:1}.json{max-height:500px;padding:18px;overflow:auto;border:1px solid #e8edf5;border-radius:10px;color:#3e4c68;background:#f7f9fc;font-size:12px;line-height:1.6}.history-card{min-height:250px}.history-card :deep(.el-card__body){padding:15px 11px}@media(max-width:1180px){.right-rail{display:none}}@media(max-width:900px){.left-rail{width:248px!important}.content-main{padding:18px}.workspace-picker{margin-left:22px}.workspace-label{display:none}}@media(max-width:700px){.topbar{height:58px;padding:0 14px}.brand small,.workspace-picker,.user-name{display:none}.user-area{margin-left:auto}.left-rail{display:none}.content-main{padding:15px}.hero-row{display:block}.stats{width:max-content;margin-top:14px}.review-bar{align-items:stretch;flex-direction:column;gap:9px}.flow-line{display:none}.selection b{max-width:none}.batch-button,.run-button{width:100%;margin-top:4px}.main-card :deep(.el-card__body){padding:0 12px 14px}.main-tabs :deep(.el-tabs__item){padding:0 10px;font-size:12px}}
</style>
