<template>
  <section class="template-audit">
    <div class="toolbar">
      <div>
        <h2>当前文档模板</h2>
        <p>上传填写好的标准样例，再确认哪些区域固定、哪些允许用户填写。</p>
      </div>
      <el-upload :show-file-list="false" :auto-upload="false" accept=".docx" :on-change="onPickTemplate">
        <el-button type="primary" :loading="uploading">{{ current ? "上传新版本" : "上传模板" }}</el-button>
      </el-upload>
    </div>

    <el-empty v-if="!current" description="当前工作区还没有文档模板，请先上传 .docx 标准样例" />

    <template v-else>
      <el-alert type="info" :closable="false" show-icon>
        <template #title>模板中的姓名、年龄、地址等不会自动当成标准答案；请将它们标记为“可变字段”。只有“固定内容”才要求文字一致。</template>
      </el-alert>

      <div class="meta-row">
        <el-tag :type="current.is_published ? 'success' : 'warning'">{{ current.is_published ? "已发布" : "待确认" }}</el-tag>
        <el-input v-model="draftName" maxlength="200"><template #prepend>模板名称</template></el-input>
        <el-select :model-value="current.id" class="version-select" @change="activateVersion">
          <el-option v-for="item in versions" :key="item.id" :value="item.id" :label="`版本 ${item.version} · ${item.filename}${item.is_active ? '（当前）' : ''}`" />
        </el-select>
        <el-switch v-model="draftCheckPage" active-text="检查页面设置" />
        <el-button type="success" :loading="saving" @click="saveConfiguration">保存并发布配置</el-button>
      </div>

      <el-table :data="visibleBlocks" border max-height="420" class="config-table" empty-text="模板中没有可配置文字">
        <el-table-column label="模板区域" min-width="230">
          <template #default="{ row }">
            <button class="text-link" type="button" @click="focusTemplate = row.content_index">{{ row.text || "（空白区域）" }}</button>
            <small>{{ row.location }}</small>
          </template>
        </el-table-column>
        <el-table-column label="字段名称" min-width="145"><template #default="{ row }"><el-input v-model="row.label" size="small" /></template></el-table-column>
        <el-table-column label="区域用途" width="130"><template #default="{ row }"><el-select v-model="row.mode" size="small"><el-option label="固定内容" value="fixed" /><el-option label="可变字段" value="variable" /><el-option label="忽略" value="ignore" /></el-select></template></el-table-column>
        <el-table-column label="字段类型" width="125"><template #default="{ row }"><el-select v-model="row.data_type" size="small" :disabled="row.mode !== 'variable'"><el-option label="文本" value="text" /><el-option label="数字" value="number" /><el-option label="日期" value="date" /><el-option label="身份证号" value="id_number" /><el-option label="电话号码" value="phone" /></el-select></template></el-table-column>
        <el-table-column label="必填" width="70" align="center"><template #default="{ row }"><el-checkbox v-model="row.required" :disabled="row.mode === 'ignore'" /></template></el-table-column>
        <el-table-column label="检查格式" width="90" align="center"><template #default="{ row }"><el-checkbox v-model="row.check_format" :disabled="row.mode === 'ignore'" /></template></el-table-column>
      </el-table>

      <div class="review-toolbar">
        <div>
          <h2>模板对比审查</h2>
          <p>左右并列查看标准样例和待审文档，点击问题可同时定位两侧区域。</p>
        </div>
        <el-select :model-value="selectedDocumentId" placeholder="选择待审文档" filterable @change="$emit('select-document', $event)">
          <el-option v-for="doc in documents" :key="doc.id" :label="doc.filename" :value="doc.id" />
        </el-select>
        <el-button type="primary" :disabled="!selectedDocumentId || !current.is_published" :loading="reviewing" @click="runReview">执行模板审查</el-button>
      </div>

      <div class="comparison">
        <div class="preview-column">
          <div class="column-title">标准模板 · v{{ current.version }}</div>
          <DocPreview :document-id="current.id" :preview-url="`/template-audits/templates/${current.id}/preview`" :focus-paragraph="focusTemplate" focus-kind="template" />
        </div>
        <div class="preview-column">
          <div class="column-title">待审文档 · {{ selectedDocument?.filename || "尚未选择" }}</div>
          <DocPreview :document-id="selectedDocumentId" :focus-paragraph="focusDocument" focus-kind="content" />
        </div>
      </div>

      <div v-if="reviews.length" class="history-row">
        <span>审查记录</span>
        <el-select :model-value="review?.id" @change="selectReview">
          <el-option v-for="item in reviews" :key="item.id" :value="item.id" :label="`模板 v${item.template_version} · ${formatTime(item.created_at)} · ${item.total} 项问题`" />
        </el-select>
        <el-button v-if="review" link type="danger" @click="deleteReview">删除记录</el-button>
      </div>

      <el-result v-if="review?.compliant" icon="success" title="模板审查通过" sub-title="文档结构、填写规则和已启用的格式检查均符合当前模板" />
      <div v-else-if="review" class="issues">
        <el-alert :title="review.summary" type="warning" :closable="false" show-icon />
        <article v-for="(issue, index) in review.issues" :key="`${review.id}-${index}`" class="issue-card">
          <div class="issue-head">
            <el-tag :type="issue.severity === '错误' ? 'danger' : 'warning'" effect="light">{{ issue.category }}</el-tag>
            <strong>{{ issue.message }}</strong>
            <el-button link type="primary" @click="locateIssue(issue)">对比定位</el-button>
            <el-checkbox v-if="issue.repairable && issue.format_violation" :model-value="isAccepted(index)" @change="toggleFormat(index, Boolean($event))">接纳修订</el-checkbox>
            <el-button v-else-if="issue.repairable" link type="success" @click="acceptText(index, issue)">{{ isAccepted(index) ? "编辑修订" : "接纳并修订" }}</el-button>
            <el-button v-if="isAccepted(index)" link type="danger" @click="$emit('reject', review.id, index)">取消接纳</el-button>
          </div>
          <div class="diff"><span><b>模板要求</b>{{ display(issue.expected) }}</span><span><b>待审内容</b>{{ display(issue.actual) }}</span></div>
          <p v-if="issue.recommended_replacement" class="recommend">推荐修订文本：{{ issue.recommended_replacement }}</p>
          <p v-if="!issue.repairable" class="manual-note">该问题无法安全地自动修改，需要人工核实后处理。</p>
        </article>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage, ElMessageBox, type UploadFile } from "element-plus";
