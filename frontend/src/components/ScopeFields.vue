<template>
  <div class="fields">
    <label>中文字体<el-input v-model="value.font!.name" clearable placeholder="不限制" /></label>
    <label>西文字体<el-input v-model="value.font!.ascii_name" clearable placeholder="不限制" /></label>
    <label>字号（pt）<el-input-number v-model="value.font!.size" :min="1" :max="400" controls-position="right" /></label>
    <label v-for="field in booleanFields" :key="field.key">{{ field.label }}<el-select v-model="value.font![field.key]" clearable placeholder="不限制"><el-option label="是" :value="true" /><el-option label="否" :value="false" /></el-select></label>
    <label>颜色（RGB）<el-input v-model="value.font!.color" clearable placeholder="如 000000；留空不限制" /></label>
    <label>对齐方式<el-select v-model="value.paragraph!.alignment" clearable placeholder="不限制"><el-option v-for="a in alignments" :key="a.value" :label="a.label" :value="a.value" /></el-select></label>
    <label>行距类型<el-select v-model="value.paragraph!.line_spacing_kind"><el-option label="倍数" value="multiple" /><el-option label="固定值（pt）" value="exact" /><el-option label="最小值（pt）" value="atLeast" /></el-select></label>
    <label>行距<el-input-number v-model="value.paragraph!.line_spacing" :min="0.1" :max="1000" :step="0.1" controls-position="right" /></label>
    <label v-for="field in spacingFields" :key="field.key">{{ field.label }}<el-input-number v-model="value.paragraph![field.key]" :min="field.key === 'first_line_indent_chars' ? -100 : 0" :max="2000" :step="0.5" controls-position="right" /></label>
    <label v-for="field in listFields" :key="field.key">{{ field.label }}<el-select v-model="value.paragraph![field.key]" clearable placeholder="不限制"><el-option label="是" :value="true" /><el-option label="否" :value="false" /></el-select></label>
  </div>
</template>
<script setup lang="ts">
import type { ScopeRule } from '@/types';
defineProps<{ value: ScopeRule }>();
const booleanFields = [{key:'bold',label:'加粗'},{key:'italic',label:'斜体'}] as const;
const spacingFields = [{key:'space_before',label:'段前（pt）'},{key:'space_after',label:'段后（pt）'},{key:'first_line_indent_chars',label:'首行缩进（字符）'}] as const;
const listFields = [{key:'numbered',label:'自动编号'},{key:'bullet',label:'项目符号'}] as const;
const alignments = [{value:'left',label:'左对齐'},{value:'center',label:'居中'},{value:'right',label:'右对齐'},{value:'justify',label:'两端对齐'}];
</script>
<style scoped>.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:16px 0}.fields label{display:grid;gap:6px;color:#65738a;font-size:12px}.fields :deep(.el-input-number){width:100%}</style>
