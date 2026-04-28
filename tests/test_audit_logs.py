import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECURITY__ALLOW_EPHEMERAL_KEYS", "true")

from alembic import command
from sqlalchemy import select

from app.config import settings
from app.db import get_session
from app.db.migrations import build_alembic_config
from app.db.models import AuditLogORM
from app.db.session import reset_engine
from app.models.user import User
from app.security import audit


class AuditLogPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "dingbridge-audit.sqlite3"
        self.db_url = f"sqlite:///{self.db_path}"
        self.database_patch = patch.object(settings.database, "url", self.db_url)
        self.database_patch.start()
        reset_engine()
        command.upgrade(build_alembic_config(self.db_url), "head")

    def tearDown(self):
        reset_engine()
        self.database_patch.stop()
        self.tmpdir.cleanup()

    def test_login_success_is_persisted(self):
        audit.log_login_success(
            user=User(subject="user-1", name="Alice", email="alice@example.com", groups=["engineering"]),
            source="session",
            client_id="client-a",
            ip="127.0.0.1",
        )

        with get_session() as db:
            rows = db.execute(select(AuditLogORM)).scalars().all()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].event, "login_success")
        self.assertEqual(rows[0].level, "info")
        self.assertEqual(rows[0].source, "session")
        self.assertEqual(rows[0].client_id, "client-a")
        self.assertEqual(rows[0].ip, "127.0.0.1")
        self.assertEqual(rows[0].user_sub, "user-1")
        self.assertEqual(rows[0].user_name, "Alice")
        self.assertEqual(rows[0].user_email, "alice@example.com")
        self.assertEqual(rows[0].user_groups, ["engineering"])
        self.assertIsNone(rows[0].reason)
        self.assertEqual(rows[0].details, {})

    def test_token_issued_persists_scope_details(self):
        audit.log_token_issued(
            user=User(subject="user-2", name="Bob"),
            client_id="client-b",
            scope="openid profile email",
            ip="10.0.0.8",
        )

        with get_session() as db:
            row = db.execute(select(AuditLogORM)).scalars().one()

        self.assertEqual(row.event, "token_issued")
        self.assertEqual(row.level, "info")
        self.assertEqual(row.client_id, "client-b")
        self.assertEqual(row.details, {"scope": "openid profile email"})

    def test_async_login_success_uses_threadpool(self):
        with patch("app.security.audit.run_in_threadpool", new_callable=AsyncMock) as threadpool:
            audit_user = User(subject="user-3")

            import asyncio

            asyncio.run(
                audit.log_login_success_async(
                    user=audit_user,
                    source="oidc_authorize",
                    client_id="client-c",
                    ip="127.0.0.1",
                )
            )

        threadpool.assert_awaited_once()
        self.assertIs(threadpool.await_args.args[0], audit.log_login_success)
        self.assertEqual(threadpool.await_args.kwargs["user"], audit_user)
        self.assertEqual(threadpool.await_args.kwargs["client_id"], "client-c")


if __name__ == "__main__":
    unittest.main()
