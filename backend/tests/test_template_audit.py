"""填写样例模板的配置、审查、版本和可控修订闭环。"""

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.schemas.template_audit import TemplateFieldRule
from app.services.template_audit import draft_field_requirements, extract_template_configuration, review_against_template


def _set_logical_end_alignment(paragraph) -> None:
    """模拟新版 Word 产生、旧版 python-docx 枚举不认识的合法对齐值。"""
    ppr = paragraph._p.get_or_add_pPr()
    jc = ppr.find(qn("w:jc"))
    if jc is None:
        jc = OxmlElement("w:jc")
        ppr.append(jc)
    jc.set(qn("w:val"), "end")


def _template_bytes(title: str = "申请表") -> bytes:
    doc = Document()
    heading = doc.add_paragraph(title)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph("张三")
    doc.add_paragraph("33")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "关系"
    table.cell(0, 1).text = "姓名"
    table.cell(1, 0).text = "兄长"
    table.cell(1, 1).text = "张三"
    _set_logical_end_alignment(table.cell(1, 1).paragraphs[0])
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def _target_bytes() -> bytes:
    doc = Document()
    heading = doc.add_paragraph("报名表")
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph("李四")
    doc.add_paragraph("三十三")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "关系"
    table.cell(0, 1).text = "姓名"
    table.cell(1, 0).text = "兄长"
    table.cell(1, 1).text = "李四"
    _set_logical_end_alignment(table.cell(1, 1).paragraphs[0])
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def _person_form_bytes(name: str, age: str, political_status: str) -> bytes:
    doc = Document()
    table = doc.add_table(rows=1, cols=6)
    for cell, value in zip(
        table.rows[0].cells,
        ("姓名", name, "年龄", age, "政治面貌", political_status),
        strict=True,
    ):
        cell.text = value
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def _mixed_form_bytes(email: str = "1105240000@qq.com", people: str = "6人") -> bytes:
    doc = Document()
    table = doc.add_table(rows=2, cols=6)
    for row, values in enumerate((
        ("姓名", "李四", "民族", "汉", "电子邮件", email),
        ("家庭人口数", people, "生源类别", "统招", "手机号码", "13800138000"),
    )):
        for cell, value in zip(table.rows[row].cells, values, strict=True):
            cell.text = value
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def test_field_detection_keeps_labels_separate_from_adjacent_values(tmp_path) -> None:
    path = tmp_path / "mixed-form.docx"
    path.write_bytes(_mixed_form_bytes())
    config = extract_template_configuration(path)
    blocks = {block.text: block for block in config.blocks if block.text}

    assert blocks["电子邮件"].mode == "fixed"
    assert blocks["1105240000@qq.com"].label == "电子邮件"
    assert blocks["1105240000@qq.com"].data_type == "email"
    assert blocks["汉"].label == "民族"
    assert blocks["6人"].label == "家庭人口数"
    assert blocks["6人"].data_type == "number"
    assert blocks["统招"].label == "生源类别"


def test_field_detection_marks_unidentified_sample_value_for_confirmation(tmp_path) -> None:
    doc = Document()
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "自定义项"
    doc.tables[0].cell(0, 1).text = "普通填写内容"
    path = tmp_path / "uncertain.docx"
    doc.save(path)

    config = extract_template_configuration(path)
    value = next(block for block in config.blocks if block.text == "普通填写内容")
    assert value.mode == "variable"
    assert value.label == value.location
    assert value.recognition_confidence == "low"
    assert value.required is False


def test_requirement_draft_reports_unsupported_instead_of_claiming_success() -> None:
    draft = draft_field_requirements("必须填写；邮箱必须是有效格式；家庭人口数为1-10人；只能填男、女；内容真实")
    assert draft.required is True
    assert [rule.kind for rule in draft.rules] == ["email", "number_range", "allowed_values"]
    assert draft.unsupported == ["内容真实"]


