"""
The players of the day, the week and the month in a league: whoever
gained the most rating points over each - the podium on the status
panel.

Most points gained, not most wins: beating someone rated far above you
is worth more than beating a newcomer, as on the ladder itself. Points
are net - what a player's wins gave them, less what their losses really
cost them (loser_elo_change, which is nothing for a loser already at the
floor of 0). Only someone who won at least once can take a period. Ties
go to more wins, then fewer losses, then the higher rating now.

The periods are calendar ones in the league's own time
(LEAGUE_TIMEZONE, New York unless the host says otherwise): today since
midnight, this week since Monday, this month since the 1st. Each start
is turned into "this many seconds ago" and compared with how long ago
each game finished by the database's clock - the same reason the queue
timer is measured there - so the server's own timezone never enters
into it.

Deleted accounts are left out, as they are off the ladder.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from database import seconds_since
from logic.tables import in_league
from models import League, Match, Player, PoolTable, db

log = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/New_York"
PERIODS = ("day", "week", "month")


def league_timezone():
    """The league's timezone: LEAGUE_TIMEZONE, or New York."""
    name = os.environ.get("LEAGUE_TIMEZONE") or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except Exception:
        log.warning("unknown LEAGUE_TIMEZONE %r; using %s", name, DEFAULT_TIMEZONE)
        return ZoneInfo(DEFAULT_TIMEZONE)


def period_lengths(now):
    """
    How many seconds ago today, this week (from Monday) and this month
    began, for `now` - an aware datetime in the league's timezone.

    Measured in UTC, so a change of clocks inside the period (the first
    Sunday of November, say) counts the hour it really added or took.
    """
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    starts = {
        "day": midnight,
        "week": midnight - timedelta(days=midnight.weekday()),
        "month": midnight.replace(day=1),
    }
    now_utc = now.astimezone(timezone.utc)
    return {
        period: (now_utc - start.astimezone(timezone.utc)).total_seconds()
        for period, start in starts.items()
    }


def top_players(league, now=None):
    """
    {league_type, timezone, day, week, month}: each period is None when
    nobody has won a game in it yet, otherwise
        {player: card, points, wins, losses}
    with points the net rating points they gained in it.
    """
    league = League.of(league)
    tz = league_timezone()
    lengths = period_lengths(now or datetime.now(tz))

    seconds_ago = seconds_since(Match.played_at)
    rows = db.session.execute(
        db.select(
            Match.winner_id, Match.loser_id, Match.elo_change, Match.loser_elo_change, seconds_ago
        )
        .outerjoin(PoolTable, PoolTable.table_id == Match.table_id)
        .where(
            Match.match_status == Match.STATUS_FINISHED,
            Match.winner_id.isnot(None),
            Match.loser_id.isnot(None),
            in_league(league),
            seconds_ago <= max(lengths.values()),
        )
    ).all()

    # {period: {user_id: [points, wins, losses]}}
    tallies = {period: {} for period in PERIODS}
    for winner_id, loser_id, change, loser_change, seconds in rows:
        if seconds is None:
            continue
        lost = change if loser_change is None else loser_change
        for period in PERIODS:
            if seconds <= lengths[period]:
                winner = tallies[period].setdefault(winner_id, [0, 0, 0])
                winner[0] += change or 0
                winner[1] += 1
                loser = tallies[period].setdefault(loser_id, [0, 0, 0])
                loser[0] -= lost or 0
                loser[2] += 1

    ids = {user_id for tally in tallies.values() for user_id in tally}
    players = {
        player.user_id: player
        for player in db.session.scalars(db.select(Player).where(Player.user_id.in_(ids)))
        if not player.is_deleted
    } if ids else {}

    result = {"league_type": league.game, "league_id": league.league_id, "timezone": tz.key}
    for period in PERIODS:
        contenders = [
            (user_id, numbers)
            for user_id, numbers in tallies[period].items()
            if user_id in players and numbers[1] > 0
        ]
        if not contenders:
            result[period] = None
            continue
        user_id, (points, wins, losses) = max(
            contenders,
            key=lambda c: (
                c[1][0],
                c[1][1],
                -c[1][2],
                players[c[0]].standing(league)["elo"] or 0,
                -c[0],
            ),
        )
        result[period] = {
            "player": players[user_id].to_card(league),
            "points": points,
            "wins": wins,
            "losses": losses,
        }
    return result
