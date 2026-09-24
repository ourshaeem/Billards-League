"""
Registration and login.

Both functions keep the behaviour the frontend already depends on:
register_user returns (success, message) with a message written to be
shown to a person, so a taken username says exactly that rather than a
catch-all "Registration failed".
"""
import logging

import bcrypt

from models import STARTING_ELO, Player, Rank, db

log = logging.getLogger(__name__)

MIN_USERNAME_LENGTH = 3
MIN_PASSWORD_LENGTH = 6

# The database columns' own limits, read from the model so the two can't
# disagree. Past them, MySQL refuses the row and the player used to get a
# vague "Couldn't create the account".
MAX_USERNAME_LENGTH = Player.__table__.c.username.type.length
MAX_NAME_LENGTH = Player.__table__.c.first_name.type.length

# bcrypt only reads the first 72 bytes, and bcrypt 5 refuses anything
# longer outright.
MAX_PASSWORD_BYTES = 72


def register_user(username, first_name, last_name, password_text):
    """Returns (success: bool, message: str)."""
    if not all(
        value is None or isinstance(value, str)
        for value in (username, first_name, last_name, password_text)
    ):
        return False, "Every field needs to be text."

    username = (username or "").strip()
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    password_text = password_text or ""

    if not username or not first_name or not last_name:
        return False, "Username, first name and last name can't be blank."
    if len(username) < MIN_USERNAME_LENGTH:
        return False, f"Usernames need at least {MIN_USERNAME_LENGTH} characters."
    if len(username) > MAX_USERNAME_LENGTH:
        return False, f"Usernames can be at most {MAX_USERNAME_LENGTH} characters."
    if len(first_name) > MAX_NAME_LENGTH or len(last_name) > MAX_NAME_LENGTH:
        return False, f"Names can be at most {MAX_NAME_LENGTH} characters."
    if len(password_text) < MIN_PASSWORD_LENGTH:
        return False, f"Passwords need at least {MIN_PASSWORD_LENGTH} characters."
    if len(password_text.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return False, f"Passwords can be at most {MAX_PASSWORD_BYTES} characters."

    try:
        existing = db.session.scalars(
            db.select(Player).where(Player.username == username)
        ).first()
        if existing:
            return False, "That username is taken. Try another one."

        hashed = bcrypt.hashpw(password_text.encode("utf-8"), bcrypt.gensalt())
        starting_rank = Rank.for_elo(STARTING_ELO)

        db.session.add(
            Player(
                username=username,
                first_name=first_name,
                last_name=last_name,
                # decode() because the column is a String. Storing bytes
                # into a String column is what produced the str/bytes mess
                # that used to crash login.
                password_hash=hashed.decode("utf-8"),
                # Everyone starts level in both leagues.
                billiards_elo=STARTING_ELO,
                billiards_rank_id=starting_rank.rank_id if starting_rank else None,
                ping_pong_elo=STARTING_ELO,
                ping_pong_rank_id=starting_rank.rank_id if starting_rank else None,
            )
        )
        db.session.commit()
        return True, "Account created. You can log in now."

    except Exception as e:
        db.session.rollback()
        # Two people can still claim a name in the same instant; the
        # UNIQUE constraint is what actually settles it.
        if "Duplicate entry" in str(e) or "UNIQUE constraint" in str(e):
            return False, "That username is taken. Try another one."
        log.exception("error registering user %r", username)
        return False, "Couldn't create the account. Please try again."


def login_user(username, password_text):
    """
    The Player on success, None on failure.

    app.py reads user["user_id"] and user["username"], so this returns a
    dict rather than the model object - keeping the login route and its
    JSON response untouched by the ORM move.
    """
    player = db.session.scalars(
        db.select(Player).where(Player.username == (username or "").strip())
    ).first()

    if player is None:
        return None

    stored_hash = player.password_hash
    # MySQL hands this back as str or bytes depending on the column type.
    # The old code assumed str and called .encode() on it, raising
    # AttributeError on a bytes column and surfacing as a 500 on a
    # perfectly valid login.
    if isinstance(stored_hash, str):
        stored_hash = stored_hash.encode("utf-8")

    password_bytes = (password_text or "").encode("utf-8")
    if len(password_bytes) > MAX_PASSWORD_BYTES:
        # Registration never allows one this long, so it can't match - and
        # bcrypt 5 raises rather than answering.
        return None

    try:
        if bcrypt.checkpw(password_bytes, stored_hash):
            return {"user_id": player.user_id, "username": player.username}
    except ValueError as e:
        # The stored value isn't a valid bcrypt hash - e.g. a row created
        # before hashing existed.
        log.warning("stored password for %r isn't a valid hash: %s", username, e)
        return None

    return None
