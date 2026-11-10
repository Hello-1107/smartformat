// 与后端 app/schemas/* 一一对应的类型定义（唯一契约来源是后端 Pydantic schema）。

export interface User {
  id: number;
  username: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Workspace {
  id: number;
  name: string;
  owner_id: number;
  role: string;
  created_at: string;
}

export interface FontInfo {
  name: string | null;
  ascii_name: string | null;
  size: number | null;
  bold: boolean | null;
  italic: boolean | null;
  color: string | null;
}

export interface ParsedParagraph {
  index: number;
  text: string;
  style_name: string;
  level: number | null;
  is_title?: boolean;
  runs?: { text: string; font: FontInfo }[];
  font: FontInfo;
  alignment: string | null;
  line_spacing: number | null;
  line_spacing_kind?: "multiple" | "exact" | "atLeast";
  space_before: number | null;
  space_after: number | null;
  first_line_indent_chars: number | null;
  numbered: boolean;
  bullet: boolean;
  role?: "title" | "heading" | "toc" | "body" | "code" | "figure_caption" | "table_caption";
  toc_level?: number | null;
}

export interface ParsedSection {
  index: number;
  paper: string | null;
  width_cm: number | null;
  height_cm: number | null;
  margin_top_cm: number | null;
  margin_bottom_cm: number | null;
  margin_left_cm: number | null;
  margin_right_cm: number | null;
  header_distance_cm: number | null;
  footer_distance_cm: number | null;
}

export interface ParsedDocument {
  parser_version?: number;
  filename: string;
  sections: ParsedSection[];
  paragraphs: ParsedParagraph[];
}

export interface DocumentItem {
  id: number;
  workspace_id: number;
  filename: string;
  size: number;
  created_at: string;
  parsed?: ParsedDocument | null;
  file_type?: "docx" | "pdf";
  pdf_page_map?: number[] | null;
  pdf_ocr_pages?: number[] | null;
}

export interface AnalysisSource {
  document_id: number;
  paragraph_index: number | null;
  page_number: number | null;
  quote: string | null;
}

export interface AnalysisFinding {
  category: string;
  status: string;
  message: string;
  sources: AnalysisSource[];
}

export interface VersionCompareResult {
  original_id: number;
  revised_id: number;
  rule_id: number;
  original_issue_count: number;
  revised_issue_count: number;
  findings: AnalysisFinding[];
  export_signature?: string | null;
}

export interface StructureCheckResult {
  document_id: number;
  headings_found: string[];
  findings: AnalysisFinding[];
  export_signature?: string | null;
}

export interface CrossFieldSpec {
  name: string;
  aliases: string[];
  value_type: "text" | "number" | "date";
}

export interface CrossFieldValue {
  document_id: number;
  value: string | null;
  normalized_value: string | null;
  source: AnalysisSource | null;
  status: "match" | "different" | "missing" | "ambiguous" | "baseline";
  candidates: AnalysisSource[];
}

export interface CrossDocumentResult {
  baseline_id: number;
  fields: { name: string; baseline_value: string | null; values: CrossFieldValue[] }[];
  export_signature?: string | null;
}

export type Alignment = "left" | "center" | "right" | "justify";

export interface FontRule {
  name?: string | null;
  ascii_name?: string | null;
  size?: number | null;
  bold?: boolean | null;
  italic?: boolean | null;
  color?: string | null;
}

export interface ParagraphRule {
  alignment?: Alignment | null;
  line_spacing?: number | null;
  line_spacing_kind?: "multiple" | "exact" | "atLeast" | null;
  space_before?: number | null;
  space_after?: number | null;
  first_line_indent_chars?: number | null;
  numbered?: boolean | null;
  bullet?: boolean | null;
}

export interface PageRule {
  paper?: string | null;
  width_cm?: number | null;
  height_cm?: number | null;
  margin_top_cm?: number | null;
  margin_bottom_cm?: number | null;
  margin_left_cm?: number | null;
  margin_right_cm?: number | null;
  header_distance_cm?: number | null;
  footer_distance_cm?: number | null;
}

export interface ScopeRule {
  font?: FontRule | null;
  paragraph?: ParagraphRule | null;
}

export interface HeadingStructureRule {
  max_level?: number | null;
  require_numbered?: boolean | null;
}

export interface TemplateRegionRule {
  id: string;
  label: string;
  anchor: string;
  level: number;
  mode: "fixed" | "variable" | "ignore";
  required: boolean;
  check_format: boolean;
  template_paragraph_index: number;
  heading_style?: ScopeRule | null;
  body_style?: ScopeRule | null;
}

export interface TemplateDocumentChecks {
  check_toc: boolean;
  toc_entries: string[];
  check_figure_numbering: boolean;
  check_table_numbering: boolean;
  check_code_style: boolean;
  code_style?: ScopeRule | null;
  figure_caption_style?: ScopeRule | null;
  table_caption_style?: ScopeRule | null;
}

export interface RuleSet {
  name: string;
  description?: string | null;
  body?: ScopeRule | null;
  title?: ScopeRule | null;
  headings?: Record<string, ScopeRule> | null;
  page?: PageRule | null;
  heading_structure?: HeadingStructureRule | null;
  template_regions?: TemplateRegionRule[] | null;
  template_checks?: TemplateDocumentChecks | null;
}

export interface RuleItem {
  id: number;
  workspace_id: number;
  name: string;
  natural_language: string;
  ruleset: RuleSet;
  created_at: string;
}

export interface RuleTemplate {
  id: string;
  name: string;
  description: string;
  ruleset: RuleSet;
  source: "system" | "workspace";
}

export interface RuleRevision {
  id: number;
  rule_id: number;
  version: number;
  name: string;
  natural_language: string;
  ruleset: RuleSet;
  created_at: string;
}

export interface Violation {
  scope: string;
  category: string;
  field: string;
  expected: unknown;
  actual: unknown;
  message: string;
  paragraph_index: number | null;
  paragraph_text: string | null;
  severity: string;
  section_index?: number | null;
  run_index?: number | null;
}

export interface CheckSummary {
  total: number;
  by_category: Record<string, number>;
  compliant: boolean;
  status?: "pass" | "fail" | "unknown";
  unknown?: number;
}

export interface CheckItem {
  id: number;
  workspace_id: number;
  document_id: number;
  rule_id: number;
  status: string;
  violations: Violation[];
  summary: CheckSummary;
  created_at: string;
  ruleset_snapshot?: { ruleset: RuleSet; hash: string; parser_version: number } | null;
}

export interface StyleCandidate {
  id: string;
  scope: string;
  count: number;
  examples: string[];
  paragraph_indexes: number[];
  style: ScopeRule;
}

export interface TemplateExtraction {
  ruleset: RuleSet;
  candidates: Record<string, StyleCandidate[]>;
  regions?: TemplateRegionRule[];
  warnings: string[];
}

export interface BatchCheckResult {
  checks: CheckItem[];
  total_documents: number;
  compliant_documents: number;
  violation_total: number;
}

export interface ContentIssue {
  paragraph_index: number;
  quote: string;
  category: "措辞" | "语法" | "逻辑" | "一致性" | "事实待核实" | "其他";
  severity: "重要" | "一般" | "建议";
  reason: string;
  suggestion: string;
  recommended_replacement?: string | null;
  related_references?: { paragraph_index: number; quote: string }[];
}

export interface ContentReview {
  id: number;
  workspace_id: number;
  document_id: number;
  instructions: string;
  model: string;
  paragraph_count: number;
  created_at: string;
  summary: string;
  issues: ContentIssue[];
}

/** 用户明确确认后，写入修订副本的内容替换；不会触发任何 AI 调用。 */
export interface ContentRepairFix {
  review_id: number;
  issue_index: number;
  replacement_text: string;
}

export type TemplateBlockMode = "fixed" | "variable" | "ignore";
export type TemplateDataType = "text" | "number" | "date" | "id_number" | "phone" | "email";

export interface TemplateFieldRule {
  kind: "email" | "length" | "chinese_length" | "number_range" | "allowed_values" | "contains" | "same_as" | "exact_text" | "forbidden_value" | "number_with_unit";
  min_value?: number | null;
  max_value?: number | null;
  min_length?: number | null;
  max_length?: number | null;
  options?: string[];
  text?: string;
  replacement_text?: string;
  other_block_id?: string;
}

export interface TemplateParagraphFormat {
  font: FontInfo;
  fonts?: FontInfo[];
  alignment: string | null;
  line_spacing: number | null;
  line_spacing_kind?: "multiple" | "exact" | "atLeast";
  space_before: number | null;
  space_after: number | null;
  first_line_indent_chars: number | null;
}

export interface TemplateBlock {
  id: string;
  order: number;
  kind: "paragraph" | "table_cell";
  location: string;
  content_index: number;
  top_level_paragraph_index: number | null;
  table_index: number | null;
  row_index: number | null;
  column_index: number | null;
  paragraph_in_cell: number | null;
  text: string;
  label: string;
  mode: TemplateBlockMode;
  required: boolean;
  data_type: TemplateDataType;
  check_format: boolean;
  recognition_confidence?: "high" | "medium" | "low";
  recognition_note?: string;
  recognition_confirmed?: boolean;
  rules: TemplateFieldRule[];
  requirement_text?: string;
  unsupported_requirements?: string[];
  format: TemplateParagraphFormat;
}

export interface DocumentTemplate {
  id: number;
  workspace_id: number;
  version: number;
  name: string;
  filename: string;
  size: number;
  is_active: boolean;
  is_published: boolean;
  is_review_active?: boolean;
  config: {
    check_page: boolean;
    page: ParsedSection | null;
    table_shapes: number[][];
    blocks: TemplateBlock[];
  };
  created_at: string;
}

export interface TemplateIssue {
  category: "结构" | "固定内容" | "必填" | "字段规范" | "填写要求" | "格式" | "页面" | "表格";
  severity: "错误" | "警告" | "提示";
  message: string;
  template_block_id: string | null;
  template_content_index: number | null;
  document_content_index: number | null;
  expected: unknown;
  actual: unknown;
  quote: string | null;
  recommended_replacement: string | null;
  repairable: boolean;
  format_violation: Violation | null;
}

export interface TemplateReview {
  template_snapshot?: DocumentTemplate | null;
  id: number;
  workspace_id: number;
  template_id: number;
  template_version: number;
  document_id: number;
  created_at: string;
  summary: string;
  issues: TemplateIssue[];
  total: number;
  repairable: number;
  compliant: boolean;
  ai_review?: {
    status: "completed" | "failed" | "not_configured";
    summary: string;
    model: string | null;
    field_ids: string[];
    suggestions: Array<{
      block_id: string;
      template_content_index: number | null;
      document_content_index: number | null;
      quote: string;
      reason: string;
      suggestion: string;
      recommended_replacement: string | null;
    }>;
  } | null;
}

export interface TemplateRepairFix {
  review_id: number;
  issue_index: number;
  replacement_text?: string | null;
}

export interface RevisedCopyRequest {
  workspace_id: number;
  check_id?: number | null;
  format_violation_indexes: number[];
  content_fixes: ContentRepairFix[];
  template_fixes: TemplateRepairFix[];
}

export interface AutoFormatPlan {
  check_id: number;
  document_id: number;
  source_sha256: string;
  format_violation_indexes: number[];
  skipped: { index: number; reason: string }[];
}
