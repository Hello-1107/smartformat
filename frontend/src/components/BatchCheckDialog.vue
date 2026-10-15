<template>
  <el-dialog :model-value="modelValue" title="批量审查文档" width="560px" @update:model-value="emit('update:modelValue', $event)">
    <p class="hint">将使用「{{ rule?.name ?? '未选择规则' }}」审查已选文档。每份文档都会生成独立、可追溯的审查记录。</p>
    <div class="toolbar">
      <span>已选 {{ selectedIds.length }} / {{ documents.length }} 份</span>
      <el-button link type="primary" @click="toggleAll">{{ allSelected ? "取消全选" : "全选" }}</el-button>
    </div>
    <el-checkbox-group v-model="selectedIds" class="document-list">
      <el-checkbox v-for="document in documents" :key="document.id" :label="document.id">
        <span class="doc-name">{{ document.filename }}</span>
        <small>{{ fileSize(document.size) }}</small>
      </el-checkbox>
    </el-checkbox-group>
    <el-empty v-if="documents.length === 0" description="当前工作区没有可审查文档" :image-size="58" />
    <template #footer>
      <el-button :disabled="running" @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :disabled="!rule || selectedIds.length === 0" :loading="running" @click="emit('run', selectedIds)">
        审查 {{ selectedIds.length }} 份文档
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { DocumentItem, RuleItem } from "@/types";

const props = defineProps<{
  modelValue: boolean;
  documents: DocumentItem[];
  rule: RuleItem | null;
  running?: boolean;
}>();
const emit = defineEmits<{
  (e: "update:modelValue", value: boolean): void;
  (e: "run", documentIds: number[]): void;
}>();

const selectedIds = ref<number[]>([]);
const allSelected = computed(() => props.documents.length > 0 && selectedIds.value.length === props.documents.length);

watch(() => props.modelValue, (visible) => {
  if (visible) selectedIds.value = props.documents.map((document) => document.id);
});
watch(() => props.documents, (documents) => {
  selectedIds.value = selectedIds.value.filter((id) => documents.some((document) => document.id === id));
});

function toggleAll() {
  selectedIds.value = allSelected.value ? [] : props.documents.map((document) => document.id);
}
function fileSize(size: number) {
  return size < 1024 * 1024 ? `${Math.max(1, Math.round(size / 1024))} KB` : `${(size / 1024 / 1024).toFixed(1)} MB`;
}
</script>

<style scoped>
.hint { margin: -8px 0 17px; color: #74829a; font-size: 13px; line-height: 1.65; }.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 7px; color: #7f8ca2; font-size: 12px; }.document-list { display: grid; max-height: 310px; overflow-y: auto; border-top: 1px solid #edf1f6; }.document-list :deep(.el-checkbox) { display: flex; height: auto; min-height: 48px; margin: 0; padding: 0 5px; border-bottom: 1px solid #edf1f6; }.document-list :deep(.el-checkbox__label) { display: flex; align-items: baseline; min-width: 0; gap: 8px; }.doc-name { overflow: hidden; color: #3f4e68; text-overflow: ellipsis; white-space: nowrap; }.document-list small { color: #9aa6b8; white-space: nowrap; }
</style>
