"""
Leagues and the tables they play on.

A league (models.League - CCNY Billiards, John Jay Ping Pong, ...) has
any number of tables, which the organiser can add, rename and remove. A
table belongs to exactly one league, and a match belongs to the league of
the table it was played on: that is how every game, rating and badge
finds its league. This module is where a table becomes a league and a
league becomes its tables.
"""
from logic.achievements import featured_badges
from models import BILLIARDS, GAMES, LEAGUE_NAMES, League, Match, PoolTable, db

# The table a request means when it names neither a table nor a league -
# the only one the UI offered before there were leagues.
DEFAULT_TABLE_ID = 1


def league_for_table(table_id):
    """
    The League a table belongs to. A table the venue never registered, or
    one from before schools that ensure_schema() hasn't placed yet, counts
    as the league of its game at CCNY - which is where every table was.
    """
    table = db.session.get(PoolTable, table_id)
    if table is not None and table.league_id is not None:
        league = db.session.get(League, table.league_id)
        if league is not None:
            return league
    game = table.league_type if table is not None and table.league_type else BILLIARDS
    return League.of(game)


def in_league(league):
    """
    A condition for a query outer-joined to Pool_Tables on the game's
    table: the table belongs to `league`. A table the venue never
    registered counts as CCNY's billiards, as league_for_table() says.
    """
    league = League.of(league)
    condition = PoolTable.league_id == league.league_id
    if league.legacy_key == BILLIARDS:
        condition = db.or_(condition, PoolTable.table_id.is_(None))
    return condition


def active_tables(league):
    """A league's tables that are in use, lowest-numbered first."""
    league = League.of(league)
    if league is None:
        return []
    return list(
        db.session.scalars(
            db.select(PoolTable)
            .where(PoolTable.league_id == league.league_id, PoolTable.is_active.is_(True))
            .order_by(PoolTable.table_id)
        )
    )


def default_table_for(league):
    """A league's first table in use, or None if it has none."""
    tables = active_tables(league)
    return tables[0].table_id if tables else None


def table_names(league):
    """{table_id: table_name} for every table a league has had."""
    league = League.of(league)
    if league is None:
        return {}
    return dict(
        db.session.execute(
            db.select(PoolTable.table_id, PoolTable.table_name).where(
                PoolTable.league_id == league.league_id
            )
        ).all()
    )


def list_leagues():
    """
    CCNY's two leagues as apps from before schools know them, for
    GET /leagues: [{league_type, name, table_id, table_name}, ...] - the
    league's first table. table_id is None for a league with no table.
    """
    result = []
    for game in GAMES:
        league = League.of(game)
        tables = active_tables(league)
        result.append(
            {
                "league_type": game,
                "league_id": league.league_id if league else None,
                "name": league.name if league else LEAGUE_NAMES[game],
                "table_id": tables[0].table_id if tables else None,
                "table_name": tables[0].table_name if tables else None,
            }
        )
    return result


def table_snapshot(table_id):
    """
    What is happening at a table right now, for everyone watching - not
    just the players on it. None if the table doesn't exist.

        {table_id, table_name, league_type, league_id, is_active, state,
         match_id, king, challenger, king_streak, table_record_streak,
         king_badge, challenger_badge}

    state is "free", "waiting_for_challenger" or "playing". king and
    challenger are player cards (see Player.to_card) carrying their rank
    and rating in this table's league; king_badge / challenger_badge are
    the badge each shows by their name in it ({key, name, tier} or None).
    table_record_streak is the longest run anyone has had here.

    A plain read, no locks: this is a display, and matchmaking - the only
    thing that changes who is at a table - never reads it.
    """
    table = db.session.get(PoolTable, table_id)
    if table is None:
        return None

    league = league_for_table(table_id)
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
    king = active.player_one if active is not None else None
    challenger = active.player_two if active is not None else None
    badges = featured_badges([king, challenger], league)

    return {
        "table_id": table.table_id,
        "table_name": table.table_name,
        "league_type": league.game if league else BILLIARDS,
        "league_id": league.league_id if league else None,
        "is_active": bool(table.is_active),
        "state": state,
        "match_id": active.match_id if active is not None else None,
        "king": king.to_card(league) if king else None,
        "challenger": challenger.to_card(league) if challenger else None,
        "king_streak": streak,
        "table_record_streak": table.table_record_streak or 0,
        "king_badge": badges.get(king.user_id) if king else None,
        "challenger_badge": badges.get(challenger.user_id) if challenger else None,
    }


def league_tables(league):
    """Every table a league has in use, as table_snapshot()s."""
    return [table_snapshot(table.table_id) for table in active_tables(league)]
