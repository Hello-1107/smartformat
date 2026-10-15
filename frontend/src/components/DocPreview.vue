<template>
  <div class="preview">
    <div v-if="!documentId" class="placeholder">请先在左侧选择一份文档</div>
    <div v-else v-loading="loading" class="doc-wrap">
      <div ref="container" class="doc-container"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import { renderAsync } from "docx-preview";
import http from "@/api/http";

const props = defineProps<{ documentId: number | null; focusParagraph?: number | null }>();

const container = ref<HTMLElement | null>(null);
const loading = ref(false);

async function render() {
  const el = container.value;
  if (!props.documentId || !el) return;
  loading.value = true;
  try {
    const resp = await http.get(`/documents/${props.documentId}/download`, {
      responseType: "blob",
    });
    el.innerHTML = "";
    await renderAsync(resp.data as Blob, el);
    // docx-preview 会将 Word 段落渲染为 p；记录序号后可由审查报告联动定位。
    el.querySelectorAll("p").forEach((paragraph, index) => {
      paragraph.setAttribute("data-paragraph-index", String(index));
    });
  } catch (e) {
    el.innerHTML = "";
    el.textContent = "预览失败，请确认文档存在";
    console.error(e);
  } finally {
    loading.value = false;
  }
}

watch(() => props.documentId, render, { immediate: true });
watch(
  () => props.focusParagraph,
  async (index) => {
    if (index == null || !container.value) return;
    await nextTick();
    const target = container.value.querySelector<HTMLElement>(`[data-paragraph-index="${index}"]`);
    if (!target) return;
    container.value.querySelectorAll(".is-focused").forEach((node) => node.classList.remove("is-focused"));
    target.classList.add("is-focused");
    target.scrollIntoView({ behavior: "smooth", block: "center" });
  }
);
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
