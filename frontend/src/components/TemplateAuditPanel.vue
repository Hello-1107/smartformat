<template>
  <section class="template-audit">
    <div class="toolbar">
      <div>
        <h2>当前表单模板</h2>
        <p>上传填写好的标准样例，核对字段名称与低置信度识别结果，再配置具体填写要求。</p>
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
        <el-button :loading="reanalyzing" @click="reanalyzeFields">重新识别字段</el-button>
        <el-button type="success" :loading="saving" @click="saveConfiguration">保存并发布配置</el-button>
      </div>

      <el-table :data="visibleBlocks" border max-height="420" class="config-table" empty-text="模板中没有可配置文字">
        <el-table-column label="模板区域" min-width="230">
          <template #default="{ row }">
            <button class="text-link" type="button" @click="focusTemplate = row.content_index">{{ row.text || "（空白区域）" }}</button>
            <small>{{ row.location }}</small>
          </template>
        </el-table-column>
        <el-table-column label="字段名称" min-width="145"><template #default="{ row }"><el-input v-model="row.label" size="small" /><small v-if="row.recognition_confidence === 'low'" class="uncertain">待确认：{{ row.recognition_note }}<el-checkbox v-model="row.recognition_confirmed" label="已核对" size="small" /></small><small v-else-if="row.recognition_confidence === 'medium'">{{ row.recognition_note }}</small></template></el-table-column>
        <el-table-column label="区域用途" width="130"><template #default="{ row }"><el-select v-model="row.mode" size="small"><el-option label="固定内容" value="fixed" /><el-option label="可变字段" value="variable" /><el-option label="忽略" value="ignore" /></el-select></template></el-table-column>
        <el-table-column label="字段类型" width="125"><template #default="{ row }"><el-select v-model="row.data_type" size="small" :disabled="row.mode !== 'variable'"><el-option label="文本" value="text" /><el-option label="数字" value="number" /><el-option label="日期" value="date" /><el-option label="身份证号" value="id_number" /><el-option label="电话号码" value="phone" /><el-option label="电子邮箱" value="email" /></el-select></template></el-table-column>
        <el-table-column label="必填" width="70" align="center"><template #default="{ row }"><el-checkbox v-model="row.required" :disabled="row.mode === 'ignore'" /></template></el-table-column>
        <el-table-column label="检查格式" width="90" align="center"><template #default="{ row }"><el-checkbox v-model="row.check_format" :disabled="row.mode === 'ignore'" /></template></el-table-column>
        <el-table-column label="填写要求" width="110"><template #default="{ row }"><el-button link type="primary" :disabled="row.mode !== 'variable'" @click="openRequirements(row)">{{ row.rules?.length ? `${row.rules.length} 条规则` : row.requirement_text?.trim() ? '要求待处理' : '设置要求' }}</el-button></template></el-table-column>
      </el-table>

      <el-dialog v-model="requirementDialog" :title="`填写要求 · ${selectedRuleBlock?.label || '字段'}`" width="min(700px, 92vw)">
        <p class="requirement-help">要求仅作用于当前字段，不从样例值推断固定答案或单位。输入后生成并核对草案，发布后才用于确定性审查。示例：人数要写6人不能写6；政治面貌为共青团员时不能够填写团员；数字后必须带人字。</p>
        <el-input v-model="requirementText" type="textarea" :rows="3" maxlength="1000" show-word-limit placeholder="每行一条当前字段的具体要求" @input="onRequirementInput" />
        <div class="draft-actions"><el-button :loading="draftingRequirements" @click="parseRequirements">生成规则草案</el-button><span v-if="unsupportedRequirements.length" class="uncertain">未启用：{{ unsupportedRequirements.join('；') }}。确定性审查不会执行这些要求，可选择 DeepSeek 获取建议。</span><el-button v-if="unsupportedRequirements.length && selectedRuleBlock?.rules.length" link @click="clearUnsupported">已手动配置对应规则</el-button></div>
        <div v-for="(rule, index) in selectedRuleBlock?.rules ?? []" :key="index" class="requirement-rule">
          <el-select v-model="rule.kind" style="width:160px" @change="resetRuleParameters(rule)"><el-option label="邮箱格式" value="email" /><el-option label="字符长度" value="length" /><el-option label="汉字字数" value="chinese_length" /><el-option label="数值范围" value="number_range" /><el-option label="限定选项" value="allowed_values" /><el-option label="包含文字" value="contains" /><el-option label="与字段一致" value="same_as" /><el-option label="必须等于" value="exact_text" /><el-option label="禁止填写" value="forbidden_value" /><el-option label="数字带单位" value="number_with_unit" /></el-select>
          <template v-if="rule.kind === 'length' || rule.kind === 'chinese_length'"><el-input-number v-model="rule.min_length" :min="0" :max="10000" placeholder="最小" /><span>至</span><el-input-number v-model="rule.max_length" :min="0" :max="10000" placeholder="最大" /></template>
          <template v-else-if="rule.kind === 'number_range'"><el-input-number v-model="rule.min_value" placeholder="最小" /><span>至</span><el-input-number v-model="rule.max_value" placeholder="最大" /></template>
          <el-input v-else-if="rule.kind === 'allowed_values'" :model-value="(rule.options ?? []).join('、')" placeholder="用顿号分隔选项" @update:model-value="setRuleOptions(rule, $event)" />
          <el-input v-else-if="rule.kind === 'contains'" v-model="rule.text" placeholder="必须包含的文字" />
          <el-input v-else-if="rule.kind === 'exact_text'" v-model="rule.text" placeholder="必须填写的完整文字" />
          <template v-else-if="rule.kind === 'forbidden_value'"><el-input v-model="rule.text" placeholder="禁止填写的完整文字" /><el-input v-model="rule.replacement_text" placeholder="建议写法（可留空）" /></template>
          <el-input v-else-if="rule.kind === 'number_with_unit'" v-model="rule.text" placeholder="单位，如 人；不设则不检查" />
          <el-select v-else-if="rule.kind === 'same_as'" v-model="rule.other_block_id" filterable placeholder="选择另一字段"><el-option v-for="other in comparableBlocks" :key="other.id" :label="`${other.label} · ${other.location}`" :value="other.id" /></el-select>
          <span v-else>检查邮箱地址格式</span>
          <el-button link type="danger" @click="selectedRuleBlock?.rules.splice(index, 1)">删除</el-button>
        </div>
        <el-button link type="primary" @click="selectedRuleBlock?.rules.push({ kind: 'email' })">新增规则</el-button>
        <template #footer><el-button @click="requirementDialog = false">完成编辑</el-button></template>
      </el-dialog>

      <div class="review-toolbar">
        <div>
          <h2>表单模板对比审查</h2>
          <p>左右并列查看标准样例和待审文档，点击问题可同时定位两侧区域。</p>
        </div>
        <el-select :model-value="selectedDocumentId" placeholder="选择待审文档" filterable @change="$emit('select-document', $event)">
          <el-option v-for="doc in documents" :key="doc.id" :label="doc.filename" :value="doc.id" />
        </el-select>
        <el-button type="primary" :disabled="!selectedDocumentId || !publishedTemplate" :loading="reviewing" @click="runReview">执行表单模板审查</el-button>
      </div>
      <div class="ai-controls">
        <el-checkbox v-model="aiEnabled">同时使用 DeepSeek 评估填写内容（可选）</el-checkbox>
        <el-select v-if="aiEnabled" v-model="aiFieldIds" multiple filterable collapse-tags placeholder="选择要发送的可变字段" :disabled="!publishedTemplate">
          <el-option v-for="block in aiOptions" :key="block.id" :label="`${block.label || block.location} · ${block.location}`" :value="block.id" />
        </el-select>
        <small>仅发送选中字段的填写内容与已发布要求；AI 建议不参与合规判定、不自动修改个人信息。</small>
      </div>

      <div class="preview-controls">
        <span v-if="!current.is_published && publishedTemplate">草稿未发布，审查使用已发布 v{{ publishedTemplate.version }}</span>
        <span>左右同步缩放</span>
        <el-button aria-label="缩小预览" :disabled="previewZoom === 25" @click="changePreviewZoom(-25)">−</el-button>
        <el-select v-model="previewZoomMode" aria-label="预览缩放比例">
          <el-option label="适应宽度" value="fit" />
          <el-option v-for="value in zoomOptions" :key="value" :label="`${value}%`" :value="String(value)" />
        </el-select>
        <el-button aria-label="放大预览" :disabled="previewZoom === 200" @click="changePreviewZoom(25)">＋</el-button>
        <el-button :disabled="previewZoomMode === 'fit'" @click="previewZoomMode = 'fit'">适应宽度</el-button>
        <small>放大后可使用横向、纵向滚动条查看完整内容</small>
      </div>

      <div class="comparison">
        <div class="preview-column">
          <div class="column-title">标准模板 · v{{ review?.template_version ?? current.version }}{{ review && !review.template_snapshot ? '（旧报告未保存配置快照）' : '' }}</div>
          <DocPreview :active="active" :document-id="comparisonTemplate?.id ?? null" :preview-url="comparisonTemplate ? `/template-audits/templates/${comparisonTemplate.id}/preview` : undefined" :focus-paragraph="focusTemplate" focus-kind="template" fit-width :zoom-percent="previewZoom" />
        </div>
        <div class="preview-column">
          <div class="column-title">待审文档 · {{ selectedDocument?.filename || "尚未选择" }}</div>
          <DocPreview :active="active" :document-id="selectedDocumentId" :focus-paragraph="focusDocument" focus-kind="content" fit-width :zoom-percent="previewZoom" />
        </div>
      </div>

      <div v-if="reviews.length" class="history-row">
        <span>审查记录</span>
        <el-select :model-value="review?.id" @change="selectReview">
          <el-option v-for="item in reviews" :key="item.id" :value="item.id" :label="`模板 v${item.template_version} · ${formatTime(item.created_at)} · ${item.total} 项问题`" />
        </el-select>
        <el-button v-if="review" link type="danger" @click="deleteReview">删除记录</el-button>
        <el-button v-if="review" :loading="exportingId === review.id" @click="exportCurrent">导出当前表单审查报告 DOCX</el-button>
        <el-button v-if="hasMoreReviews" link :loading="moreLoading" @click="loadMoreReviews">加载更早记录</el-button>
      </div>

      <el-result v-if="review?.compliant" icon="success" title="表单模板审查通过" :sub-title="`文档符合本次审查使用的模板 v${review.template_version}`" />
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
      <section v-if="review?.ai_review" class="ai-results">
        <h3>DeepSeek 填写内容建议 <small>不影响上方合规结论</small></h3>
        <el-alert :title="review.ai_review.summary" :type="review.ai_review.status === 'completed' ? 'info' : 'warning'" :closable="false" show-icon />
        <article v-for="(suggestion, index) in review.ai_review.suggestions" :key="`${review.id}-ai-${index}`" class="issue-card">
          <div class="issue-head"><el-tag type="info">AI 建议</el-tag><strong>{{ aiFieldLabel(suggestion.block_id) }}</strong><el-button link type="primary" @click="locateAiSuggestion(suggestion)">定位字段</el-button></div>
          <div class="diff"><span><b>原文</b>{{ suggestion.quote }}</span><span><b>原因</b>{{ suggestion.reason }}</span></div>
          <p class="manual-note">{{ suggestion.suggestion }}</p>
          <p v-if="suggestion.recommended_replacement" class="recommend">可核实的替换文字：{{ suggestion.recommended_replacement }}（不会自动应用）</p>
        </article>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus/es/components/message/index";
