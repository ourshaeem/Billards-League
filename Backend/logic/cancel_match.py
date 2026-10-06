"""
Calling a game off, when both players agree.

Either player in a game can ask to cancel it - say the challenger has to
leave before they could finish. Nothing happens until the other player
agrees; until then either of them can take the request back and play on.
A game is never cancelled on one player's word: that would let anyone
about to lose wipe the game out.

A cancelled game is as if it was never played: no result, no rating
change, nothing in the history. Its Active row is deleted rather than
given a new status - the local database's match_status column is an ENUM
that only allows the statuses already in use. After that:

  - If player one was holding the table - they won the last game here and
    stayed on - they keep it, and the next in line is up to challenge
    them. The other player is free to go.
  - Otherwise both had come off the queue together for this game, and
    the table goes to the next two in line.
"""
import logging

from database import retry_on_deadlock
from logic.manage_queue import attempt_matchmaking, lock_active_match_for_player
from logic.tables import league_for_table
from models import Match, db

log = logging.getLogger(__name__)

# request_cancel outcomes.
CANCEL_RESULT_REQUESTED = "requested"
CANCEL_RESULT_ALREADY_REQUESTED = "already_requested"
CANCEL_RESULT_CANCELLED = "cancelled"
CANCEL_RESULT_NO_GAME = "no_game"
CANCEL_RESULT_NO_OPPONENT = "no_opponent"
CANCEL_RESULT_GAME_OVER = "game_over"

# keep_playing outcomes.
KEEP_RESULT_KEPT = "kept"
KEEP_RESULT_NOTHING_TO_KEEP = "nothing_to_keep"
KEEP_RESULT_NO_GAME = "no_game"
KEEP_RESULT_GAME_OVER = "game_over"


@retry_on_deadlock
def request_cancel(user_id, expected_match_id=None):
    """
    Ask to call off your game, or agree to the other player's asking.
    Returns one of the CANCEL_RESULT_*.

    expected_match_id is the game the player saw, as for reporting a
    score: if that game is over, nothing happens, rather than the request
    landing on whatever game they're in now.
    """
    try:
        match = lock_active_match_for_player(user_id)
        problem = _problem_with(match, expected_match_id)
        if problem:
            db.session.rollback()
            return {
                "no_game": CANCEL_RESULT_NO_GAME,
                "game_over": CANCEL_RESULT_GAME_OVER,
                "no_opponent": CANCEL_RESULT_NO_OPPONENT,
            }[problem]

        if match.cancel_requested_by is None:
            match.cancel_requested_by = user_id
            db.session.commit()
            return CANCEL_RESULT_REQUESTED
        if match.cancel_requested_by == user_id:
            db.session.rollback()
            return CANCEL_RESULT_ALREADY_REQUESTED

        # The other player asked, and this one agrees.
        table_id = match.table_id
        _call_off(match)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    # The table has room again: the next in line is up.
    try:
        attempt_matchmaking(league_for_table(table_id).league_id)
    except Exception:
        log.exception("game called off, but matchmaking failed (table %s)", table_id)
    return CANCEL_RESULT_CANCELLED


@retry_on_deadlock
def keep_playing(user_id, expected_match_id=None):
    """
    Take back your own request to cancel, or turn down the other
    player's: the game goes on. Returns one of the KEEP_RESULT_*.
    """
    try:
        match = lock_active_match_for_player(user_id)
        problem = _problem_with(match, expected_match_id)
        if problem == "no_opponent":
            problem = "no_game"
        if problem:
            db.session.rollback()
            return KEEP_RESULT_GAME_OVER if problem == "game_over" else KEEP_RESULT_NO_GAME

        if match.cancel_requested_by is None:
            db.session.rollback()
            return KEEP_RESULT_NOTHING_TO_KEEP
        match.cancel_requested_by = None
        db.session.commit()
        return KEEP_RESULT_KEPT
    except Exception:
        db.session.rollback()
        raise


def _problem_with(match, expected_match_id):
    """Why there's no game here to cancel, or None if there is one."""
    if match is None:
        return "game_over" if expected_match_id is not None else "no_game"
    if expected_match_id is not None and match.match_id != expected_match_id:
        return "game_over"
    if not match.is_in_progress:
        # A king waiting for a challenger has no game to call off; they
        # can give up the table instead.
        return "no_opponent"
    return None


def _call_off(match):
    """
    Delete a game both players agreed to cancel. A king who was holding
    the table goes back to waiting for a challenger, under a new match
    row: a score either player sends for the cancelled game then finds
    nothing, rather than landing on the king's next game.
    """
    king_keeps_table = _was_holding_the_table(match)
    db.session.delete(match)
    if king_keeps_table:
        db.session.add(
            Match(
                table_id=match.table_id,
                player_one_id=match.player_one_id,
                player_two_id=None,
                match_status=Match.STATUS_ACTIVE,
            )
        )
    log.info(
        "game %s called off by agreement (%s keeps the table)",
        match.match_id,
        match.player_one_id if king_keeps_table else "nobody",
    )


def _was_holding_the_table(match):
    """
    True if player one won the last game at this table and stayed on: a
    king, rather than the first of two players who came off the queue
    together. Read from Matches, never from Pool_Tables' king columns -
    those are a display cache, and nothing decides anything from them.
    """
    last_winner = db.session.scalar(
        db.select(Match.winner_id)
        .where(
            Match.table_id == match.table_id,
            Match.match_status == Match.STATUS_FINISHED,
            Match.match_id < match.match_id,
        )
        .order_by(Match.match_id.desc())
        .limit(1)
    )
    return last_winner is not None and last_winner == match.player_one_id
