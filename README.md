# AI 协同办公 · 智能格式审查助手

这是一个面向 Word 文档的格式审查 Web 应用：上传 `.docx` 文件并描述格式要求后，DeepSeek 会提取结构化规则，后端确定性规则引擎再逐项检查并给出可定位的违规报告。

> AI 只负责“自然语言 → 格式规则”的提取；格式是否合规始终由确定性后端代码判断。

## 功能

- JWT 登录、注册与工作区隔离。
- `.docx` 上传、解析与浏览器预览。
- 自然语言生成格式规则，并提供毕业论文、商务报告快捷示例。
- 可视化编辑正文、标题、页面等常用规则，无需重新调用 AI。
- 审查报告按类别汇总和筛选；点击违规行可定位并高亮对应段落。
- 单条或批量审查；工作区概览按每份文档的最新结果汇总通过状态与问题分布。
- 内置毕业论文、商务报告、会议纪要规则模板；每次保存都保留可恢复的规则版本。
- 审查历史回看与响应式工作台界面。

## 技术栈

- 前端：Vue 3、Vite、TypeScript、Pinia、Element Plus、docx-preview
- 后端：FastAPI、SQLAlchemy、Pydantic v2、python-docx
- AI：DeepSeek `deepseek-chat`（仅用于规则提取）
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
  app/services/deepseek_spec.py  唯一的 DeepSeek 调用点
  app/services/checker.py        确定性规则引擎
frontend/                        Vue 3 客户端
  src/components/RuleEditor.vue  可视化规则编辑
  src/components/CheckHistory.vue 审查历史
```

## 安全约定

- `.env` 中的 DeepSeek Key 不会提交到仓库，也不会暴露给前端。
- 所有工作区数据均经过成员关系校验。
- 规则字段以 `RuleSet` 为唯一契约；新增检查维度时须同步更新解析器、规则引擎与前端类型。
