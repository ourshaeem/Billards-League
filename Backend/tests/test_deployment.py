"""
Running on the internet: a brand-new RDS database, the PyMySQL driver,
configuration from environment variables, and refusing to start with
settings that would be unsafe in production.
"""
import os
import unittest
from unittest import mock

import pymysql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from tests.conftest_base import ApiTestCase, BaseTestCase
from app import create_app, cors_origins
from database import (
    DEFAULT_RANKS,
    MYSQL_DEADLOCK,
    check_schema,
    ensure_schema,
    get_database_uri,
    mysql_error_code,
    prepare_database,
    retry_on_deadlock,
)
from models import PING_PONG, Player, PoolTable, Rank, db

LONG_SECRET = "a-production-secret-that-is-long-enough-1234"


class EmptyDatabase(ApiTestCase):
    """A fresh RDS instance has no tables at all."""

    def test_ensure_schema_builds_an_empty_database_ready_to_play(self):
        db.session.remove()
        db.drop_all()
        self.assertEqual(db.inspect(db.engine).get_table_names(), [])

        ensure_schema()

        self.assertTrue(check_schema())
        ranks = db.session.scalars(db.select(Rank).order_by(Rank.min_elo)).all()
        self.assertEqual([(r.rank_name, r.min_elo) for r in ranks], DEFAULT_RANKS)
        self.assertIsNotNone(db.session.get(PoolTable, 1))
        self.assertIsNotNone(
            db.session.scalar(db.select(PoolTable).where(PoolTable.league_type == PING_PONG))
        )

        # And the app works on it from the first request.
        res = self.client.post(
            "/register",
            json={"username": "first", "first_name": "F", "last_name": "P", "password": "hunter22"},
        )
        self.assertEqual(res.status_code, 201)
        first = db.session.scalars(db.select(Player).where(Player.username == "first")).one()
        self.assertEqual(first.rank.rank_name, "Unranked", "the tier a rating of 0 earns")

    def test_rank_tiers_already_there_are_left_alone(self):
        before = db.session.scalar(db.select(db.func.count()).select_from(Rank))

        ensure_schema()

        after = db.session.scalar(db.select(db.func.count()).select_from(Rank))
        self.assertEqual(before, after)

    def prepare(self):
        return prepare_database(self.app, require_connection=True)

    def test_prepare_database_says_plainly_when_it_cant_connect(self):
        refused = OperationalError("SELECT 1", {}, Exception("refused"))
        with mock.patch.object(db.session, "execute", side_effect=refused):
            with self.assertRaises(RuntimeError) as caught:
                self.prepare()
        self.assertIn("Can't reach the database", str(caught.exception))

    def test_prepare_database_reports_a_healthy_database(self):
        self.assertTrue(self.prepare())

    def test_the_prepare_db_command_gunicorn_runs(self):
        """What the container runs before starting its workers."""
        runner = self.app.test_cli_runner()

        ok = runner.invoke(args=["prepare-db"])
        self.assertEqual(ok.exit_code, 0, ok.output)

        refused = OperationalError("SELECT 1", {}, Exception("refused"))
        with mock.patch.object(db.session, "execute", side_effect=refused):
            failed = runner.invoke(args=["prepare-db"])
        self.assertEqual(failed.exit_code, 1)
        self.assertIn("Can't reach the database", failed.output)


class DeadlockCodesFromEitherDriver(unittest.TestCase):
    def test_pymysql_keeps_the_code_in_args(self):
        error = OperationalError("UPDATE ...", {}, pymysql.err.OperationalError(MYSQL_DEADLOCK, "Deadlock found"))
        self.assertEqual(mysql_error_code(error), MYSQL_DEADLOCK)

    def test_a_pymysql_deadlock_is_retried(self):
        calls = []

        @retry_on_deadlock
        def flaky():
            calls.append(1)
            if len(calls) < 2:
                raise OperationalError(
                    "UPDATE ...", {}, pymysql.err.OperationalError(MYSQL_DEADLOCK, "Deadlock found")
                )
            return "done"

        with mock.patch("database.db.session.rollback"):
            self.assertEqual(flaky(), "done")
        self.assertEqual(len(calls), 2)

    def test_an_error_without_a_code(self):
        self.assertIsNone(mysql_error_code(OperationalError("x", {}, Exception("no code"))))


