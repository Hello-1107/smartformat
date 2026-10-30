const CATEGORY_LABELS: Record<string, string> = {
  font: "字体",
  paragraph: "段落",
  page: "页面",
  heading_structure: "标题结构",
  template_structure: "模板结构",
  template_content: "固定内容",
  toc: "目录",
  caption: "图表题注",
  coverage: "审查范围",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}