import { templateAuditApi } from "@/api";
import DocPreview from "@/components/DocPreview.vue";
import type { DocumentItem, DocumentTemplate, TemplateBlock, TemplateIssue, TemplateRepairFix, TemplateReview } from "@/types";

const props = defineProps<{
  workspaceId: number | null;
  documents: DocumentItem[];
  selectedDocumentId: number | null;
  acceptedFixes: TemplateRepairFix[];
}>();
const emit = defineEmits<{
  (e: "select-document", id: number): void;
  (e: "accept", fix: TemplateRepairFix): void;
  (e: "reject", reviewId: number, issueIndex: number): void;
  (e: "clear-review", reviewId: number): void;
}>();

const current = ref<DocumentTemplate | null>(null);
const versions = ref<DocumentTemplate[]>([]);
const draftBlocks = ref<TemplateBlock[]>([]);
const draftName = ref("");
const draftCheckPage = ref(true);
const reviews = ref<TemplateReview[]>([]);
const review = ref<TemplateReview | null>(null);
const uploading = ref(false);
const saving = ref(false);
const reviewing = ref(false);
const focusTemplate = ref<number | null>(null);
const focusDocument = ref<number | null>(null);
let templateGeneration = 0;
let reviewGeneration = 0;

const visibleBlocks = computed(() => draftBlocks.value.filter(block => block.text.trim()));
const selectedDocument = computed(() => props.documents.find(doc => doc.id === props.selectedDocumentId) ?? null);

