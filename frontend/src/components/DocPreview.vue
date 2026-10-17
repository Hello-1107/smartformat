<template>
  <div class="preview">
    <div v-if="documentId == null" class="placeholder">请先在左侧选择一份文档</div>
    <div v-else v-loading="loading" class="doc-wrap" :class="{ 'fit-mode': fitWidth }">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-button v-if="error" @click="render">重新加载预览</el-button>
      <el-alert v-if="locateError" :title="locateError" type="warning" :closable="false" />
      <div ref="container" class="doc-container" :class="{ 'fit-width': fitWidth }"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { renderAsync } from "docx-preview";
import http from "@/api/http";

const props = withDefaults(defineProps<{
  documentId: number | null;
  focusParagraph?: number | null;
  focusKind?: "format" | "content" | "template";
  previewUrl?: string;
  active?: boolean;
  fitWidth?: boolean;
  zoomPercent?: number | null;
}>(), { focusKind: "format", active: true, fitWidth: false, zoomPercent: null });
const container = ref<HTMLElement | null>(null);
const loading = ref(false); const error = ref(""); const locateError = ref("");
let renderRequest = 0;
let loadedDocument: number | null = null;
let controller: AbortController | null = null;
let resizeObserver: ResizeObserver | null = null;

function applyFitWidth() {
  const el = container.value;
  if (!el) return;
  el.style.removeProperty("--doc-fit-scale");
  if (props.zoomPercent != null) {
    const scale = Math.min(2, Math.max(0.25, props.zoomPercent / 100));
    el.style.setProperty("--doc-fit-scale", String(scale));
    return;
  }
  if (!props.fitWidth) return;
  const pages = Array.from(el.querySelectorAll<HTMLElement>("section.docx"));
  if (!pages.length) return;
  const pageWidth = Math.max(...pages.map(page => page.offsetWidth));
  if (!pageWidth) return;
  // 两侧预览只缩小、不放大；预留边距后让整张页面完整落在当前栏内。
  const availableWidth = Math.max(1, el.clientWidth - 24);
  el.style.setProperty("--doc-fit-scale", String(Math.min(1, availableWidth / pageWidth)));
}

async function render() {
  const request = ++renderRequest;
  controller?.abort();
  controller = new AbortController();
  const signal = controller.signal;
  const documentId = props.documentId;
  loadedDocument = null; error.value = ""; locateError.value = "";
  loading.value = documentId != null;
  await nextTick();
  const el = container.value;
  if (!el || documentId == null || request !== renderRequest) return;
  el.replaceChildren();
  try {
    const response = await http.get(props.previewUrl || "/documents/" + documentId + "/preview", { responseType: "blob", signal });
    if (request !== renderRequest) return;
    // 每次请求使用独立容器，过期的异步渲染不能覆盖当前文档。
    const stage = document.createElement("div");
    await renderAsync(response.data as Blob, stage, undefined, { useBase64URL: true });
    if (request !== renderRequest) return;
    el.replaceChildren(...Array.from(stage.childNodes));
    loadedDocument = documentId;
    applyFitWidth();
  } catch {
    if (request !== renderRequest) return;
    error.value = "预览加载失败，请确认后端已重启、文档存在，然后重试。";
  } finally {
    if (request === renderRequest) {
      loading.value = false;
      await locate();
    }
  }
}

async function locate() {
  await nextTick();
  if (!props.active || props.focusParagraph == null || loading.value || loadedDocument !== props.documentId) return;
  const el = container.value;
  if (!el) return;
  // 书签来自 Word XML 中的原始段落；表格、页眉和分页不会改变编号。
  const anchor = el.querySelector<HTMLElement>('[id="sf_' + props.focusKind + '_' + props.focusParagraph + '"]');
  const target = anchor?.closest("p") ?? anchor;
  el.querySelectorAll(".is-focused").forEach(node => node.classList.remove("is-focused"));
  if (!target) {
    locateError.value = "当前预览无法显示该段落，可能包含不受支持的 Word 对象。请结合报告原文检查文档。";
    return;
  }
  locateError.value = "";
  target.classList.add("is-focused");
  if (target.isConnected && target.getClientRects().length) {
    target.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}
onMounted(() => {
  resizeObserver = new ResizeObserver(() => applyFitWidth());
  if (container.value) resizeObserver.observe(container.value);
  void render();
});
watch(() => [props.documentId, props.previewUrl], () => { void render(); });
watch(() => [props.focusParagraph, props.focusKind, props.active], () => { void locate(); }, { flush: "post" });
watch(() => [props.fitWidth, props.zoomPercent], async () => { await nextTick(); applyFitWidth(); });
onBeforeUnmount(() => { renderRequest++; controller?.abort(); resizeObserver?.disconnect(); });
</script>

<style scoped>
.preview{min-height:480px}.placeholder{min-height:480px;display:flex;align-items:center;justify-content:center;color:#909399}.doc-wrap{min-height:480px;overflow:auto;background:#fff;border:1px solid #ebeef5;border-radius:4px;padding:16px}.doc-wrap.fit-mode{overflow:auto}.doc-container{background:#fff}.doc-container.fit-width :deep(.docx-wrapper){width:max-content;min-width:100%;box-sizing:border-box;padding:12px!important}.doc-container.fit-width :deep(section.docx){zoom:var(--doc-fit-scale,1)}.doc-container :deep(.is-focused){background:#fff3bd!important;border-radius:3px;outline:2px solid #f4c84b;outline-offset:2px;scroll-margin:40px}.el-alert{margin-bottom:12px}
</style>
