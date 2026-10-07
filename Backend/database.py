"""
Database configuration and startup checks.

SQLAlchemy replaces the hand-rolled connection helper, so this module no
longer opens connections itself - it builds the connection URI and holds
the startup work: ensure_schema() (idempotent, additive: builds an empty
database, fixes up an existing one) and check_schema() (a read-only
report of anything still missing). prepare_database() runs both, once
per start.
"""
import functools
import logging
import os
import random
import time

from sqlalchemy import func, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError

from models import db

log = logging.getLogger(__name__)

# Load Backend/.env if python-dotenv is installed. Optional on purpose: if
# it isn't there, everything falls back to the values below, so this can't
# break a machine that already works.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

# This machine's MySQL, for local development when nothing else is set.
# There is deliberately no password here: it comes from DB_PASSWORD in
# Backend/.env, which git ignores.
# Shaeem reminder: the password that used to be written here is still in
# this repo's git history, and the repo is on GitHub - change it on your
# local MySQL too.
LOCAL_DEFAULTS = {
    "DB_HOST": "127.0.0.1",
    "DB_USER": "root",
    "DB_NAME": "ranked_billards",
    "DB_PORT": "3306",
}

# The driver SQLAlchemy talks to MySQL through. PyMySQL is pure Python,
# so the container needs no compiler and no MySQL client libraries.
MYSQL_DRIVER = "mysql+pymysql"


def is_production():
    """True in the deployed container, which sets APP_ENV=production."""
    return os.environ.get("APP_ENV", "").strip().lower() == "production"


def normalize_database_url(url):
    """
    A plain mysql:// URL - what Railway and most guides hand out - means
    SQLAlchemy's default MySQL driver, mysqlclient, which isn't installed.
    Point it at PyMySQL. A URL naming its driver is left alone.
    """
    if url.startswith("mysql://"):
        return MYSQL_DRIVER + url[len("mysql"):]
    return url


def get_database_uri():
    """
    The SQLAlchemy connection string, from the first of:

      1. DATABASE_URL - the whole string, the way a host such as Render,
         Railway or AWS RDS is usually configured. It's also how the
         tests point everything at in-memory SQLite.
      2. DB_HOST / DB_USER / DB_PASSWORD / DB_NAME / DB_PORT - the pieces,
         for local development, normally from Backend/.env. DB_PASSWORD is
         required (it may be empty, for a MySQL with no password); the
         others fall back to this machine's MySQL.

    The pieces are assembled by SQLAlchemy rather than pasted into a
    string, so a password containing @, / or # still works.

    In production the local fallback is refused. A container quietly
    aiming at its own 127.0.0.1 would fail every request with a
    connection error, instead of failing once, at startup, with a reason.
    """
    override = os.environ.get("DATABASE_URL", "").strip()
    if override:
        return normalize_database_url(override)

    if is_production() and not all(key in os.environ for key in ("DB_HOST", "DB_PASSWORD")):
        raise RuntimeError(
            "APP_ENV is production but no database is configured. Set DATABASE_URL "
            "(see Backend/.env.example), or DB_HOST and DB_PASSWORD."
        )

    if "DB_PASSWORD" not in os.environ:
        raise RuntimeError(
            "No database password is set. Copy Backend/.env.example to "
            "Backend/.env and fill in DB_PASSWORD (or set DATABASE_URL)."
        )

    settings = {key: os.environ.get(key, default) for key, default in LOCAL_DEFAULTS.items()}
    return URL.create(
        MYSQL_DRIVER,
        username=settings["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=settings["DB_HOST"],
        port=int(settings["DB_PORT"]),
        database=settings["DB_NAME"],
    ).render_as_string(hide_password=False)


def describe_database(uri):
    """Where a connection string points, safe to print: no password."""
    url = make_url(uri)
    if url.get_backend_name() == "sqlite":
        return url.render_as_string(hide_password=True)
    return f"{url.host}:{url.port or 3306}/{url.database}"


def configure_app(app):
    """Apply database settings to a Flask app and bind SQLAlchemy to it."""
    app.config["SQLALCHEMY_DATABASE_URI"] = get_database_uri()

    # Event-tracking is off by default in newer versions, but being
    # explicit avoids a startup warning and the memory it would cost.
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # MySQL drops idle connections (wait_timeout, 8 hours by default).
    # Recycling below that, and checking a connection is alive before
    # handing it out, avoids the "MySQL server has gone away" error that
    # otherwise appears on the first request after a quiet night.
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 3600,
    }

    db.init_app(app)
    return app


