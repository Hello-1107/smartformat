<template>
  <section class="history">
    <div class="history-head">
      <div>
        <p class="eyebrow">RECENT ACTIVITY</p>
        <h3>审查历史</h3>
      </div>
      <span>{{ checks.length }} 条记录</span>
    </div>
    <el-empty v-if="checks.length === 0" description="完成审查后，记录会显示在这里" :image-size="56" />
    <div v-else class="history-list">
      <div v-for="item in checks.slice(0, 8)" :key="item.id" class="history-item" :class="{ active: item.id === activeId }">
        <button class="history-select" type="button" @click="$emit('select', item)">
          <span class="result-mark" :class="item.summary.compliant ? 'pass' : 'issue'">{{ item.summary.compliant ? '✓' : '!' }}</span>
          <span class="history-info"><b>{{ item.summary.compliant ? '审查通过' : `${item.summary.total} 项待修正` }}</b><small>{{ date(item.created_at) }}</small></span>
          <span class="arrow">›</span>
        </button>
        <el-button class="delete-button" link type="danger" size="small" title="删除此审查记录" @click="$emit('delete', item)">删除</el-button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { CheckItem } from "@/types";
defineProps<{ checks: CheckItem[]; activeId: number | null }>();
defineEmits<{ (e: "select", check: CheckItem): void; (e: "delete", check: CheckItem): void }>();
function date(value: string) { return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); }
</script>

<style scoped>
.history { height: 100%; }
.history-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.eyebrow { margin: 0 0 3px; color: #7183a9; font-size: 10px; font-weight: 800; letter-spacing: .1em; }
h3 { margin: 0; color: #1a2945; font-size: 16px; }.history-head > span { color: #99a4b7; font-size: 12px; }
.history-list { display: grid; gap: 5px; }.history-item { display:flex; align-items:center; border-radius:8px; }.history-item:hover, .history-item.active { background: #f1f5ff; }.history-item.active { box-shadow: inset 2px 0 #4c6fff; }.history-select { width:100%; min-width:0; display: flex; align-items: center; gap: 9px; padding: 9px 2px 9px 7px; border:0; color:inherit; background:transparent; text-align:left; cursor:pointer; }.delete-button{display:none;flex:0 0 auto;margin-right:4px;font-size:11px}.history-item:hover .delete-button,.history-item.active .delete-button{display:inline-flex}
.result-mark { display: grid; place-items: center; width: 23px; height: 23px; flex: 0 0 auto; border-radius: 50%; font-weight: 800; font-size: 13px; }.pass { color: #148b65; background: #e1f6ee; }.issue { color: #d05a39; background: #fff0eb; }.history-info { min-width: 0; display: grid; gap: 2px; }.history-info b { overflow: hidden; color: #35425d; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.history-info small { color: #98a4b6; font-size: 11px; }.arrow { margin-left: auto; color: #aab5c8; font-size: 21px; line-height: 1; }
</style>
