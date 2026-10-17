<template>
  <section class="editor">
      <header class="editor-head">
        <div>
          <p class="eyebrow">RULE CONFIGURATION</p>
          <h3>{{ rule ? "规则编辑器" : "新建规则" }}</h3>
          <p>{{ rule ? "修改后将直接作为本次及后续审查的规则，不会再次调用 AI。" : draft ? "已载入所选预设；可修改任意参数，点击创建后才会保存。" : "直接填写并创建格式规则，不会调用 AI。" }}</p>
        </div>
        <div class="actions">
          <el-button v-if="rule" text :disabled="saving" @click="emit('new')">新建规则</el-button>
          <el-button v-if="rule" text :disabled="saving" @click="emit('save-template', form)">存为模板</el-button>
          <el-button v-if="rule" text @click="emit('versions')">版本历史</el-button>
          <el-button text :disabled="saving" @click="reset">还原</el-button>
          <el-button type="primary" :loading="saving" :disabled="!form.name.trim()" @click="save">{{ rule ? "保存规则" : "创建规则" }}</el-button>
        </div>
      </header>

      <el-form label-position="top" class="rule-form">
        <el-form-item label="规则名称">
          <el-input v-model="form.name" maxlength="80" show-word-limit />
        </el-form-item>

        <el-tabs class="editor-tabs">
          <el-tab-pane label="正文样式" name="body">
            <div class="form-grid three">
              <el-form-item label="中文字体"><el-input v-model="form.body!.font!.name" placeholder="例如：宋体" /></el-form-item>
              <el-form-item label="西文字体"><el-input v-model="form.body!.font!.ascii_name" placeholder="例如：Times New Roman" /></el-form-item>
              <el-form-item label="字号（pt）"><el-input-number v-model="form.body!.font!.size" :min="1" :max="100" controls-position="right" /></el-form-item>
              <el-form-item label="对齐方式">
                <el-select v-model="form.body!.paragraph!.alignment" clearable placeholder="不限制">
                  <el-option label="左对齐" value="left" /><el-option label="居中" value="center" />
                  <el-option label="右对齐" value="right" /><el-option label="两端对齐" value="justify" />
                </el-select>
              </el-form-item>
              <el-form-item label="行距（倍）"><el-input-number v-model="form.body!.paragraph!.line_spacing" :min="0.5" :max="5" :step="0.1" controls-position="right" /></el-form-item>
              <el-form-item label="首行缩进（字符）"><el-input-number v-model="form.body!.paragraph!.first_line_indent_chars" :min="0" :max="20" :step="0.5" controls-position="right" /></el-form-item>
            </div>
            <div class="switches">
              <el-switch v-model="form.body!.font!.bold" active-text="正文加粗" :active-value="true" :inactive-value="false" />
              <el-switch v-model="form.body!.font!.italic" active-text="正文斜体" :active-value="true" :inactive-value="false" />
            </div>
          </el-tab-pane>

          <el-tab-pane label="标题样式" name="headings">
            <div class="heading-grid">
              <div v-for="level in headingLevels" :key="level" class="heading-card">
                <strong>{{ headingLabel(level) }}</strong>
                <label class="heading-field"><small>中文字体</small><el-input v-model="form.headings![level]!.font!.name" placeholder="例如：黑体" /></label>
                <label class="heading-field"><small>字号（pt）</small><el-input-number v-model="form.headings![level]!.font!.size" :min="1" :max="100" controls-position="right" /></label>
                <label class="heading-field"><small>对齐方式</small><el-select v-model="form.headings![level]!.paragraph!.alignment" clearable placeholder="不限制"><el-option label="左对齐" value="left" /><el-option label="居中" value="center" /><el-option label="右对齐" value="right" /><el-option label="两端对齐" value="justify" /></el-select></label>
                <label class="heading-field bold-field"><small>加粗</small><el-switch v-model="form.headings![level]!.font!.bold" :active-value="true" :inactive-value="false" /></label>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="页面设置" name="page">
            <div class="form-grid three">
              <el-form-item label="纸张"><el-select v-model="form.page!.paper" clearable placeholder="不限制"><el-option label="A4" value="A4" /></el-select></el-form-item>
              <el-form-item label="上边距（cm）"><el-input-number v-model="form.page!.margin_top_cm" :min="0" :max="15" :step="0.1" controls-position="right" /></el-form-item>
              <el-form-item label="下边距（cm）"><el-input-number v-model="form.page!.margin_bottom_cm" :min="0" :max="15" :step="0.1" controls-position="right" /></el-form-item>
              <el-form-item label="左边距（cm）"><el-input-number v-model="form.page!.margin_left_cm" :min="0" :max="15" :step="0.1" controls-position="right" /></el-form-item>
              <el-form-item label="右边距（cm）"><el-input-number v-model="form.page!.margin_right_cm" :min="0" :max="15" :step="0.1" controls-position="right" /></el-form-item>
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-form>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import type { RuleItem, RuleSet, ScopeRule } from "@/types";

