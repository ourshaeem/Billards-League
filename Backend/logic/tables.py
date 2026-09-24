"""
Tables and the leagues that play on them.

A league is a property of a table: Pool_Tables.league_type. Everything
else follows from that. Queues and matches were already keyed on
table_id, so once a request has been turned into a table, the one
matchmaking implementation in manage_queue serves both leagues without
knowing either exists. This module is where a league becomes a table and
a table becomes a league.
"""
from models import BILLIARDS, LEAGUE_NAMES, LEAGUE_TYPES, Match, PoolTable, db

# The table a request means when it names neither a table nor a league -
# the only one the UI offered before there were two leagues.
DEFAULT_TABLE_ID = 1


def league_for_table(table_id):
    """
    The league a table belongs to. A table the venue never registered
    counts as billiards, which is what every table was before ping pong.
    """
    league = db.session.scalar(
        db.select(PoolTable.league_type).where(PoolTable.table_id == table_id)
    )
    return league or BILLIARDS


def default_table_for(league):
    """The table a league plays on when none is named: its lowest-numbered."""
    return db.session.scalar(
        db.select(PoolTable.table_id)
        .where(PoolTable.league_type == league)
        .order_by(PoolTable.table_id)
        .limit(1)
    )


def list_leagues():
    """
    Every league with the table it plays on, for GET /leagues:
        [{league_type, name, table_id, table_name}, ...]
    table_id is None for a league with no table yet.
    """
    tables = {
        table.league_type: table
        for table in db.session.scalars(
            # Highest first, so the dict ends up holding each league's lowest.
            db.select(PoolTable).order_by(PoolTable.table_id.desc())
        )
    }
    return [
        {
            "league_type": league,
            "name": LEAGUE_NAMES[league],
            "table_id": tables[league].table_id if league in tables else None,
            "table_name": tables[league].table_name if league in tables else None,
        }
        for league in LEAGUE_TYPES
    ]


def table_snapshot(table_id):
    """
    What is happening at a table right now, for everyone watching - not
    just the players on it. None if the table doesn't exist.

        {table_id, table_name, league_type, state, match_id,
         king, challenger, king_streak}

    state is "free", "waiting_for_challenger" or "playing". king and
    challenger are player cards (see Player.to_card) carrying their rank
    and rating in this table's league.

    A plain read, no locks: this is a display, and matchmaking - the only
    thing that changes who is at a table - never reads it.
    """
    table = db.session.get(PoolTable, table_id)
    if table is None:
        return None

    league = table.league_type or BILLIARDS
    active = db.session.scalars(
        db.select(Match)
        .where(Match.table_id == table_id, Match.match_status == Match.STATUS_ACTIVE)
        .order_by(Match.match_id.desc())
        .limit(1)
    ).first()

    if active is None:
        state = "free"
    elif active.is_awaiting_challenger:
        state = "waiting_for_challenger"
    else:
        state = "playing"

    # The streak lives in the Pool_Tables display cache. Shown only when
    # the cache agrees with Matches about who the king is; otherwise it
    # describes a reign that has already ended.
    king_id = active.player_one_id if active is not None else None
    streak = (table.current_streak or 0) if king_id and table.current_king_id == king_id else 0

    return {
        "table_id": table.table_id,
        "table_name": table.table_name,
        "league_type": league,
        "state": state,
        "match_id": active.match_id if active is not None else None,
        "king": active.player_one.to_card(league) if active and active.player_one else None,
        "challenger": active.player_two.to_card(league) if active and active.player_two else None,
        "king_streak": streak,
    }
