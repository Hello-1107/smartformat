<template>
  <div class="report">
    <template v-if="check">
      <div class="report-download"><el-button :loading="exporting" @click="emit('export')">导出当前格式审查报告 DOCX</el-button></div>
      <el-alert v-if="check.summary.unknown" :title="`${check.summary.unknown} 项格式无法解析，尚不能确认合规；请人工核实。`" type="warning" :closable="false" />
      <p v-if="check.ruleset_snapshot" class="snapshot">审查依据：{{ check.ruleset_snapshot.ruleset.name }} · {{ check.ruleset_snapshot.hash.slice(0, 12) }}（执行时快照）</p>
      <div class="summary" :class="check.summary.compliant ? 'is-pass' : 'is-issue'">
        <span class="summary-icon">{{ check.summary.compliant ? "✓" : "!" }}</span>
        <div><strong>{{ check.summary.compliant ? "本次格式审查通过" : `有 ${check.summary.total} 项需要处理或核实` }}</strong><p>{{ check.summary.compliant ? "已检查的格式项符合所选规则。" : "点击下方问题可在文档预览中快速定位。" }}</p></div>
        <div class="summary-chips"><span v-for="(cnt, cat) in check.summary.by_category" :key="cat" class="chip">{{ catLabel(cat) }} {{ cnt }}</span></div>
      </div>

      <el-empty
        v-if="check.violations.length === 0"
        description="恭喜，未发现格式问题"
      />
      <div v-if="!check.summary.compliant" class="report-tools">
        <el-radio-group v-model="filter" size="small">
          <el-radio-button label="all">全部 {{ check.violations.length }}</el-radio-button>
          <el-radio-button v-for="(_, cat) in check.summary.by_category" :key="cat" :label="cat">{{ catLabel(cat) }}</el-radio-button>
        </el-radio-group>
        <span>点击行可定位段落</span>
      </div>
      <el-table
        v-if="check.violations.length > 0"
        :data="filteredViolations"
        class="violation-table"
        max-height="480"
        @row-click="locate"
      >
        <el-table-column prop="scope" label="作用域" width="110">
          <template #default="{ row }">{{ scopeLabel(row.scope) }}</template>
        </el-table-column>
        <el-table-column prop="category" label="类别" width="100">
          <template #default="{ row }">{{ catLabel(row.category) }}</template>
        </el-table-column>
        <el-table-column prop="field" label="字段" width="150" />
        <el-table-column label="期望值" width="140">
          <template #default="{ row }">{{ fmt(row.expected) }}</template>
        </el-table-column>
        <el-table-column label="实际值" width="140">
          <template #default="{ row }">{{ fmt(row.actual) }}</template>
        </el-table-column>
        <el-table-column prop="message" label="审查说明" min-width="220" />
        <el-table-column label="段落" width="90">
          <template #default="{ row }">
            {{ row.paragraph_index == null ? "-" : `#${row.paragraph_index}` }}
          </template>
        </el-table-column>
        <el-table-column label="修订" width="112">
          <template #default="{ row }">
            <el-tooltip :disabled="repairable(row)" content="此类问题不能安全地自动修订，请手动处理。" placement="left">
              <span><el-checkbox :model-value="acceptedIndexes.includes(row._index)" :disabled="!repairable(row)" @click.stop @change="emit('accept', row._index, Boolean($event))">接纳修复</el-checkbox></span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </template>
    <el-empty v-else description="选择文档与规则后，点击「开始审查」" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { CheckItem, Violation } from "@/types";

type IndexedViolation = Violation & { _index: number };
const props = withDefaults(defineProps<{ check: CheckItem | null; acceptedIndexes: number[]; exporting?: boolean }>(), { exporting: false });
const emit = defineEmits<{
  (e: "locate", paragraphIndex: number): void;
  (e: "accept", violationIndex: number, accepted: boolean): void;
  (e: "export"): void;
}>();
const filter = ref("all");
const filteredViolations = computed<IndexedViolation[]>(() => props.check?.violations
  .map((violation, index) => ({ ...violation, _index: index }))
  .filter((violation) => filter.value === "all" || violation.category === filter.value) ?? []);
watch(() => props.check?.id, () => { filter.value = "all"; });

const CAT: Record<string, string> = {
  font: "字体",
  paragraph: "段落",
  page: "页面",
  heading_structure: "标题结构",
  coverage: "审查范围",
};

function catLabel(c: string): string {
  return CAT[c] ?? c;
}

function scopeLabel(s: string): string {
  if (s === "title") return "大标题";
  if (s === "body") return "正文";
  if (s === "page") return "页面";
  if (s === "heading_structure") return "标题结构";
  if (/^h[1-6]$/.test(s)) return `${s[1]} 级标题`;
  return s;
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "未设置";
  if (typeof v === "boolean") return v ? "是" : "否";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function repairable(violation: Violation): boolean {
  const fields = new Set([
    "font:name", "font:ascii_name", "font:size", "font:bold", "font:italic", "font:color",
    "paragraph:alignment", "paragraph:line_spacing", "paragraph:space_before", "paragraph:space_after", "paragraph:first_line_indent_chars",
    "page:paper", "page:width_cm", "page:height_cm", "page:margin_top_cm", "page:margin_bottom_cm", "page:margin_left_cm", "page:margin_right_cm", "page:header_distance_cm", "page:footer_distance_cm",
  ]);
  return violation.severity !== "unknown" && fields.has(`${violation.category}:${violation.field}`);
}

function locate(row: Violation) {
  if (row.paragraph_index != null) emit("locate", row.paragraph_index);
}
</script>

<style scoped>
.report-download{display:flex;justify-content:flex-end;margin-bottom:12px}
.report { min-height: 480px; }.summary { display: flex; align-items: center; gap: 13px; padding: 16px 18px; margin-bottom: 16px; border: 1px solid; border-radius: 12px; }.summary.is-pass { border-color: #bcead8; background: linear-gradient(100deg, #effcf6, #fbfffd); }.summary.is-issue { border-color: #ffe0cc; background: linear-gradient(100deg, #fff6f0, #fffdfb); }.summary-icon { display: grid; place-items: center; width: 35px; height: 35px; border-radius: 50%; font-size: 20px; font-weight: 800; }.is-pass .summary-icon { color: #138d64; background: #d8f7e8; }.is-issue .summary-icon { color: #d95e3c; background: #ffe4d8; }.summary strong { color: #24344f; font-size: 15px; }.summary p { margin: 3px 0 0; color: #8390a5; font-size: 12px; }.summary-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-left: auto; }.chip { padding: 4px 8px; color: #5b6981; border-radius: 20px; background: rgba(255,255,255,.72); font-size: 12px; }.report-tools { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0 0 12px; }.report-tools > span { color: #95a1b5; font-size: 12px; }.violation-table { --el-table-border-color: #edf1f6; --el-table-header-bg-color: #f7f9fc; }.violation-table :deep(.el-table__row) { cursor: pointer; }.violation-table :deep(.el-table__row:hover > td) { background: #f2f6ff !important; }
@media (max-width: 720px) { .summary { align-items: flex-start; flex-wrap: wrap; }.summary-chips { width: 100%; margin-left: 48px; }.report-tools { align-items: flex-start; flex-direction: column; } }
</style>
