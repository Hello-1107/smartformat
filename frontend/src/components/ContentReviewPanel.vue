<template>
  <section class="content-review">
    <header>
      <div><h3>AI 内容审查</h3><p>{{ document?.filename ?? '请先选择文档' }}</p></div>
      <div class="header-actions"><el-button :disabled="!current || running" :loading="exportingId === current?.id" @click="exportCurrent">导出当前内容审查报告 DOCX</el-button>
      <el-button type="primary" :disabled="!document || historyLoading" :loading="running" @click="run">用 DeepSeek 审查内容</el-button></div>
    </header>
    <p class="notice">点击审查将把{{ document?.file_type === 'pdf' ? 'PDF 提取或识别的文字' : '正文和表格文字' }}发送给 DeepSeek，检查措辞、语法、逻辑与一致性。建议需人工确认，不自动修改原文。<span v-if="document?.file_type === 'pdf'">扫描件识别可能有误，点击建议后请核对对应页原件；PDF 建议仅供人工处理，不生成修订副本。</span></p>
    <el-checkbox v-model="chunked" :disabled="running">长文分段审查（最多 60000 字符，将产生多次模型请求；跨段复核基于节选）</el-checkbox>
    <el-input v-model="instructions" type="textarea" :rows="2" maxlength="1000" show-word-limit :disabled="running" placeholder="可选：补充审查重点，例如：关注前后数据是否矛盾、表达是否适合学术论文。" />
    <p class="scope">范围：{{ document?.file_type === 'pdf' ? 'PDF 可提取或本地 OCR 识别的文字；图片含义、版式与无法识别的细节不审查。' : '正文与表格；不含页眉页脚、图片、文本框和已删除修订。' }}{{ chunked ? '分段模式最多 60000 字符、3000 个非空段落。' : '单次最多 30000 字符、1500 个非空段落。' }}最多列出 50 条建议。</p>
    <el-alert v-if="running" :title="chunked ? '正在分段审查并复核节选，可能需要数分钟。' : '正在审查，请稍候，最长约两分钟。'" type="info" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-if="history.length" class="history">
      <span>审查历史</span>
      <el-select v-model="selectedId" :disabled="running" aria-label="内容审查历史">
        <el-option v-for="item in history" :key="item.id" :value="item.id" :label="date(item.created_at) + ' · ' + item.issues.length + ' 条建议'" />
      </el-select>
      <el-button link type="danger" :disabled="running || !current" @click="removeCurrent">删除本次</el-button>
      <el-button v-if="hasMore" link :loading="historyLoading" :disabled="running" @click="loadMore">加载更早记录</el-button>
    </div>
    <div v-if="current" class="result">
      <h4>发现 {{ current.issues.length }} 条修改建议</h4>
      <p>{{ current.summary }}</p>
      <p class="scope">已审查 {{ current.paragraph_count }} 个非空段落 · {{ current.model }}<span v-if="current.instructions"> · 审查重点：{{ current.instructions }}</span></p>
      <el-empty v-if="!current.issues.length" description="本次未发现明显问题；AI 审查结果不代表内容完全正确。" :image-size="60" />
      <article v-for="(issue, index) in current.issues" :key="index" class="issue">
        <div class="issue-head">
          <el-tag :type="issue.severity === '重要' ? 'danger' : issue.severity === '一般' ? 'warning' : 'info'" size="small">{{ issue.severity }}</el-tag>
          <span>{{ issue.category }}</span>
          <el-button link type="primary" @click="emit('locate', current.document_id, issue.paragraph_index)">定位原文 · {{ locationLabel(issue.paragraph_index) }} →</el-button>
          <template v-if="document?.file_type !== 'pdf'"><el-tag v-if="acceptedFix(index)" type="success" size="small">已接纳</el-tag>
          <el-button v-if="acceptedFix(index)" link type="danger" @click="emit('reject', current.id, index)">取消接纳</el-button>
          <el-button v-else link type="success" @click="acceptIssue(issue, index)">接纳并修订</el-button></template>
        </div>
        <button class="quote" type="button" title="点击定位到原文段落" @click="emit('locate', current.document_id, issue.paragraph_index)">{{ issue.quote }}</button>
        <button v-for="reference in issue.related_references" :key="`${reference.paragraph_index}-${reference.quote}`" class="quote" @click="emit('locate', current.document_id, reference.paragraph_index)">关联依据 · {{ locationLabel(reference.paragraph_index) }}：{{ reference.quote }}</button>
        <p><b>问题：</b>{{ issue.reason }}</p>
        <p class="suggestion"><b>建议：</b>{{ issue.suggestion }}</p>
        <p v-if="replacementCandidate(issue)" class="recommended"><b>推荐修订文本：</b>{{ replacementCandidate(issue) }}</p>
        <p v-if="acceptedFix(index)" class="accepted"><b>确认替换为：</b>{{ acceptedFix(index)?.replacement_text }}</p>
      </article>
    </div>
    <el-empty v-else-if="!running && !historyLoading && !error" description="选择文档后开始内容审查，无需格式规则。" :image-size="70" />
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ElMessage } from "element-plus/es/components/message/index";
import { ElMessageBox } from "element-plus/es/components/message-box/index";
import { contentReviewApi, reportApi } from "@/api";
import { errText } from "@/api/http";
import { downloadBlob, downloadErrorText } from "@/utils/download";
import type { ContentIssue, ContentRepairFix, ContentReview, DocumentItem } from "@/types";

