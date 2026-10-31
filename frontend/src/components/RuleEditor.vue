<template>
  <section class="editor">
    <header><div><small>RULE CONFIGURATION</small><h3>{{ rule ? '规则编辑器' : '新建规则' }}<span v-if="isDirty"> · 未保存</span></h3><p>{{ form.template_regions?.length ? '按模板章节锚点映射并分区审查；可继续调整区域用途和样式。' : '大标题与一级标题分别配置；空白参数表示不限制。' }}旧规则中的 0 仍表示明确限制；如不需要，请设为“不限制”并保存。</p></div>
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
          <label v-for="field in pageFields" :key="field.key">{{ field.label }}（cm）<el-input-number v-model="form.page![field.key]" :min="0" :max="200" :step="0.1" :value-on-clear="null" placeholder="不限制" controls-position="right" /><el-button v-if="form.page![field.key] != null" link type="primary" @click="form.page![field.key] = null">设为不限制</el-button></label>
          <label>最大标题层级<el-input-number v-model="form.heading_structure!.max_level" :min="1" :max="6" :value-on-clear="null" placeholder="不限制" /><el-button v-if="form.heading_structure!.max_level != null" link type="primary" @click="form.heading_structure!.max_level = null">设为不限制</el-button></label>
          <label>标题必须编号<el-select v-model="form.heading_structure!.require_numbered" clearable placeholder="不限制"><el-option label="是" :value="true" /><el-option label="否" :value="false" /></el-select></label></div>
        </el-tab-pane>
        <el-tab-pane v-if="form.template_regions?.length" label="模板章节">
          <div class="template-region-list">
            <article v-for="region in form.template_regions" :key="region.id" class="template-region-card">
              <div class="template-region-head">
                <div><el-tag size="small" effect="plain">{{ region.level === 0 ? '大标题' : `${region.level} 级标题` }}</el-tag><strong>{{ region.label }}</strong></div>
                <div class="template-region-options">
                  <el-select v-model="region.mode"><el-option label="固定章节" value="fixed" /><el-option label="可变章节" value="variable" /><el-option label="忽略区域" value="ignore" /></el-select>
                  <el-checkbox v-model="region.required" :disabled="region.mode === 'ignore'">必须存在</el-checkbox>
                  <el-checkbox v-model="region.check_format" :disabled="region.mode === 'ignore'">检查格式</el-checkbox>
                </div>
              </div>
              <el-collapse v-if="region.mode !== 'ignore' && region.check_format">
                <el-collapse-item title="标题格式" name="heading"><ScopeFields :value="region.heading_style!" /></el-collapse-item>
                <el-collapse-item v-if="region.body_style" title="本章节正文格式" name="body"><ScopeFields :value="region.body_style" /></el-collapse-item>
              </el-collapse>
            </article>
          </div>
        </el-tab-pane>
        <el-tab-pane v-if="form.template_checks" label="目录图表与代码">
          <div class="document-check-editor">
            <div class="document-check-options">
              <el-checkbox v-model="form.template_checks.check_toc">目录与正文标题一致</el-checkbox>
              <el-checkbox v-model="form.template_checks.check_figure_numbering">图片题注编号连续</el-checkbox>
              <el-checkbox v-model="form.template_checks.check_table_numbering">表格题注编号连续</el-checkbox>
              <el-checkbox v-model="form.template_checks.check_code_style">识别并检查代码块样式</el-checkbox>
            </div>
            <div v-if="form.template_checks.check_toc" class="toc-entries"><small>模板目录条目</small><el-tag v-for="entry in form.template_checks.toc_entries" :key="entry" effect="plain">{{ entry }}</el-tag></div>
            <el-collapse>
              <el-collapse-item v-if="form.template_checks.check_code_style && form.template_checks.code_style" title="代码块格式" name="code"><ScopeFields :value="form.template_checks.code_style" /></el-collapse-item>
              <el-collapse-item v-if="form.template_checks.check_figure_numbering && form.template_checks.figure_caption_style" title="图片题注格式" name="figure"><ScopeFields :value="form.template_checks.figure_caption_style" /></el-collapse-item>
              <el-collapse-item v-if="form.template_checks.check_table_numbering && form.template_checks.table_caption_style" title="表格题注格式" name="table"><ScopeFields :value="form.template_checks.table_caption_style" /></el-collapse-item>
            </el-collapse>
          </div>
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
  form.value = {...source,body:scope(source.body),title:scope(source.title),headings:Object.fromEntries(levels.map(level=>[level,scope(source.headings?.[level])])),page:{...source.page},heading_structure:{...source.heading_structure},template_regions:source.template_regions?.map(region=>({...region,heading_style:scope(region.heading_style),body_style:region.body_style?scope(region.body_style):null})),template_checks:source.template_checks?{...source.template_checks,code_style:source.template_checks.code_style?scope(source.template_checks.code_style):null,figure_caption_style:source.template_checks.figure_caption_style?scope(source.template_checks.figure_caption_style):null,table_caption_style:source.template_checks.table_caption_style?scope(source.template_checks.table_caption_style):null}:null};
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
.editor{min-height:460px;color:#31415f}header{display:flex;justify-content:space-between;gap:16px;margin-bottom:20px}header small{color:#8495b0;font-size:10px}h3{margin:5px 0}h3 span{color:#c17d37;font-size:12px}header p{font-size:12px;color:#8693a8}.actions{display:flex;flex-wrap:wrap;gap:5px;align-items:start}.heading-card{padding:12px 16px;margin:12px 0;border:1px solid #e7ecf5;border-radius:10px;background:#fbfcff}.heading-card h4{margin:4px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;padding-top:16px}.grid label{display:grid;gap:6px;font-size:12px}.grid :deep(.el-input-number){width:100%}.template-region-list{display:grid;gap:12px;padding-top:12px}.template-region-card{padding:14px 16px;border:1px solid #e2e8f2;border-radius:10px;background:#fbfcff}.template-region-head,.template-region-head>div,.template-region-options{display:flex;align-items:center;gap:10px}.template-region-head{justify-content:space-between}.template-region-head strong{color:#31415f}.template-region-options .el-select{width:120px}.template-region-card :deep(.el-collapse){margin-top:10px;border-bottom:0}.template-region-card :deep(.el-collapse-item__wrap){background:transparent}.template-region-card :deep(.el-collapse-item__content){padding:10px 0}.document-check-editor{display:grid;gap:16px;padding-top:14px}.document-check-options{display:flex;flex-wrap:wrap;gap:10px 20px}.toc-entries{display:flex;flex-wrap:wrap;gap:7px;padding:12px;border-radius:9px;background:#f7f9fc}.toc-entries small{width:100%;color:#8495b0}@media(max-width:760px){header{flex-direction:column}.template-region-head{align-items:stretch;flex-direction:column}.template-region-options{flex-wrap:wrap}}
</style>
