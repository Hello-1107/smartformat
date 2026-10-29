<template>
  <el-dialog :model-value="!!extraction" class="template-candidates-dialog" title="确认文本模板的候选样式" width="min(850px, 95vw)" @close="emit('cancel')">
    <p>{{ hasRegions ? '确认模板章节的用途与检查范围；保存后将按章节锚点映射待审文档。' : '为每类段落选择一个完整样式；确认后载入规则草稿，点击“创建规则”保存。' }}</p>
    <el-alert v-for="warning in extraction?.warnings" :key="warning" :title="warning" type="warning" :closable="false" />
    <section v-if="hasRegions" class="region-config">
      <div class="region-heading"><h3>模板结构</h3><small>固定章节检查标题文字；可变章节只按顺序和层级映射；忽略区域不参与审查。</small></div>
      <article v-for="region in regionDrafts" :key="region.id" class="region-card">
        <div class="region-main">
          <el-tag size="small" effect="plain">{{ region.level === 0 ? '大标题' : `${region.level} 级标题` }}</el-tag>
          <div><strong>{{ region.label }}</strong><small>模板段落 {{ region.template_paragraph_index + 1 }}{{ region.body_style ? ' · 已识别章节正文样式' : '' }}</small></div>
        </div>
        <div class="region-options">
          <el-select v-model="region.mode" aria-label="区域用途">
            <el-option label="固定章节" value="fixed" />
            <el-option label="可变章节" value="variable" />
            <el-option label="忽略区域" value="ignore" />
          </el-select>
          <el-checkbox v-model="region.required" :disabled="region.mode === 'ignore'">必须存在</el-checkbox>
          <el-checkbox v-model="region.check_format" :disabled="region.mode === 'ignore'">检查格式</el-checkbox>
        </div>
      </article>
    </section>
    <section v-if="documentChecks" class="document-checks">
      <div><h3>文档级检查</h3><small>从模板中识别目录、题注和代码块；可关闭不适用于当前任务的项目。</small></div>
      <el-checkbox v-model="documentChecks.check_toc">目录与正文标题一致<span v-if="documentChecks.toc_entries.length">（{{ documentChecks.toc_entries.length }} 项）</span></el-checkbox>
      <el-checkbox v-model="documentChecks.check_figure_numbering">图片题注编号连续</el-checkbox>
      <el-checkbox v-model="documentChecks.check_table_numbering">表格题注编号连续</el-checkbox>
      <el-checkbox v-model="documentChecks.check_code_style">识别代码块并检查代码样式</el-checkbox>
    </section>
    <section v-for="(candidates, scope) in (hasRegions ? {} : extraction?.candidates)" :key="scope">
      <h3>{{ label(String(scope)) }}</h3>
      <el-radio-group v-model="choices[scope]" class="candidates">
        <el-radio v-for="candidate in candidates" :key="candidate.id" :value="candidate.id" border>
          <article class="candidate-card">
            <strong>{{ describe(candidate) }}</strong>
            <small>{{ candidate.count }} 段 · 原文段落 {{ candidate.paragraph_indexes.map(i => i + 1).join('、') }}</small>
            <p class="candidate-example">{{ candidate.examples.join(' / ') }}</p>
            <ul v-if="details(candidate).length" class="style-details" aria-label="样式详情">
              <li v-for="item in details(candidate)" :key="item.label"><span>{{ item.label }}</span>{{ item.value }}</li>
            </ul>
          </article>
        </el-radio>
      </el-radio-group>
    </section>
    <template #footer><el-button @click="emit('cancel')">取消</el-button><el-button type="primary" :disabled="!complete" @click="confirm">确认并编辑规则</el-button></template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, ref, watch, toRaw } from 'vue';
import type { TemplateDocumentChecks, TemplateExtraction, RuleSet, StyleCandidate, TemplateRegionRule } from '@/types';
const props = defineProps<{ extraction: TemplateExtraction | null }>();
const emit = defineEmits<{ (e: 'cancel'): void; (e: 'confirm', ruleset: RuleSet): void }>();
const choices = ref<Record<string, string>>({});
const regionDrafts = ref<TemplateRegionRule[]>([]);
const documentChecks = ref<TemplateDocumentChecks | null>(null);
watch(() => props.extraction, value => {
  choices.value = {};
  regionDrafts.value = structuredClone(toRaw(value?.regions ?? []));
  documentChecks.value = structuredClone(toRaw(value?.ruleset.template_checks ?? null));
}, { immediate: true });
const hasRegions = computed(() => regionDrafts.value.length > 0);
const hasDocumentChecks = computed(() => !!documentChecks.value && !!(
  documentChecks.value.check_toc || documentChecks.value.check_figure_numbering
  || documentChecks.value.check_table_numbering || documentChecks.value.check_code_style
));
const complete = computed(() => !!props.extraction && (hasRegions.value
  ? regionDrafts.value.some(region => region.mode !== 'ignore' && (region.required || region.check_format)) || hasDocumentChecks.value
  : Object.keys(props.extraction.candidates).every(key => choices.value[key])));
