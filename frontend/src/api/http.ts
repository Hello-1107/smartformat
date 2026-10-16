import axios from "axios";

// 统一 axios 实例：自动附带 JWT，401 时回登录页。
const http = axios.create({
  baseURL: "/api",
  timeout: 60000,
});

http.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export default http;

export function errText(e: unknown): string {
  const anyE = e as {
    response?: { data?: { detail?: unknown }; status?: number };
    config?: { method?: string; url?: string };
    message?: string;
  };
  const detail = anyE.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // Pydantic 校验错误带 "Value error, " 前缀，这里去掉以便直接展示
    return detail
      .map((d: { msg?: unknown }) => String(d.msg ?? "参数校验失败").replace(/^Value error,\s*/, ""))
      .join("；");
  }
  const status = anyE.response?.status;
  if (status) {
    const method = anyE.config?.method?.toUpperCase();
    const url = anyE.config?.url;
    const request = [method, url].filter(Boolean).join(" ");
    return `请求失败（${status}${request ? `：${request}` : ""}）`;
  }
  return anyE.message || "请求失败";
}
