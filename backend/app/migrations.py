"""演示环境的轻量兼容迁移。

项目启动时使用 ``create_all`` 建表，但该方法不会为已经存在的表补充新列。
这里仅维护可重复执行、不会删除数据的已知兼容迁移。
"""

from sqlalchemy import Engine, inspect, text


def apply_compatibility_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    if "document_templates" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("document_templates")}
    if "is_published" in columns:
        return

    default = "FALSE" if engine.dialect.name == "postgresql" else "0"
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE document_templates "
            f"ADD COLUMN is_published BOOLEAN NOT NULL DEFAULT {default}"
        ))