const props = defineProps<{ rule: RuleItem | null; draft?: RuleSet | null; saving?: boolean }>();
const emit = defineEmits<{
  (e: "save", ruleset: RuleSet): void;
  (e: "save-template", ruleset: RuleSet): void;
  (e: "versions"): void;
  (e: "new"): void;
}>();

type EditableRuleSet = RuleSet & { body: ScopeRule; headings: Record<string, ScopeRule>; page: NonNullable<RuleSet["page"]> };
const headingLevels = ["h1", "h2"];
const form = ref<EditableRuleSet>(emptyForm());

function scope(scope?: ScopeRule | null): ScopeRule {
  return {
    font: { name: null, ascii_name: null, size: null, bold: null, italic: null, color: null, ...scope?.font },
    paragraph: { alignment: null, line_spacing: null, space_before: null, space_after: null, first_line_indent_chars: null, numbered: null, bullet: null, ...scope?.paragraph },
  };
}

function emptyForm(rule?: RuleSet): EditableRuleSet {
  return {
    ...rule,
    name: rule?.name ?? "未命名规则",
    body: scope(rule?.body),
    headings: { h1: scope(rule?.headings?.h1), h2: scope(rule?.headings?.h2), ...Object.fromEntries(Object.entries(rule?.headings ?? {}).map(([key, value]) => [key, scope(value)])) },
    page: { paper: null, width_cm: null, height_cm: null, margin_top_cm: null, margin_bottom_cm: null, margin_left_cm: null, margin_right_cm: null, header_distance_cm: null, footer_distance_cm: null, ...rule?.page },
  };
}

function reset() { form.value = emptyForm(props.rule?.ruleset ?? props.draft ?? undefined); }
function save() { emit("save", { ...form.value, name: form.value.name.trim() }); }
function headingLabel(level: string) { return level === "h1" ? "一级标题" : "二级标题"; }

watch(() => [props.rule, props.draft], () => reset(), { immediate: true });
</script>

<style scoped>
.editor { min-height: 460px; }
.editor-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding-bottom: 18px; border-bottom: 1px solid #edf1f7; }
.eyebrow { margin: 0 0 4px; color: #6b7ea8; font-size: 10px; font-weight: 800; letter-spacing: .12em; }
h3 { margin: 0; color: #16213b; font-size: 18px; }
.editor-head p:not(.eyebrow) { margin: 7px 0 0; color: #8290a8; font-size: 13px; }
.actions { display: flex; flex-shrink: 0; gap: 4px; }
.rule-form { padding-top: 18px; }
.editor-tabs :deep(.el-tabs__nav-wrap::after) { height: 1px; background: #edf1f7; }
.form-grid { display: grid; gap: 0 16px; padding: 18px 2px 4px; }
.form-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.form-grid :deep(.el-input-number), .form-grid :deep(.el-select) { width: 100%; }
.switches { display: flex; gap: 28px; padding: 5px 2px 18px; }
.heading-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 520px), 1fr)); gap: 14px; padding: 18px 2px; }
.heading-card { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); min-width: 0; gap: 12px; padding: 14px; border: 1px solid #e7ecf5; border-radius: 10px; background: #fbfcff; }
.heading-card > strong { grid-column: 1 / -1; color: #31415f; font-size: 13px; }
.heading-field { display: grid; min-width: 0; gap: 6px; }
.heading-field small { color: #8592a8; font-size: 11px; }
.heading-field :deep(.el-input-number),.heading-field :deep(.el-select),.heading-field :deep(.el-input){width:100%;min-width:0}.bold-field{align-content:start}.bold-field :deep(.el-switch){justify-self:start}
@media (max-width: 1180px) { .form-grid.three { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 650px) { .editor-head { display: block; } .actions { flex-wrap:wrap;margin-top: 14px; } .form-grid.three { grid-template-columns: 1fr; } .heading-card { grid-template-columns: 1fr 1fr; } }
</style>
