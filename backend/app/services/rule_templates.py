"""不依赖大模型的系统内置规则模板。"""

from app.schemas.rule import (
    FontRule,
    HeadingStructureRule,
    PageRule,
    ParagraphRule,
    RuleSet,
    RuleTemplateOut,
    ScopeRule,
)


def _templates() -> list[RuleTemplateOut]:
    """每次构造新对象，避免调用方修改共享模板。"""
    return [
        RuleTemplateOut(
            id="thesis-standard",
            name="毕业论文规范",
            description="适用于常见中文毕业论文正文、一级和二级标题及 A4 页面设置。",
            ruleset=RuleSet(
                name="毕业论文规范",
                description="内置模板：常见中文毕业论文格式",
                body=ScopeRule(
                    font=FontRule(name="宋体", ascii_name="Times New Roman", size=12),
                    paragraph=ParagraphRule(
                        alignment="justify", line_spacing=1.5,
                        first_line_indent_chars=2,
                    ),
                ),
                headings={
                    "h1": ScopeRule(
                        font=FontRule(name="黑体", size=16, bold=True),
                        paragraph=ParagraphRule(alignment="center"),
                    ),
                    "h2": ScopeRule(
                        font=FontRule(name="黑体", size=14, bold=True),
                        paragraph=ParagraphRule(alignment="left"),
                    ),
                },
                page=PageRule(
                    paper="A4", margin_top_cm=2.54, margin_bottom_cm=2.54,
                    margin_left_cm=3.17, margin_right_cm=3.17,
                ),
                heading_structure=HeadingStructureRule(
                    max_level=3, require_numbered=True
                ),
            ),
        ),
        RuleTemplateOut(
            id="business-report",
            name="商务报告",
            description="适用于简洁、可读性优先的商务报告排版。",
            ruleset=RuleSet(
                name="商务报告",
                description="内置模板：商务报告格式",
                body=ScopeRule(
                    font=FontRule(name="微软雅黑", ascii_name="Calibri", size=12),
                    paragraph=ParagraphRule(alignment="justify", line_spacing=1.5),
                ),
                headings={
                    "h1": ScopeRule(
                        font=FontRule(name="微软雅黑", size=16, bold=True),
                        paragraph=ParagraphRule(alignment="left"),
                    ),
                    "h2": ScopeRule(
                        font=FontRule(name="微软雅黑", size=14, bold=True),
                        paragraph=ParagraphRule(alignment="left"),
                    ),
                },
                page=PageRule(
                    paper="A4", margin_top_cm=2.54, margin_bottom_cm=2.54,
                    margin_left_cm=2.54, margin_right_cm=2.54,
                ),
            ),
        ),
        RuleTemplateOut(
            id="meeting-minutes",
            name="会议纪要",
            description="适用于层级清晰、便于归档的会议纪要。",
            ruleset=RuleSet(
                name="会议纪要",
                description="内置模板：会议纪要格式",
                body=ScopeRule(
                    font=FontRule(name="仿宋", size=14),
                    paragraph=ParagraphRule(
                        alignment="justify", line_spacing=1.5,
                        first_line_indent_chars=2,
                    ),
                ),
                headings={
                    "h1": ScopeRule(
                        font=FontRule(name="黑体", size=16, bold=True),
                        paragraph=ParagraphRule(alignment="center"),
                    ),
                    "h2": ScopeRule(
                        font=FontRule(name="黑体", size=14, bold=True),
                        paragraph=ParagraphRule(alignment="left"),
                    ),
                },
                page=PageRule(
                    paper="A4", margin_top_cm=2.54, margin_bottom_cm=2.54,
                    margin_left_cm=2.8, margin_right_cm=2.6,
                ),
                heading_structure=HeadingStructureRule(max_level=3),
            ),
        ),
    ]


def list_rule_templates() -> list[RuleTemplateOut]:
    return _templates()


def get_rule_template(template_id: str) -> RuleTemplateOut | None:
    return next((item for item in _templates() if item.id == template_id), None)
