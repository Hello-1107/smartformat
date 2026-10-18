<template>
  <section class="editor">
    <header><div><small>RULE CONFIGURATION</small><h3>{{ rule ? '规则编辑器' : '新建规则' }}<span v-if="isDirty"> · 未保存</span></h3><p>大标题与一级标题分别配置；空白参数表示不限制。</p></div>
      <div class="actions"><el-button @click="emit('new')">新建规则</el-button><el-button v-if="rule" @click="emit('save-template', cleaned())">存为模板</el-button><el-button v-if="rule" @click="emit('versions')">版本历史</el-button><el-button @click="reset">还原</el-button><el-button type="primary" :loading="saving" :disabled="!form.name.trim()" @click="emit('save', cleaned())">{{ rule ? '保存规则' : '创建规则' }}</el-button></div>
    </header>
    <el-form label-position="top" :disabled="saving">
      <el-form-item label="规则名称"><el-input v-model="form.name" maxlength="200" /></el-form-item>
      <el-tabs>
        <el-tab-pane label="正文样式"><ScopeFields :value="form.body!" /></el-tab-pane>
        <el-tab-pane label="大标题"><ScopeFields :value="form.title!" /></el-tab-pane>
        <el-tab-pane label="各级标题"><div v-for="level in levels" :key="level" class="heading-card"><h4>{{ level.slice(1) }} 级标题</h4><ScopeFields :value="form.headings![level]!" /></div></el-tab-pane>
        <el-tab-pane label="页面与结构">
          <div class="grid"><label>纸张<el-select v-model="form.page!.paper" clearable placeholder="不限制"><el-option v-for="paper in ['A4','A3','A5','Letter','Legal']" :key="paper" :value="paper" /></el-select></label>
          <label v-for="field in pageFields" :key="field.key">{{ field.label }}（cm）<el-input-number v-model="form.page![field.key]" :min="0" :max="200" :step="0.1" controls-position="right" /></label>
          <label>最大标题层级<el-input-number v-model="form.heading_structure!.max_level" :min="1" :max="6" /></label>
          <label>标题必须编号<el-select v-model="form.heading_structure!.require_numbered" clearable placeholder="不限制"><el-option label="是" :value="true" /><el-option label="否" :value="false" /></el-select></label></div>
        </el-tab-pane>
      </el-tabs>
    </el-form>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, toRaw, watch } from 'vue';
import ScopeFields from './ScopeFields.vue';
import type { RuleItem, RuleSet, ScopeRule } from '@/types';
const props = defineProps<{ rule: RuleItem | null; draft?: RuleSet | null; saving?: boolean }>();
const emit = defineEmits<{(e:'new'):void;(e:'save', value:RuleSet):void;(e:'save-template',value:RuleSet):void;(e:'versions'):void}>();
const levels = ['h1','h2','h3','h4','h5','h6'];
const pageFields = [{key:'width_cm',label:'页面宽度'},{key:'height_cm',label:'页面高度'},{key:'margin_top_cm',label:'上边距'},{key:'margin_bottom_cm',label:'下边距'},{key:'margin_left_cm',label:'左边距'},{key:'margin_right_cm',label:'右边距'},{key:'header_distance_cm',label:'页眉距离'},{key:'footer_distance_cm',label:'页脚距离'}] as const;
const form = ref<RuleSet>({name:'自定义格式规则'});
const baseline = ref('');
function scope(value?: ScopeRule | null): ScopeRule {
  return {font:{name:null,ascii_name:null,size:null,bold:null,italic:null,color:null,...value?.font}, paragraph:{alignment:null,line_spacing:null,line_spacing_kind:'multiple',space_before:null,space_after:null,first_line_indent_chars:null,numbered:null,bullet:null,...value?.paragraph}};
}
function reset() {
  const source = structuredClone(toRaw(props.rule?.ruleset ?? props.draft ?? {name:'自定义格式规则'}));
  form.value = {...source,body:scope(source.body),title:scope(source.title),headings:Object.fromEntries(levels.map(level=>[level,scope(source.headings?.[level])])),page:{...source.page},heading_structure:{...source.heading_structure}};
  baseline.value = JSON.stringify(form.value);
}
function cleaned(): RuleSet {
  const value = JSON.parse(JSON.stringify(form.value), (_key, item) => item === '' ? null : item) as RuleSet;
  value.name = form.value.name.trim();
  return value;
}
const isDirty = computed(()=>JSON.stringify(form.value)!==baseline.value);
defineExpose({isDirty});
watch(()=>JSON.stringify({id:props.rule?.id,ruleset:props.rule?.ruleset,draft:props.draft}),reset,{immediate:true});
function beforeUnload(event: BeforeUnloadEvent) { if(isDirty.value){event.preventDefault();event.returnValue='';} }
onMounted(()=>window.addEventListener('beforeunload',beforeUnload));
onBeforeUnmount(()=>window.removeEventListener('beforeunload',beforeUnload));
</script>
<style scoped>
.editor{min-height:460px;color:#31415f}header{display:flex;justify-content:space-between;gap:16px;margin-bottom:20px}header small{color:#8495b0;font-size:10px}h3{margin:5px 0}h3 span{color:#c17d37;font-size:12px}header p{font-size:12px;color:#8693a8}.actions{display:flex;flex-wrap:wrap;gap:5px;align-items:start}.heading-card{padding:12px 16px;margin:12px 0;border:1px solid #e7ecf5;border-radius:10px;background:#fbfcff}.heading-card h4{margin:4px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;padding-top:16px}.grid label{display:grid;gap:6px;font-size:12px}.grid :deep(.el-input-number){width:100%}@media(max-width:760px){header{flex-direction:column}}
</style>
