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
