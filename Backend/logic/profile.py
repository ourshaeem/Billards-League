"""
A player's own profile: reading it, and changing their flag and picture.

update_profile() says which field a problem concerns, so the frontend can
put the message beside that field rather than in a toast about the form.
"""
import logging
from urllib.parse import urlsplit

from logic.countries import COUNTRIES
from models import Player, db

log = logging.getLogger(__name__)

EDITABLE_FIELDS = ("country_flag", "profile_picture")

# The column's own limit, read from the model so the two can't disagree.
MAX_PICTURE_URL_LENGTH = Player.__table__.c.profile_picture.type.length


def get_profile(user_id):
    """The player's profile dict, or None if the account no longer exists."""
    player = db.session.get(Player, user_id)
    return player.to_profile_dict() if player is not None else None


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
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return None, player.to_profile_dict()
