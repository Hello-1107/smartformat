<template>
  <el-dialog :model-value="modelValue" title="规则版本历史" width="650px" @update:model-value="emit('update:modelValue', $event)">
    <p class="hint">每次创建、保存或恢复规则都会生成快照。恢复历史版本会再创建一个新版本，不会覆盖原有记录。</p>
    <el-skeleton v-if="loading" :rows="4" animated />
    <el-empty v-else-if="versions.length === 0" description="该规则暂没有版本记录" :image-size="58" />
    <div v-else class="versions">
      <article v-for="(revision, index) in versions" :key="revision.id" class="revision">
        <div class="revision-head"><span class="version">v{{ revision.version }}</span><b>{{ revision.name }}</b><span v-if="index === 0" class="current">当前版本</span><time>{{ date(revision.created_at) }}</time></div>
        <p>{{ summary(revision) }}</p>
        <ul v-if="changes(index).length" class="changes"><li v-for="change in changes(index)" :key="change">{{ change }}</li></ul>
        <p v-else-if="index === versions.length - 1" class="initial">初始版本</p>
        <div class="revision-actions"><span>{{ revision.natural_language }}</span><el-button v-if="index !== 0" link type="primary" :loading="restoring === revision.version" @click="restore(revision.version)">恢复此版本</el-button></div>
      </article>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { ElMessage } from "element-plus/es/components/message/index";
import { ElMessageBox } from "element-plus/es/components/message-box/index";
import { ruleApi } from "@/api";
import { errText } from "@/api/http";
import type { RuleItem, RuleRevision, RuleSet } from "@/types";

const props = defineProps<{ modelValue: boolean; rule: RuleItem | null }>();
const emit = defineEmits<{ (e: "update:modelValue", value: boolean): void; (e: "restored", rule: RuleItem): void }>();
const versions = ref<RuleRevision[]>([]); const loading = ref(false); const restoring = ref<number | null>(null);

async function load() {
  if (!props.rule) return;
  const ruleId=props.rule.id;
  loading.value = true;
  versions.value=[];
  try { const response=await ruleApi.revisions(ruleId); if(props.modelValue && props.rule?.id===ruleId)versions.value=response.data; } catch (error) { if(props.rule?.id===ruleId)ElMessage.error(errText(error)); } finally { if(props.rule?.id===ruleId)loading.value = false; }
}
async function restore(version: number) {
  if (!props.rule) return;
  const ruleId=props.rule.id;
  try {
    await ElMessageBox.confirm(`恢复至 v${version} 后会生成新的当前版本，确认继续吗？`, "恢复规则版本", { type: "warning", confirmButtonText: "恢复", cancelButtonText: "取消" });
    restoring.value = version;
    if(props.rule?.id!==ruleId || !props.modelValue)return;
    const rule = (await ruleApi.restoreRevision(ruleId, version)).data;
    if(props.rule?.id!==ruleId || !props.modelValue)return;
    emit("restored", rule); emit("update:modelValue", false); ElMessage.success(`已恢复至 v${version}`);
  } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(errText(error)); } finally { restoring.value = null; }
}
function date(value: string) { return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); }
function summary(revision: RuleRevision) { const ruleset = revision.ruleset; const parts: string[] = []; if (ruleset.body) parts.push("正文"); if (ruleset.headings && Object.keys(ruleset.headings).length) parts.push("标题"); if (ruleset.page) parts.push("页面"); if (ruleset.heading_structure) parts.push("标题结构"); if(ruleset.template_regions?.length)parts.push(`${ruleset.template_regions.length} 个模板章节`); if(ruleset.template_checks)parts.push("目录图表与代码"); return parts.length ? `包含：${parts.join("、")}规则` : "未设置格式约束"; }
function changes(index: number) {
  const current=versions.value[index]?.ruleset;const previous=versions.value[index+1]?.ruleset;
  if(!current || !previous)return [];
  const result:string[]=[];const before=new Map((previous.template_regions??[]).map(item=>[item.id,item]));const after=new Map((current.template_regions??[]).map(item=>[item.id,item]));
  for(const [id,region] of after){const old=before.get(id);if(!old)result.push(`新增模板章节：${region.label}`);else if(JSON.stringify(region)!==JSON.stringify(old))result.push(`调整模板章节：${region.label}`);}
  for(const [id,region] of before)if(!after.has(id))result.push(`移除模板章节：${region.label}`);
  const checkLabels:Record<string,string>={check_toc:'目录校验',check_figure_numbering:'图片题注编号',check_table_numbering:'表格题注编号',check_code_style:'代码块样式'};
  for(const [key,label] of Object.entries(checkLabels)){const field=key as keyof NonNullable<RuleSet['template_checks']>;if(Boolean(current.template_checks?.[field])!==Boolean(previous.template_checks?.[field]))result.push(`${Boolean(current.template_checks?.[field])?'启用':'关闭'}${label}`);}
  if(JSON.stringify(current.page)!==JSON.stringify(previous.page))result.push('调整页面规则');
  if(JSON.stringify(current.body)!==JSON.stringify(previous.body) || JSON.stringify(current.headings)!==JSON.stringify(previous.headings))result.push('调整通用正文或标题规则');
  return result.slice(0,12);
}
watch(() => [props.modelValue, props.rule?.id], ([visible]) => { if (visible) void load(); }, { immediate: true });
</script>

<style scoped>
.hint { margin: -8px 0 17px; color: #74829a; font-size: 13px; line-height: 1.65; }.versions { display: grid; max-height: 480px; overflow-y: auto; border-top: 1px solid #edf1f6; }.revision { padding: 13px 3px; border-bottom: 1px solid #edf1f6; }.revision-head,.revision-actions { display: flex; align-items: center; gap: 8px; }.revision-head b { color: #3b4b65; font-size: 13px; }.version { padding: 2px 6px; border-radius: 5px; color: #526bd0; background: #eaf0ff; font-size: 11px; font-weight: 800; }.current { padding: 2px 6px; border-radius: 10px; color: #168d66; background: #e6f7ef; font-size: 10px; }.revision time { margin-left: auto; color: #9aa6b7; font-size: 11px; }.revision p { margin: 8px 0; color: #708098; font-size: 12px; }.changes{display:flex;flex-wrap:wrap;gap:5px 14px;margin:7px 0;padding:8px 10px;border-radius:7px;color:#586981;background:#f7f9fc;font-size:11px;list-style-position:inside}.initial{color:#9aa6b7!important}.revision-actions > span { overflow: hidden; color: #9aa6b7; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.revision-actions > .el-button { margin-left: auto; flex: 0 0 auto; }
</style>
