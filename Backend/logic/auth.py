"""
Registration and login.

Registration needs an email, and one email makes one account. That's
what stops a player who forgot their password making a second account:
signing up again with their email is refused, and the email gets them a
reset code instead (password_reset.py). Sign-in takes the username or
the email.

register_user returns (success, message, field): a message written to be
shown to a person - a taken username says exactly that, rather than a
catch-all "Registration failed" - and the field it's about, so the form
can put it beside that field.
"""
import logging
import re

import bcrypt

from models import Player, db

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

MAX_EMAIL_LENGTH = Player.__table__.c.email.type.length
# Deliberately loose: something@something.something, no spaces. Whether
# an address really works is for the reset email to find out; a stricter
# pattern only refuses unusual addresses that are perfectly real.
EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

EMAIL_TAKEN = (
    "An account already uses that email. If it's yours, sign in - or reset "
    "your password if you've forgotten it."
)


def clean_email(value):
    """
    (email, problem): the address as stored - trimmed, lowercased - or the
    reason it can't be used, written for the person typing it.
    """
    if not isinstance(value, str) or not value.strip():
        return None, "Enter your email address."
    email = value.strip().lower()
    if len(email) > MAX_EMAIL_LENGTH:
        return None, f"Email addresses can be at most {MAX_EMAIL_LENGTH} characters."
    if not EMAIL_SHAPE.match(email):
        return None, "That doesn't look like an email address."
    return email, None


def email_in_use(email, except_user_id=None):
    """True if another account already uses this (cleaned) email."""
    stmt = db.select(Player.user_id).where(Player.email == email)
    if except_user_id is not None:
        stmt = stmt.where(Player.user_id != except_user_id)
    return db.session.scalar(stmt.limit(1)) is not None


def password_problem(password_text):
    """Why a new password can't be used, or None. Sign-up and resets share it."""
    if not isinstance(password_text, str) or len(password_text) < MIN_PASSWORD_LENGTH:
        return f"Passwords need at least {MIN_PASSWORD_LENGTH} characters."
    if len(password_text.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"Passwords can be at most {MAX_PASSWORD_BYTES} characters."
    return None


def hash_password(password_text):
    """
    The bcrypt hash to store, as text: the column is a String. Storing
    bytes into a String column is what produced the str/bytes mess that
    used to crash login.
    """
    return bcrypt.hashpw(password_text.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def register_user(username, first_name, last_name, password_text, email=None):
    """Returns (success: bool, message: str, field: str or None)."""
    if not all(
        value is None or isinstance(value, str)
        for value in (username, first_name, last_name, password_text, email)
    ):
        return False, "Every field needs to be text.", None

    username = (username or "").strip()
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    password_text = password_text or ""

    if not username:
        return False, "Choose a username.", "username"
    if not first_name or not last_name:
        return False, "Username, first name and last name can't be blank.", (
            "first_name" if not first_name else "last_name"
        )
    if len(username) < MIN_USERNAME_LENGTH:
        return False, f"Usernames need at least {MIN_USERNAME_LENGTH} characters.", "username"
    if len(username) > MAX_USERNAME_LENGTH:
        return False, f"Usernames can be at most {MAX_USERNAME_LENGTH} characters.", "username"
    if "@" in username:
        # Sign-in reads anything with an @ as an email.
        return False, "Usernames can't contain @.", "username"
    if len(first_name) > MAX_NAME_LENGTH or len(last_name) > MAX_NAME_LENGTH:
        return False, f"Names can be at most {MAX_NAME_LENGTH} characters.", (
            "first_name" if len(first_name) > MAX_NAME_LENGTH else "last_name"
        )
    email, problem = clean_email(email)
    if problem:
        return False, problem, "email"
    problem = password_problem(password_text)
    if problem:
        return False, problem, "password"

    try:
        existing = db.session.scalars(
            db.select(Player).where(Player.username == username)
        ).first()
        if existing:
            return False, "That username is taken. Try another one.", "username"
        if email_in_use(email):
            return False, EMAIL_TAKEN, "email"

        # No leagues yet: a player gets a place in one (a Standing, where
        # everyone starts) on entering its PIN - see logic/leagues.py.
        db.session.add(
            Player(
                username=username,
                first_name=first_name,
                last_name=last_name,
                email=email,
                password_hash=hash_password(password_text),
            )
        )
        db.session.commit()
        return True, "Account created. You can log in now.", None

    except Exception as e:
        db.session.rollback()
        # Two people can still claim a name or an email in the same
        # instant; the UNIQUE constraints are what actually settle it.
        message = str(e)
        if "Duplicate entry" in message or "UNIQUE constraint" in message:
            if "email" in message:
                return False, EMAIL_TAKEN, "email"
            return False, "That username is taken. Try another one.", "username"
        log.exception("error registering user %r", username)
        return False, "Couldn't create the account. Please try again.", None


def find_player(identifier):
    """
    The account a sign-in names: by email if it has an @, else by username.
    An @ that matches no email falls back to the username: some players
    signed up before emails were asked for with an email address as their
    username, and they still sign in with it.
    """
    identifier = (identifier or "").strip()
    if "@" in identifier:
        by_email = db.session.scalars(
            db.select(Player).where(Player.email == identifier.lower())
        ).first()
        if by_email is not None:
            return by_email
    return db.session.scalars(db.select(Player).where(Player.username == identifier)).first()


def login_user(identifier, password_text):
    """
    {user_id, username, email, is_admin} on success, None on failure.
    identifier is the username or the email - anything with an @ is read
    as an email.
    """
    player = find_player(identifier)

    # A deleted account can't sign in. (Its name and password are wiped
    # too, so this is belt and braces.)
    if player is None or player.is_deleted:
        return None

    if password_matches(player, password_text):
        return {
            "user_id": player.user_id,
            "username": player.username,
            "email": player.email,
            "is_admin": bool(player.is_admin),
        }
    return None


def password_matches(player, password_text):
    """
    Whether password_text is this player's password. Used by sign-in and
    by account deletion, which asks for the password again.
    """
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
        return False

    try:
        return bcrypt.checkpw(password_bytes, stored_hash)
    except ValueError as e:
        # The stored value isn't a valid bcrypt hash - e.g. a row created
        # before hashing existed, or a deleted account's wiped password.
        log.warning("stored password for user %s isn't a valid hash: %s", player.user_id, e)
        return False