import { ElMessageBox } from "element-plus/es/components/message-box/index";
import type { UploadFile } from "element-plus";
import { reportApi, templateAuditApi } from "@/api";
import { downloadBlob, downloadErrorText } from "@/utils/download";
import DocPreview from "@/components/DocPreview.vue";
import type { DocumentItem, DocumentTemplate, TemplateBlock, TemplateFieldRule, TemplateIssue, TemplateRepairFix, TemplateReview } from "@/types";

const props = withDefaults(defineProps<{
  workspaceId: number | null;
  documents: DocumentItem[];
  selectedDocumentId: number | null;
  acceptedFixes: TemplateRepairFix[];
  active?: boolean;
}>(), {active:true});
const emit = defineEmits<{
  (e: "select-document", id: number): void;
  (e: "accept", fix: TemplateRepairFix): void;
  (e: "reject", reviewId: number, issueIndex: number): void;
  (e: "clear-review", reviewId: number): void;
}>();

const current = ref<DocumentTemplate | null>(null);
const versions = ref<DocumentTemplate[]>([]);
const draftBlocks = ref<TemplateBlock[]>([]);
const requirementDialog = ref(false);
const selectedRuleBlock = ref<TemplateBlock | null>(null);
const requirementText = ref("");
const unsupportedRequirements = ref<string[]>([]);
const draftingRequirements = ref(false);
const draftName = ref("");
const draftCheckPage = ref(true);
const reviews = ref<TemplateReview[]>([]);
const review = ref<TemplateReview | null>(null);
const exportingId = ref<number | null>(null);
const hasMoreReviews=ref(false);const moreLoading=ref(false);
const uploading = ref(false);
const saving = ref(false);
const reviewing = ref(false);
const reanalyzing = ref(false);
const activating = ref(false);
const aiEnabled = ref(false);
const aiFieldIds = ref<string[]>([]);
const mutationBusy = computed(() => uploading.value || saving.value || reanalyzing.value || activating.value);
const historyTemplate = ref<DocumentTemplate | null>(null);
const publishedTemplate = computed(() => versions.value.find(item=>item.is_published && item.is_review_active) ?? (current.value?.is_published ? current.value : [...versions.value].filter(item=>item.is_published).sort((a,b)=>b.version-a.version)[0] ?? null));
const aiOptions = computed(() => (publishedTemplate.value?.config.blocks ?? []).filter(block => block.mode === "variable"));
const comparisonTemplate = computed(() => review.value ? (review.value.template_snapshot ?? historyTemplate.value) : current.value);
let workspaceEpoch = 0;
function context(documentId?: number | null) {
  const epoch = workspaceEpoch;
  return () => epoch === workspaceEpoch && (documentId === undefined || documentId === props.selectedDocumentId);
}
const focusTemplate = ref<number | null>(null);
const focusDocument = ref<number | null>(null);
const zoomOptions = [25, 50, 75, 100, 125, 150, 175, 200];
const previewZoomMode = ref("fit");
let templateGeneration = 0;
let reviewGeneration = 0;

