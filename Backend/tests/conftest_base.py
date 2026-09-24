"""
Shared test setup.

The fake_db.py translation layer is gone. SQLAlchemy speaks SQLite
natively, so the tests now build a real app against an in-memory database
and run the genuine ORM queries - no '%s' to '?' rewriting, no hand-built
connection shim. That is the clearest practical win from the ORM move.
"""
import logging
import os
import unittest

# Several tests make things fail on purpose; the app logs each one with a
# full traceback, which would bury the test results.
logging.disable(logging.CRITICAL)

# Point the app at in-memory SQLite before anything imports the config.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
# 32+ bytes, or PyJWT warns on every token the tests make.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-long-enough-for-hs256")

from app import create_app  # noqa: E402
from models import BILLIARDS, PING_PONG, Match, PoolTable, Player, Rank, db  # noqa: E402

SEED_RANKS = [
    ("Bronze", 0),
    ("Silver", 1100),
    ("Gold", 1300),
    ("Platinum", 1500),
]

# Well clear of the table numbers the older tests use as "some other
# table" (2, 42, 99), so none of them lands on the ping pong table.
PING_PONG_TABLE_ID = 10


class BaseTestCase(unittest.TestCase):
    """Builds a fresh in-memory database for every test."""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True

        self.ctx = self.app.app_context()
        self.ctx.push()

        db.create_all()
        self._seed()

        self.client = self.app.test_client()
        self.addCleanup(self._teardown)

    def _teardown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.ctx.pop()

    def _seed(self):
        for name, min_elo in SEED_RANKS:
            db.session.add(Rank(rank_name=name, min_elo=min_elo))
        db.session.add(PoolTable(table_id=1, table_name="Table 1", league_type=BILLIARDS))
        db.session.add(
            PoolTable(
                table_id=PING_PONG_TABLE_ID, table_name="Ping Pong Table", league_type=PING_PONG
            )
        )
        db.session.commit()

        self.alice = self.add_player("alice")
        self.bob = self.add_player("bob")
        self.carol = self.add_player("carol")

    # --- helpers ---

    def add_player(self, username, elo=1200, ping_pong_elo=1200):
        player = Player(
            username=username,
            first_name="Test",
            last_name="Player",
            password_hash="x",
            elo_rating=elo,
            ping_pong_elo=ping_pong_elo,
        )
        db.session.add(player)
        db.session.commit()
        return player.user_id

    def active_match(self, table_id=1):
        return db.session.scalars(
            db.select(Match).where(
                Match.table_id == table_id,
                Match.match_status == Match.STATUS_ACTIVE,
            )
        ).first()

    def queued_user_ids(self, table_id=1):
        from models import QueueEntry

        return [
            e.user_id
            for e in db.session.scalars(
                db.select(QueueEntry)
                .where(QueueEntry.table_id == table_id)
                .order_by(QueueEntry.queue_position)
            )
        ]

    def make_king(self, user_id, table_id=1):
        """A player who won and holds the table, with no challenger yet."""
        db.session.add(
            Match(
                table_id=table_id,
                player_one_id=user_id,
                player_two_id=None,
                match_status=Match.STATUS_ACTIVE,
            )
        )
        db.session.commit()

    def start_match(self, p1, p2, table_id=1):
        match = Match(
            table_id=table_id,
            player_one_id=p1,
            player_two_id=p2,
            match_status=Match.STATUS_ACTIVE,
        )
        db.session.add(match)
        db.session.commit()
        return match

    def backdate_queue_join(self, user_id, seconds, table_id=1):
        """
        Age a queue entry using the DATABASE's clock, never Python's.

        The whole reason the wait is computed in SQL is that the app
        server's clock never enters into it. A test that mixed the two
        would quietly re-admit the timezone bug it exists to prevent.
        """
        db.session.execute(
            db.text(
                "UPDATE Queue SET joined_at = datetime('now', :offset) "
                "WHERE user_id = :uid AND table_id = :tid"
            ),
            {"offset": f"-{int(seconds)} seconds", "uid": user_id, "tid": table_id},
        )
        db.session.commit()

    def auth_headers(self, user_id):
        from flask_jwt_extended import create_access_token

        with self.app.app_context():
            token = create_access_token(identity=str(user_id))
        return {"Authorization": f"Bearer {token}"}


class ApiTestCase(BaseTestCase):
    """Adds header-carrying request helpers."""

    def login_as(self, user_id):
        self._headers = self.auth_headers(user_id)

    def get(self, url, **kwargs):
        return self.client.get(url, headers=getattr(self, "_headers", {}), **kwargs)

    def post(self, url, **kwargs):
        return self.client.post(url, headers=getattr(self, "_headers", {}), **kwargs)

    def patch(self, url, **kwargs):
        return self.client.patch(url, headers=getattr(self, "_headers", {}), **kwargs)
