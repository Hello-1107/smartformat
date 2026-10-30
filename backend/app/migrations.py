"""演示环境的轻量兼容迁移。

项目启动时使用 ``create_all`` 建表，但该方法不会为已经存在的表补充新列。
这里仅维护可重复执行、不会删除数据的已知兼容迁移。
"""

from sqlalchemy import Engine, inspect, text


def apply_compatibility_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    columns = {table: {column["name"] for column in inspector.get_columns(table)} for table in tables}
    with engine.begin() as connection:
        if "workspaces" in tables and "next_template_version" not in columns["workspaces"]:
            connection.execute(text("ALTER TABLE workspaces ADD COLUMN next_template_version INTEGER NOT NULL DEFAULT 1"))
            if "document_templates" in tables:
                connection.execute(text("UPDATE workspaces SET next_template_version = COALESCE((SELECT MAX(version) + 1 FROM document_templates WHERE workspace_id = workspaces.id), 1)"))
        if "document_templates" in tables and "is_published" not in columns["document_templates"]:
            default = "FALSE" if engine.dialect.name == "postgresql" else "0"
            connection.execute(text("ALTER TABLE document_templates " + f"ADD COLUMN is_published BOOLEAN NOT NULL DEFAULT {default}"))
        if "check_results" in tables and "ruleset_snapshot" not in columns["check_results"]:
            connection.execute(text("ALTER TABLE check_results ADD COLUMN ruleset_snapshot JSON"))
        if "documents" in tables and "pdf_json" not in columns["documents"]:
            connection.execute(text("ALTER TABLE documents ADD COLUMN pdf_json JSON"))
        if "document_templates" in tables and "is_review_active" not in columns["document_templates"]:
            default = "FALSE" if engine.dialect.name == "postgresql" else "0"
            connection.execute(text(f"ALTER TABLE document_templates ADD COLUMN is_review_active BOOLEAN NOT NULL DEFAULT {default}"))
            if "is_active" in columns["document_templates"]:
                connection.execute(text("UPDATE document_templates SET is_review_active = TRUE WHERE is_active = TRUE AND is_published = TRUE"))
        # 早期 SQLite 未启用外键；仅清理已删除来源的记录。
        for table in ("check_results", "content_reviews", "template_reviews"):
            if table in tables and "documents" in tables:
                connection.execute(text(f"DELETE FROM {table} WHERE document_id NOT IN (SELECT id FROM documents)"))
        if "check_results" in tables and "rules" in tables:
            connection.execute(text("DELETE FROM check_results WHERE rule_id NOT IN (SELECT id FROM rules)"))
        if "rule_revisions" in tables and "rules" in tables:
            connection.execute(text("DELETE FROM rule_revisions WHERE rule_id NOT IN (SELECT id FROM rules)"))