function setCurrent(value: DocumentTemplate | null) {
  current.value = value;
  draftName.value = value?.name ?? "";
  draftCheckPage.value = value?.config.check_page ?? true;
  draftBlocks.value = value ? structuredClone(value.config.blocks) : [];
  focusTemplate.value = null;
}
function errorText(error: unknown) {
  const value = (error as { response?: { data?: { detail?: string } }; message?: string });
  return value.response?.data?.detail || value.message || "操作失败";
}
async function loadTemplate() {
  const generation = ++templateGeneration;
  if (props.workspaceId == null) { setCurrent(null); versions.value = []; return; }
  const [currentResponse, versionsResponse] = await Promise.all([
    templateAuditApi.current(props.workspaceId), templateAuditApi.versions(props.workspaceId),
  ]);
  if (generation !== templateGeneration) return;
  setCurrent(currentResponse.data);
  versions.value = versionsResponse.data;
}
async function loadReviews() {
  const generation = ++reviewGeneration;
  const workspaceId = props.workspaceId;
  const documentId = props.selectedDocumentId;
  if (workspaceId == null || documentId == null) { reviews.value = []; review.value = null; return; }
  const response = await templateAuditApi.reviews(workspaceId, documentId);
  if (generation !== reviewGeneration) return;
  reviews.value = response.data;
  review.value = response.data[0] ?? null;
}
async function onPickTemplate(file: UploadFile) {
  if (!file.raw || props.workspaceId == null) return;
  uploading.value = true;
  try {
    const defaultName = file.name.replace(/\.docx$/i, "");
    const { value } = await ElMessageBox.prompt("请输入模板名称", "上传模板版本", { inputValue: defaultName, inputPattern: /\S+/, inputErrorMessage: "名称不能为空" });
    const response = await templateAuditApi.upload(props.workspaceId, file.raw, value.trim());
    setCurrent(response.data);
    versions.value = (await templateAuditApi.versions(props.workspaceId)).data;
    ElMessage.success(`模板版本 ${response.data.version} 已上传，请确认区域用途后保存`);
  } catch (error) {
    if (error !== "cancel" && error !== "close") ElMessage.error(errorText(error));
  } finally { uploading.value = false; }
}
async function saveConfiguration() {
  if (!current.value || props.workspaceId == null) return;
  saving.value = true;
  try {
    const response = await templateAuditApi.update(props.workspaceId, draftName.value.trim(), draftCheckPage.value, draftBlocks.value);
    setCurrent(response.data);
    versions.value = versions.value.map(item => item.id === response.data.id ? response.data : item);
    ElMessage.success("模板配置已保存并发布");
  } catch (error) { ElMessage.error(errorText(error)); } finally { saving.value = false; }
}
async function activateVersion(id: number) {
  if (props.workspaceId == null || id === current.value?.id) return;
  try {
    await ElMessageBox.confirm("切换后，该版本会成为工作区当前模板。继续吗？", "切换模板版本");
    const response = await templateAuditApi.activate(props.workspaceId, id);
    setCurrent(response.data);
    versions.value = (await templateAuditApi.versions(props.workspaceId)).data;
    ElMessage.success(`已切换到模板版本 ${response.data.version}`);
  } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(errorText(error)); }
}
async function runReview() {
  if (props.workspaceId == null || props.selectedDocumentId == null) return;
  reviewing.value = true;
  try {
    const response = await templateAuditApi.run(props.workspaceId, props.selectedDocumentId);
    reviews.value = [response.data, ...reviews.value];
    review.value = response.data;
    ElMessage.success(response.data.compliant ? "模板审查通过" : `发现 ${response.data.total} 项模板差异`);
  } catch (error) { ElMessage.error(errorText(error)); } finally { reviewing.value = false; }
}
function selectReview(id: number) { review.value = reviews.value.find(item => item.id === id) ?? null; }
async function deleteReview() {
  if (!review.value) return;
  const id = review.value.id;
  try { await ElMessageBox.confirm("确认删除这条模板审查记录？", "删除审查记录", { type: "warning" }); }
  catch { return; }
  try {
    await templateAuditApi.removeReview(id);
    emit("clear-review", id);
    reviews.value = reviews.value.filter(item => item.id !== id);
    review.value = reviews.value[0] ?? null;
    ElMessage.success("模板审查记录已删除");
  } catch (error) { ElMessage.error(errorText(error)); }
}
function locateIssue(issue: TemplateIssue) {
  focusTemplate.value = null; focusDocument.value = null;
  window.setTimeout(() => {
    focusTemplate.value = issue.template_content_index;
    focusDocument.value = issue.document_content_index;
  }, 0);
}
function isAccepted(index: number) { return !!review.value && props.acceptedFixes.some(fix => fix.review_id === review.value!.id && fix.issue_index === index); }
function toggleFormat(index: number, accepted: boolean) {
  if (!review.value) return;
  if (accepted) emit("accept", { review_id: review.value.id, issue_index: index, replacement_text: null });
  else emit("reject", review.value.id, index);
}
async function acceptText(index: number, issue: TemplateIssue) {
  if (!review.value) return;
  const existing = props.acceptedFixes.find(fix => fix.review_id === review.value!.id && fix.issue_index === index)?.replacement_text;
  try {
    const { value } = await ElMessageBox.prompt("请输入仅用于替换问题原文的具体内容", "确认模板修订", {
      inputValue: existing || issue.recommended_replacement || "",
      inputPattern: /\S+/, inputErrorMessage: "替换内容不能为空",
      confirmButtonText: "接纳", cancelButtonText: "取消",
    });
    emit("accept", { review_id: review.value.id, issue_index: index, replacement_text: value });
  } catch { /* 用户取消 */ }
}
function display(value: unknown) {
  if (value == null || value === "") return "（无）";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
function formatTime(value: string) { return new Date(value).toLocaleString("zh-CN"); }

watch(() => props.workspaceId, async () => {
  reviews.value = []; review.value = null;
  try { await loadTemplate(); await loadReviews(); } catch (error) { ElMessage.error(errorText(error)); }
}, { immediate: true });
watch(() => props.selectedDocumentId, async () => {
  focusDocument.value = null;
  try { await loadReviews(); } catch (error) { ElMessage.error(errorText(error)); }
});
</script>

<style scoped>
.template-audit{display:grid;gap:18px}.toolbar,.review-toolbar,.meta-row,.history-row{display:flex;align-items:center;gap:12px}.toolbar,.review-toolbar{justify-content:space-between}.toolbar h2,.review-toolbar h2{margin:0;color:#243552;font-size:17px}.toolbar p,.review-toolbar p{margin:4px 0 0;color:#8793a7;font-size:12px}.meta-row{flex-wrap:wrap;padding:14px;border:1px solid #e5eaf3;border-radius:9px;background:#fafbfe}.meta-row .el-input{max-width:390px}.version-select{width:260px}.config-table small{display:block;margin-top:4px;color:#98a3b6}.text-link{padding:0;border:0;color:#405a9f;background:none;text-align:left;cursor:pointer}.review-toolbar{padding-top:8px;border-top:1px solid #edf0f5}.review-toolbar .el-select{width:260px;margin-left:auto}.comparison{display:grid;grid-template-columns:1fr 1fr;gap:14px}.preview-column{min-width:0;border:1px solid #e5eaf3;border-radius:10px;overflow:hidden}.column-title{padding:10px 14px;color:#495a78;background:#f5f7fb;font-size:12px;font-weight:700}.preview-column :deep(.preview),.preview-column :deep(.placeholder){min-height:390px}.preview-column :deep(.doc-wrap){height:390px;min-height:390px;border:0;border-radius:0}.history-row{padding:10px 12px;border-radius:8px;background:#f7f9fc;color:#65738a;font-size:12px}.history-row .el-select{width:330px}.issues{display:grid;gap:10px}.issue-card{padding:14px;border:1px solid #e7ebf3;border-radius:10px;background:#fff}.issue-head{display:flex;align-items:center;gap:10px}.issue-head strong{margin-right:auto;color:#31415e;font-size:13px}.diff{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:11px}.diff span{padding:10px;border-radius:7px;color:#56657e;background:#f7f9fc;font-size:12px;overflow-wrap:anywhere}.diff b{display:block;margin-bottom:4px;color:#8995a9;font-size:10px}.recommend{padding:9px 11px;margin:9px 0 0;border-left:3px solid #65bd8c;color:#376c50;background:#f0faf5;font-size:12px}.manual-note{margin:9px 0 0;color:#a17045;font-size:12px}@media(max-width:900px){.comparison{grid-template-columns:1fr}.toolbar,.review-toolbar{align-items:stretch;flex-direction:column}.review-toolbar .el-select{width:100%;margin-left:0}.diff{grid-template-columns:1fr}}
</style>