class DatabaseUrl(unittest.TestCase):
    def uri(self, env):
        keep = {k: v for k, v in os.environ.items() if not k.startswith("DB_") and k not in ("DATABASE_URL", "APP_ENV")}
        with mock.patch.dict(os.environ, {**keep, **env}, clear=True):
            return get_database_uri()

    def test_database_url_wins(self):
        url = "mysql+pymysql://u:p@db.example.com:3306/league"
        self.assertEqual(self.uri({"DATABASE_URL": url}), url)

    def test_a_plain_mysql_url_is_given_the_installed_driver(self):
        uri = self.uri({"DATABASE_URL": "mysql://u:p@db.example.com:3306/league"})
        self.assertEqual(uri, "mysql+pymysql://u:p@db.example.com:3306/league")

    def test_the_rds_certificate_option_reaches_the_driver_as_tls_settings(self):
        uri = self.uri({"DATABASE_URL": "mysql+pymysql://u:p@db.example.com:3306/league?ssl_ca=/app/certs/rds-global-bundle.pem"})
        url = make_url(uri)
        _args, kwargs = url.get_dialect()().create_connect_args(url)
        self.assertEqual(kwargs["ssl"], {"ca": "/app/certs/rds-global-bundle.pem"})

    def test_pieces_are_assembled_safely_even_with_awkward_passwords(self):
        uri = self.uri({"DB_HOST": "db.example.com", "DB_PASSWORD": "p@ss/w#rd:1", "DB_USER": "admin"})
        url = make_url(uri)
        self.assertEqual(url.drivername, "mysql+pymysql")
        self.assertEqual((url.host, url.username, url.password), ("db.example.com", "admin", "p@ss/w#rd:1"))

    def test_local_development_falls_back_to_this_machines_mysql(self):
        url = make_url(self.uri({}))
        self.assertEqual((url.host, url.port, url.database), ("127.0.0.1", 3306, "ranked_billards"))

    def test_production_refuses_to_guess_a_database(self):
        with self.assertRaises(RuntimeError) as caught:
            self.uri({"APP_ENV": "production"})
        self.assertIn("DATABASE_URL", str(caught.exception))


class ProductionSettings(BaseTestCase):
    def build(self, env):
        with mock.patch.dict(os.environ, env):
            if "JWT_SECRET_KEY" not in env:
                os.environ.pop("JWT_SECRET_KEY", None)
            return create_app()

    def test_production_refuses_to_start_without_a_signing_key(self):
        with self.assertRaises(RuntimeError) as caught:
            self.build({"APP_ENV": "production"})
        self.assertIn("JWT_SECRET_KEY", str(caught.exception))

    def test_production_refuses_the_key_committed_to_the_repo_or_a_short_one(self):
        for secret in ("super-secret-pool-key-change-in-production", "short"):
            with self.assertRaises(RuntimeError, msg=secret):
                self.build({"APP_ENV": "production", "JWT_SECRET_KEY": secret})

    def test_production_starts_with_a_real_key_and_database(self):
        app = self.build({"APP_ENV": "production", "JWT_SECRET_KEY": LONG_SECRET})
        self.assertEqual(app.config["JWT_SECRET_KEY"], LONG_SECRET)


class Cors(BaseTestCase):
    def preflight(self, app, origin):
        return app.test_client().options(
            "/queue/join",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )

    def test_any_origin_is_allowed_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CORS_ORIGINS", None)
            app = create_app()
        res = self.preflight(app, "http://10.0.2.2:8081")
        # Flask-CORS answers "*" by echoing the caller's origin back, which
        # grants exactly the same thing.
        self.assertIn(res.headers.get("Access-Control-Allow-Origin"), ("*", "http://10.0.2.2:8081"))
        self.assertIn("Authorization", res.headers.get("Access-Control-Allow-Headers", ""))

    def test_origins_can_be_narrowed_later_without_a_code_change(self):
        with mock.patch.dict(os.environ, {"CORS_ORIGINS": "https://league.example.com, http://localhost:5173"}):
            self.assertEqual(cors_origins(), ["https://league.example.com", "http://localhost:5173"])
            app = create_app()
        allowed = self.preflight(app, "https://league.example.com")
        refused = self.preflight(app, "https://elsewhere.example.com")
        self.assertEqual(allowed.headers.get("Access-Control-Allow-Origin"), "https://league.example.com")
        self.assertIsNone(refused.headers.get("Access-Control-Allow-Origin"))


if __name__ == "__main__":
    unittest.main()
