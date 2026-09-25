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
# The password is the one that was already hardcoded here, kept so a
# machine without a .env carries on working. It is not a safe
# Shaeem reminder long-term: that string is in this repo's git history and the repo
# is on GitHub. Set DB_PASSWORD in Backend/.env and rotate the password on
# the database itself.
LOCAL_DEFAULTS = {
    "DB_HOST": "127.0.0.1",
    "DB_USER": "root",
    "DB_PASSWORD": "Skythekidrs679op",
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
         for local development. Anything missing falls back to this
         machine's MySQL.

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

    settings = {key: os.environ.get(key, default) for key, default in LOCAL_DEFAULTS.items()}
    if "DB_PASSWORD" not in os.environ:
        print(
            "WARNING: DB_PASSWORD isn't set, so the password committed in "
            "database.py is being used. Set it in Backend/.env (see .env.example)."
        )

    return URL.create(
        MYSQL_DRIVER,
        username=settings["DB_USER"],
        password=settings["DB_PASSWORD"],
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
    ("Players", "ping_pong_elo", "INTEGER NOT NULL DEFAULT 0"),
    ("Players", "ping_pong_wins", "INTEGER NOT NULL DEFAULT 0"),
    ("Players", "ping_pong_losses", "INTEGER NOT NULL DEFAULT 0"),
    ("Players", "ping_pong_rank_id", "INTEGER NULL"),
    ("Players", "country_flag", "VARCHAR(2) NULL"),
    ("Players", "profile_picture", "VARCHAR(512) NULL"),
]

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
         missing and touches nothing else.
      2. Every column in ADDED_COLUMNS exists: the leave-queue timer, each
         table's league, the ping pong ratings, and profile flag/picture.
         Players.ping_pong_rank_id also gets its foreign key to Ranks.
      3. An empty Ranks table gets the DEFAULT_RANKS tiers.
      4. Table 1 exists in Pool_Tables. The UI plays on table 1, and Queue
         and Matches both have foreign keys to it, so without the row
         every join fails.
      5. The ping pong league has a table. Without one, nobody could join
         its queue.
      6. Players who have never played ping pong start in the rank a
         rating of 0 earns, exactly as a newly registered player would.
      7. Old-style Matches rows are converted. The original code kept the
         two seats in winner_id/loser_id during a game; the app now keeps
         them in king_id/challenger_id. Left unconverted, an old Active
         row is a king nobody can see or play.
      8. Duplicate queue entries are removed, then every index the models
         declare is created if missing - including the unique index that
         stops a double-tapped Join queueing someone twice.

    Never raises. Each step reports what it did, or why it couldn't.
    """
    # Imported here: models imports db from this module's neighbour, and
    # these are only needed once the app is configured.
    from models import BILLIARDS, PING_PONG, STARTING_ELO, Match, Player, PoolTable, QueueEntry, Rank

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

    def add_ping_pong_rank_key():
        # SQLite (the tests) can't add a constraint to an existing table,
        # and gets it from the model when the tests build their tables.
        if db.engine.dialect.name != "mysql":
            return None
        keys = inspect(db.engine).get_foreign_keys(Player.__tablename__)
        if any(k["constrained_columns"] == ["ping_pong_rank_id"] for k in keys):
            return None
        db.session.execute(
            text(
                f"ALTER TABLE {Player.__tablename__} ADD CONSTRAINT fk_players_ping_pong_rank "
                f"FOREIGN KEY (ping_pong_rank_id) REFERENCES {Rank.__tablename__} (rank_id)"
            )
        )
        return "added the foreign key from Players.ping_pong_rank_id to Ranks"

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

    def seed_ping_pong_ranks():
        # Only players with no ping pong games and no rank yet, so this
        # never overrides a rank that play has earned (or lost).
        starting = Rank.for_elo(STARTING_ELO)
        if starting is None:
            return None
        count = db.session.execute(
            db.update(Player)
            .where(
                Player.ping_pong_rank_id.is_(None),
                Player.ping_pong_elo == STARTING_ELO,
                Player.ping_pong_wins == 0,
                Player.ping_pong_losses == 0,
            )
            .values(ping_pong_rank_id=starting.rank_id)
        ).rowcount
        return f"gave {count} player(s) their starting ping pong rank" if count else None

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

    # Tables and columns first: every later step reads models that map them.
    step("Missing tables", create_missing_tables)
    step("New columns", add_columns)
    step("Ping pong rank key", add_ping_pong_rank_key)
    # Before anything that looks a rank up by rating.
    step("Rank tiers", seed_ranks)
    step("Table 1", add_table_one)
    step("Ping pong table", add_ping_pong_table)
    step("Ping pong ranks", seed_ping_pong_ranks)
    step("Old match rows", convert_legacy_matches)
    step("Duplicate queue entries", dedupe_queue)
    step("Indexes", add_indexes)


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
        db.session.remove()
    return ok


def reset_session():
    """
    Drop the current session, used after an error so a failed transaction
    can't poison the next request on the same connection.
    """
    try:
        db.session.remove()
    except Exception:
        pass