def check_schema():
    """
    Confirm the database has every table and column the models map.

    Read-only, and driven by the models themselves rather than a
    hand-kept list. The hand-kept list is how the app came to query a
    `player_one_id` column that never existed: the list and the models
    agreed with each other, and neither agreed with the database.

    Never raises - a failed check prints what's wrong and lets the app
    start, so you get a clear message rather than a stack trace.
    """
    try:
        inspector = inspect(db.engine)
        existing = {name.lower(): name for name in inspector.get_table_names()}
        problems = []

        for table in db.metadata.sorted_tables:
            actual_name = existing.get(table.name.lower())
            if actual_name is None:
                problems.append(f"  - table '{table.name}' is missing")
                continue

            present = {c["name"] for c in inspector.get_columns(actual_name)}
            for column in table.columns:
                if column.name not in present:
                    problems.append(f"  - {table.name}.{column.name} is missing")

        if problems:
            print("\nDatabase schema doesn't match what the app expects:")
            print("\n".join(problems))
            print("The app will start, but anything touching those columns will fail.\n")
            return False

        return True

    except Exception as e:
        print(f"[schema] Could not check the database schema: {e}")
        return False


# Columns added since the database was first built, as (table, column,
# definition). Each is added only if missing, and every definition either
# allows NULL or carries a default, so adding one to a table that already
# has rows can't fail. Kept as an explicit list rather than generated from
# the models: an ALTER on the live database should be something a person
# can read before it runs.
ADDED_COLUMNS = [
    ("Queue", "joined_at", "TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP"),
    ("Pool_Tables", "league_type", "VARCHAR(20) NOT NULL DEFAULT 'billiards'"),
    ("Players", "country_flag", "VARCHAR(2) NULL"),
    ("Players", "profile_picture", "VARCHAR(512) NULL"),
    ("Players", "deleted_at", "DATETIME NULL"),
    ("Queue", "called_at", "DATETIME NULL"),
    ("Queue", "confirmed_at", "DATETIME NULL"),
    ("Matches", "cancel_requested_by", "INTEGER NULL"),
    ("Players", "email", "VARCHAR(254) NULL"),
    ("Matches", "loser_elo_change", "INTEGER NULL"),
    ("Players", "is_admin", "BOOLEAN NOT NULL DEFAULT 0"),
    ("Matches", "winner_elo_before", "INTEGER NULL"),
    ("Matches", "loser_elo_before", "INTEGER NULL"),
    ("Pool_Tables", "is_active", "BOOLEAN NOT NULL DEFAULT 1"),
    ("Queue", "league_id", "INTEGER NULL"),
    ("Player_Achievements", "league_id", "INTEGER NULL"),
    ("Queue", "target_table_id", "INTEGER NULL"),
    ("Pool_Tables", "table_record_holder_id", "INTEGER NULL"),
    ("Matches", "removal_vote_at", "DATETIME NULL"),
]
# (Ratings used to be columns on Players - elo_rating, ping_pong_elo and
# the rest - and each league's chosen badge too. They moved to Standings;
# the columns are left in the database as they were, unused, and no
# longer added to a new one.)

