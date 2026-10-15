"""API 集成测试（DeepSeek 调用被 monkeypatch，保持离线可测）。"""

import io

from docx import Document
from docx.shared import Pt

from app.schemas.rule import FontRule, RuleSet, ScopeRule


def _docx_bytes() -> bytes:
    doc = Document()
    p = doc.add_paragraph("测试正文")
    p.runs[0].font.size = Pt(14)  # 故意与规则(12pt)不一致
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_auth_flow(client) -> None:
    r = client.post(
        "/api/auth/register",
        json={"username": "userb", "password": "secret123", "confirm_password": "secret123"},
    )
    assert r.status_code == 201
    token = r.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "userb"


def test_register_password_mismatch(client) -> None:
    """注册时两次密码不一致必须被拒绝。"""
    r = client.post(
        "/api/auth/register",
        json={
            "username": "mismatch",
            "password": "secret123",
            "confirm_password": "secret456",
        },
    )
    assert r.status_code == 422
    assert "密码不一致" in r.text


def test_register_username_format(client) -> None:
    """账号过短 / 格式非法必须被拒绝。"""
    bad = client.post(
        "/api/auth/register",
        json={"username": "a", "password": "secret123", "confirm_password": "secret123"},
    )
    assert bad.status_code == 422


def test_login_with_username(client) -> None:
    """登录用账号 + 密码；密码错误或账号不存在统一 401。"""
    client.post(
        "/api/auth/register",
        json={"username": "loginuser", "password": "secret123", "confirm_password": "secret123"},
    )
    ok = client.post("/api/auth/login", json={"username": "loginuser", "password": "secret123"})
    assert ok.status_code == 200
    assert ok.json()["user"]["username"] == "loginuser"

    wrong_pwd = client.post(
        "/api/auth/login", json={"username": "loginuser", "password": "wrong-password"}
    )
    assert wrong_pwd.status_code == 401

    missing = client.post("/api/auth/login", json={"username": "nobody", "password": "secret123"})
    assert missing.status_code == 401


def test_duplicate_register(client) -> None:
    data = {"username": "userc", "password": "secret123", "confirm_password": "secret123"}
    assert client.post("/api/auth/register", json=data).status_code == 201
    assert client.post("/api/auth/register", json=data).status_code == 409


def test_workspace_isolation(client, auth) -> None:
    headers, _ = auth
    r = client.post("/api/workspaces", json={"name": "A"}, headers=headers)
    assert r.status_code == 201
    ws_id = r.json()["id"]
    lst = client.get("/api/workspaces", headers=headers)
    assert any(w["id"] == ws_id for w in lst.json())

    # 另一个用户无法访问该工作区
    other = client.post(
        "/api/auth/register",
        json={"username": "userd", "password": "secret123", "confirm_password": "secret123"},
    ).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get(f"/api/workspaces/{ws_id}", headers=other_headers).status_code == 403


