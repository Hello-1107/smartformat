"""DeepSeek 集成：把自然语言格式要求提取为结构化 JSON 规则。

本模块只做「自然语言 → 结构化规则」，格式合规由 checker.py 的确定性引擎判断。
用户授权的独立文字内容审查位于 deepseek_content.py。
API Key 只存在于后端环境，前端不可见。
"""

from __future__ import annotations

import json

from openai import OpenAI

from app.config import settings
from app.schemas.rule import RuleSet

_SYSTEM_PROMPT = """\
你是文档格式规范提取器。用户会用自然语言描述一份 Word 文档的格式要求，
你要把它转成严格的 JSON，不要添加用户没提到的约束（没提到的字段一律省略或置 null）。

JSON 结构如下（所有字段都可选，键名必须完全一致）：

{
  "name": "规则简称（简短中文）",
  "description": "可选，一句话说明",
  "body": {
    "font": {"name": "中文字体名", "ascii_name": "西文字体名", "size": 字号pt, "bold": true/false, "italic": true/false, "color": "十六进制RRGGBB"},
    "paragraph": {"alignment": "left|center|right|justify", "line_spacing": 行距倍数如1.5, "space_before": 段前pt, "space_after": 段后pt, "first_line_indent_chars": 首行缩进字符数, "numbered": true/false, "bullet": true/false}
  },
  "headings": {
    "h1": {与 body 结构相同的 "font"/"paragraph"},
    "h2": {...}, "h3": {...}, "h4": {...}, "h5": {...}, "h6": {...}
  },
  "page": {"paper": "A4|A3|A5|Letter", "width_cm": 宽cm, "height_cm": 高cm, "margin_top_cm": 上边距cm, "margin_bottom_cm": 下边距cm, "margin_left_cm": 左边距cm, "margin_right_cm": 右边距cm, "header_distance_cm": 页眉距cm, "footer_distance_cm": 页脚距cm},
  "heading_structure": {"max_level": 1到6的最大标题层级, "require_numbered": true/false}
}

规则：
1. 只输出 JSON 对象，不要输出 Markdown 代码块或任何解释文字。
2. 用户说的「正文」「正文字体」对应 body；「一级标题」对应 h1，以此类推。
3. 字号单位统一为 pt（磅）；「小四」=12pt，「四号」=14pt，「小三」=15pt，「三号」=16pt，「小二」=18pt，「二号」=22pt。
4. 行距保留类型：line_spacing_kind 为 multiple/exact/atLeast，line_spacing 存倍率或磅数；固定 22 磅为 exact、22，不能换算成倍数。
5. 页边距单位统一为 cm（厘米）；「上下 2.54cm、左右 3.17cm」等直接转数字。
6. 颜色转成 6 位十六进制 RRGGBB（如「黑色」=000000，「红色」=FF0000）。
7. 用户没提到的约束不要编造，对应字段省略。
8. 文档大标题对应独立 title，结构与 body 相同；一级标题仍为 headings.h1。
"""

def _client() -> OpenAI:
    return OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=120.0,
        max_retries=0,
    )


def extract_ruleset(natural_language: str) -> RuleSet:
    """调用 DeepSeek 提取规则，失败时抛出异常（由 API 层转成 502）。"""
    if not settings.deepseek_api_key:
        raise ValueError("请在后端配置 DEEPSEEK_API_KEY")
    with _client() as client:
        response = client.chat.completions.create(
            model=settings.deepseek_model, temperature=0, max_tokens=6000,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": natural_language}],
        )
    if not response.choices:
        raise ValueError("规则提取未返回结果，请重试")
    content = (response.choices[0].message.content or "").strip()
    if response.choices[0].finish_reason != "stop":
        raise ValueError("规则提取结果不完整，请缩短要求后重试")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("DeepSeek 返回了无效规则，请重试") from exc
    ruleset = RuleSet.model_validate(data)
    if not ruleset.name:
        ruleset.name = "未命名规则"
    return ruleset
