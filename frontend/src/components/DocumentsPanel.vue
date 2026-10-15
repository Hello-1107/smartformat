<template>
  <div class="panel">
    <div class="panel-head">
      <div><p class="eyebrow">DOCUMENTS</p><span class="panel-title">文档库</span></div>
      <el-upload
        :show-file-list="false"
        :auto-upload="false"
        accept=".docx"
        :on-change="onPick"
      >
        <el-button size="small" type="primary" :loading="uploading">
          上传 .docx
        </el-button>
      </el-upload>
    </div>

    <el-empty
      v-if="documents.length === 0"
      description="暂无文档"
      :image-size="50"
    />
    <ul v-else class="list">
      <li
        v-for="d in documents"
        :key="d.id"
        class="item"
        :class="{ active: d.id === modelValue }"
        @click="$emit('update:modelValue', d.id)"
      >
        <span class="doc-badge">DOC</span>
        <span class="doc-info"><span class="doc-name" :title="d.filename">{{ d.filename }}</span><small>{{ fileSize(d.size) }} · {{ formatDate(d.created_at) }}</small></span>
        <el-button
          link
          type="danger"
          size="small"
          @click.stop="$emit('delete', d)"
        >
          删除
        </el-button>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import type { UploadFile } from "element-plus";
import type { DocumentItem } from "@/types";

defineProps<{
  documents: DocumentItem[];
  modelValue: number | null;
  uploading?: boolean;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", id: number): void;
  (e: "delete", doc: DocumentItem): void;
  (e: "upload", file: File): void;
}>();

function onPick(file: UploadFile) {
  if (file.raw) emit("upload", file.raw);
}
function fileSize(size: number) { return size < 1024 * 1024 ? `${Math.max(1, Math.round(size / 1024))} KB` : `${(size / 1024 / 1024).toFixed(1)} MB`; }
function formatDate(value: string) { return new Date(value).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" }); }
</script>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.eyebrow { margin: 0 0 2px; color: #8292b0; font-size: 9px; font-weight: 800; letter-spacing: .12em; }.panel-title { color: #22324f; font-size: 15px; font-weight: 700; }
.list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 260px;
  overflow-y: auto;
}
.item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 8px;
  border-radius: 8px;
  cursor: pointer;
}
.item:hover { background: #f3f6fc; }
.item.active {
  background: #ebf1ff;
  color: #3f63dd;
}
.doc-badge { display: grid; place-items: center; width: 29px; height: 29px; flex: 0 0 auto; border-radius: 7px; color: #4968c8; background: #eaf0ff; font-size: 9px; font-weight: 800; }.doc-info { min-width: 0; display: grid; gap: 2px; margin-right: auto; }.doc-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }.doc-info small { color: #9ba7ba; font-size: 10px; }.item.active .doc-badge { background: #dce6ff; }
</style>