# Every league, in the order the apps list them: (slug, name, school,
# game, primary colour, secondary colour, legacy key) - two per school,
# billiards and ping pong, in the school's own colours. CCNY's two are the
# leagues that existed before there were schools - the legacy key is what
# apps from then call them.
#
# A database gets the whole list the first time (ensure_schema's
# add_leagues); a league added here later is added to an existing
# database on its next start (add_new_leagues), with a first table and no
# PIN. Leagues are never removed or recoloured from here: once a league
# exists, it's the database's.
CCNY_LAVENDER = "#B57EDC"
LEAGUES = [
    ("ccny-billiards", "CCNY Billiards", "CCNY", "billiards", CCNY_LAVENDER, "#000000", "billiards"),
    ("ccny-ping-pong", "CCNY Ping Pong", "CCNY", "ping_pong", CCNY_LAVENDER, "#000000", "ping_pong"),
    ("john-jay-billiards", "John Jay Billiards", "John Jay", "billiards", "#232C64", "#00AEEF", None),
    ("john-jay-ping-pong", "John Jay Ping Pong", "John Jay", "ping_pong", "#232C64", "#00AEEF", None),
    ("brooklyn-billiards", "Brooklyn College Billiards", "Brooklyn College", "billiards", "#882345", "#EBB700", None),
    ("brooklyn-ping-pong", "Brooklyn College Ping Pong", "Brooklyn College", "ping_pong", "#882345", "#EBB700", None),
    # Hunter: purple and gold.
    ("hunter-billiards", "Hunter College Billiards", "Hunter College", "billiards", "#3F0157", "#FCB827", None),
    ("hunter-ping-pong", "Hunter College Ping Pong", "Hunter College", "ping_pong", "#3F0157", "#FCB827", None),
    # City Tech: royal blue and goldenrod.
    ("city-tech-billiards", "City Tech Billiards", "City Tech", "billiards", "#003DA5", "#F4AA00", None),
    ("city-tech-ping-pong", "City Tech Ping Pong", "City Tech", "ping_pong", "#003DA5", "#F4AA00", None),
    # Queens College: navy and red.
    ("queens-billiards", "Queens College Billiards", "Queens College", "billiards", "#063358", "#E71939", None),
    ("queens-ping-pong", "Queens College Ping Pong", "Queens College", "ping_pong", "#063358", "#E71939", None),
    # Baruch: navy and light steel blue.
    ("baruch-billiards", "Baruch College Billiards", "Baruch College", "billiards", "#052D4F", "#9FC1E9", None),
    ("baruch-ping-pong", "Baruch College Ping Pong", "Baruch College", "ping_pong", "#052D4F", "#9FC1E9", None),
]
# What a new league's first table is called.
FIRST_TABLE_NAME = "Table 1"

# The name ping pong's first table is given when ensure_schema creates it.
PING_PONG_TABLE_NAME = "Ping Pong Table"

# The tiers a brand-new database starts with: the ones the league has
# always used, as (rank_name, min_elo). Only ever written into an empty
# Ranks table, so tiers someone has edited are never overwritten.
DEFAULT_RANKS = [
    ("Unranked", 0),
    ("Bronze", 200),
    ("Silver", 500),
    ("Gold", 800),
    ("Platinum", 1200),
]


