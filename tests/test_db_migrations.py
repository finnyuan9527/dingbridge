import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("SECURITY__ALLOW_EPHEMERAL_KEYS", "true")

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.config import settings
from app.db import get_engine, get_session
from app.db.migrations import build_alembic_config, ensure_schema_current
from app.db.models import DingTalkAppORM, IdPSettingsORM, OIDCClientORM
from app.db.session import reset_engine
from app.services.config_store import seed_defaults_if_needed


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "dingbridge-test.sqlite3"
        self.db_url = f"sqlite:///{self.db_path}"
        self.database_patch = patch.object(settings.database, "url", self.db_url)
        self.database_patch.start()
        reset_engine()

    def tearDown(self):
        reset_engine()
        self.database_patch.stop()
        self.tmpdir.cleanup()

    def test_uninitialized_database_requires_alembic_upgrade(self):
        with self.assertRaisesRegex(RuntimeError, "alembic upgrade head"):
            ensure_schema_current()

    def test_seed_defaults_after_upgrade_head(self):
        command.upgrade(build_alembic_config(self.db_url), "head")

        ensure_schema_current()
        seed_defaults_if_needed()

        with get_session() as db:
            self.assertIsNotNone(db.get(IdPSettingsORM, 1))
            oidc_clients = db.execute(select(OIDCClientORM)).scalars().all()
            self.assertEqual(len(oidc_clients), 1)
            self.assertEqual(oidc_clients[0].client_id, settings.oidc.client_id)
            self.assertTrue(oidc_clients[0].require_pkce)

    def test_plain_alembic_config_uses_settings_database_url(self):
        default_db_path = Path(self.tmpdir.name) / "wrong-default.sqlite3"
        config = Config(str(Path.cwd() / "alembic.ini"))
        config.set_main_option("script_location", str(Path.cwd() / "alembic"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{default_db_path}")

        command.upgrade(config, "head")

        self.assertFalse(default_db_path.exists(), "Alembic should not migrate the hard-coded/default URL")
        ensure_schema_current()

    def test_upgrade_head_adopts_legacy_create_all_schema(self):
        engine = get_engine()
        IdPSettingsORM.__table__.create(bind=engine)
        DingTalkAppORM.__table__.create(bind=engine)
        OIDCClientORM.__table__.create(bind=engine)

        command.upgrade(build_alembic_config(self.db_url), "head")

        ensure_schema_current()


if __name__ == "__main__":
    unittest.main()
