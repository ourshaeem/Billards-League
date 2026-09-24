"""
Database configuration and startup checks.

SQLAlchemy replaces the hand-rolled connection helper, so this module no
longer opens connections itself - it builds the connection URI and holds
the startup work: ensure_schema() (idempotent, additive fixes to an
existing database) and check_schema() (a read-only report of anything
still missing).
"""
import functools
import os
import random
import time

from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from models import db

# Load Backend/.env if python-dotenv is installed. Optional on purpose: if
# it isn't there, everything falls back to the values below, so this can't
# break a machine that already works.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "Skythekidrs679op")
DB_NAME = os.environ.get("DB_NAME", "ranked_billards")
DB_PORT = os.environ.get("DB_PORT", "3306")

# The fallback password above is the one that was already hardcoded here,
# kept so a machine without a .env carries on working. It is not a safe
# long-term answer: that string is in this repo's git history and the repo
# is on GitHub. Set DB_PASSWORD in Backend/.env and rotate the password on
# the database itself.
if "DB_PASSWORD" not in os.environ:
    print(
        "WARNING: DB_PASSWORD isn't set, so the password committed in "
        "database.py is being used. Set it in Backend/.env (see .env.example)."
    )


def get_database_uri():
    """
    The SQLAlchemy connection string.

    DATABASE_URL wins if it's set, which is how the tests point everything
    at in-memory SQLite without touching MySQL.
    """
    override = os.environ.get("DATABASE_URL")
    if override:
        return override

    return (
        f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )


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


def ensure_schema():
    """
    Bring an existing database up to what the app needs. Safe to run on
    every startup: each step checks before it changes anything, and only
    ever adds - no column or table is dropped.

    Steps:
      1. Queue.joined_at exists (powers the leave-queue timer).
      2. Table 1 exists in Pool_Tables. The UI plays on table 1, and Queue
         and Matches both have foreign keys to it, so without the row
         every join fails.
      3. Old-style Matches rows are converted. The original code kept the
         two seats in winner_id/loser_id during a game; the app now keeps
         them in king_id/challenger_id. Left unconverted, an old Active
         row is a king nobody can see or play.
      4. Duplicate queue entries are removed, then every index the models
         declare is created if missing - including the unique index that
         stops a double-tapped Join queueing someone twice.

    Never raises. Each step reports what it did, or why it couldn't.
    """
    # Imported here: models imports db from this module's neighbour, and
    # these are only needed once the app is configured.
    from models import Match, PoolTable, QueueEntry

    def step(label, fn):
        try:
            result = fn()
            db.session.commit()
            if result:
                print(f"[schema] {label}: {result}")
        except Exception as e:
            db.session.rollback()
            print(f"[schema] {label} - skipped, couldn't apply it: {e}")

    def add_joined_at():
        columns = {c["name"] for c in inspect(db.engine).get_columns(QueueEntry.__tablename__)}
        if "joined_at" in columns:
            return None
        db.session.execute(
            text(
                f"ALTER TABLE {QueueEntry.__tablename__} "
                "ADD COLUMN joined_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP"
            )
        )
        return "added Queue.joined_at"

    def add_table_one():
        if db.session.get(PoolTable, 1) is not None:
            return None
        db.session.add(PoolTable(table_id=1, table_name="Table 1"))
        return "added 'Table 1' to Pool_Tables"

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
        # Keep each player's earliest entry per table; the rest are what a
        # unique index would have prevented.
        rows = db.session.execute(
            db.select(QueueEntry.queue_id, QueueEntry.user_id, QueueEntry.table_id)
            .order_by(QueueEntry.queue_id)
        ).all()
        seen, duplicates = set(), []
        for queue_id, user_id, table_id in rows:
            if (user_id, table_id) in seen:
                duplicates.append(queue_id)
            seen.add((user_id, table_id))
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

    step("Queue timer column", add_joined_at)
    step("Table 1", add_table_one)
    step("Old match rows", convert_legacy_matches)
    step("Duplicate queue entries", dedupe_queue)
    step("Indexes", add_indexes)


# MySQL's "deadlock found - try restarting transaction". It isn't a bug
# in the query: when requests race for the same rows (five taps on Join
# at once), InnoDB cancels all but one and expects them to be re-run.
MYSQL_DEADLOCK = 1213


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
                if getattr(e.orig, "errno", None) != MYSQL_DEADLOCK or attempt == attempts:
                    raise
                db.session.rollback()
                # A little jitter so the retries don't collide again.
                time.sleep(random.uniform(0.01, 0.05) * attempt)

    return wrapper


def reset_session():
    """
    Drop the current session, used after an error so a failed transaction
    can't poison the next request on the same connection.
    """
    try:
        db.session.remove()
    except Exception:
        pass
