"""旧 SQLite 数据库应在启动时补齐新增列且保留已有数据。"""

from sqlalchemy import create_engine, inspect, text

from app.migrations import apply_compatibility_migrations


def test_adds_is_published_to_legacy_document_templates() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE document_templates ("
            "id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL"
            ")"
        ))
        connection.execute(text(
            "INSERT INTO document_templates (id, name) VALUES (1, '旧模板')"
        ))

    apply_compatibility_migrations(engine)
    apply_compatibility_migrations(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("document_templates")}
    assert "is_published" in columns
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT name, is_published FROM document_templates WHERE id = 1"
        )).one()
    assert row.name == "旧模板"
    assert row.is_published == 0