def test_document_rule_check_flow(client, auth, workspace, monkeypatch) -> None:
    headers, _ = auth

    # 上传文档（原始二进制体）
    r = client.post(
        "/api/documents",
        params={"workspace_id": workspace, "filename": "sample.docx"},
        content=_docx_bytes(),
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    assert r.json()["parsed"] is not None

    # 生成规则（monkeypatch 掉真实 DeepSeek 调用）
    fixed = RuleSet(name="正文规则", body=ScopeRule(font=FontRule(size=12)))
    monkeypatch.setattr("app.api.rules.extract_ruleset", lambda text: fixed)
    r = client.post(
        "/api/rules",
        json={"workspace_id": workspace, "natural_language": "正文用 12 号字"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    rule_id = r.json()["id"]
    assert r.json()["ruleset"]["body"]["font"]["size"] == 12

    # 执行审查
    r = client.post(
        "/api/checks",
        json={
            "workspace_id": workspace,
            "document_id": doc_id,
            "rule_id": rule_id,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    result = r.json()
    assert result["summary"]["total"] >= 1
    assert any(v["field"] == "size" for v in result["violations"])


def test_batch_check_creates_one_result_per_document(client, auth, workspace, monkeypatch) -> None:
    headers, _ = auth
    document_ids = []
    for filename in ("first.docx", "second.docx"):
        response = client.post(
            "/api/documents",
            params={"workspace_id": workspace, "filename": filename},
            content=_docx_bytes(),
            headers={**headers, "Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 201, response.text
        document_ids.append(response.json()["id"])

    fixed = RuleSet(name="正文规则", body=ScopeRule(font=FontRule(size=12)))
    monkeypatch.setattr("app.api.rules.extract_ruleset", lambda text: fixed)
    rule_response = client.post(
        "/api/rules",
        json={"workspace_id": workspace, "natural_language": "正文用 12 号字"},
        headers=headers,
    )
    assert rule_response.status_code == 201, rule_response.text

    response = client.post(
        "/api/checks/batch",
        json={
            "workspace_id": workspace,
            "document_ids": document_ids,
            "rule_id": rule_response.json()["id"],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["total_documents"] == 2
    assert result["compliant_documents"] == 0
    assert result["violation_total"] >= 2
    assert {item["document_id"] for item in result["checks"]} == set(document_ids)

    history = client.get("/api/checks", params={"workspace_id": workspace}, headers=headers)
    assert history.status_code == 200
    assert len(history.json()) == 2


def test_rule_template_versions_and_restore(client, auth, workspace) -> None:
    headers, _ = auth
    templates = client.get(
        "/api/rules/templates", params={"workspace_id": workspace}, headers=headers
    )
    assert templates.status_code == 200
    assert any(item["id"] == "thesis-standard" for item in templates.json())

    created = client.post(
        "/api/rules/from-template",
        json={"workspace_id": workspace, "template_id": "thesis-standard"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    rule = created.json()
    rule_id = rule["id"]
    assert rule["ruleset"]["body"]["font"]["size"] == 12

    versions = client.get(f"/api/rules/{rule_id}/versions", headers=headers)
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()] == [1]

    updated_ruleset = rule["ruleset"]
    updated_ruleset["name"] = "已修改的论文规范"
    updated_ruleset["body"]["font"]["size"] = 13
    updated = client.put(
        f"/api/rules/{rule_id}/ruleset", json=updated_ruleset, headers=headers
    )
    assert updated.status_code == 200, updated.text

    versions = client.get(f"/api/rules/{rule_id}/versions", headers=headers)
    assert [item["version"] for item in versions.json()] == [2, 1]

    restored = client.put(f"/api/rules/{rule_id}/versions/1/restore", headers=headers)
    assert restored.status_code == 200, restored.text
    assert restored.json()["ruleset"]["name"] == "毕业论文规范"
    assert restored.json()["ruleset"]["body"]["font"]["size"] == 12

    versions = client.get(f"/api/rules/{rule_id}/versions", headers=headers)
    assert [item["version"] for item in versions.json()] == [3, 2, 1]


def test_workspace_templates_can_be_created_applied_and_deleted(client, auth, workspace) -> None:
    headers, _ = auth
    payload = {
        "workspace_id": workspace,
        "name": "团队周报规范",
        "description": "测试用自定义模板",
        "ruleset": {
            "name": "团队周报规范",
            "body": {"font": {"name": "宋体", "size": 12}},
        },
    }
    created = client.post("/api/rules/templates", json=payload, headers=headers)
    assert created.status_code == 201, created.text
    template = created.json()
    assert template["source"] == "workspace"
    assert template["id"].startswith("workspace:")

    templates = client.get(
        "/api/rules/templates", params={"workspace_id": workspace}, headers=headers
    )
    assert any(item["id"] == template["id"] for item in templates.json())
    assert any(item["source"] == "system" for item in templates.json())

    applied = client.post(
        "/api/rules/from-template",
        json={"workspace_id": workspace, "template_id": template["id"]},
        headers=headers,
    )
    assert applied.status_code == 201, applied.text
    assert applied.json()["natural_language"] == "工作区模板：团队周报规范"

    other_workspace = client.post(
        "/api/workspaces", json={"name": "另一工作区"}, headers=headers
    ).json()["id"]
    denied = client.post(
        "/api/rules/from-template",
        json={"workspace_id": other_workspace, "template_id": template["id"]},
        headers=headers,
    )
    assert denied.status_code == 404

    template_id = int(template["id"].split(":", 1)[1])
    assert client.delete(f"/api/rules/templates/{template_id}", headers=headers).status_code == 204
    templates_after = client.get(
        "/api/rules/templates", params={"workspace_id": workspace}, headers=headers
    )
    assert all(item["id"] != template["id"] for item in templates_after.json())


def test_delete_check_history_keeps_other_document_results(client, auth, workspace) -> None:
    headers, _ = auth
    documents = []
    for filename in ("one.docx", "two.docx"):
        uploaded = client.post(
            "/api/documents",
            params={"workspace_id": workspace, "filename": filename},
            content=_docx_bytes(),
            headers={**headers, "Content-Type": "application/octet-stream"},
        )
        assert uploaded.status_code == 201, uploaded.text
        documents.append(uploaded.json()["id"])

    rule = client.post(
        "/api/rules/from-template",
        json={"workspace_id": workspace, "template_id": "business-report"},
        headers=headers,
    )
    assert rule.status_code == 201, rule.text
    results = []
    for document_id in documents:
        response = client.post(
            "/api/checks",
            json={"workspace_id": workspace, "document_id": document_id, "rule_id": rule.json()["id"]},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        results.append(response.json())

    assert client.delete(f"/api/checks/{results[0]['id']}", headers=headers).status_code == 204
    history = client.get("/api/checks", params={"workspace_id": workspace}, headers=headers)
    assert history.status_code == 200
    assert [item["document_id"] for item in history.json()] == [documents[1]]
