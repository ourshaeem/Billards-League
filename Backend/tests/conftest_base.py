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
from models import (  # noqa: E402
    BILLIARDS,
    PING_PONG,
    League,
    LeagueAccess,
    Match,
    PoolTable,
    Player,
    Rank,
    Standing,
    db,
)

SEED_RANKS = [
    ("Bronze", 0),
    ("Silver", 1100),
    ("Gold", 1300),
    ("Platinum", 1500),
]

# Well clear of the table numbers the older tests use as "some other
# table" (2, 42, 99), so none of them lands on the ping pong table.
PING_PONG_TABLE_ID = 10


def make_league(slug, name, game, legacy_key=None, school="CCNY", order=0):
    league = League(
        slug=slug,
        name=name,
        school=school,
        game=game,
        primary_color="#B57EDC",
        secondary_color="#000000",
        legacy_key=legacy_key,
        sort_order=order,
    )
    db.session.add(league)
    db.session.flush()
    return league


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
        # CCNY's two leagues: the ones "billiards" and "ping_pong" mean.
        billiards = make_league("ccny-billiards", "CCNY Billiards", BILLIARDS, BILLIARDS)
        ping_pong = make_league("ccny-ping-pong", "CCNY Ping Pong", PING_PONG, PING_PONG, order=1)
        self.billiards_league_id = billiards.league_id
        self.ping_pong_league_id = ping_pong.league_id
        db.session.add(
            PoolTable(
                table_id=1, table_name="Table 1", league_type=BILLIARDS, league_id=billiards.league_id
            )
        )
        db.session.add(
            PoolTable(
                table_id=PING_PONG_TABLE_ID,
                table_name="Ping Pong Table",
                league_type=PING_PONG,
                league_id=ping_pong.league_id,
            )
        )
        db.session.commit()

        self.alice = self.add_player("alice")
        self.bob = self.add_player("bob")
        self.carol = self.add_player("carol")

    # --- helpers ---

    def add_player(self, username, elo=1200, ping_pong_elo=1200):
        """
        A player in both of CCNY's leagues - with a standing there at these
        ratings, and access, as everyone had before there were PINs.
        """
        player = Player(
            username=username,
            first_name="Test",
            last_name="Player",
            password_hash="x",
        )
        db.session.add(player)
        db.session.flush()
        for league_id, rating in (
            (self.billiards_league_id, elo),
            (self.ping_pong_league_id, ping_pong_elo),
        ):
            # No rank yet, as the old fixtures had: "Unranked" until a game.
            db.session.add(Standing(user_id=player.user_id, league_id=league_id, elo=rating))
            db.session.add(LeagueAccess(user_id=player.user_id, league_id=league_id))
        db.session.commit()
        return player.user_id

    def league_id(self, league=BILLIARDS):
        return {BILLIARDS: self.billiards_league_id, PING_PONG: self.ping_pong_league_id}.get(
            league, league
        )

    def standing(self, user_id, league=BILLIARDS):
        """A player's Standing in one of CCNY's leagues (or any league_id), freshly read."""
        db.session.expire_all()
        return db.session.get(Standing, (user_id, self.league_id(league)))

    def rating(self, user_id, league=BILLIARDS):
        return self.standing(user_id, league).elo

    def record(self, user_id, league=BILLIARDS):
        """(wins, losses)."""
        standing = self.standing(user_id, league)
        return standing.wins, standing.losses

    def set_rating(self, user_id, elo, league=BILLIARDS, wins=None, losses=None):
        standing = self.standing(user_id, league)
        standing.elo = elo
        if wins is not None:
            standing.wins = wins
        if losses is not None:
            standing.losses = losses
        db.session.commit()

    def active_match(self, table_id=1):
        return db.session.scalars(
            db.select(Match).where(
                Match.table_id == table_id,
                Match.match_status == Match.STATUS_ACTIVE,
            )
        ).first()

    def queued_user_ids(self, league=BILLIARDS):
        """Who is in one of CCNY's leagues' line (or any league_id's), in order."""
        from models import QueueEntry

        return [
            e.user_id
            for e in db.session.scalars(
                db.select(QueueEntry)
                .where(QueueEntry.league_id == self.league_id(league))
                .order_by(QueueEntry.queue_position, QueueEntry.queue_id)
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

    def backdate_queue_join(self, user_id, seconds, league=BILLIARDS):
        """
        Age a queue entry using the DATABASE's clock, never Python's.

        The whole reason the wait is computed in SQL is that the app
        server's clock never enters into it. A test that mixed the two
        would quietly re-admit the timezone bug it exists to prevent.
        """
        self._backdate_queue_column("joined_at", user_id, seconds, league)

    def backdate_turn(self, user_id, seconds, league=BILLIARDS):
        """Make a player's turn have come `seconds` ago (the ready check)."""
        self._backdate_queue_column("called_at", user_id, seconds, league)

    def backdate_confirmation(self, user_id, seconds, league=BILLIARDS):
        """Make a player have last said they were here `seconds` ago."""
        self._backdate_queue_column("confirmed_at", user_id, seconds, league)

    def _backdate_queue_column(self, column, user_id, seconds, league):
        db.session.execute(
            db.text(
                f"UPDATE Queue SET {column} = datetime('now', :offset) "
                "WHERE user_id = :uid AND league_id = :lid"
            ),
            {"offset": f"-{int(seconds)} seconds", "uid": user_id, "lid": self.league_id(league)},
        )
        db.session.commit()
        db.session.expire_all()

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
