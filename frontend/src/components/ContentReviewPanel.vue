<template>
  <section class="content-review">
    <header>
      <div><h3>AI 内容审查</h3><p>{{ document?.filename ?? '请先选择文档' }}</p></div>
      <el-button type="primary" :disabled="!document || historyLoading" :loading="running" @click="run">用 DeepSeek 审查内容</el-button>
    </header>
    <p class="notice">点击审查将把正文和表格文字发送给 DeepSeek，检查措辞、语法、逻辑与一致性。建议需人工确认，不自动修改原文。</p>
    <el-input v-model="instructions" type="textarea" :rows="2" maxlength="1000" show-word-limit :disabled="running" placeholder="可选：补充审查重点，例如：关注前后数据是否矛盾、表达是否适合学术论文。" />
    <p class="scope">范围：正文与表格；不含页眉页脚、图片、文本框和已删除修订。单次最多 30000 字符、1500 个非空段落，最多列出 50 条建议。</p>
    <el-alert v-if="running" title="正在审查，请稍候。通常需要几十秒，最长约两分钟。" type="info" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-if="history.length" class="history">
      <span>审查历史（最近 50 次）</span>
      <el-select v-model="selectedId" :disabled="running" aria-label="内容审查历史">
        <el-option v-for="item in history" :key="item.id" :value="item.id" :label="date(item.created_at) + ' · ' + item.issues.length + ' 条建议'" />
      </el-select>
      <el-button link type="danger" :disabled="running || !current" @click="removeCurrent">删除本次</el-button>
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
          <el-button link type="primary" @click="emit('locate', current.document_id, issue.paragraph_index)">定位原文 · 段落 {{ issue.paragraph_index + 1 }} →</el-button>
        </div>
        <button class="quote" type="button" title="点击定位到原文段落" @click="emit('locate', current.document_id, issue.paragraph_index)">{{ issue.quote }}</button>
        <p><b>问题：</b>{{ issue.reason }}</p>
        <p class="suggestion"><b>建议：</b>{{ issue.suggestion }}</p>
      </article>
    </div>
    <el-empty v-else-if="!running && !historyLoading && !error" description="选择文档后开始内容审查，无需格式规则。" :image-size="70" />
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { contentReviewApi } from "@/api";
import { errText } from "@/api/http";
import type { ContentReview, DocumentItem } from "@/types";

const props = defineProps<{ workspaceId: number | null; document: DocumentItem | null }>();
const emit = defineEmits<{ (e: "locate", documentId: number, paragraphIndex: number): void }>();
const instructions = ref(""); const history = ref<ContentReview[]>([]);
const selectedId = ref<number | null>(null); const running = ref(false);
const historyLoading = ref(false); const error = ref("");
const current = computed(() => history.value.find(item => item.id === selectedId.value) ?? null);
let generation = 0;

watch([() => props.workspaceId, () => props.document?.id], async () => {
  const request = ++generation;
  history.value = []; selectedId.value = null; running.value = false; error.value = ""; instructions.value = "";
  const workspaceId = props.workspaceId; const documentId = props.document?.id;
  historyLoading.value = false;
  if (workspaceId == null || documentId == null) return;
  historyLoading.value = true;
  try {
    const response = await contentReviewApi.list(workspaceId, documentId);
    if (request !== generation) return;
    history.value = response.data;
    selectedId.value = response.data[0]?.id ?? null;
  } catch (e) { if (request === generation) error.value = errText(e); }
  finally { if (request === generation) historyLoading.value = false; }
}, { immediate: true });

async function run() {
  if (props.workspaceId == null || !props.document || running.value) return;
  const request = generation;
  running.value = true; error.value = "";
  try {
    const response = await contentReviewApi.run(props.workspaceId, props.document.id, instructions.value.trim());
    if (request !== generation) return;
    history.value = [response.data, ...history.value].slice(0, 50);
    selectedId.value = response.data.id;
  } catch (e) { if (request === generation) error.value = errText(e); }
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
    history.value = history.value.filter(review => review.id !== item.id);
    selectedId.value = history.value[0]?.id ?? null;
    ElMessage.success("内容审查记录已删除");
  } catch (e) {
    if (request === generation) error.value = errText(e);
  }
}
onBeforeUnmount(() => { generation++; });
function date(value: string) {
  return new Date(/[Zz]|[+-]\d{2}:\d{2}$/.test(value) ? value : value + "Z").toLocaleString("zh-CN");
}
</script>

<style scoped>
.content-review{min-height:480px;color:#34445f}header,.history,.issue-head{display:flex;align-items:center;gap:12px;justify-content:space-between}h3{margin:0;font-size:19px}header p{margin:6px 0;font-size:13px;word-break:break-all}.notice{color:#65738c;line-height:1.8;font-size:13px}.scope{color:#7e8b9f;font-size:12px;line-height:1.7}.history{justify-content:flex-start;margin:20px 0;font-size:13px}.history .el-select{width:300px;max-width:100%}.result>p{white-space:pre-wrap;line-height:1.7}.issue{margin:16px 0;padding:16px;border:1px solid #e4eaf4;border-radius:10px}.issue-head{justify-content:flex-start;font-size:13px}.issue-head .el-button{margin-left:auto}.quote{display:block;width:100%;text-align:left;white-space:pre-wrap;overflow-wrap:anywhere;border:0;border-left:3px solid #6b85df;background:#f3f6fd;color:#3c507d;padding:12px;margin-top:12px;cursor:pointer;font:inherit;font-size:14px;line-height:1.7}.quote:hover{background:#eaf0ff}.issue p{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:1.8}.suggestion{padding:12px;border-radius:8px;background:#f0f9f5}.el-alert{margin-top:12px}@media(max-width:760px){header,.history{align-items:flex-start;flex-direction:column}.issue-head{flex-wrap:wrap}}
</style>
