<template>
  <el-dialog :model-value="!!extraction" title="确认文本模板的候选样式" width="min(850px, 95vw)" @close="emit('cancel')">
    <p>为每类段落选择一个完整样式；确认后载入规则草稿，点击“创建规则”保存。</p>
    <el-alert v-for="warning in extraction?.warnings" :key="warning" :title="warning" type="warning" :closable="false" />
    <section v-for="(candidates, scope) in extraction?.candidates" :key="scope">
      <h3>{{ label(String(scope)) }}</h3>
      <el-radio-group v-model="choices[scope]" class="candidates">
        <el-radio v-for="candidate in candidates" :key="candidate.id" :value="candidate.id" border>
          <div><strong>{{ describe(candidate) }}</strong><small>{{ candidate.count }} 段 · 原文段落 {{ candidate.paragraph_indexes.map(i => i + 1).join('、') }}</small><p>{{ candidate.examples.join(' / ') }}</p><small>{{ JSON.stringify(candidate.style) }}</small></div>
        </el-radio>
      </el-radio-group>
    </section>
    <template #footer><el-button @click="emit('cancel')">取消</el-button><el-button type="primary" :disabled="!complete" @click="confirm">确认并编辑规则</el-button></template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, ref, watch, toRaw } from 'vue';
import type { TemplateExtraction, RuleSet, StyleCandidate } from '@/types';
const props = defineProps<{ extraction: TemplateExtraction | null }>();
const emit = defineEmits<{ (e: 'cancel'): void; (e: 'confirm', ruleset: RuleSet): void }>();
const choices = ref<Record<string, string>>({});
watch(() => props.extraction, () => { choices.value = {}; });
const complete = computed(() => !!props.extraction && Object.keys(props.extraction.candidates).every(key => choices.value[key]));
function label(scope: string) { return scope === 'title' ? '大标题' : scope === 'body' ? '正文' : `${scope.slice(1)} 级标题`; }
function describe(c: StyleCandidate) {
  const f = c.style.font; const p = c.style.paragraph;
  return [f?.name, f?.ascii_name, f?.size ? `${f.size}pt` : '字号未解析', f?.bold === true ? '加粗' : f?.bold === false ? '不加粗' : '', p?.alignment, p?.line_spacing ? `行距 ${p.line_spacing} ${p.line_spacing_kind === 'multiple' ? '倍' : 'pt'}` : ''].filter(Boolean).join(' · ');
}
function confirm() {
  if (!props.extraction || !complete.value) return;
  const result = structuredClone(toRaw(props.extraction.ruleset));
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
section{margin:20px 0}.candidates{display:grid;width:100%;gap:10px}.candidates :deep(.el-radio){height:auto;min-height:72px;margin:0;padding:14px}.candidates :deep(.el-radio__label){white-space:normal}.candidates small{display:block;margin-top:5px;color:#8491a5}.candidates p{margin:6px 0;overflow-wrap:anywhere}.el-alert{margin:8px 0}
</style>
