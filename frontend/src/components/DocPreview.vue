<template>
  <div class="preview">
    <div v-if="!documentId" class="placeholder">请先在左侧选择一份文档</div>
    <div v-else v-loading="loading" class="doc-wrap">
      <div ref="container" class="doc-container"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";
import { renderAsync } from "docx-preview";
import http from "@/api/http";

const props = defineProps<{ documentId: number | null; focusParagraph?: number | null }>();

const container = ref<HTMLElement | null>(null);
const loading = ref(false);
let renderRequest = 0;

async function render() {
  const documentId = props.documentId;
  if (!documentId) {
    renderRequest += 1;
    loading.value = false;
    return;
  }
  // documentId 变化会切换 v-if；等容器实际挂载后再读取 ref，避免首次预览空白。
  await nextTick();
  const el = container.value;
  if (!el || documentId !== props.documentId) return;
  const requestId = ++renderRequest;
  loading.value = true;
  try {
    const resp = await http.get(`/documents/${documentId}/download`, {
      responseType: "blob",
    });
    if (requestId !== renderRequest || documentId !== props.documentId) return;
    el.innerHTML = "";
    await renderAsync(resp.data as Blob, el);
    if (requestId !== renderRequest || documentId !== props.documentId) return;
    // docx-preview 会将 Word 段落渲染为 p；记录序号后可由审查报告联动定位。
    el.querySelectorAll("p").forEach((paragraph, index) => {
      paragraph.setAttribute("data-paragraph-index", String(index));
    });
    // 报告可能在文档尚未渲染完时先发出定位请求；渲染完成后再补一次定位。
    if (props.focusParagraph != null) await focusParagraph(props.focusParagraph);
  } catch (e) {
    if (requestId !== renderRequest) return;
    el.innerHTML = "";
    el.textContent = "预览失败，请确认文档存在";
    console.error(e);
  } finally {
    if (requestId === renderRequest) loading.value = false;
  }
}

// 首次挂载和之后切换文档都要渲染：仅 immediate watch 会早于 ref 挂载而直接返回。
onMounted(() => { void render(); });
watch(() => props.documentId, () => { void render(); });

async function focusParagraph(index: number) {
  await nextTick();
  const el = container.value;
  if (!el) return;
  const target = el.querySelector<HTMLElement>(`[data-paragraph-index="${index}"]`);
  if (!target) return;
  el.querySelectorAll(".is-focused").forEach((node) => node.classList.remove("is-focused"));
  target.classList.add("is-focused");
  target.scrollIntoView({ behavior: "smooth", block: "center" });
}

watch(() => props.focusParagraph, (index) => {
  if (index != null) void focusParagraph(index);
});
</script>

<style scoped>
.preview {
  height: 100%;
  min-height: 480px;
}
.placeholder {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #909399;
}
.doc-wrap {
  height: 100%;
  overflow-y: auto;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 16px;
}
.doc-container {
  background: #fff;
}
.doc-container :deep(.is-focused) {
  background: #fff3bd !important;
  border-radius: 3px;
  outline: 2px solid #f4c84b;
  outline-offset: 2px;
  transition: background .2s ease;
}
</style>
