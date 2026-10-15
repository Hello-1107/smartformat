"""DeepSeek 集成：把自然语言格式要求提取为结构化 JSON 规则。

架构约定：DeepSeek 只做「自然语言 → 结构化规则」这一步，
绝不参与合规判断；合规判断由 checker.py 的确定性引擎完成。
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
4. 行距统一为倍数（如「1.5 倍行距」→ 1.5，「固定值 22 磅」→ 换算约 1.83）。
5. 页边距单位统一为 cm（厘米）；「上下 2.54cm、左右 3.17cm」等直接转数字。
6. 颜色转成 6 位十六进制 RRGGBB（如「黑色」=000000，「红色」=FF0000）。
7. 用户没提到的约束不要编造，对应字段省略。
"""

def _client() -> OpenAI:
    return OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )


def extract_ruleset(natural_language: str) -> RuleSet:
    """调用 DeepSeek 提取规则，失败时抛出异常（由 API 层转成 502）。"""
    client = _client()
    response = client.chat.completions.create(
        model=settings.deepseek_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": natural_language},
        ],
    )
    content = (response.choices[0].message.content or "").strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"DeepSeek 返回内容不是合法 JSON: {content[:200]}") from exc
    ruleset = RuleSet.model_validate(data)
    if not ruleset.name:
        ruleset.name = "未命名规则"
    return ruleset