def test_draft_exact_value_forbidden_abbreviation_and_explicit_unit() -> None:
    draft = draft_field_requirements(
        "人数要写6人不能写6；政治面貌为共青团员时不能够填写团员；数字后必须带人字"
    )
    assert [rule.kind for rule in draft.rules] == ["exact_text", "forbidden_value", "number_with_unit"]
    assert draft.rules[0].text == "6人"
    assert draft.rules[1].text == "团员"
    assert draft.rules[1].replacement_text == "共青团员"
    assert draft.rules[2].text == "人"
    assert not draft.unsupported


def test_units_are_checked_only_when_field_rule_explicitly_requires_them(tmp_path) -> None:
    template_path = tmp_path / "sample.docx"
    target_path = tmp_path / "target.docx"
    template_path.write_bytes(_mixed_form_bytes(people="6人"))
    target_path.write_bytes(_mixed_form_bytes(people="6"))
    config = extract_template_configuration(template_path)
    people = next(block for block in config.blocks if block.text == "6人")
    assert not [issue for issue in review_against_template(config, target_path).issues
                if issue.category == "填写要求" and issue.template_block_id == people.id]
    people.rules = [TemplateFieldRule(kind="exact_text", text="6人")]
    issues = [issue for issue in review_against_template(config, target_path).issues
              if issue.category == "填写要求" and issue.template_block_id == people.id]
    assert len(issues) == 1
    assert issues[0].actual == "6"
    assert issues[0].recommended_replacement == "6人"
    assert not issues[0].repairable
    people.rules = [TemplateFieldRule(kind="number_with_unit", text="人")]
    assert len([issue for issue in review_against_template(config, target_path).issues
                if issue.category == "填写要求" and issue.template_block_id == people.id]) == 1


def test_forbidden_short_form_does_not_reject_full_political_status(tmp_path) -> None:
    template_path = tmp_path / "politics.docx"
    target_path = tmp_path / "politics-target.docx"
    template_path.write_bytes(_person_form_bytes("李四", "22", "共青团员"))
    target_path.write_bytes(_person_form_bytes("李四", "22", "团员"))
    config = extract_template_configuration(template_path)
    block = next(block for block in config.blocks if block.label == "政治面貌" and block.mode == "variable")
    block.rules = [TemplateFieldRule(kind="forbidden_value", text="团员", replacement_text="共青团员")]
    issues = [issue for issue in review_against_template(config, target_path).issues
              if issue.category == "填写要求" and issue.template_block_id == block.id]
    assert len(issues) == 1
    assert issues[0].recommended_replacement == "共青团员"
    assert not issues[0].repairable
    template_path.write_bytes(_person_form_bytes("李四", "22", "共青团员"))
    assert not [issue for issue in review_against_template(config, template_path).issues
                if issue.category == "填写要求" and issue.template_block_id == block.id]


def test_review_checks_published_field_requirements(tmp_path) -> None:
    template_path = tmp_path / "template.docx"
    target_path = tmp_path / "target.docx"
    template_path.write_bytes(_mixed_form_bytes())
    target_path.write_bytes(_mixed_form_bytes(email="wrong-address", people="12人"))
    config = extract_template_configuration(template_path)
    for block in config.blocks:
        if block.text == "1105240000@qq.com":
            block.rules = [TemplateFieldRule(kind="email")]
        if block.text == "6人":
            block.rules = [TemplateFieldRule(kind="number_range", min_value=1, max_value=10)]
    result = review_against_template(config, target_path)
    requirement_issues = [issue for issue in result.issues if issue.category == "填写要求"]
    assert len(requirement_issues) == 2
    assert {issue.actual for issue in requirement_issues} == {"wrong-address", "12人"}
    assert all(issue.document_content_index is not None for issue in requirement_issues)


