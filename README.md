# AI 协同办公 · 智能格式审查助手

这是一个面向 Word 文档的格式审查 Web 应用：上传 `.docx` 文件并描述格式要求后，DeepSeek 会提取结构化规则，后端确定性规则引擎再逐项检查并给出可定位的违规报告。

> 格式是否合规始终由确定性后端代码判断。独立的 AI 内容审查由 DeepSeek 提供措辞、语法、逻辑和一致性修改建议。

## 功能

- JWT 登录、注册与工作区隔离。
- `.docx` 上传、解析与浏览器预览。
- 自然语言生成格式规则，并提供毕业论文、商务报告快捷示例。
- 可视化编辑正文、标题、页面等常用规则，无需重新调用 AI。
- 审查报告按类别汇总和筛选；点击违规行可定位并高亮对应段落。
- 单条或批量审查；工作区概览按每份文档的最新结果汇总通过状态与问题分布。
- 内置毕业论文、商务报告、会议纪要规则模板；每次保存都保留可恢复的规则版本。
- 审查历史回看与响应式工作台界面。
- 内容审查：选择文档 → “内容审查” → “用 DeepSeek 审查内容”，无需格式规则。
  展示原文引用、问题原因、修改建议，点击引用或“定位原文”跳转高亮；保留最近 50 次历史供查看。
  文字发送至后端配置的 DeepSeek 服务，建议需人工确认，不自动修改原件。
  当前范围为正文和表格，不含页眉页脚、图片、文本框及已删除修订；
  每次最多 30000 字符、1500 个非空段落，最多输出 50 条建议，超限明确提示拆分。
  无联网事实核查，存疑的外部事实仅标记“事实待核实”。

## 技术栈

- 前端：Vue 3、Vite、TypeScript、Pinia、Element Plus、docx-preview
- 后端：FastAPI、SQLAlchemy、Pydantic v2、python-docx
- AI：DeepSeek `deepseek-chat`（规则提取及独立内容审查）
- 存储：SQLite（演示环境），可替换为 PostgreSQL + Redis

## 启动

### 后端

```bash
cd backend
python -m pip install -r requirements.txt
```

将 `.env.example` 复制为 `.env`，设置 `DEEPSEEK_API_KEY` 后启动：

```bash
uvicorn app.main:app --reload
```

健康检查：<http://127.0.0.1:8000/api/health>

### 前端

```bash
cd frontend
npm install
npm run dev
```

访问：<http://127.0.0.1:5173>

## 验证

```bash
# 后端测试
cd backend
python -m pytest

# 前端构建
cd frontend
npm run build
```

## 结构

```text
backend/                         FastAPI 服务
  app/services/docx_parser.py    Word 格式确定性解析
  app/services/deepseek_spec.py  格式规则提取
  app/services/deepseek_content.py 内容审查及原文引用校验
  app/services/document_content.py 内容提取及预览书签
  app/services/checker.py        确定性规则引擎
frontend/                        Vue 3 客户端
  src/components/RuleEditor.vue  可视化规则编辑
  src/components/CheckHistory.vue 审查历史
```

## 安全约定

- `.env` 中的 DeepSeek Key 不会提交到仓库，也不会暴露给前端。
- 所有工作区数据均经过成员关系校验。
- 规则字段以 `RuleSet` 为唯一契约；新增检查维度时须同步更新解析器、规则引擎与前端类型。

## 内容审查升级与验证

重启后端会自动创建新的 content_reviews 表，保留原有数据。已有文档可直接审查，无需重新上传。
后端需配置 DEEPSEEK_API_KEY；单次模型请求最长等待 120 秒，失败不写入成功记录。
前端预览改用 /api/documents/{id}/preview，需同时更新并重启后端。

离线回归：后端运行 python -m pytest；前端运行 npm run build。
启动 Vite 后可访问 /tests/content-review.browser.html，使用合成文档与模拟 AI 响应验证点击定位。
