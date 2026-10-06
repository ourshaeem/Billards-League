"""
Leagues: who may play in which, the 4-digit PINs that let them in, and
the organiser's say over each league's PIN and tables.

Anyone can look at any league - its tables, queue, ladder and games.
Playing there - joining its queue, saying "I'm here", reporting a score -
takes access: a League_Access row, made the first time a player enters
the league's PIN and kept from then on, so they never have to again.
When the organiser changes a league's PIN, every row for that league is
deleted and everyone has to enter the new one. Admins (Player.is_admin)
can play anywhere. Leaving is never locked: anyone can leave a queue,
give up a table or call a game off.

A 4-digit PIN has only 10,000 possibilities, so wrong guesses are
limited: MAX_PIN_FAILURES within PIN_LOCKOUT_SECONDS, and then nothing
more until that time has passed. The PIN itself is never stored, only a
bcrypt hash of it.
"""
import logging
import re

import bcrypt
from sqlalchemy.exc import IntegrityError

from database import retry_on_deadlock, seconds_since
from logic.manage_queue import (
    _active_match_for_table,
    _lock_league,
    _lock_table,
    attempt_matchmaking,
)
from logic.tables import active_tables, league_for_table
from models import (
    STARTING_ELO,
    League,
    LeagueAccess,
    PinAttempt,
    Player,
    PoolTable,
    Rank,
    Standing,
    db,
)

log = logging.getLogger(__name__)

PIN_PATTERN = re.compile(r"^\d{4}$")
MAX_PIN_FAILURES = 5
PIN_LOCKOUT_SECONDS = 15 * 60
MAX_TABLE_NAME = PoolTable.__table__.c.table_name.type.length

# unlock_league outcomes.
UNLOCK_RESULT_UNLOCKED = "unlocked"
UNLOCK_RESULT_ALREADY = "already_unlocked"
UNLOCK_RESULT_BAD_FORMAT = "bad_format"
UNLOCK_RESULT_WRONG = "wrong_pin"
UNLOCK_RESULT_NO_PIN = "no_pin"
UNLOCK_RESULT_TOO_MANY = "too_many_tries"

# remove_table outcomes.
REMOVE_TABLE_RESULT_REMOVED = "removed"
REMOVE_TABLE_RESULT_BUSY = "busy"
REMOVE_TABLE_RESULT_NOT_FOUND = "not_found"


class LeagueProblem(ValueError):
    """Something the organiser asked for that can't be done; the message says why."""


# --- Who may play where ---


def has_access(user_id, league):
    """Whether this player may play in this league: an admin, or someone who has entered its PIN."""
    league = League.of(league)
    if user_id is None or league is None:
        return False
    player = db.session.get(Player, user_id)
    if player is None or player.is_deleted:
        return False
    if player.is_admin:
        return True
    return (
        db.session.get(LeagueAccess, (user_id, league.league_id)) is not None
    )


def accessible_league_ids(user_id):
    """The leagues this player may play in: every one for an admin."""
    if user_id is None:
        return set()
    player = db.session.get(Player, user_id)
    if player is None or player.is_deleted:
        return set()
    if player.is_admin:
        return set(db.session.scalars(db.select(League.league_id)))
    return set(
        db.session.scalars(db.select(LeagueAccess.league_id).where(LeagueAccess.user_id == user_id))
    )


def ensure_standing(user_id, league, lock=False):
    """
    The player's Standing in a league, made - where every new player starts
    - if they don't have one yet. With lock, the row is held FOR UPDATE and
    re-read, for changing the numbers. Doesn't commit.
    """
    league = League.of(league)
    key = (user_id, league.league_id)
    standing = db.session.get(Standing, key, with_for_update=lock, populate_existing=lock)
    if standing is not None:
        return standing
    player = db.session.get(Player, user_id)
    starting = Rank.for_elo(STARTING_ELO)
    standing = Standing(
        user_id=user_id,
        league_id=league.league_id,
        elo=STARTING_ELO,
        wins=0,
        losses=0,
        rank_id=starting.rank_id if starting else None,
    )
    # Through the player, so their standings already loaded include it.
    if player is not None:
        player.standings.append(standing)
    else:
        db.session.add(standing)
    db.session.flush()
    return standing


def grant_access(user_id, league):
    """
    Let a player into a league for good (until its PIN changes), with a
    place on its ladder. Commits. True if they didn't have access before.
    """
    league = League.of(league)
    try:
        new = db.session.get(LeagueAccess, (user_id, league.league_id)) is None
        if new:
            db.session.add(LeagueAccess(user_id=user_id, league_id=league.league_id))
        ensure_standing(user_id, league)
        db.session.commit()
        return new
    except IntegrityError:
        # Granted at this instant by another request, which made the
        # standing too.
        db.session.rollback()
        return False
    except Exception:
        db.session.rollback()
        raise