def ensure_schema():
    """
    Bring a database up to what the app needs - an existing one, or a
    brand-new empty one such as a fresh AWS RDS instance. Safe to run on
    every startup: each step checks before it changes anything, and only
    ever adds - no column or table is dropped.

    Steps:
      1. Every table the models map exists. On an empty database this
         builds them all; on an existing one it creates only what's
         missing (Leagues, Standings, League_Access, Pin_Attempts, ...)
         and touches nothing else.
      2. Every column in ADDED_COLUMNS exists, and Queue.table_id allows
         NULL (a queue row names a table only once its player is called).
      3. An empty Ranks table gets the DEFAULT_RANKS tiers.
      4. Table 1, and a ping pong table, exist - what every database had
         before there were schools.
      5. The leagues exist. The first time - an empty Leagues table - this
         also moves a database from before schools across, in one go:
         its tables become CCNY's (each new league gets a "Table 1"),
         every player's ratings, records, ranks and chosen badges become
         their Standings in CCNY's two leagues, and every player there is
         gets into both without the PIN. Only that first time: after it,
         access is the PIN's to give, and a changed PIN must stay changed.
         On later starts, any league in LEAGUES the database doesn't have
         yet is added, with a first table and no PIN.
      6. Every table, queue row and badge belongs to a league - the ones
         from before schools go to CCNY's league of their game.
      7. Old-style Matches rows are converted. The original code kept the
         two seats in winner_id/loser_id during a game; the app now keeps
         them in king_id/challenger_id. Left unconverted, an old Active
         row is a king nobody can see or play.
      8. Duplicate queue entries are removed, then every index the models
         declare is created if missing - including the unique ones that
         stop a double-tapped Join queueing someone twice, and a badge
         being earned twice in one league - and the old one-badge-per-game
         index goes (it would stop the same badge in two leagues).
      9. No rating is below ELO_FLOOR (0): any older one is raised to it,
         with the rank that earns. Games no longer take anyone below it,
         so after the first run this finds nothing.
     10. Every table record says who holds it, worked out from the games
         at that table for records set before that was kept.

    Never raises. Each step reports what it did, or why it couldn't.
    """
    # Imported here: models imports db from this module's neighbour, and
    # these are only needed once the app is configured.
    from models import (
        BILLIARDS,
        ELO_FLOOR,
        PING_PONG,
        League,
        LeagueAccess,
        Match,
        Player,
        PlayerAchievement,
        PoolTable,
        QueueEntry,
        Rank,
        Standing,
    )

    def step(label, fn):
        try:
            result = fn()
            db.session.commit()
            if result:
                print(f"[schema] {label}: {result}")
        except Exception as e:
            db.session.rollback()
            print(f"[schema] {label} - skipped, couldn't apply it: {e}")

    def create_missing_tables():
        existing = {name.lower() for name in inspect(db.engine).get_table_names()}
        missing = [t for t in db.metadata.sorted_tables if t.name.lower() not in existing]
        if not missing:
            return None
        # Only the missing ones, in foreign-key order. Also creates the
        # indexes the models declare on them.
        db.metadata.create_all(bind=db.session.connection(), tables=missing)
        return f"created {', '.join(t.name for t in missing)}"

    def seed_ranks():
        if db.session.scalar(db.select(Rank.rank_id).limit(1)) is not None:
            return None
        db.session.add_all(Rank(rank_name=name, min_elo=elo) for name, elo in DEFAULT_RANKS)
        return f"added the {len(DEFAULT_RANKS)} rank tiers ({', '.join(n for n, _ in DEFAULT_RANKS)})"

    def add_columns():
        added = []
        inspector = inspect(db.engine)
        existing_tables = {name.lower(): name for name in inspector.get_table_names()}
        for table, column, definition in ADDED_COLUMNS:
            actual = existing_tables.get(table.lower())
            if actual is None:
                continue  # check_schema() reports a missing table
            if column in {c["name"] for c in inspector.get_columns(actual)}:
                continue
            db.session.execute(text(f"ALTER TABLE {actual} ADD COLUMN {column} {definition}"))
            added.append(f"{table}.{column}")
        return f"added {', '.join(added)}" if added else None

    def queue_table_optional():
        # SQLite (the tests) builds Queue from the models, where it already
        # allows NULL.
        if db.engine.dialect.name != "mysql":
            return None
        column = next(
            (c for c in inspect(db.engine).get_columns(QueueEntry.__tablename__) if c["name"] == "table_id"),
            None,
        )
        if column is None or column["nullable"]:
            return None
        db.session.execute(
            text(f"ALTER TABLE {QueueEntry.__tablename__} MODIFY COLUMN table_id INT NULL DEFAULT NULL")
        )
        return "Queue.table_id now allows NULL"

    def add_table_one():
        if db.session.get(PoolTable, 1) is not None:
            return None
        db.session.add(PoolTable(table_id=1, table_name="Table 1", league_type=BILLIARDS))
        return "added 'Table 1' to Pool_Tables"

    def add_ping_pong_table():
        has_one = db.session.scalar(
            db.select(PoolTable.table_id).where(PoolTable.league_type == PING_PONG).limit(1)
        )
        if has_one is not None:
            return None
        db.session.add(PoolTable(table_name=PING_PONG_TABLE_NAME, league_type=PING_PONG))
        return f"added '{PING_PONG_TABLE_NAME}' to Pool_Tables"

    def new_league(order, slug, name, school, game, primary, secondary, legacy):
        league = League(
            slug=slug,
            name=name,
            school=school,
            game=game,
            primary_color=primary,
            secondary_color=secondary,
            legacy_key=legacy,
            sort_order=order,
        )
        db.session.add(league)
        return league

    def add_leagues():
        if db.session.scalar(db.select(League.league_id).limit(1)) is not None:
            return None
        leagues = [new_league(order, *row) for order, row in enumerate(LEAGUES)]
        db.session.flush()
        legacy = {league.legacy_key: league for league in leagues if league.legacy_key}

        # The tables there are were all CCNY's: each goes to the league of
        # its game. Every league without a table gets its first.
        for table in db.session.scalars(db.select(PoolTable)):
            if table.league_id not in {league.league_id for league in leagues}:
                table.league_id = legacy[table.league_type or BILLIARDS].league_id
        db.session.flush()
        for league in leagues:
            has_table = db.session.scalar(
                db.select(PoolTable.table_id).where(PoolTable.league_id == league.league_id).limit(1)
            )
            if has_table is None:
                db.session.add(
                    PoolTable(table_name=FIRST_TABLE_NAME, league_id=league.league_id, league_type=league.game)
                )

        moved = _move_ratings_to_standings(legacy)

        # Everyone who already plays gets into CCNY's leagues without the
        # PIN, as they always could.
        players = list(db.session.scalars(db.select(Player.user_id).where(Player.deleted_at.is_(None))))
        for user_id in players:
            for league in legacy.values():
                db.session.add(LeagueAccess(user_id=user_id, league_id=league.league_id))
        return (
            f"added the {len(leagues)} leagues ({', '.join(l.name for l in leagues)}); "
            f"moved {moved} player(s)' ratings into Standings; let {len(players)} player(s) into "
            f"{' and '.join(l.name for l in legacy.values())}"
        )

    def add_new_leagues():
        # Leagues added to LEAGUES since this database got its first ones.
        # Nobody is let in: a new league is the PIN's to open.
        existing = set(db.session.scalars(db.select(League.slug)))
        if not existing:
            return None  # no leagues at all is add_leagues' job
        added = [
            new_league(order, *row)
            for order, row in enumerate(LEAGUES)
            if row[0] not in existing
        ]
        if not added:
            return None
        db.session.flush()
        for league in added:
            db.session.add(
                PoolTable(table_name=FIRST_TABLE_NAME, league_id=league.league_id, league_type=league.game)
            )
        return f"added {len(added)} league(s): {', '.join(l.name for l in added)}"

    def _move_ratings_to_standings(legacy):
        """
        Every player's numbers, from the old Players columns into Standings
        in CCNY's two leagues. Plain SQL: the models no longer map those
        columns. A new database has none of them, and nothing to move.
        """
        # The step's own connection: a separate one could reset this one's
        # transaction where the tests share a single connection.
        present = {c["name"] for c in inspect(db.session.connection()).get_columns(Player.__tablename__)}
        sources = {
            BILLIARDS: ("elo_rating", "total_wins", "total_losses", "rank_id", "billiards_featured_badge"),
            PING_PONG: ("ping_pong_elo", "ping_pong_wins", "ping_pong_losses", "ping_pong_rank_id", "ping_pong_featured_badge"),
        }
        moved = set()
        for game, columns in sources.items():
            if not set(columns[:3]) <= present or game not in legacy:
                continue
            picked = ", ".join(c if c in present else "NULL" for c in columns)
            rows = db.session.execute(
                text(f"SELECT user_id, {picked} FROM {Player.__tablename__}")
            ).all()
            for user_id, elo, wins, losses, rank_id, badge in rows:
                db.session.add(
                    Standing(
                        user_id=user_id,
                        league_id=legacy[game].league_id,
                        elo=elo or 0,
                        wins=wins or 0,
                        losses=losses or 0,
                        rank_id=rank_id,
                        featured_badge=badge,
                    )
                )
                moved.add(user_id)
        return len(moved)

    def place_tables():
        homeless = list(db.session.scalars(db.select(PoolTable).where(PoolTable.league_id.is_(None))))
        for table in homeless:
            league = League.of(table.league_type or BILLIARDS)
            if league is not None:
                table.league_id = league.league_id
                table.league_type = league.game
        return f"placed {len(homeless)} table(s) in a league" if homeless else None

    def place_queue_rows():
        rows = list(db.session.scalars(db.select(QueueEntry).where(QueueEntry.league_id.is_(None))))
        for entry in rows:
            entry.league_id = db.session.scalar(
                db.select(PoolTable.league_id).where(PoolTable.table_id == entry.table_id)
            ) or League.of(BILLIARDS).league_id
            # Called to that table, or only waiting: before there were
            # leagues the row's table meant the line it was in.
            if entry.called_at is None:
                entry.table_id = None
        return f"put {len(rows)} queue entr{'y' if len(rows) == 1 else 'ies'} in their league's line" if rows else None

    def place_badges():
        rows = list(
            db.session.scalars(db.select(PlayerAchievement).where(PlayerAchievement.league_id.is_(None)))
        )
        for row in rows:
            league = League.of(row.league_type or BILLIARDS)
            if league is not None:
                row.league_id = league.league_id
        return f"put {len(rows)} badge(s) in their league" if rows else None

    def drop_old_badge_index():
        table = PlayerAchievement.__tablename__
        names = {index["name"] for index in inspect(db.session.connection()).get_indexes(table)}
        if "uq_achievement" not in names:
            return None
        if db.engine.dialect.name == "mysql":
            db.session.execute(text(f"ALTER TABLE {table} DROP INDEX uq_achievement"))
        else:
            db.session.execute(text("DROP INDEX uq_achievement"))
        return "dropped the old one-badge-per-game index"

    def convert_legacy_matches():
        # A row written by the new code always has a king, so "no king but
        # a winner" can only be an old row. That is what makes this safe to
        # repeat: once converted, a row no longer matches.
        legacy = (Match.player_one_id.is_(None), Match.winner_id.isnot(None))

        # Active: winner_id/loser_id were seats, not a result. Move them,
        # then clear them - nobody has won yet. ordered_values because
        # MySQL applies SET assignments left to right.
        active = db.session.execute(
            db.update(Match)
            .where(Match.match_status == Match.STATUS_ACTIVE, *legacy)
            .ordered_values(
                (Match.player_one_id, Match.winner_id),
                (Match.player_two_id, Match.loser_id),
                (Match.winner_id, None),
                (Match.loser_id, None),
            )
        ).rowcount

        # Finished: winner/loser really are the result. Copy them into the
        # seats so every row answers "who played" the same way.
        finished = db.session.execute(
            db.update(Match)
            .where(Match.match_status == Match.STATUS_FINISHED, *legacy)
            .values(player_one_id=Match.winner_id, player_two_id=Match.loser_id)
        ).rowcount

        if active or finished:
            return f"converted {active} active and {finished} finished match(es) from the old layout"
        return None

    def dedupe_queue():
        # Keep each player's earliest entry per league; the rest are what a
        # unique index would have prevented.
        rows = db.session.execute(
            db.select(QueueEntry.queue_id, QueueEntry.user_id, QueueEntry.league_id)
            .order_by(QueueEntry.queue_id)
        ).all()
        seen, duplicates = set(), []
        for queue_id, user_id, league_id in rows:
            if (user_id, league_id) in seen:
                duplicates.append(queue_id)
            seen.add((user_id, league_id))
        if not duplicates:
            return None
        db.session.execute(db.delete(QueueEntry).where(QueueEntry.queue_id.in_(duplicates)))
        return f"removed {len(duplicates)} duplicate queue entr{'y' if len(duplicates) == 1 else 'ies'}"

    def add_indexes():
        added = []
        connection = db.session.connection()
        for table in db.metadata.sorted_tables:
            for index in table.indexes:
                if not inspect(connection).has_index(table.name, index.name):
                    index.create(bind=connection)
                    added.append(index.name)
        return f"added index(es) {', '.join(added)}" if added else None

    def name_record_holders():
        # Records set before their holder was kept: replay each table's
        # games, as the badges do (logic/achievements.py) - the king holds
        # the first seat, and a run is the king winning again. The holder
        # is whoever most recently put together a run as long as the
        # record; after a season reset that is this season's.
        tables = list(
            db.session.scalars(
                db.select(PoolTable).where(
                    PoolTable.table_record_holder_id.is_(None),
                    PoolTable.table_record_streak > 0,
                )
            )
        )
        named = 0
        for table in tables:
            games = db.session.execute(
                db.select(Match.player_one_id, Match.winner_id)
                .where(
                    Match.table_id == table.table_id,
                    Match.match_status == Match.STATUS_FINISHED,
                    Match.winner_id.isnot(None),
                )
                .order_by(Match.played_at, Match.match_id)
            ).all()
            king, run, holder = None, 0, None
            for first_seat, winner in games:
                run = run + 1 if king is not None and first_seat == king and winner == king else 1
                king = winner
                if run == table.table_record_streak:
                    holder = winner
            if holder is not None:
                table.table_record_holder_id = holder
                named += 1
        return f"named the holder of {named} table record(s)" if named else None

    def raise_ratings_to_floor():
        floor_rank = Rank.for_elo(ELO_FLOOR)
        below = list(db.session.scalars(db.select(Standing).where(Standing.elo < ELO_FLOOR)))
        for standing in below:
            standing.elo = ELO_FLOOR
            standing.rank_id = floor_rank.rank_id if floor_rank else None
        return f"raised {len(below)} rating(s) to {ELO_FLOOR}" if below else None

    # Tables and columns first: every later step reads models that map them.
    step("Missing tables", create_missing_tables)
    step("New columns", add_columns)
    step("Queue tables optional", queue_table_optional)
    # Before anything that looks a rank up by rating.
    step("Rank tiers", seed_ranks)
    step("Table 1", add_table_one)
    step("Ping pong table", add_ping_pong_table)
    step("Leagues", add_leagues)
    step("New leagues", add_new_leagues)
    step("Tables' leagues", place_tables)
    step("Queue entries' leagues", place_queue_rows)
    step("Badges' leagues", place_badges)
    step("Old match rows", convert_legacy_matches)
    step("Duplicate queue entries", dedupe_queue)
    step("Indexes", add_indexes)
    step("Old badge index", drop_old_badge_index)
    step("Ratings below the floor", raise_ratings_to_floor)
    step("Table record holders", name_record_holders)


