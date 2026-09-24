"""
Finished games, newest first: for one league (optionally one table), or
for one player.

Each entry carries both players as cards - avatar, flag, and their
current rank and rating in that league - so the feed and its hover cards
need no further requests. See Match.to_history_dict for the shape.
"""
from sqlalchemy.orm import selectinload

from database import seconds_since
from models import BILLIARDS, PING_PONG, Match, Player, PoolTable, db

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def _finished_in_league(league):
    """
    Finished games whose table belongs to `league`, newest first, each
    paired with how many seconds ago it finished.

    The outer join counts a game on a table the venue never registered as
    billiards - the same default league_for_table() uses.
    """
    seconds_ago = seconds_since(Match.played_at).label("seconds_ago")
    table_league = db.func.coalesce(PoolTable.league_type, BILLIARDS)

    stmt = (
        db.select(Match, seconds_ago)
        .outerjoin(PoolTable, PoolTable.table_id == Match.table_id)
        .where(
            Match.match_status == Match.STATUS_FINISHED,
            Match.winner_id.isnot(None),
            table_league == league,
        )
        .order_by(Match.played_at.desc(), Match.match_id.desc())
    )
    if league == PING_PONG:
        # Each card shows a ping pong rank. Load every one needed in one
        # query up front, rather than one per player as the cards are drawn.
        stmt = stmt.options(
            selectinload(Match.winner).selectinload(Player.ping_pong_rank),
            selectinload(Match.loser).selectinload(Player.ping_pong_rank),
        )
    return stmt


def league_history(league, table_id=None, limit=DEFAULT_LIMIT):
    """The latest finished games in a league, optionally at one table."""
    stmt = _finished_in_league(league)
    if table_id is not None:
        stmt = stmt.where(Match.table_id == table_id)

    rows = db.session.execute(stmt.limit(limit)).all()
    return [match.to_history_dict(league, _whole(seconds)) for match, seconds in rows]


def player_history(user_id, league, limit=DEFAULT_LIMIT):
    """
    One player's finished games in a league, each with "result" ("won" or
    "lost") from their side.
    """
    stmt = _finished_in_league(league).where(
        db.or_(Match.winner_id == user_id, Match.loser_id == user_id)
    )
    rows = db.session.execute(stmt.limit(limit)).all()
    return [
        match.to_history_dict(league, _whole(seconds), viewer_id=user_id)
        for match, seconds in rows
    ]


def _whole(seconds):
    """
    Seconds as a whole, never-negative number, or None if the row has no
    timestamp. A clock nudged backwards must not read "-3 seconds ago".
    """
    if seconds is None:
        return None
    return max(0, int(seconds))
