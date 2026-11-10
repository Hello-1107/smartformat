import http from "./http";
import type {
  BatchCheckResult,
  CheckItem,
  ContentReview,
  DocumentItem,
  RuleItem,
  RuleRevision,
  RuleSet,
  RuleTemplate,
  DocumentTemplate,
  TemplateBlock,
  TemplateReview,
  RevisedCopyRequest,
  AutoFormatPlan,
  TokenResponse,
  TemplateExtraction,
  VersionCompareResult,
  StructureCheckResult,
  CrossDocumentResult,
  CrossFieldSpec,
  Workspace,
} from "@/types";

async function paged<T extends { id: number }>(path: string, params: Record<string, unknown>) {
  const items: T[]=[]; let before: number | undefined;
  for (;;) {
    const response=await http.get<T[]>(path,{params:{...params,limit:100,before_id:before}});
    const batch=response.data; items.push(...batch);
    if(batch.length<100){response.data=items;return response;}
    before=batch[batch.length-1]!.id;
  }
}

// ---- 认证（账号 + 密码）----
export const authApi = {
  register(data: {
    username: string;
    password: string;
    confirm_password: string;
  }) {
    return http.post<TokenResponse>("/auth/register", data);
  },
  login(data: { username: string; password: string }) {
    return http.post<TokenResponse>("/auth/login", data);
  },
};

// ---- 工作区 ----
export const workspaceApi = {
  list() {
    return http.get<Workspace[]>("/workspaces");
  },
  create(name: string) {
    return http.post<Workspace>("/workspaces", { name });
  },
  remove(id: number) {
    return http.delete(`/workspaces/${id}`);
  },
};

// ---- 文档 ----
export const documentApi = {
  list(workspaceId: number) {
    return paged<DocumentItem>("/documents", { workspace_id: workspaceId });
  },
  upload(workspaceId: number, file: File) {
    // 原始二进制上传：workspace_id / filename 走 query，请求体即 docx 字节。
    return http.post<DocumentItem>("/documents", file, {
      params: { workspace_id: workspaceId, filename: file.name },
      headers: { "Content-Type": "application/octet-stream" },
    });
  },
  remove(id: number) {
    return http.delete(`/documents/${id}`);
  },
  revisedCopy(documentId: number, data: RevisedCopyRequest) {
    return http.post(`/documents/${documentId}/revised-copy`, data, {
      responseType: "blob",
      timeout: 120000,
    });
  },
  autoFormatPlan(documentId: number, workspaceId: number, checkId: number) {
    return http.get<AutoFormatPlan>(`/documents/${documentId}/auto-format-plan`, {
      params: { workspace_id: workspaceId, check_id: checkId }, timeout: 120000,
    });
  },
  autoFormatCopy(documentId: number, workspaceId: number, plan: AutoFormatPlan) {
    return http.post(`/documents/${documentId}/auto-format-copy`, {
      workspace_id: workspaceId, check_id: plan.check_id, source_sha256: plan.source_sha256,
    }, { responseType: "blob", timeout: 120000 });
  },
};

// ---- 填写样例模板审查（每个工作区一个当前版本）----
export const templateAuditApi = {
  get(templateId: number) { return http.get<DocumentTemplate>(`/template-audits/templates/${templateId}`); },
  current(workspaceId: number) {
    return http.get<DocumentTemplate | null>("/template-audits/current", { params: { workspace_id: workspaceId } });
  },
  versions(workspaceId: number) {
    return paged<DocumentTemplate>("/template-audits/versions", { workspace_id: workspaceId });
  },
  upload(workspaceId: number, file: File, name: string) {
    return http.post<DocumentTemplate>("/template-audits/template", file, {
      params: { workspace_id: workspaceId, filename: file.name, name },
      headers: { "Content-Type": "application/octet-stream" },
      timeout: 120000,
    });
  },
  update(workspaceId: number, name: string, checkPage: boolean, blocks: TemplateBlock[], templateId?: number) {
    return http.put<DocumentTemplate>("/template-audits/current", {
      workspace_id: workspaceId,
      template_id: templateId,
      name,
      check_page: checkPage,
      blocks: blocks.map(({ id, label, mode, required, data_type, check_format, recognition_confirmed, rules, requirement_text, unsupported_requirements }) => ({
        id, label, mode, required, data_type, check_format, recognition_confirmed: recognition_confirmed ?? false,
        rules: rules ?? [], requirement_text: requirement_text ?? "", unsupported_requirements: unsupported_requirements ?? [],
      })),
    });
  },
  draftRequirements(text: string) {
    return http.post<{ rules: import("@/types").TemplateFieldRule[]; unsupported: string[]; required: boolean | null }>("/template-audits/requirements/draft", { text });
  },
  reanalyze(workspaceId: number) {
    return http.post<DocumentTemplate>("/template-audits/current/reanalyze", null, {
      params: { workspace_id: workspaceId },
    });
  },
  activate(workspaceId: number, templateId: number) {
    return http.post<DocumentTemplate>(`/template-audits/versions/${templateId}/activate`, null, {
      params: { workspace_id: workspaceId },
    });
  },
  removeVersion(workspaceId: number, templateId: number) {
    return http.delete(`/template-audits/versions/${templateId}`, { params: { workspace_id: workspaceId } });
  },
  run(workspaceId: number, documentId: number, aiFieldIds: string[] = []) {
    return http.post<TemplateReview>("/template-audits/reviews", {
      workspace_id: workspaceId, document_id: documentId, ai_field_ids: aiFieldIds,
    }, { timeout: aiFieldIds.length ? 180000 : 120000 });
  },
  reviews(workspaceId: number, documentId: number, beforeId?: number) {
    return http.get<TemplateReview[]>("/template-audits/reviews", {
      params: { workspace_id: workspaceId, document_id: documentId, before_id: beforeId },
    });
  },
  removeReview(reviewId: number) {
    return http.delete(`/template-audits/reviews/${reviewId}`);
  },
};

