"""DeepSeek 集成：把自然语言格式要求提取为结构化 JSON 规则。

本模块只做「自然语言 → 结构化规则」，格式合规由 checker.py 的确定性引擎判断。
用户授权的独立文字内容审查位于 deepseek_content.py。
API Key 只存在于后端环境，前端不可见。
"""

from __future__ import annotations

import json
import re

from openai import OpenAI
from pydantic import ValidationError

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
    "paragraph": {"alignment": "left|center|right|justify", "line_spacing_kind": "multiple|exact|atLeast", "line_spacing": 行距倍数或磅数, "space_before": 段前pt, "space_after": 段后pt, "first_line_indent_chars": 首行缩进字符数, "numbered": true/false, "bullet": true/false}
  },
  "title": {与 body 结构相同的 "font"/"paragraph"，用于文档题目或大标题},
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
9. 「题目：黑体、三号字、居中」对应 title.font.name=黑体、size=16、title.paragraph.alignment=center。
10. 「正文：宋体、小四、首行缩进2字、行间距固定值22」对应 body.font.name=宋体、size=12、body.paragraph.first_line_indent_chars=2、line_spacing_kind=exact、line_spacing=22。
11. 「自动」「不限制」「未要求」表示不检查该字段，必须省略或设为 null，绝不能写成 0。
"""

_FONT_SIZES = {"初号": 42, "小初": 36, "一号": 26, "小一": 24, "二号": 22,
               "小二": 18, "三号": 16, "小三": 15, "四号": 14, "小四": 12,
               "五号": 10.5, "小五": 9, "六号": 7.5, "小六": 6.5, "七号": 5.5, "八号": 5}
_UNRESTRICTED = {"自动", "不限制", "不限", "未要求", "默认", "无要求"}


def _numeric(value: object) -> object:
    if isinstance(value, str):
        match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*(?:pt|磅|字|字符|倍)?\s*", value, re.I)
        if match:
            return float(match.group(1))
    return value


def _normalize_rules(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("规则结果不是 JSON 对象")
    data = dict(data)
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        data["name"] = "格式审查规则"
    for alias, target in (("题目", "title"), ("正文", "body")):
        if alias in data:
            value = data.pop(alias)
            data.setdefault(target, value)
    headings = data.get("headings") if isinstance(data.get("headings"), dict) else {}
    for scope_key in ("title", "body", *headings):
        scope = headings.get(scope_key) if scope_key.startswith("h") else data.get(scope_key)
        if not isinstance(scope, dict):
            continue
        font = scope.get("font")
        if isinstance(font, dict) and "size" in font:
            size = font["size"]
            if isinstance(size, str):
                label = size.strip().removesuffix("字")
                if label.startswith("小") and label.endswith("号"):
                    label = label.removesuffix("号")
                font["size"] = _FONT_SIZES.get(label, _numeric(size))
        paragraph = scope.get("paragraph")
        if not isinstance(paragraph, dict):
            continue
        alignments = {"居中": "center", "左对齐": "left", "右对齐": "right", "两端对齐": "justify"}
        if isinstance(paragraph.get("alignment"), str):
            paragraph["alignment"] = alignments.get(paragraph["alignment"].strip(), paragraph["alignment"])
        kinds = {"固定值": "exact", "固定": "exact", "最小值": "atLeast", "倍数": "multiple"}
        if isinstance(paragraph.get("line_spacing_kind"), str):
            paragraph["line_spacing_kind"] = kinds.get(paragraph["line_spacing_kind"].strip(), paragraph["line_spacing_kind"])
        spacing = paragraph.get("line_spacing")
        if isinstance(spacing, str):
            match = re.fullmatch(r"\s*(固定值|固定|最小值|倍数)\s*([\d.]+)\s*(?:磅|pt|倍)?\s*", spacing, re.I)
            if match:
                paragraph["line_spacing_kind"] = kinds[match.group(1)]
                paragraph["line_spacing"] = float(match.group(2))
        for key in ("line_spacing", "space_before", "space_after", "first_line_indent_chars"):
            value = paragraph.get(key)
            if isinstance(value, str) and value.strip() in _UNRESTRICTED:
                paragraph[key] = None
            elif value is not None:
                paragraph[key] = _numeric(value)
    return data


def _honor_unrestricted_text(data: dict, natural_language: str) -> None:
    """明确写了「自动」的字段，不能因模型猜成 0 而变成约束。"""
    sections = list(re.finditer(r"(题目|大标题|正文)\s*[：:]", natural_language))
    for index, match in enumerate(sections):
        text = natural_language[match.end():sections[index + 1].start() if index + 1 < len(sections) else None]
        scope_key = "body" if match.group(1) == "正文" else "title"
        scope = data.get(scope_key)
        if not isinstance(scope, dict):
            continue
        if not isinstance(scope.get("paragraph"), dict):
            scope["paragraph"] = {}
        paragraph = scope["paragraph"]
        fixed_spacing = re.search(r"(?:行间距|行距)\s*[：:]?\s*(?:为|设为)?\s*(固定值|固定|最小值)\s*(\d+(?:\.\d+)?)", text)
        if fixed_spacing:
            paragraph["line_spacing_kind"] = "atLeast" if fixed_spacing.group(1) == "最小值" else "exact"
            paragraph["line_spacing"] = float(fixed_spacing.group(2))
        for label, field in (("段前", "space_before"), ("段后", "space_after"), ("行间距|行距", "line_spacing")):
            if re.search(rf"(?:{label})(?:间距)?\s*[：:]?\s*(?:为|设为)?\s*(?:自动|不限制|不限)", text):
                paragraph[field] = None


def _parse_response(response: object, natural_language: str) -> RuleSet:
    if not response.choices:
        raise ValueError("规则提取未返回结果")
    content = (response.choices[0].message.content or "").strip()
    if response.choices[0].finish_reason != "stop":
        raise ValueError("规则提取结果不完整")
    try:
        data = _normalize_rules(json.loads(content))
    except json.JSONDecodeError as exc:
        raise ValueError("规则不是有效 JSON") from exc
    _honor_unrestricted_text(data, natural_language)
    try:
        ruleset = RuleSet.model_validate(data)
    except ValidationError as exc:
        fields = "、".join(".".join(map(str, error["loc"])) for error in exc.errors()[:4])
        raise ValueError(f"规则字段不合法：{fields}") from exc
    if not ruleset.has_constraints():
        raise ValueError("未识别到可检查的格式要求")
    return ruleset

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
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": natural_language}]
    with _client() as client:
        for attempt in range(2):
            response = client.chat.completions.create(
                model=settings.deepseek_model, temperature=0, max_tokens=6000,
                response_format={"type": "json_object"}, messages=messages,
            )
            try:
                return _parse_response(response, natural_language)
            except ValueError as exc:
                if attempt:
                    raise
                messages.append({"role": "user", "content": f"上次提取未通过校验（{exc}）。请重新输出完整 JSON；未指定的字段用 null，题目与正文分别放 title 和 body。"})
    raise ValueError("规则提取失败")