def test_review_checks_allowed_values_and_same_as_without_auto_repair(tmp_path) -> None:
    template = Document()
    table = template.add_table(rows=1, cols=4)
    for cell, value in zip(table.rows[0].cells, ("姓名", "张三", "成员姓名", "张三"), strict=True):
        cell.text = value
    template_path = tmp_path / "matching.docx"
    template.save(template_path)
    config = extract_template_configuration(template_path)
    name_blocks = [block for block in config.blocks if block.text == "张三"]
    assert len(name_blocks) == 2
    name_blocks[0].rules = [TemplateFieldRule(kind="same_as", other_block_id=name_blocks[1].id)]
    name_blocks[1].rules = [TemplateFieldRule(kind="allowed_values", options=["张三", "王五"])]

    target = Document()
    table = target.add_table(rows=1, cols=4)
    for cell, value in zip(table.rows[0].cells, ("姓名", "李四", "成员姓名", "赵六"), strict=True):
        cell.text = value
    target_path = tmp_path / "not-matching.docx"
    target.save(target_path)
    result = review_against_template(config, target_path)
    issues = [issue for issue in result.issues if issue.category == "填写要求"]
    assert len(issues) == 2
    assert {issue.actual for issue in issues} == {"李四", "赵六"}
    assert all(not issue.repairable for issue in issues)


