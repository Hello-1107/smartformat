<template>
  <el-dialog :model-value="modelValue" title="规则版本历史" width="650px" @update:model-value="emit('update:modelValue', $event)">
    <p class="hint">每次创建、保存或恢复规则都会生成快照。恢复历史版本会再创建一个新版本，不会覆盖原有记录。</p>
    <el-skeleton v-if="loading" :rows="4" animated />
    <el-empty v-else-if="versions.length === 0" description="该规则暂没有版本记录" :image-size="58" />
    <div v-else class="versions">
      <article v-for="(revision, index) in versions" :key="revision.id" class="revision">
        <div class="revision-head"><span class="version">v{{ revision.version }}</span><b>{{ revision.name }}</b><span v-if="index === 0" class="current">当前版本</span><time>{{ date(revision.created_at) }}</time></div>
        <p>{{ summary(revision) }}</p>
        <div class="revision-actions"><span>{{ revision.natural_language }}</span><el-button v-if="index !== 0" link type="primary" :loading="restoring === revision.version" @click="restore(revision.version)">恢复此版本</el-button></div>
      </article>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { ruleApi } from "@/api";
import { errText } from "@/api/http";
import type { RuleItem, RuleRevision } from "@/types";

const props = defineProps<{ modelValue: boolean; rule: RuleItem | null }>();
const emit = defineEmits<{ (e: "update:modelValue", value: boolean): void; (e: "restored", rule: RuleItem): void }>();
const versions = ref<RuleRevision[]>([]); const loading = ref(false); const restoring = ref<number | null>(null);

async function load() {
  if (!props.rule) return;
  loading.value = true;
  try { versions.value = (await ruleApi.revisions(props.rule.id)).data; } catch (error) { ElMessage.error(errText(error)); } finally { loading.value = false; }
}
async function restore(version: number) {
  if (!props.rule) return;
  try {
    await ElMessageBox.confirm(`恢复至 v${version} 后会生成新的当前版本，确认继续吗？`, "恢复规则版本", { type: "warning", confirmButtonText: "恢复", cancelButtonText: "取消" });
    restoring.value = version;
    const rule = (await ruleApi.restoreRevision(props.rule.id, version)).data;
    emit("restored", rule); emit("update:modelValue", false); ElMessage.success(`已恢复至 v${version}`);
  } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(errText(error)); } finally { restoring.value = null; }
}
function date(value: string) { return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); }
function summary(revision: RuleRevision) { const ruleset = revision.ruleset; const parts: string[] = []; if (ruleset.body) parts.push("正文"); if (ruleset.headings && Object.keys(ruleset.headings).length) parts.push("标题"); if (ruleset.page) parts.push("页面"); if (ruleset.heading_structure) parts.push("标题结构"); return parts.length ? `包含：${parts.join("、")}规则` : "未设置格式约束"; }
watch(() => [props.modelValue, props.rule?.id], ([visible]) => { if (visible) void load(); }, { immediate: true });
</script>

<style scoped>
.hint { margin: -8px 0 17px; color: #74829a; font-size: 13px; line-height: 1.65; }.versions { display: grid; max-height: 420px; overflow-y: auto; border-top: 1px solid #edf1f6; }.revision { padding: 13px 3px; border-bottom: 1px solid #edf1f6; }.revision-head,.revision-actions { display: flex; align-items: center; gap: 8px; }.revision-head b { color: #3b4b65; font-size: 13px; }.version { padding: 2px 6px; border-radius: 5px; color: #526bd0; background: #eaf0ff; font-size: 11px; font-weight: 800; }.current { padding: 2px 6px; border-radius: 10px; color: #168d66; background: #e6f7ef; font-size: 10px; }.revision time { margin-left: auto; color: #9aa6b7; font-size: 11px; }.revision p { margin: 8px 0; color: #708098; font-size: 12px; }.revision-actions > span { overflow: hidden; color: #9aa6b7; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.revision-actions > .el-button { margin-left: auto; flex: 0 0 auto; }
</style>