const visibleBlocks = computed(() => draftBlocks.value.filter(block => block.text.trim()));
const comparableBlocks = computed(() => draftBlocks.value.filter(block => block.mode === "variable" && block.id !== selectedRuleBlock.value?.id));
const selectedDocument = computed(() => props.documents.find(doc => doc.id === props.selectedDocumentId) ?? null);
const previewZoom = computed<number | null>(() => previewZoomMode.value === "fit" ? null : Number(previewZoomMode.value));

function changePreviewZoom(delta: number) {
  const currentZoom = previewZoom.value ?? 100;
  previewZoomMode.value = String(Math.min(200, Math.max(25, currentZoom + delta)));
}

function setCurrent(value: DocumentTemplate | null) {
  current.value = value;
  draftName.value = value?.name ?? "";
  draftCheckPage.value = value?.config.check_page ?? true;
  draftBlocks.value = value ? structuredClone(value.config.blocks) : [];
  requirementDialog.value = false;
  selectedRuleBlock.value = null;
  focusTemplate.value = null;
}

function openRequirements(block: TemplateBlock) {
  block.rules ??= [];
  selectedRuleBlock.value = block;
  requirementText.value = block.requirement_text ?? "";
  unsupportedRequirements.value = block.unsupported_requirements ?? [];
  requirementDialog.value = true;
}

