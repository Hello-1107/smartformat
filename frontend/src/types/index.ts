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
  font: FontInfo;
  alignment: string | null;
  line_spacing: number | null;
  space_before: number | null;
  space_after: number | null;
  first_line_indent_chars: number | null;
  numbered: boolean;
  bullet: boolean;
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

export interface RuleSet {
  name: string;
  description?: string | null;
  body?: ScopeRule | null;
  headings?: Record<string, ScopeRule> | null;
  page?: PageRule | null;
  heading_structure?: HeadingStructureRule | null;
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
}

export interface CheckSummary {
  total: number;
  by_category: Record<string, number>;
  compliant: boolean;
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
