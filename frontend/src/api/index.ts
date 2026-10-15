import http from "./http";
import type {
  CheckItem,
  DocumentItem,
  RuleItem,
  RuleSet,
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
  updateRuleset(ruleId: number, ruleset: RuleSet) {
    return http.put<RuleItem>(`/rules/${ruleId}/ruleset`, ruleset);
  },
  remove(id: number) {
    return http.delete(`/rules/${id}`);
  },
};

// ---- 审查 ----
export const checkApi = {
  run(workspaceId: number, documentId: number, ruleId: number) {
    return http.post<CheckItem>("/checks", {
      workspace_id: workspaceId,
      document_id: documentId,
      rule_id: ruleId,
    });
  },
  list(workspaceId: number) {
    return http.get<CheckItem[]>("/checks", {
      params: { workspace_id: workspaceId },
    });
  },
};