function onRequirementInput(value: string) {
  const block = selectedRuleBlock.value;
  if (!block || value === (block.requirement_text ?? "")) return;
  block.requirement_text = value;
  block.rules = [];
  block.unsupported_requirements = value.trim() ? [value.trim()] : [];
  unsupportedRequirements.value = block.unsupported_requirements;
}
function clearUnsupported() {
  if (!selectedRuleBlock.value) return;
  selectedRuleBlock.value.unsupported_requirements = [];
  unsupportedRequirements.value = [];
}

function resetRuleParameters(rule: TemplateFieldRule) {
  rule.min_value = null; rule.max_value = null;
  rule.min_length = null; rule.max_length = null;
  rule.options = []; rule.text = ""; rule.other_block_id = "";
  rule.replacement_text = "";
}

function setRuleOptions(rule: TemplateFieldRule, value: string) {
  rule.options = value.split(/[、，,|]/).map(item => item.trim()).filter(Boolean);
}

async function parseRequirements() {
  if (!selectedRuleBlock.value || !requirementText.value.trim()) return;
  draftingRequirements.value = true;
  try {
    const response = await templateAuditApi.draftRequirements(requirementText.value.trim());
    unsupportedRequirements.value = response.data.unsupported;
    selectedRuleBlock.value.requirement_text = requirementText.value.trim();
    selectedRuleBlock.value.unsupported_requirements = response.data.unsupported;
    if (response.data.required !== null) selectedRuleBlock.value.required = response.data.required;
    selectedRuleBlock.value.rules = response.data.rules;
    if (response.data.rules.length) {
      ElMessage.success(`生成 ${response.data.rules.length} 条规则草案，请核对后发布`);
    } else if (response.data.required !== null) ElMessage.success("已将此字段设为必填，请核对后发布");
    else ElMessage.warning("没有可执行的规则，请修改表述或手动新增规则");
  } catch (error) { ElMessage.error(errorText(error)); }
  finally { draftingRequirements.value = false; }
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
  reviews.value=[]; review.value=null;
  const workspaceId = props.workspaceId;
  const documentId = props.selectedDocumentId;
  if (workspaceId == null || documentId == null) { reviews.value = []; review.value = null; return; }
  const response = await templateAuditApi.reviews(workspaceId, documentId);
  if (generation !== reviewGeneration) return;
  reviews.value = response.data;
  hasMoreReviews.value=response.data.length===50;
  review.value = response.data[0] ?? null;
}
async function onPickTemplate(file: UploadFile) {
  if (!file.raw || props.workspaceId == null || mutationBusy.value) return;
  const valid=context(); const workspaceId=props.workspaceId; ++templateGeneration;
  uploading.value = true;
  try {
    const defaultName = file.name.replace(/\.docx$/i, "");
    const { value } = await ElMessageBox.prompt("请输入模板名称", "上传模板版本", { inputValue: defaultName, inputPattern: /\S+/, inputErrorMessage: "名称不能为空" });
    if(!valid())return;
    const response = await templateAuditApi.upload(workspaceId, file.raw, value.trim());
    if(!valid())return;
    setCurrent(response.data);
    const listed = await templateAuditApi.versions(workspaceId);
    if(!valid())return;
    versions.value=listed.data;
    ElMessage.success(`模板版本 ${response.data.version} 已上传，请确认区域用途后保存`);
  } catch (error) {
    if (error !== "cancel" && error !== "close") ElMessage.error(errorText(error));
  } finally { uploading.value = false; }
}
async function saveConfiguration() {
  if (!current.value || props.workspaceId == null || mutationBusy.value) return;
  const valid=context();
  for (const block of draftBlocks.value) {
    if (block.rules?.length && block.mode !== "variable") { ElMessage.error(`${block.label}不是可变字段，不能设置填写要求`); return; }
    for (const rule of block.rules ?? []) {
      if ((rule.kind === "length" || rule.kind === "chinese_length") && rule.min_length == null && rule.max_length == null ||
          rule.kind === "number_range" && rule.min_value == null && rule.max_value == null ||
          rule.kind === "allowed_values" && !(rule.options?.length) ||
          (rule.kind === "contains" || rule.kind === "exact_text" || rule.kind === "forbidden_value" || rule.kind === "number_with_unit") && !rule.text?.trim() ||
          rule.kind === "same_as" && !rule.other_block_id) {
        ElMessage.error(`${block.label}有未填写完整的规则`); return;
      }
    }
  }
  const unreviewed = draftBlocks.value.filter(block => block.recognition_confidence === "low" && !block.recognition_confirmed &&
    current.value?.config.blocks.some(original => original.id === block.id && original.label === block.label && original.mode === block.mode));
  if (unreviewed.length) { ElMessage.error(`还有 ${unreviewed.length} 个低置信度字段未核对，请修改字段名称或勾选“已核对”`); return; }
  if (!valid()) return;
  ++templateGeneration;
  saving.value = true;
  try {
    const response = await templateAuditApi.update(props.workspaceId, draftName.value.trim(), draftCheckPage.value, draftBlocks.value, current.value.id);
    if(!valid())return;
    setCurrent(response.data);
    versions.value = [response.data, ...versions.value.filter(item => item.id !== response.data.id).map(item=>({...item,is_active:false,is_review_active:false}))];
    ElMessage.success("模板配置已保存并发布");
  } catch (error) { ElMessage.error(errorText(error)); } finally { saving.value = false; }
}
async function reanalyzeFields() {
  if (!current.value || props.workspaceId == null || mutationBusy.value) return;
  const valid=context(); const workspaceId=props.workspaceId; ++templateGeneration;
  try {
    await ElMessageBox.confirm("将使用最新识别逻辑重新区分字段名和样例数据，当前尚未保存的配置会被重置；已保存的填写要求会尽量按区域沿用，并标记待核对。继续吗？", "重新识别表单字段", {
      type: "warning", confirmButtonText: "重新识别", cancelButtonText: "取消",
    });
  } catch { return; }
  if(!valid())return;
  reanalyzing.value = true;
  try {
    const response = await templateAuditApi.reanalyze(workspaceId);
    if(!valid())return;
    setCurrent(response.data);
    versions.value = [response.data, ...versions.value.filter(item => item.id !== response.data.id)];
    ElMessage.success("字段已重新识别，请确认配置后保存并发布");
  } catch (error) { ElMessage.error(errorText(error)); } finally { reanalyzing.value = false; }
}
async function activateVersion(id: number) {
  if (props.workspaceId == null || id === current.value?.id || mutationBusy.value) return;
  const valid=context(); const workspaceId=props.workspaceId; ++templateGeneration;
  activating.value=true;
  try {
    await ElMessageBox.confirm("切换后，该版本会成为工作区当前模板。继续吗？", "切换模板版本");
    if(!valid())return;
    const response = await templateAuditApi.activate(workspaceId, id);
    if(!valid())return;
    setCurrent(response.data);
    const listed = await templateAuditApi.versions(workspaceId);
    if(!valid())return;
    versions.value=listed.data;
    ElMessage.success(`已切换到模板版本 ${response.data.version}`);
  } catch (error) { if (error !== "cancel" && error !== "close" && valid()) ElMessage.error(errorText(error)); } finally {activating.value=false;}
}
async function runReview() {
  if (props.workspaceId == null || props.selectedDocumentId == null || reviewing.value) return;
  if (aiEnabled.value && !aiFieldIds.value.length) { ElMessage.warning("请先选择需要 DeepSeek 审查的字段，或关闭 AI 建议"); return; }
  const valid=context(props.selectedDocumentId); ++reviewGeneration;
  reviewing.value = true;
  try {
    const response = await templateAuditApi.run(props.workspaceId, props.selectedDocumentId, aiEnabled.value ? aiFieldIds.value : []);
    if(!valid())return;
    reviews.value = [response.data, ...reviews.value];
    review.value = response.data;
    ElMessage.success(response.data.compliant ? "表单模板审查通过" : `发现 ${response.data.total} 项模板差异`);
    if (response.data.ai_review && response.data.ai_review.status !== "completed") ElMessage.warning(response.data.ai_review.summary);
  } catch (error) { ElMessage.error(errorText(error)); } finally { reviewing.value = false; }
}
function selectReview(id: number) { review.value = reviews.value.find(item => item.id === id) ?? null; }
async function exportCurrent() {
  const selected = review.value;
  if (!selected || exportingId.value != null) return;
  const valid = context(selected.document_id);
  exportingId.value = selected.id;
  try {
    const response = await reportApi.template(selected.id);
    if (!valid() || review.value?.id !== selected.id) return;
    downloadBlob(response.data, `${(selectedDocument.value?.filename ?? "文档.docx").replace(/\.docx$/i, "")}_表单模板审查报告.docx`);
  } catch (cause) { if (valid()) ElMessage.error(await downloadErrorText(cause)); }
  finally { exportingId.value = null; }
}
async function loadMoreReviews(){
  if(props.workspaceId==null || props.selectedDocumentId==null || !reviews.value.length || moreLoading.value || reviewing.value)return;
  const valid=context(props.selectedDocumentId);const generation=reviewGeneration;moreLoading.value=true;
  try{const response=await templateAuditApi.reviews(props.workspaceId,props.selectedDocumentId,Math.min(...reviews.value.map(item=>item.id)));if(!valid() || generation!==reviewGeneration)return;reviews.value=[...new Map([...reviews.value,...response.data].map(item=>[item.id,item])).values()];hasMoreReviews.value=response.data.length===50;}
  catch(error){if(valid())ElMessage.error(errorText(error));}finally{moreLoading.value=false;}
}
async function deleteReview() {
  if (!review.value) return;
  const id = review.value.id;
  const valid=context(props.selectedDocumentId);
  try { await ElMessageBox.confirm("确认删除这条表单模板审查记录？", "删除审查记录", { type: "warning" }); }
  catch { return; }
  try {
    await templateAuditApi.removeReview(id);
    if(!valid())return;
    emit("clear-review", id);
    reviews.value = reviews.value.filter(item => item.id !== id);
    review.value = reviews.value[0] ?? null;
    ElMessage.success("表单模板审查记录已删除");
  } catch (error) { ElMessage.error(errorText(error)); }
}
function locateIssue(issue: TemplateIssue) {
  focusTemplate.value = null; focusDocument.value = null;
  window.setTimeout(() => {
    focusTemplate.value = issue.template_content_index;
    focusDocument.value = issue.document_content_index;
  }, 0);
}
function locateAiSuggestion(item: { template_content_index: number | null; document_content_index: number | null }) {
  focusTemplate.value = null; focusDocument.value = null;
  window.setTimeout(() => {
    focusTemplate.value = item.template_content_index;
    focusDocument.value = item.document_content_index;
  }, 0);
}
function aiFieldLabel(blockId: string) {
  const blocks = comparisonTemplate.value?.config.blocks ?? [];
  const block = blocks.find(item => item.id === blockId);
  return block?.label || block?.location || "所选字段";
}
function isAccepted(index: number) { return !!review.value && props.acceptedFixes.some(fix => fix.review_id === review.value!.id && fix.issue_index === index); }
function toggleFormat(index: number, accepted: boolean) {
  if (!review.value) return;
  if (accepted) emit("accept", { review_id: review.value.id, issue_index: index, replacement_text: null });
  else emit("reject", review.value.id, index);
}
async function acceptText(index: number, issue: TemplateIssue) {
  if (!review.value) return;
  const valid=context(props.selectedDocumentId); const reviewId=review.value.id;
  const existing = props.acceptedFixes.find(fix => fix.review_id === review.value!.id && fix.issue_index === index)?.replacement_text;
  try {
    const { value } = await ElMessageBox.prompt("请输入仅用于替换问题原文的具体内容", "确认模板修订", {
      inputValue: existing || issue.recommended_replacement || "",
      inputPattern: /\S+/, inputErrorMessage: "替换内容不能为空",
      confirmButtonText: "接纳", cancelButtonText: "取消",
    });
    if(valid() && review.value?.id===reviewId) emit("accept", { review_id: reviewId, issue_index: index, replacement_text: value });
  } catch { /* 用户取消 */ }
}
function display(value: unknown) {
  if (value == null || value === "") return "（无）";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
function formatTime(value: string) { return new Date(/[Zz]|[+-]\d{2}:\d{2}$/.test(value)?value:value+'Z').toLocaleString("zh-CN"); }

watch(() => review.value, async (value) => {
  historyTemplate.value=null;
  if(!value || value.template_snapshot)return;
  const valid=context(props.selectedDocumentId);
  try {const response=await templateAuditApi.get(value.template_id);if(valid() && review.value?.id===value.id)historyTemplate.value=response.data;} catch { /* 无法加载时不展示其他版本 */ }
});

watch(() => props.workspaceId, async () => {
  workspaceEpoch++; templateGeneration++; reviewGeneration++; setCurrent(null); versions.value=[];
  aiEnabled.value = false; aiFieldIds.value = [];
  reviews.value = []; review.value = null;
  try { await loadTemplate(); await loadReviews(); } catch (error) { ElMessage.error(errorText(error)); }
}, { immediate: true, flush:'sync' });
watch(() => props.selectedDocumentId, async () => {
  focusDocument.value = null;
  try { await loadReviews(); } catch (error) { ElMessage.error(errorText(error)); }
});
watch(() => publishedTemplate.value?.id, () => {
  const allowed = new Set(aiOptions.value.map(block => block.id));
  aiFieldIds.value = aiFieldIds.value.filter(id => allowed.has(id));
});
</script>

<style scoped>
.template-audit{display:grid;gap:18px}.toolbar,.review-toolbar,.meta-row,.history-row{display:flex;align-items:center;gap:12px}.toolbar,.review-toolbar{justify-content:space-between}.toolbar h2,.review-toolbar h2{margin:0;color:#243552;font-size:17px}.toolbar p,.review-toolbar p{margin:4px 0 0;color:#8793a7;font-size:12px}.meta-row{flex-wrap:wrap;padding:14px;border:1px solid #e5eaf3;border-radius:9px;background:#fafbfe}.meta-row .el-input{max-width:390px}.version-select{width:260px}.config-table small{display:block;margin-top:4px;color:#98a3b6}.config-table .uncertain,.uncertain{color:#c47b28}.text-link{padding:0;border:0;color:#405a9f;background:none;text-align:left;cursor:pointer}.requirement-help{color:#65738a;font-size:12px;line-height:1.6}.draft-actions{display:flex;align-items:center;gap:10px;margin:10px 0}.draft-actions span{font-size:12px}.requirement-rule{display:flex;align-items:center;gap:8px;margin:8px 0}.requirement-rule .el-input{flex:1;min-width:0}.requirement-rule .el-input-number{width:125px}.review-toolbar{padding-top:8px;border-top:1px solid #edf0f5}.review-toolbar .el-select{width:260px;margin-left:auto}.comparison{display:grid;grid-template-columns:1fr 1fr;gap:14px}.preview-column{min-width:0;border:1px solid #e5eaf3;border-radius:10px;overflow:hidden}.column-title{padding:10px 14px;color:#495a78;background:#f5f7fb;font-size:12px;font-weight:700}.preview-column :deep(.preview),.preview-column :deep(.placeholder){min-height:480px}.preview-column :deep(.doc-wrap){height:min(62vh,620px);min-height:480px;border:0;border-radius:0}.preview-controls{display:flex;align-items:center;justify-content:center;gap:8px;padding:10px 14px;border:1px solid #e5eaf3;border-radius:9px;color:#65738a;background:#f8faff;font-size:12px}.preview-controls .el-select{width:120px}.preview-controls small{margin-left:8px;color:#8b96a9}.history-row{padding:10px 12px;border-radius:8px;background:#f7f9fc;color:#65738a;font-size:12px}.history-row .el-select{width:330px}.issues{display:grid;gap:10px}.issue-card{padding:14px;border:1px solid #e7ebf3;border-radius:10px;background:#fff}.issue-head{display:flex;align-items:center;gap:10px}.issue-head strong{margin-right:auto;color:#31415e;font-size:13px}.diff{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:11px}.diff span{padding:10px;border-radius:7px;color:#56657e;background:#f7f9fc;font-size:12px;overflow-wrap:anywhere}.diff b{display:block;margin-bottom:4px;color:#8995a9;font-size:10px}.recommend{padding:9px 11px;margin:9px 0 0;border-left:3px solid #65bd8c;color:#376c50;background:#f0faf5;font-size:12px}.manual-note{margin:9px 0 0;color:#a17045;font-size:12px}@media(max-width:900px){.comparison{grid-template-columns:1fr}.toolbar,.review-toolbar{align-items:stretch;flex-direction:column}.review-toolbar .el-select{width:100%;margin-left:0}.preview-controls{flex-wrap:wrap}.preview-controls small{width:100%;margin-left:0;text-align:center}.requirement-rule{flex-wrap:wrap}.diff{grid-template-columns:1fr}}
.ai-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 12px 14px; border: 1px solid #e5eaf3; border-radius: 9px; background: #fafbfe; }
.draft-actions { flex-wrap: wrap; }
.draft-actions .uncertain { min-width: 0; overflow-wrap: anywhere; }
.ai-controls .el-select { min-width: 260px; max-width: 440px; flex: 1; }
.ai-controls small { color: #7d8aa0; line-height: 1.5; }
.ai-results { display: grid; gap: 10px; padding-top: 8px; border-top: 1px solid #e5eaf3; }
.ai-results h3 { margin: 0; color: #31415e; font-size: 16px; }
.ai-results h3 small { color: #8793a7; font-size: 12px; font-weight: 400; }
</style>
