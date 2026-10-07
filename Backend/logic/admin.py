"""
The organiser's controls: taking a player out of a queue, or off a table.

For when someone has gone: a player who joined and walked off, a king who
left without giving the table up, a game that will never be reported.
Only an admin may use them (Player.is_admin, granted from the command
line). The routes check that against the database on every request;
nothing here relies on the apps having hidden the buttons.

Taking a player out of a queue ignores the wait before leaving - that
rule is there to stop players dodging a game, not the organiser. If it
was their turn, the next in line is up at once.

Taking a player off a table:

  - Holding it with no challenger: as if they had given it up themselves
    (step_down) - the table goes to the next two in line.
  - Mid-game: the game is called off, as if both players had agreed to
    cancel it (cancel_match.py) - nothing recorded, no rating moves. The
    other player stays at the table, holding it, and the next in line is
    up to challenge them: they came to play, and did nothing wrong.

Either way, the removed player's winning streak at the table ends.
"""
import logging

from database import retry_on_deadlock
from logic.manage_queue import (
    attempt_matchmaking,
    leave_queue,
    lock_active_match_for_player,
    take_off_table,
)
from logic.tables import league_for_table
from models import League, Player, db

log = logging.getLogger(__name__)

# remove_from_queue outcomes.
QUEUE_REMOVE_RESULT_REMOVED = "removed"
QUEUE_REMOVE_RESULT_NOT_QUEUED = "not_queued"

# remove_from_table outcomes.
TABLE_REMOVE_RESULT_TABLE_FREED = "table_freed"
TABLE_REMOVE_RESULT_GAME_CALLED_OFF = "game_called_off"
TABLE_REMOVE_RESULT_NOT_AT_TABLE = "not_at_table"
TABLE_REMOVE_RESULT_GAME_CHANGED = "game_changed"


def is_admin(user_id):
    """
    Whether this account may use the organiser's controls - read from the
    database each time, so taking the right away (or deleting the
    account) works at once, not when a login token expires.
    """
    player = db.session.get(Player, user_id, populate_existing=True)
    return player is not None and not player.is_deleted and bool(player.is_admin)


def remove_from_queue(user_id, league, by=None):
    """
    Take a player out of a league's queue. `by` is the admin, for the log.
    Returns one of the QUEUE_REMOVE_RESULT_*.
    """
    league = League.of(league)
    if not leave_queue(user_id, league.league_id):
        return QUEUE_REMOVE_RESULT_NOT_QUEUED
    log.info("admin %s took player %s out of %s's queue", by, user_id, league.slug)

    # If it was their turn, the next in line is up now, not at the next poll.
    try:
        attempt_matchmaking(league.league_id)
    except Exception:
        log.exception("removed from the queue, but matchmaking failed (league %s)", league.slug)
    return QUEUE_REMOVE_RESULT_REMOVED


def remove_from_table(user_id, table_id, expected_match_id=None, by=None):
    """
    Take a player off a table: see the module docstring for what happens
    to the table and to a game in progress. `expected_match_id` is the
    game the admin saw there (GET /table's match_id); if the player is in
    a different one by now, nothing happens. `by` is the admin, for the
    log.

    Returns (outcome, other_player_id): one of the TABLE_REMOVE_RESULT_*,
    and for a game called off, who now holds the table.
    """
    outcome, other_id = _take_off_table(user_id, table_id, expected_match_id)
    if outcome not in (TABLE_REMOVE_RESULT_TABLE_FREED, TABLE_REMOVE_RESULT_GAME_CALLED_OFF):
        return outcome, None

    log.info(
        "admin %s took player %s off table %s (%s)",
        by,
        user_id,
        table_id,
        f"game called off, {other_id} holds the table" if other_id else "table freed",
    )
    # The table has room again: the next in line is up, or the next two.
    try:
        attempt_matchmaking(league_for_table(table_id).league_id)
    except Exception:
        log.exception("taken off the table, but matchmaking failed (table %s)", table_id)
    return outcome, other_id


@retry_on_deadlock
def _take_off_table(user_id, table_id, expected_match_id):
    """The change at the table, in one transaction. Returns (outcome, other_id)."""
    try:
        # The table's lock, then the match's - the order matchmaking uses.
        match = lock_active_match_for_player(user_id)
        if match is None or match.table_id != table_id:
            db.session.rollback()
            return TABLE_REMOVE_RESULT_NOT_AT_TABLE, None
        if expected_match_id is not None and match.match_id != expected_match_id:
            db.session.rollback()
            return TABLE_REMOVE_RESULT_GAME_CHANGED, None

        other_id = take_off_table(match, user_id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    if other_id is None:
        return TABLE_REMOVE_RESULT_TABLE_FREED, None
    return TABLE_REMOVE_RESULT_GAME_CALLED_OFF, other_id
