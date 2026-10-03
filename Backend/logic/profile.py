"""
A player's own profile: reading it, and changing their flag, picture and
email. Uploading a picture, rather than linking one, is in pictures.py.

update_profile() says which field a problem concerns, so the frontend can
put the message beside that field rather than in a toast about the form.
"""
import logging
from urllib.parse import urlsplit

from logic.auth import EMAIL_TAKEN, clean_email, email_in_use, password_matches
from logic.countries import COUNTRIES
from logic.pictures import forget_uploaded_picture
from models import Player, db

log = logging.getLogger(__name__)

EDITABLE_FIELDS = ("country_flag", "profile_picture")

# The column's own limit, read from the model so the two can't disagree.
MAX_PICTURE_URL_LENGTH = Player.__table__.c.profile_picture.type.length


def get_profile(user_id):
    """The player's profile dict, or None if the account no longer exists."""
    player = db.session.get(Player, user_id)
    return player.to_profile_dict() if player is not None else None


def get_public_profile(user_id):
    """
    Another player's profile, as anyone may see it, or None if there is
    no such player. A deleted account has no profile: what was in it is
    gone, and its games show it only as "Deleted player".
    """
    player = db.session.get(Player, user_id)
    if player is None or player.is_deleted:
        return None
    return player.to_public_profile_dict()


def clean_country_flag(value):
    """(code or None, problem or None). Blank or null clears the flag."""
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, "Pick a country from the list."
    code = value.strip().upper()
    if not code:
        return None, None
    if code not in COUNTRIES:
        return None, "Pick a country from the list."
    return code, None


def clean_profile_picture(value):
    """
    (url or None, problem or None). Blank or null clears the picture.

    Only http(s) links. Whatever is saved here goes into an <img src> on
    every other player's screen, and a javascript: or data: link has no
    business there. The image itself isn't fetched: the server has no
    need to, and fetching a URL a user typed is a door best left shut.
    """
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, "The picture needs to be a web link."
    url = value.strip()
    if not url:
        return None, None
    if len(url) > MAX_PICTURE_URL_LENGTH:
        return None, f"Picture links can be at most {MAX_PICTURE_URL_LENGTH} characters."
    if any(ch.isspace() for ch in url):
        return None, "That doesn't look like a web link - it has spaces in it."

    try:
        parts = urlsplit(url)
    except ValueError:
        return None, "That doesn't look like a web link."
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None, "Use a link that starts with https:// (or http://)."
    return url, None


CLEANERS = {"country_flag": clean_country_flag, "profile_picture": clean_profile_picture}


def set_email(user_id, email, password=None):
    """
    Add or change a player's email - where password reset codes go.
    Returns (problem, profile) like update_profile: problem is {field,
    message} and nothing is saved; both None if the account is gone.

    Adding the first email needs no password: whoever is signed in can
    already do anything with the account, and accounts from before
    sign-up asked for an email need one added. Changing an email that's
    already there does need it - otherwise a phone left signed in could
    redirect the reset codes, and with them the account.
    """
    player = db.session.get(Player, user_id)
    if player is None or player.is_deleted:
        return None, None

    cleaned, problem = clean_email(email)
    if problem:
        return {"field": "email", "message": problem}, None
    if player.email and cleaned != player.email:
        if not isinstance(password, str) or not password:
            return {"field": "password", "message": "Enter your password to change your email."}, None
        if not password_matches(player, password):
            # 403, not 401: to the apps a 401 means "your session ended".
            return {"field": "password", "message": "That password isn't right.", "status": 403}, None
    if email_in_use(cleaned, except_user_id=user_id):
        return {"field": "email", "message": EMAIL_TAKEN}, None

    try:
        player.email = cleaned
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        if "Duplicate entry" in str(e) or "UNIQUE constraint" in str(e):
            return {"field": "email", "message": EMAIL_TAKEN}, None
        raise
    return None, player.to_profile_dict()


def update_profile(user_id, data):
    """
    Apply whichever of EDITABLE_FIELDS are present in `data`.

    Returns (problem, profile):
      - problem is None and profile is the updated profile on success;
      - problem is {"field": ..., "message": ...} for a value that can't
        be saved - and then nothing is saved, not even the other field;
      - both are None if the account doesn't exist.
    """
    player = db.session.get(Player, user_id)
    if player is None:
        return None, None

    cleaned = {}
    for field in EDITABLE_FIELDS:
        if field not in data:
            continue
        value, problem = CLEANERS[field](data[field])
        if problem:
            return {"field": field, "message": problem}, None
        cleaned[field] = value

    try:
        for field, value in cleaned.items():
            setattr(player, field, value)
        if "profile_picture" in cleaned:
            # A new link, or none: an uploaded picture they had is replaced,
            # and isn't kept once nothing shows it.
            forget_uploaded_picture(user_id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return None, player.to_profile_dict()
