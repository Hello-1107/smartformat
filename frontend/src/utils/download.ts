import { errText } from "@/api/http";

export function downloadBlob(blob: Blob, filename: string): void {
  if (!blob.size) throw new Error("导出的文件为空");
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function downloadErrorText(error: unknown): Promise<string> {
  const data = (error as { response?: { data?: unknown } }).response?.data;
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text()) as { detail?: unknown };
      if (typeof parsed.detail === "string") return parsed.detail;
    } catch { /* 使用常规网络错误文案。 */ }
  }
  return errText(error);
}
