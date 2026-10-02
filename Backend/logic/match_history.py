"""
Finished games, newest first: for one league (optionally one table), or
for one player (optionally against one opponent) - and a player's record
against each person they've played.

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


def player_history(user_id, league, limit=DEFAULT_LIMIT, opponent_id=None):
    """
    One player's finished games in a league, each with "result" ("won" or
    "lost") from their side. With opponent_id, only the games between
    those two - head to head.
    """
    stmt = _finished_in_league(league).where(
        db.or_(Match.winner_id == user_id, Match.loser_id == user_id)
    )
    if opponent_id is not None:
        if opponent_id == user_id:
            return []  # nobody plays themselves
        stmt = stmt.where(db.or_(Match.winner_id == opponent_id, Match.loser_id == opponent_id))
    rows = db.session.execute(stmt.limit(limit)).all()
    return [
        match.to_history_dict(league, _whole(seconds), viewer_id=user_id)
        for match, seconds in rows
    ]


# The most opponents player_opponents lists: more than anyone plays in a
# league season here, and it keeps one response from growing without end.
MAX_OPPONENTS = 100


def player_opponents(user_id, league):
    """
    Everyone a player has played in a league, with the player's record
    against each: [{opponent: card, wins, losses}], most games first.
    wins and losses are from the player's side.
    """
    won = db.case((Match.winner_id == user_id, 1), else_=0)
    games = (
        db.select(
            db.case((Match.winner_id == user_id, Match.loser_id), else_=Match.winner_id).label(
                "opponent_id"
            ),
            won.label("won"),
            Match.match_id,
        )
        .outerjoin(PoolTable, PoolTable.table_id == Match.table_id)
        .where(
            Match.match_status == Match.STATUS_FINISHED,
            Match.winner_id.isnot(None),
            Match.loser_id.isnot(None),
            db.func.coalesce(PoolTable.league_type, BILLIARDS) == league,
            db.or_(Match.winner_id == user_id, Match.loser_id == user_id),
        )
        .subquery()
    )
    played = db.func.count()
    latest = db.func.max(games.c.match_id)
    rows = db.session.execute(
        db.select(games.c.opponent_id, db.func.sum(games.c.won), played)
        .group_by(games.c.opponent_id)
        .order_by(played.desc(), latest.desc())
        .limit(MAX_OPPONENTS)
    ).all()

    stmt = db.select(Player).where(Player.user_id.in_([row[0] for row in rows]))
    if league == PING_PONG:
        stmt = stmt.options(selectinload(Player.ping_pong_rank))
    players = {player.user_id: player for player in db.session.scalars(stmt)}

    return [
        {
            "opponent": players[opponent_id].to_card(league),
            "wins": int(wins or 0),
            "losses": int(total) - int(wins or 0),
        }
        for opponent_id, wins, total in rows
        if opponent_id in players
    ]


def _whole(seconds):
    """
    Seconds as a whole, never-negative number, or None if the row has no
    timestamp. A clock nudged backwards must not read "-3 seconds ago".
    """
    if seconds is None:
        return None
    return max(0, int(seconds))
