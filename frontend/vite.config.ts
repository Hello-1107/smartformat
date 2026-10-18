import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

// 前端不暴露 DeepSeek Key：所有 AI 调用都经由后端 /api 转发。
export default defineConfig({
  plugins: [vue()],
  build: { rollupOptions: { output: { manualChunks(id) {
    if(id.includes('node_modules/element-plus') || id.includes('node_modules/@element-plus'))return 'ui-components';
    if(id.includes('node_modules/@vue') || /node_modules\/vue\//.test(id))return 'vue-runtime';
  } } } },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