def seconds_since(column):
    """
    Seconds between a timestamp column and now, computed by the database.

    Both timestamps then come from one clock in one timezone. Doing this
    subtraction in Python is the trap: the column is written by MySQL's
    clock, datetime.now() reads the app server's, and the two disagree by
    however far apart their timezones are.

    MySQL has TIMESTAMPDIFF; SQLite (the tests) doesn't, and the old code
    treated that failure as "let everyone leave at once" - which switched
    the queue's wait rule off in exactly the place meant to prove it works.
    """
    if db.session.get_bind().dialect.name == "sqlite":
        return db.cast((func.julianday("now") - func.julianday(column)) * 86400, db.Integer)
    return func.timestampdiff(text("SECOND"), column, func.now())


# MySQL's "deadlock found - try restarting transaction". It isn't a bug
# in the query: when requests race for the same rows (five taps on Join
# at once), InnoDB cancels all but one and expects them to be re-run.
MYSQL_DEADLOCK = 1213


def mysql_error_code(error):
    """
    The MySQL error number inside a SQLAlchemy DBAPIError, whichever
    driver raised it. mysql-connector keeps it in .errno; PyMySQL keeps
    it as the first of .args and has no .errno at all. Reading only
    .errno would quietly stop deadlocks being retried under PyMySQL.
    """
    orig = getattr(error, "orig", None)
    code = getattr(orig, "errno", None)
    if code is None and getattr(orig, "args", None) and isinstance(orig.args[0], int):
        code = orig.args[0]
    return code


