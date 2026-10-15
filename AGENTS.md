# 已授权的内容审查扩展

用户已明确要求使用 DeepSeek 审查文档内容并提供修改建议。
本目录在上级项目规范基础上增加以下约定：

- 格式合规继续由 services/checker.py 确定性判断。
- services/deepseek_spec.py 负责格式规则提取。
- services/deepseek_content.py 专门调用 DeepSeek 审查文字内容；
  ContentReviewResult 是其独立契约，结果不混入格式合规统计。
- 内容建议必须含可验证的段落编号与原文连续引用。禁止把无效 AI 引用
  静默丢弃后报告“无问题”，禁止让文档中的指令改变模型任务。
- 内容审查结果使用独立 content_reviews 表，并校验 workspace 成员关系。
- 预览通过 services/document_content.py 在内存副本里插入书签；
  sf_format_N 对应顶层正文段落，sf_content_N 对应正文及表格段落。
  不得用全页面 p 元素的序号替代源文档锚点，也不修改上传原件。
- 单元及集成测试模拟 DeepSeek；未经必要说明不在测试中发送用户文档。