@retry_on_deadlock
def unlock_league(user_id, league, pin):
    """
    A player enters a league's PIN. Returns (outcome, detail): one of the
    UNLOCK_RESULT_*, and for WRONG {"tries_left": n}, for TOO_MANY
    {"retry_in": seconds}.
    """
    league = League.of(league)
    if not isinstance(pin, str) or not PIN_PATTERN.match(pin.strip()):
        return UNLOCK_RESULT_BAD_FORMAT, None
    pin = pin.strip()
    if has_access(user_id, league):
        return UNLOCK_RESULT_ALREADY, None
    if not league.has_pin:
        return UNLOCK_RESULT_NO_PIN, None

    try:
        row = db.session.execute(
            db.select(PinAttempt, seconds_since(PinAttempt.first_failed_at))
            .where(PinAttempt.user_id == user_id, PinAttempt.league_id == league.league_id)
            .with_for_update()
        ).first()
        attempt, elapsed = row if row is not None else (None, None)
        if attempt is not None and (elapsed or 0) >= PIN_LOCKOUT_SECONDS:
            # The last run of wrong guesses was long enough ago to forget.
            db.session.delete(attempt)
            db.session.flush()
            attempt = None
        if attempt is not None and attempt.failures >= MAX_PIN_FAILURES:
            db.session.commit()
            return UNLOCK_RESULT_TOO_MANY, {"retry_in": max(1, PIN_LOCKOUT_SECONDS - int(elapsed or 0))}

        if bcrypt.checkpw(pin.encode(), league.pin_hash.encode()):
            if attempt is not None:
                db.session.delete(attempt)
            db.session.commit()
            grant_access(user_id, league)
            log.info("player %s unlocked %s", user_id, league.slug)
            return UNLOCK_RESULT_UNLOCKED, None

        if attempt is None:
            attempt = PinAttempt(user_id=user_id, league_id=league.league_id, failures=0)
            db.session.add(attempt)
        attempt.failures += 1
        failures = attempt.failures
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return UNLOCK_RESULT_WRONG, {"tries_left": max(0, MAX_PIN_FAILURES - failures)}


# --- The organiser's controls ---


def hash_pin(pin):
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def set_league_pin(league, pin):
    """
    Give a league a new 4-digit PIN. Everyone who had entered the old one
    has to enter the new one: every access row for the league goes, and
    any wrong-guess counts with them. Returns how many players lost
    access. Raises LeagueProblem for a PIN that isn't 4 digits.
    """
    league = League.of(league)
    if not isinstance(pin, str) or not PIN_PATTERN.match(pin.strip()):
        raise LeagueProblem("The PIN has to be 4 digits.")
    try:
        league.pin_hash = hash_pin(pin.strip())
        revoked = db.session.execute(
            db.delete(LeagueAccess).where(LeagueAccess.league_id == league.league_id)
        ).rowcount
        db.session.execute(db.delete(PinAttempt).where(PinAttempt.league_id == league.league_id))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    log.info("PIN changed for %s; %s player(s) must enter it again", league.slug, revoked)
    return revoked


def _clean_table_name(name, league, except_table_id=None):
    """A table name the organiser typed, checked; raises LeagueProblem."""
    if not isinstance(name, str) or not name.strip():
        raise LeagueProblem("Give the table a name, like \"Table 2\".")
    name = " ".join(name.split())
    if len(name) > MAX_TABLE_NAME:
        raise LeagueProblem(f"Table names can be at most {MAX_TABLE_NAME} characters.")
    for table in active_tables(league):
        if table.table_id != except_table_id and table.table_name.lower() == name.lower():
            raise LeagueProblem(f"{league.name} already has a table called {table.table_name}.")
    return name


def add_table(league, name):
    """
    Add a table to a league; the next in its queue can be sent there at
    once. Returns the new PoolTable. Raises LeagueProblem for a bad name.
    """
    league = League.of(league)
    name = _clean_table_name(name, league)
    try:
        _lock_league(league.league_id)
        table = PoolTable(
            table_name=name, league_id=league.league_id, league_type=league.game, is_active=True
        )
        db.session.add(table)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    log.info("table %s (%s) added to %s", table.table_id, name, league.slug)
    try:
        attempt_matchmaking(league.league_id)
    except Exception:
        log.exception("table added, but matchmaking failed (league %s)", league.league_id)
    return table


def rename_table(table_id, name):
    """Rename a table in use. Returns the PoolTable, or None if there's no such table."""
    table = db.session.get(PoolTable, table_id)
    if table is None or not table.is_active:
        return None
    league = league_for_table(table_id)
    table.table_name = _clean_table_name(name, league, except_table_id=table_id)
    db.session.commit()
    return table


@retry_on_deadlock
def remove_table(table_id):
    """
    Stop using a table. Refused while anyone is at it - take them off (or
    let them finish) first, so nobody's game disappears. Its games stay
    in the history. Players called to it are sent to another table, or
    back to the front of the line. Returns (outcome, active match or None).
    """
    table = db.session.get(PoolTable, table_id)
    if table is None or not table.is_active:
        return REMOVE_TABLE_RESULT_NOT_FOUND, None
    league = league_for_table(table_id)
    try:
        _lock_table(table_id)
        active = _active_match_for_table(table_id, lock=True)
        if active is not None:
            db.session.rollback()
            return REMOVE_TABLE_RESULT_BUSY, active
        table = db.session.get(PoolTable, table_id, populate_existing=True)
        table.is_active = False
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    log.info("table %s removed from %s", table_id, league.slug)
    try:
        attempt_matchmaking(league.league_id)
    except Exception:
        log.exception("table removed, but matchmaking failed (league %s)", league.league_id)
    return REMOVE_TABLE_RESULT_REMOVED, None


# --- What the apps list ---


def league_summary(league, user_id=None, allowed=None):
    """
    A league for the apps to list: League.to_dict() plus its tables in use
    and read_only - True unless this player may play there.
    """
    if allowed is None:
        allowed = accessible_league_ids(user_id)
    return {
        **league.to_dict(),
        "tables": [
            {"table_id": t.table_id, "table_name": t.table_name} for t in active_tables(league)
        ],
        "read_only": league.league_id not in allowed,
    }


def league_directory(user_id=None):
    """Every league, in order, as league_summary()s."""
    allowed = accessible_league_ids(user_id)
    return [
        league_summary(league, allowed=allowed)
        for league in db.session.scalars(
            db.select(League).order_by(League.sort_order, League.league_id)
        )
    ]