def retry_on_deadlock(fn, attempts=3):
    """
    Re-run a function whose transaction MySQL cancelled as a deadlock.

    Only for functions that are safe to repeat from the start: each one
    here commits or rolls back its own work, so a cancelled attempt has
    left nothing behind. Any other error passes straight through.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        for attempt in range(1, attempts + 1):
            try:
                return fn(*args, **kwargs)
            except DBAPIError as e:
                if mysql_error_code(e) != MYSQL_DEADLOCK or attempt == attempts:
                    raise
                db.session.rollback()
                # A little jitter so the retries don't collide again.
                time.sleep(random.uniform(0.01, 0.05) * attempt)

    return wrapper


def prepare_database(app, require_connection=False):
    """
    Everything the database needs before the app takes requests:
    ensure_schema(), then check_schema(). Returns check_schema()'s answer.

    Run once per start - by `python app.py` locally, and in the container
    by `flask prepare-db`, which gunicorn runs before starting any worker
    (see gunicorn.conf.py) - rather than once per worker, so two workers
    never race to ALTER the same table.

    require_connection makes an unreachable database an error rather than
    a warning. The container uses it: a deploy that can't see its database
    should fail where the log says why, not start and answer every request
    with "something went wrong".
    """
    with app.app_context():
        where = describe_database(app.config["SQLALCHEMY_DATABASE_URI"])
        if require_connection:
            try:
                db.session.execute(text("SELECT 1"))
                db.session.rollback()
            except Exception as e:
                db.session.rollback()
                log.error("can't reach the database at %s: %s", where, e)
                raise RuntimeError(
                    f"Can't reach the database at {where}. Check DATABASE_URL, that the "
                    "database accepts connections from this server (security group, "
                    "public access), and the username and password."
                ) from None

        print(f"[schema] Database: {where}")
        ensure_schema()
        ok = check_schema()
        _credit_past_games()
        db.session.remove()
    return ok


def _credit_past_games():
    """
    Award achievements for games played before they existed (or while
    awarding failed). Later results award their own, so after the first
    start this finds nothing. Never stops the app starting.
    """
    try:
        from logic.achievements import sync_achievements

        awarded = sync_achievements()
        if awarded:
            print(f"[achievements] awarded {awarded} badge(s) from past games")
    except Exception as e:
        db.session.rollback()
        print(f"[achievements] couldn't check past games: {e}")


def reset_session():
    """
    Drop the current session, used after an error so a failed transaction
    can't poison the next request on the same connection.
    """
    try:
        db.session.remove()
    except Exception:
        pass
