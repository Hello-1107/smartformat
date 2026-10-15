<template>
  <div class="panel">
    <div class="panel-head">
      <div><p class="eyebrow">AI RULES</p><span class="panel-title">格式规则</span></div>
    </div>

    <el-input
      v-model="text"
      type="textarea"
      :rows="3"
      placeholder="用自然语言描述格式要求，例如：正文用宋体小四、1.5 倍行距、首行缩进 2 字符，一级标题黑体三号居中，页面 A4 上下边距 2.54cm、左右边距 3.17cm"
    />
    <el-button
      type="primary"
      class="gen-btn"
      :loading="generating"
      :disabled="!text.trim()"
      @click="emit('generate', text.trim())"
    >
      用 AI 提取规则
    </el-button>
    <div class="samples">
      <span>快速示例</span>
      <button v-for="sample in samples" :key="sample.label" type="button" @click="text = sample.text">{{ sample.label }}</button>
    </div>
    <div v-if="templates.length" class="templates">
      <span>规范模板</span>
      <el-tooltip v-for="template in templates" :key="template.id" :content="template.description || '未填写模板说明'" placement="top">
        <div class="template-item">
          <button type="button" :disabled="applyingTemplate === template.id" @click="emit('apply-template', template)">
            {{ applyingTemplate === template.id ? "创建中…" : template.name }}
          </button>
          <el-button v-if="template.source === 'workspace'" link type="danger" size="small" class="template-delete" title="删除自定义模板" @click.stop="emit('delete-template', template)">×</el-button>
        </div>
      </el-tooltip>
    </div>

    <el-empty
      v-if="rules.length === 0"
      description="暂无规则"
      :image-size="50"
    />
    <ul v-else class="list">
      <li
        v-for="r in rules"
        :key="r.id"
        class="item"
        :class="{ active: r.id === modelValue }"
        @click="$emit('update:modelValue', r.id)"
      >
        <span class="rule-name" :title="r.name">{{ r.name }}</span>
        <el-button
          link
          type="danger"
          size="small"
          @click.stop="$emit('delete', r)"
        >
          删除
        </el-button>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import type { RuleItem, RuleTemplate } from "@/types";

defineProps<{
  rules: RuleItem[];
  templates: RuleTemplate[];
  modelValue: number | null;
  generating?: boolean;
  applyingTemplate?: string | null;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", id: number): void;
  (e: "delete", rule: RuleItem): void;
  (e: "generate", text: string): void;
  (e: "apply-template", template: RuleTemplate): void;
  (e: "delete-template", template: RuleTemplate): void;
}>();

const text = ref("");
const samples = [
  { label: "毕业论文", text: "正文宋体小四、1.5 倍行距、首行缩进 2 字符；一级标题黑体三号居中；页面 A4，上下边距 2.54cm，左右边距 3.17cm" },
  { label: "商务报告", text: "正文使用微软雅黑 12 磅、两端对齐、1.5 倍行距；一级标题加粗 16 磅左对齐；A4 页面，四边距 2.54cm" },
];
</script>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
}
.panel-head {
  margin-bottom: 8px;
}
.eyebrow { margin: 0 0 2px; color: #8292b0; font-size: 9px; font-weight: 800; letter-spacing: .12em; }.panel-title { color: #22324f; font-size: 15px; font-weight: 700; }
.gen-btn {
  margin-top: 8px;
  width: 100%;
}
.samples,.templates { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; margin-top: 10px; }.samples span,.templates > span { margin-right: 2px; color: #99a5b9; font-size: 11px; }.samples button,.template-item > button { padding: 3px 7px; border: 1px solid #e1e7f2; border-radius: 12px; color: #647593; background: #fff; font-size: 11px; cursor: pointer; }.samples button:hover,.template-item > button:hover { color: #4162d4; border-color: #b9c9fa; background: #f4f7ff; }.templates { margin-top: 7px; }.template-item > button:disabled { cursor: wait; opacity: .65; }.template-item{display:inline-flex;align-items:center;gap:1px}.template-delete{padding:0 2px!important;font-size:13px!important;line-height:1}
.list {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  max-height: 220px;
  overflow-y: auto;
}
.item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px;
  border-radius: 8px;
  cursor: pointer;
}
.item:hover { background: #f3f6fc; }
.item.active {
  background: #ebf1ff;
  color: #3f63dd;
}
.rule-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