const props = withDefaults(defineProps<{ workspaceId: number | null; document: DocumentItem | null; acceptedFixes?: ContentRepairFix[] }>(), { acceptedFixes: () => [] });
const emit = defineEmits<{
  (e: "locate", documentId: number, paragraphIndex: number): void;
  (e: "accept", fix: ContentRepairFix): void;
  (e: "reject", reviewId: number, issueIndex: number): void;
  (e: "clear-review", reviewId: number): void;
}>();
const instructions = ref(""); const history = ref<ContentReview[]>([]);
const chunked = ref(false);
const selectedId = ref<number | null>(null); const running = ref(false);
const historyLoading = ref(false); const error = ref("");
const hasMore=ref(false);
const current = computed(() => history.value.find(item => item.id === selectedId.value) ?? null);
const exportingId = ref<number | null>(null);
let generation = 0;

async function exportCurrent() {
  const selected = current.value;
  if (!selected || exportingId.value != null) return;
  const request = generation;
  exportingId.value = selected.id;
  try {
    const response = await reportApi.content(selected.id);
    if (request !== generation || current.value?.id !== selected.id) return;
    downloadBlob(response.data, `${(props.document?.filename ?? "文档").replace(/\.(docx|pdf)$/i, "")}_内容审查报告.docx`);
  } catch (cause) { if (request === generation) ElMessage.error(await downloadErrorText(cause)); }
  finally { exportingId.value = null; }
}

watch([() => props.workspaceId, () => props.document?.id], async () => {
  const request = ++generation;
  chunked.value=false;
  history.value = []; selectedId.value = null; running.value = false; error.value = ""; instructions.value = "";
  const workspaceId = props.workspaceId; const documentId = props.document?.id;
  historyLoading.value = false;
  if (workspaceId == null || documentId == null) return;
  historyLoading.value = true;
  try {
    const response = await contentReviewApi.list(workspaceId, documentId);
    if (request !== generation) return;
    history.value = [...new Map([...history.value, ...response.data].map(item => [item.id, item])).values()].sort((a,b) => b.id-a.id);
    hasMore.value=response.data.length===50;
    if (selectedId.value == null) selectedId.value = history.value[0]?.id ?? null;
  } catch (e) { if (request === generation) error.value = errText(e); }
  finally { if (request === generation) historyLoading.value = false; }
}, { immediate: true, flush: 'sync' });

