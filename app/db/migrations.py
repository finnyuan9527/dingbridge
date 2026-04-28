from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.config import settings
from app.db.session import get_engine


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_alembic_config(database_url: str | None = None) -> Config:
    root = _repo_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.attributes["database_url"] = database_url or settings.database.url
    config.set_main_option("sqlalchemy.url", database_url or settings.database.url)
    return config


def get_head_revision() -> str:
    script = ScriptDirectory.from_config(build_alembic_config())
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one Alembic head revision, got {len(heads)}")
    return heads[0]


def get_current_revision() -> str | None:
    engine = get_engine()
    inspector = inspect(engine)
    if not inspector.has_table("alembic_version"):
        return None

    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
    return row[0] if row else None


def ensure_schema_current() -> None:
    current_revision = get_current_revision()
    if current_revision is None:
        raise RuntimeError("database schema is not initialized; run `alembic upgrade head` before starting dingbridge")

    head_revision = get_head_revision()
    if current_revision != head_revision:
        raise RuntimeError(
            f"database schema revision {current_revision} is behind head {head_revision}; "
            "run `alembic upgrade head` before starting dingbridge"
        )