// ---- 规则 ----
export const ruleApi = {
  list(workspaceId: number) {
    return paged<RuleItem>("/rules", { workspace_id: workspaceId });
  },
  generate(workspaceId: number, naturalLanguage: string, name?: string) {
    return http.post<RuleItem>("/rules", {
      workspace_id: workspaceId,
      natural_language: naturalLanguage,
      name,
    }, { timeout: 150000 });
  },
  createManual(workspaceId: number, ruleset: RuleSet) {
    return http.post<RuleItem>("/rules/manual", { workspace_id: workspaceId, ruleset });
  },
  extractFromDocument(workspaceId: number, file: File, name?: string) {
    return http.post<RuleItem>("/rules/from-document-template", file, {
      params: { workspace_id: workspaceId, filename: file.name, name },
      headers: { "Content-Type": "application/octet-stream" },
      timeout: 120000,
    });
  },
  extractCandidates(workspaceId: number, file: File) {
    return http.post<TemplateExtraction>("/rules/document-template-candidates", file, {
      params: { workspace_id: workspaceId, filename: file.name },
      headers: { "Content-Type": "application/octet-stream" }, timeout: 120000,
    });
  },
  templates(workspaceId: number) {
    return http.get<RuleTemplate[]>("/rules/templates", {
      params: { workspace_id: workspaceId },
    });
  },
  createTemplate(workspaceId: number, name: string, description: string, ruleset: RuleSet) {
    return http.post<RuleTemplate>("/rules/templates", {
      workspace_id: workspaceId,
      name,
      description,
      ruleset,
    });
  },
  removeTemplate(templateId: number) {
    return http.delete(`/rules/templates/${templateId}`);
  },
  createFromTemplate(workspaceId: number, templateId: string, name?: string) {
    return http.post<RuleItem>("/rules/from-template", {
      workspace_id: workspaceId,
      template_id: templateId,
      name,
    });
  },
  updateRuleset(ruleId: number, ruleset: RuleSet) {
    return http.put<RuleItem>(`/rules/${ruleId}/ruleset`, ruleset);
  },
  revisions(ruleId: number) {
    return http.get<RuleRevision[]>(`/rules/${ruleId}/versions`);
  },
  restoreRevision(ruleId: number, version: number) {
    return http.put<RuleItem>(`/rules/${ruleId}/versions/${version}/restore`);
  },
  remove(id: number) {
    return http.delete(`/rules/${id}`);
  },
};

// ---- 审查 ----
export const contentReviewApi = {
  run(workspaceId: number, documentId: number, instructions: string, chunked = false) {
    return http.post<ContentReview>("/content-reviews", {
      workspace_id: workspaceId, document_id: documentId, instructions, chunked,
    }, { timeout: 600000 });
  },
  list(workspaceId: number, documentId: number, beforeId?: number) {
    return http.get<ContentReview[]>("/content-reviews", {
      params: { workspace_id: workspaceId, document_id: documentId, before_id: beforeId },
    });
  },
  remove(id: number) {
    return http.delete(`/content-reviews/${id}`);
  },
};

export const checkApi = {
  run(workspaceId: number, documentId: number, ruleId: number) {
    return http.post<CheckItem>("/checks", {
      workspace_id: workspaceId,
      document_id: documentId,
      rule_id: ruleId,
    });
  },
  runBatch(workspaceId: number, documentIds: number[], ruleId: number) {
    return http.post<BatchCheckResult>("/checks/batch", {
      workspace_id: workspaceId,
      document_ids: documentIds,
      rule_id: ruleId,
    });
  },
  list(workspaceId: number, documentId?: number) {
    return paged<CheckItem>("/checks", { workspace_id: workspaceId, document_id: documentId, latest_only: documentId == null });
  },
  remove(id: number) {
    return http.delete(`/checks/${id}`);
  },
};

export const analysisApi = {
  compareVersions(workspaceId: number, originalId: number, revisedId: number, ruleId: number) {
    return http.post<VersionCompareResult>("/analysis/versions", { workspace_id: workspaceId, original_id: originalId, revised_id: revisedId, rule_id: ruleId });
  },
  checkStructure(workspaceId: number, documentId: number, requiredHeadings: string[], requireOrder: boolean) {
    return http.post<StructureCheckResult>("/analysis/structure", { workspace_id: workspaceId, document_id: documentId, required_headings: requiredHeadings, require_order: requireOrder });
  },
  compareDocuments(workspaceId: number, documentIds: number[], baselineId: number, fields: CrossFieldSpec[]) {
    return http.post<CrossDocumentResult>("/analysis/cross-documents", { workspace_id: workspaceId, document_ids: documentIds, baseline_id: baselineId, fields });
  },
};

export const reportApi = {
  format(checkId: number) { return http.get<Blob>(`/reports/checks/${checkId}`, { responseType: "blob", timeout: 120000 }); },
  content(reviewId: number) { return http.get<Blob>(`/reports/content-reviews/${reviewId}`, { responseType: "blob", timeout: 120000 }); },
  template(reviewId: number) { return http.get<Blob>(`/reports/template-reviews/${reviewId}`, { responseType: "blob", timeout: 120000 }); },
  analysis(workspaceId: number, kind: "versions" | "structure" | "cross-documents", result: VersionCompareResult | StructureCheckResult | CrossDocumentResult) {
    return http.post<Blob>(`/reports/analysis/${kind}`, { workspace_id: workspaceId, result }, { responseType: "blob", timeout: 120000 });
  },
};