async function run(): Promise<boolean> {
  if (props.workspaceId == null || !props.document || running.value) return false;
  const request = generation;
  running.value = true; error.value = "";
  try {
    const response = await contentReviewApi.run(props.workspaceId, props.document.id, instructions.value.trim(), chunked.value);
    if (request !== generation) return false;
    history.value = [response.data, ...history.value];
    selectedId.value = response.data.id;
    return true;
  } catch (e) {
    if (request === generation) error.value = errText(e);
    return false;
  }
  finally { if (request === generation) running.value = false; }
}
async function removeCurrent() {
  const item = current.value;
  if (!item || running.value) return;
  try {
    await ElMessageBox.confirm("删除后无法恢复，确认删除本次内容审查记录？", "删除审查记录", {
      type: "warning", confirmButtonText: "删除", cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  const request = generation;
  try {
    await contentReviewApi.remove(item.id);
    if (request !== generation) return;
    emit("clear-review", item.id);
    history.value = history.value.filter(review => review.id !== item.id);
    selectedId.value = history.value[0]?.id ?? null;
    ElMessage.success("内容审查记录已删除");
  } catch (e) {
    if (request === generation) error.value = errText(e);
  }
}
async function loadMore(){
  if(props.workspaceId==null || !props.document || historyLoading.value || running.value || !history.value.length)return;
  const request=generation;historyLoading.value=true;
  try{const response=await contentReviewApi.list(props.workspaceId,props.document.id,Math.min(...history.value.map(item=>item.id)));if(request!==generation)return;history.value=[...new Map([...history.value,...response.data].map(item=>[item.id,item])).values()].sort((a,b)=>b.id-a.id);hasMore.value=response.data.length===50;}
  catch(e){if(request===generation)error.value=errText(e);}finally{if(request===generation)historyLoading.value=false;}
}
function acceptedFix(issueIndex: number): ContentRepairFix | undefined {
  return props.acceptedFixes.find(fix => fix.review_id === current.value?.id && fix.issue_index === issueIndex);
}
function locationLabel(index: number): string {
  if (props.document?.file_type === 'pdf') return `第 ${props.document.pdf_page_map?.[index] ?? '?'} 页`;
  return `段落 ${index + 1}`;
}
function replacementCandidate(issue: ContentIssue): string | null {
  const explicit = issue.recommended_replacement?.trim();
  if (explicit) return explicit;
  // 兼容旧历史：只取“改为/替换为”之后引号中的目标文本。
  // 无法确定时留空，绝不把整段说明复制进 Word。
  const afterChange = issue.suggestion.split(/改为|改成|修改为|更正为|替换为|调整为/, 2)[1];
  if (!afterChange) return null;
  const match = afterChange.match(/[“"「]([^”"」]{1,300})[”"」]/);
  return match?.[1].trim() || null;
}
async function acceptIssue(issue: ContentIssue, issueIndex: number) {
  const review = current.value;
  const request = generation;
  if (!review) return;
  try {
    const { value } = await ElMessageBox.prompt(
      "请确认将替换原文引用的具体文本。系统只会按此处确认的文本生成副本，不会再次调用 AI。",
      "接纳内容建议",
      {
        inputValue: replacementCandidate(issue) ?? "",
        inputType: "textarea",
        inputPlaceholder: "请输入要替换原文引用的具体文本",
        inputValidator: (value) => value.trim() ? true : "替换文本不能为空",
        confirmButtonText: "确认接纳",
        cancelButtonText: "取消",
      },
    );
    if (request === generation && current.value?.id === review.id) emit("accept", { review_id: review.id, issue_index: issueIndex, replacement_text: value.trim() });
  } catch {
    // 用户取消时不改变接纳状态。
  }
}
onBeforeUnmount(() => { generation++; });
defineExpose({ run, running });
function date(value: string) {
  return new Date(/[Zz]|[+-]\d{2}:\d{2}$/.test(value) ? value : value + "Z").toLocaleString("zh-CN");
}
</script>

<style scoped>
.header-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.content-review{min-height:480px;color:#34445f}header,.history,.issue-head{display:flex;align-items:center;gap:12px;justify-content:space-between}h3{margin:0;font-size:19px}header p{margin:6px 0;font-size:13px;word-break:break-all}.notice{color:#65738c;line-height:1.8;font-size:13px}.scope{color:#7e8b9f;font-size:12px;line-height:1.7}.history{justify-content:flex-start;margin:20px 0;font-size:13px}.history .el-select{width:300px;max-width:100%}.result>p{white-space:pre-wrap;line-height:1.7}.issue{margin:16px 0;padding:16px;border:1px solid #e4eaf4;border-radius:10px}.issue-head{justify-content:flex-start;font-size:13px}.issue-head .el-button{margin-left:auto}.issue-head .el-tag~.el-button{margin-left:0}.quote{display:block;width:100%;text-align:left;white-space:pre-wrap;overflow-wrap:anywhere;border:0;border-left:3px solid #6b85df;background:#f3f6fd;color:#3c507d;padding:12px;margin-top:12px;cursor:pointer;font:inherit;font-size:14px;line-height:1.7}.quote:hover{background:#eaf0ff}.issue p{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:1.8}.suggestion{padding:12px;border-radius:8px;background:#f0f9f5}.recommended{padding:10px 12px;border-radius:8px;border:1px solid #cfe0ff;background:#f2f6ff;color:#36528f}.accepted{padding:10px 12px;border-radius:8px;background:#eef9f3;color:#276a50}.el-alert{margin-top:12px}@media(max-width:760px){header,.history{align-items:flex-start;flex-direction:column}.issue-head{flex-wrap:wrap}}
</style>
