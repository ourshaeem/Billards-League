"""
One-time setup for a machine that doesn't have the database yet.

    python3 setup_db.py

Creates the `ranked_billards` database (or whatever DB_NAME says), every
table the models describe, the rank tiers, and Table 1. Safe to run again:
nothing that already exists is touched, so on a machine with a working
league this does nothing.

app.py's ensure_schema() can't do this on its own - it only adds to a
database that already exists, and SQLAlchemy can't connect to a database
that isn't there.
"""
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from database import check_schema, ensure_schema, get_database_uri

# The ELO tiers. Every player starts at 0 (models.STARTING_ELO), and the
# lowest tier must start at 0 too, or new players show as "Unranked".
# These match the tiers the tests use; change them before the first run
# if your league uses different ones.
RANKS = [
    ("Bronze", 0),
    ("Silver", 1100),
    ("Gold", 1300),
    ("Platinum", 1500),
]


def create_database():
    """CREATE DATABASE if it's missing. Returns True if it was created."""
    url = make_url(get_database_uri())
    name = url.database

    # Connect through MySQL's built-in schema - ours may not exist yet.
    # (url.set(database=None) means "leave it unchanged", not "none".)
    engine = create_engine(url.set(database="information_schema"))
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :name"),
            {"name": name},
        ).first()
        if not exists:
            conn.execute(text(f"CREATE DATABASE `{name}`"))
    engine.dispose()
    return not exists


def main():
    try:
        created = create_database()
    except Exception as e:
        print(f"Couldn't reach MySQL: {e}")
        print("Check DB_USER and DB_PASSWORD in Backend/.env.")
        return 1

    print("Created the database." if created else "The database already exists.")

    # Imported only now: importing app builds the Flask app.
    from app import app
    from models import Rank, db

    with app.app_context():
        db.create_all()

        if db.session.scalar(db.select(Rank).limit(1)) is None:
            db.session.add_all(Rank(rank_name=n, min_elo=m) for n, m in RANKS)
            db.session.commit()
            print(f"Added {len(RANKS)} rank tiers.")

        ensure_schema()
        ok = check_schema()

    print("Ready. Start the server with: python3 app.py" if ok else "Setup finished with problems - see above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
