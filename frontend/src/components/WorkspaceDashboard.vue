<template>
  <section class="dashboard">
    <header class="dashboard-head">
      <div><p class="eyebrow">WORKSPACE OVERVIEW</p><h3>工作区审查概览</h3><p>按每份文档的最新一次审查结果汇总。</p></div>
      <el-button type="primary" plain :disabled="documents.length === 0 || rules.length === 0" @click="emit('batch')">批量审查</el-button>
    </header>
    <div class="metrics">
      <div><span>文档总数</span><b>{{ documents.length }}</b><small>{{ reviewedCount }} 份已审查</small></div>
      <div><span>规则数量</span><b>{{ rules.length }}</b><small>可复用的格式规范</small></div>
      <div><span>最新通过</span><b :class="passedCount === reviewedCount && reviewedCount ? 'pass' : ''">{{ passedCount }}</b><small>在 {{ reviewedCount }} 份已审中</small></div>
      <div><span>待处理问题</span><b :class="violationTotal ? 'issue' : 'pass'">{{ violationTotal }}</b><small>来自最新审查记录</small></div>
    </div>
    <div class="content-grid">
      <div class="panel">
        <div class="panel-head"><h4>文档状态</h4><span>{{ pendingDocuments.length }} 份待审</span></div>
        <el-empty v-if="documents.length === 0" description="上传文档后将在此显示状态" :image-size="58" />
        <ul v-else class="status-list">
          <li v-for="document in documentStatuses" :key="document.id">
            <span class="status-mark" :class="document.status">{{ mark(document.status) }}</span>
            <span class="item-name" :title="document.filename">{{ document.filename }}</span>
            <span v-if="document.check" class="item-detail">{{ document.check.summary.compliant ? "通过" : `${document.check.summary.total} 项问题` }}</span>
            <span v-else class="item-detail">尚未审查</span>
            <el-button v-if="document.check" link type="primary" size="small" @click="emit('select', document.check)">查看</el-button>
          </li>
        </ul>
      </div>
      <div class="panel">
        <div class="panel-head"><h4>问题分布</h4><span>最新审查</span></div>
        <el-empty v-if="!categoryRows.length" description="审查后显示问题类别" :image-size="58" />
        <div v-else class="category-list">
          <div v-for="item in categoryRows" :key="item.category" class="category-row">
            <span>{{ categoryLabel(item.category) }}</span><div class="bar"><i :style="{ width: `${item.percent}%` }" /></div><b>{{ item.count }}</b>
          </div>
        </div>
        <div class="tip"><b>提示：</b>{{ tipText }}</div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { CheckItem, DocumentItem, RuleItem } from "@/types";

const props = defineProps<{ documents: DocumentItem[]; rules: RuleItem[]; checks: CheckItem[] }>();
const emit = defineEmits<{ (e: "select", check: CheckItem): void; (e: "batch"): void }>();

const latestChecks = computed(() => {
  const sorted = [...props.checks].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  const result = new Map<number, CheckItem>();
  for (const check of sorted) if (!result.has(check.document_id)) result.set(check.document_id, check);
  return result;
});
const documentStatuses = computed(() => props.documents.map((document) => {
  const check = latestChecks.value.get(document.id);
  return { ...document, check, status: !check ? "pending" : check.summary.compliant ? "pass" : "issue" };
}));
const reviewedCount = computed(() => latestChecks.value.size);
const passedCount = computed(() => [...latestChecks.value.values()].filter((check) => check.summary.compliant).length);
const pendingDocuments = computed(() => documentStatuses.value.filter((document) => document.status === "pending"));
const violationTotal = computed(() => [...latestChecks.value.values()].reduce((total, check) => total + check.summary.total, 0));
const categoryRows = computed(() => {
  const totals: Record<string, number> = {};
  for (const check of latestChecks.value.values()) for (const [category, count] of Object.entries(check.summary.by_category)) totals[category] = (totals[category] ?? 0) + count;
  const highest = Math.max(...Object.values(totals), 1);
  return Object.entries(totals).sort((a, b) => b[1] - a[1]).map(([category, count]) => ({ category, count, percent: count / highest * 100 }));
});
const tipText = computed(() => !props.documents.length ? "请先上传 Word 文档并选择规则。" : !props.rules.length ? "创建或套用一套规则后即可开始审查。" : !reviewedCount.value ? "选择规则后使用批量审查，可快速建立基线。" : violationTotal.value ? "优先处理数量最多的问题类别，可最快提升整体合规率。" : "所有已审查文档均符合其最新应用的规则。" );
function categoryLabel(category: string) { return ({ font: "字体", paragraph: "段落", page: "页面", heading_structure: "标题结构" } as Record<string, string>)[category] ?? category; }
function mark(status: string) { return status === "pass" ? "✓" : status === "issue" ? "!" : "·"; }
</script>

<style scoped>
.dashboard { min-height: 480px; padding: 4px 1px; }.dashboard-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 8px 2px 21px; }.eyebrow { margin: 0 0 4px; color: #6b7ea8; font-size: 10px; font-weight: 800; letter-spacing: .12em; }h3 { margin: 0; color: #16213b; font-size: 18px; }.dashboard-head p:not(.eyebrow) { margin: 7px 0 0; color: #8290a8; font-size: 13px; }.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }.metrics > div,.panel { border: 1px solid #e7ecf5; border-radius: 11px; background: #fbfcff; }.metrics > div { display: grid; gap: 4px; padding: 15px; }.metrics span,.metrics small,.panel-head > span { color: #8b98ad; font-size: 11px; }.metrics b { color: #30415f; font-size: 24px; }.pass { color: #149269 !important; }.issue { color: #db6645 !important; }.content-grid { display: grid; grid-template-columns: 1.15fr .85fr; gap: 13px; margin-top: 14px; }.panel { min-height: 235px; padding: 15px; }.panel-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }.panel-head h4 { margin: 0; color: #33435f; font-size: 14px; }.status-list { display: grid; max-height: 260px; margin: 0; padding: 0; overflow-y: auto; list-style: none; }.status-list li { display: flex; align-items: center; min-width: 0; gap: 8px; padding: 10px 3px; border-bottom: 1px solid #edf1f6; }.status-mark { display: grid; place-items: center; width: 21px; height: 21px; flex: 0 0 auto; border-radius: 50%; color: #708098; background: #eef1f6; font-size: 12px; font-weight: 800; }.status-mark.pass { background: #e1f6ee; }.status-mark.issue { background: #fff0eb; }.item-name { overflow: hidden; color: #4b5b74; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.item-detail { margin-left: auto; color: #98a4b6; font-size: 11px; white-space: nowrap; }.category-list { display: grid; gap: 14px; padding: 12px 2px; }.category-row { display: grid; grid-template-columns: 62px 1fr 28px; align-items: center; gap: 8px; color: #64738b; font-size: 12px; }.bar { height: 7px; overflow: hidden; border-radius: 10px; background: #edf1f8; }.bar i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg,#7890f4,#526ddb); }.category-row b { color: #40506a; text-align: right; }.tip { margin-top: 25px; padding: 10px; border-radius: 8px; color: #728098; background: #f3f6fc; font-size: 12px; line-height: 1.6; }.tip b { color: #536bca; }@media (max-width: 760px) { .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }.content-grid { grid-template-columns: 1fr; }.dashboard-head { display: block; }.dashboard-head > .el-button { margin-top: 13px; } }
</style>