def _upload_template(client, headers, workspace, content: bytes, name="申请模板"):
    response = client.post(
        "/api/template-audits/template",
        params={"workspace_id": workspace, "filename": "template.docx", "name": name},
        content=content,
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_template_review_distinguishes_fixed_and_variable_and_repairs(client, auth, workspace) -> None:
    headers, _ = auth
    template = _upload_template(client, headers, workspace, _template_bytes())
    blocks = template["config"]["blocks"]
    for block in blocks:
        if block["id"] == "p:0":
            block.update(label="表单标题", mode="fixed", required=True, data_type="text", check_format=True)
        elif block["id"] == "p:1":
            block.update(label="申请人姓名", mode="variable", required=True, data_type="text", check_format=False)
        elif block["id"] == "p:2":
            block.update(label="年龄", mode="variable", required=True, data_type="number", check_format=False)
        elif block["row_index"] == 1:
            block.update(mode="variable", required=True, data_type="text", check_format=False)
    update = client.put(
        "/api/template-audits/current",
        json={
            "workspace_id": workspace,
            "name": "申请模板",
            "check_page": True,
            "blocks": [{key: block[key] for key in ("id", "label", "mode", "required", "data_type", "check_format")} for block in blocks],
        },
        headers=headers,
    )
    assert update.status_code == 200, update.text

    uploaded = client.post(
        "/api/documents",
        params={"workspace_id": workspace, "filename": "target.docx"},
        content=_target_bytes(),
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]
    reviewed = client.post(
        "/api/template-audits/reviews",
        json={"workspace_id": workspace, "document_id": document_id},
        headers=headers,
    )
    assert reviewed.status_code == 201, reviewed.text
    result = reviewed.json()
    assert any(issue["category"] == "固定内容" and issue["recommended_replacement"] == "申请表" for issue in result["issues"])
    assert any(issue["category"] == "字段规范" and issue["actual"] == "三十三" for issue in result["issues"])
    assert not any(issue.get("actual") == "李四" and issue["category"] == "固定内容" for issue in result["issues"])

    fixed_index = next(index for index, issue in enumerate(result["issues"]) if issue["category"] == "固定内容")
    age_index = next(index for index, issue in enumerate(result["issues"]) if issue["category"] == "字段规范")
    revised = client.post(
        f"/api/documents/{document_id}/revised-copy",
        json={
            "workspace_id": workspace,
            "format_violation_indexes": [],
            "content_fixes": [],
            "template_fixes": [
                {"review_id": result["id"], "issue_index": fixed_index, "replacement_text": "申请表"},
                {"review_id": result["id"], "issue_index": age_index, "replacement_text": "33"},
            ],
        },
        headers=headers,
    )
    assert revised.status_code == 200, revised.text
    revised_doc = Document(io.BytesIO(revised.content))
    assert revised_doc.paragraphs[0].text == "申请表"
    assert revised_doc.paragraphs[1].text == "李四"
    assert revised_doc.paragraphs[2].text == "33"
    assert "修订清单" in [paragraph.text for paragraph in revised_doc.paragraphs]


def test_template_versions_can_be_reactivated(client, auth, workspace) -> None:
    headers, _ = auth
    first = _upload_template(client, headers, workspace, _template_bytes("模板一"), "模板一")
    second = _upload_template(client, headers, workspace, _template_bytes("模板二"), "模板二")
    assert first["version"] == 1
    assert second["version"] == 2
    versions = client.get(
        "/api/template-audits/versions", params={"workspace_id": workspace}, headers=headers
    ).json()
    assert [item["version"] for item in versions] == [2, 1]
    restored = client.post(
        f"/api/template-audits/versions/{first['id']}/activate",
        params={"workspace_id": workspace}, headers=headers,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["version"] == 1
    current = client.get(
        "/api/template-audits/current", params={"workspace_id": workspace}, headers=headers
    )
    assert current.json()["id"] == first["id"]


def test_unpublished_template_cannot_review(client, auth, workspace) -> None:
    headers, _ = auth
    template = _upload_template(client, headers, workspace, _template_bytes())
    assert template["is_published"] is False
    uploaded = client.post(
        "/api/documents",
        params={"workspace_id": workspace, "filename": "target.docx"},
        content=_target_bytes(),
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    response = client.post(
        "/api/template-audits/reviews",
        json={"workspace_id": workspace, "document_id": uploaded.json()["id"]},
        headers=headers,
    )
    assert response.status_code == 400
    assert "保存发布" in response.json()["detail"]


def test_form_labels_are_fixed_but_filled_examples_are_variable(client, auth, workspace) -> None:
    headers, _ = auth
    template = _upload_template(
        client, headers, workspace, _person_form_bytes("张三", "20岁", "群众"), "人员信息表"
    )
    blocks = {block["text"]: block for block in template["config"]["blocks"] if block["text"]}
    assert blocks["姓名"]["mode"] == "fixed"
    assert blocks["张三"]["mode"] == "variable"
    assert blocks["张三"]["label"] == "姓名"
    assert blocks["年龄"]["mode"] == "fixed"
    assert blocks["20岁"]["mode"] == "variable"
    assert blocks["20岁"]["data_type"] == "number"
    assert blocks["政治面貌"]["mode"] == "fixed"
    assert blocks["群众"]["mode"] == "variable"
    assert blocks["群众"]["label"] == "政治面貌"

    update_blocks = template["config"]["blocks"]
    published = client.put(
        "/api/template-audits/current",
        json={
            "workspace_id": workspace,
            "name": "人员信息表",
            "check_page": False,
            "blocks": [{key: block[key] for key in ("id", "label", "mode", "required", "data_type", "check_format")} for block in update_blocks],
        },
        headers=headers,
    )
    assert published.status_code == 200, published.text
    uploaded = client.post(
        "/api/documents",
        params={"workspace_id": workspace, "filename": "李四.docx"},
        content=_person_form_bytes("李四", "21", "共青团员"),
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    reviewed = client.post(
        "/api/template-audits/reviews",
        json={"workspace_id": workspace, "document_id": uploaded.json()["id"]},
        headers=headers,
    )
    assert reviewed.status_code == 201, reviewed.text
    issues = reviewed.json()["issues"]
    assert not any(issue["category"] == "固定内容" and issue["expected"] in {"张三", "20岁", "群众"} for issue in issues)

    # 已有模板可以重新识别，不需要重新上传；新结果要求用户再次确认发布。
    update_blocks = published.json()["config"]["blocks"]
    next(block for block in update_blocks if block["text"] == "张三")["mode"] = "fixed"
    changed = client.put(
        "/api/template-audits/current",
        json={
            "workspace_id": workspace,
            "name": "人员信息表",
            "check_page": False,
            "blocks": [{key: block[key] for key in ("id", "label", "mode", "required", "data_type", "check_format")} for block in update_blocks],
        },
        headers=headers,
    )
    assert changed.status_code == 200
    reanalyzed = client.post(
        "/api/template-audits/current/reanalyze",
        params={"workspace_id": workspace}, headers=headers,
    )
    assert reanalyzed.status_code == 200, reanalyzed.text
    refreshed = {block["text"]: block for block in reanalyzed.json()["config"]["blocks"] if block["text"]}
    assert refreshed["张三"]["mode"] == "variable"
    assert reanalyzed.json()["is_published"] is False