function label(scope: string) { return scope === 'title' ? '大标题' : scope === 'body' ? '正文' : `${scope.slice(1)} 级标题`; }
const alignmentLabels: Record<string, string> = { left: '左对齐', center: '居中', right: '右对齐', justify: '两端对齐' };
const lineSpacingLabels: Record<string, string> = { multiple: '倍', exact: '固定值', atLeast: '最小值' };
function describe(c: StyleCandidate) {
  const f = c.style.font; const p = c.style.paragraph;
  return [f?.name, f?.ascii_name, f?.size ? `${f.size}pt` : '字号未解析', f?.bold === true ? '加粗' : f?.bold === false ? '不加粗' : '', p?.alignment ? alignmentLabels[p.alignment] ?? p.alignment : '', p?.line_spacing != null ? `行距 ${p.line_spacing} ${lineSpacingLabels[p.line_spacing_kind ?? 'multiple'] ?? ''}` : ''].filter(Boolean).join(' · ');
}
function details(c: StyleCandidate) {
  const p = c.style.paragraph;
  if (!p) return [];
  return [
    p.space_before != null ? { label: '段前', value: `${p.space_before} 磅` } : null,
    p.space_after != null ? { label: '段后', value: `${p.space_after} 磅` } : null,
    p.first_line_indent_chars != null ? { label: '首行缩进', value: `${p.first_line_indent_chars} 字符` } : null,
    p.numbered === true ? { label: '编号', value: '是' } : p.bullet === true ? { label: '项目符号', value: '是' } : null,
  ].filter((item): item is { label: string; value: string } => item !== null);
}
function confirm() {
  if (!props.extraction || !complete.value) return;
  const result = structuredClone(toRaw(props.extraction.ruleset));
  result.template_checks = structuredClone(toRaw(documentChecks.value));
  if (hasRegions.value) {
    result.template_regions = structuredClone(toRaw(regionDrafts.value));
    emit('confirm', result);
    return;
  }
  for (const [scope, candidates] of Object.entries(props.extraction.candidates)) {
    const selected = candidates.find(c => c.id === choices.value[scope]);
    if (!selected) return;
    const style = structuredClone(toRaw(selected.style));
    if (scope === 'body' || scope === 'title') result[scope] = style;
    else { result.headings ??= {}; result.headings[scope] = style; }
  }
  emit('confirm', result);
}
</script>
<style scoped>
.template-candidates-dialog :deep(.el-dialog__body){max-height:min(62vh,680px);overflow-y:auto}
section{margin:20px 0}.candidates{display:grid;width:100%;gap:10px}.candidates :deep(.el-radio){align-items:flex-start;box-sizing:border-box;height:auto;min-height:72px;width:100%;margin:0;padding:14px}.candidates :deep(.el-radio__input){flex:0 0 auto;margin-top:3px}.candidates :deep(.el-radio__label){display:block;min-width:0;flex:1;padding-left:12px;white-space:normal}.candidate-card{min-width:0}.candidate-card strong{display:block;color:#303133;font-size:17px;line-height:1.45}.candidates small{display:block;margin-top:5px;color:#8491a5}.candidate-example{margin:7px 0 0;line-height:1.55;overflow-wrap:anywhere}.style-details{display:flex;flex-wrap:wrap;gap:6px 12px;margin:9px 0 0;padding:0;list-style:none;color:#606266;font-size:13px}.style-details li{white-space:nowrap}.style-details span{margin-right:4px;color:#909399}.el-alert{margin:8px 0}
.region-heading{display:flex;align-items:baseline;justify-content:space-between;gap:16px}.region-heading h3{margin:0}.region-heading small{color:#8491a5}.region-config{display:grid;gap:10px}.region-card{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:13px 14px;border:1px solid #dfe5ef;border-radius:9px;background:#fbfcff}.region-main,.region-options{display:flex;align-items:center;gap:10px}.region-main{min-width:0}.region-main>div{min-width:0}.region-main strong,.region-main small{display:block}.region-main strong{overflow:hidden;color:#303133;text-overflow:ellipsis;white-space:nowrap}.region-main small{margin-top:4px;color:#8491a5}.region-options{flex:0 0 auto}.region-options .el-select{width:116px}@media(max-width:760px){.region-card{align-items:stretch;flex-direction:column}.region-options{flex-wrap:wrap}.region-main strong{white-space:normal}}
.document-checks{display:flex;align-items:center;flex-wrap:wrap;gap:10px 20px;padding:14px;border:1px solid #dfe5ef;border-radius:9px;background:#f8faff}.document-checks>div{width:100%}.document-checks h3{margin:0 0 3px}.document-checks small{color:#8491a5}
</style>
