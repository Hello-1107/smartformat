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
  TokenResponse,
  Workspace,
} from "@/types";

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
};

// ---- 文档 ----
export const documentApi = {
  list(workspaceId: number) {
    return http.get<DocumentItem[]>("/documents", {
      params: { workspace_id: workspaceId },
    });
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
};

// ---- 填写样例模板审查（每个工作区一个当前版本）----
export const templateAuditApi = {
  current(workspaceId: number) {
    return http.get<DocumentTemplate | null>("/template-audits/current", { params: { workspace_id: workspaceId } });
  },
  versions(workspaceId: number) {
    return http.get<DocumentTemplate[]>("/template-audits/versions", { params: { workspace_id: workspaceId } });
  },
  upload(workspaceId: number, file: File, name: string) {
    return http.post<DocumentTemplate>("/template-audits/template", file, {
      params: { workspace_id: workspaceId, filename: file.name, name },
      headers: { "Content-Type": "application/octet-stream" },
      timeout: 120000,
    });
  },
  update(workspaceId: number, name: string, checkPage: boolean, blocks: TemplateBlock[]) {
    return http.put<DocumentTemplate>("/template-audits/current", {
      workspace_id: workspaceId,
      name,
      check_page: checkPage,
      blocks: blocks.map(({ id, label, mode, required, data_type, check_format }) => ({
        id, label, mode, required, data_type, check_format,
      })),
    });
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
  run(workspaceId: number, documentId: number) {
    return http.post<TemplateReview>("/template-audits/reviews", {
      workspace_id: workspaceId, document_id: documentId,
    }, { timeout: 120000 });
  },
  reviews(workspaceId: number, documentId: number) {
    return http.get<TemplateReview[]>("/template-audits/reviews", {
      params: { workspace_id: workspaceId, document_id: documentId },
    });
  },
  removeReview(reviewId: number) {
    return http.delete(`/template-audits/reviews/${reviewId}`);
  },
};

// ---- 规则 ----
export const ruleApi = {
  list(workspaceId: number) {
    return http.get<RuleItem[]>("/rules", {
      params: { workspace_id: workspaceId },
    });
  },
  generate(workspaceId: number, naturalLanguage: string, name?: string) {
    return http.post<RuleItem>("/rules", {
      workspace_id: workspaceId,
      natural_language: naturalLanguage,
      name,
    });
  },
  createManual(workspaceId: number, ruleset: RuleSet) {
    return http.post<RuleItem>("/rules/manual", { workspace_id: workspaceId, ruleset });
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
  run(workspaceId: number, documentId: number, instructions: string) {
    return http.post<ContentReview>("/content-reviews", {
      workspace_id: workspaceId, document_id: documentId, instructions,
    }, { timeout: 150000 });
  },
  list(workspaceId: number, documentId: number) {
    return http.get<ContentReview[]>("/content-reviews", {
      params: { workspace_id: workspaceId, document_id: documentId },
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
  list(workspaceId: number) {
    return http.get<CheckItem[]>("/checks", {
      params: { workspace_id: workspaceId },
    });
  },
  remove(id: number) {
    return http.delete(`/checks/${id}`);
  },
};
