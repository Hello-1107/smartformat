<template>
  <div class="pdf-preview">
    <el-empty v-if="documentId == null" description="请先选择 PDF 文档" />
    <el-alert v-else-if="error" :title="error" type="error" :closable="false" />
    <div v-else v-loading="loading" class="frame-wrap">
      <p v-if="focusPage">定位到 PDF 第 {{ focusPage }} 页；请对照报告中的原文引用核实。</p>
      <iframe v-if="url" :key="`${documentId}-${focusPage}`" :src="url + '#page=' + (focusPage || 1)" title="PDF 文档预览" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import http from "@/api/http";

const props = defineProps<{ documentId: number | null; focusPage?: number | null; active?: boolean }>();
const url = ref(""); const loading = ref(false); const error = ref("");
let request = 0; let controller: AbortController | null = null;
function release() { if (url.value) URL.revokeObjectURL(url.value); url.value = ""; }
async function load() {
  const current = ++request;
  controller?.abort(); controller = new AbortController(); release(); error.value = "";
  if (props.documentId == null || !props.active) return;
  loading.value = true;
  try {
    const response = await http.get(`/documents/${props.documentId}/preview`, { responseType: "blob", signal: controller.signal });
    if (current === request) url.value = URL.createObjectURL(response.data as Blob);
  } catch { if (current === request) error.value = "PDF 预览加载失败，请重试或下载原件查看。"; }
  finally { if (current === request) loading.value = false; }
}
watch(() => [props.documentId, props.active], load, { immediate: true });
onBeforeUnmount(() => { request++; controller?.abort(); release(); });
</script>

<style scoped>
.pdf-preview{min-height:520px}.frame-wrap{min-height:520px}.frame-wrap p{color:#64738b;font-size:12px}.frame-wrap iframe{width:100%;height:70vh;min-height:520px;border:1px solid #e8edf5;border-radius:8px}
</style>
