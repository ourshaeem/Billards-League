"""
The champions across every school: the top 3 in each game - billiards and
ping pong - this week, this month and of all time, whichever league they
play in. Shown at the top of the league picker, before anyone chooses.

This week and this month: most rating points gained, net, as for the
players of the day, week and month (logic/top_players.py) - but across
all of a game's leagues at once, adding up what a player gained in each.
Only someone who won a game in the period can place; the periods are the
same calendar ones, in LEAGUE_TIMEZONE. All time: the highest rating
anyone holds in a league of that game - their best, if they're in more
than one - among players who have finished a game there. Rating rather
than wins, because it's what each ladder is ordered by: a hundred wins
against newcomers shouldn't outrank a player nobody can beat.

Ties go to more wins, then fewer losses, then whoever joined first (the
lower user_id), so the order never flickers between loads. Deleted
accounts are left out, as they are off the ladders.

Each place carries the player's card in the league the place was earned
in - where they gained the most points that period, or whose rating it
is - with that league's name and school, so the apps can say "Giant,
CCNY Ping Pong".
"""
from collections import defaultdict
from datetime import datetime

from database import seconds_since
from logic.top_players import league_timezone, period_lengths
from models import BILLIARDS, GAMES, League, Match, Player, PoolTable, Standing, db

TOP = 3
PERIODS = ("week", "month")


def global_leaderboard(now=None):
    """
    {timezone, sports: {billiards: {week, month, all_time}, ping_pong: ...}},
    each timeframe a list of up to TOP places, best first:
        {place, player: card, league_id, league_name, school, wins, losses,
         points (week and month: net points gained) | elo (all time)}
    wins and losses are the period's, in every league of the game, or (all
    time) the record in the league whose rating it is.
    """
    tz = league_timezone()
    lengths = period_lengths(now or datetime.now(tz))
    leagues = {league.league_id: league for league in db.session.scalars(db.select(League))}
    # A game at a table nobody registered counts as CCNY's billiards, as
    # everywhere else (logic.tables.league_for_table).
    fallback = League.of(BILLIARDS)

    period_places = _period_tallies(lengths, leagues, fallback)
    best = _best_ratings()

    ids = {uid for game in period_places.values() for tally in game.values() for uid in tally}
    ids |= {uid for game in best.values() for uid in game}
    players = (
        {
            player.user_id: player
            for player in db.session.scalars(db.select(Player).where(Player.user_id.in_(ids)))
            if not player.is_deleted
        }
        if ids
        else {}
    )

    sports = {}
    for game in GAMES:
        sports[game] = {
            **{
                period: _rank_period(period_places[game][period], players, leagues)
                for period in PERIODS
            },
            "all_time": _rank_all_time(best[game], players, leagues),
        }
    return {"timezone": tz.key, "sports": sports}


def _period_tallies(lengths, leagues, fallback):
    """
    {game: {period: {user_id: {points, wins, losses, by_league}}}} for the
    finished games in each period - by_league being the points gained in
    each league, to say where the place was earned.
    """
    seconds_ago = seconds_since(Match.played_at)
    longest = max(lengths[period] for period in PERIODS)
    rows = db.session.execute(
        db.select(
            Match.winner_id,
            Match.loser_id,
            Match.elo_change,
            Match.loser_elo_change,
            PoolTable.league_id,
            seconds_ago,
        )
        .outerjoin(PoolTable, PoolTable.table_id == Match.table_id)
        .where(
            Match.match_status == Match.STATUS_FINISHED,
            Match.winner_id.isnot(None),
            Match.loser_id.isnot(None),
            seconds_ago <= longest,
        )
    ).all()

    def blank():
        return {"points": 0, "wins": 0, "losses": 0, "by_league": defaultdict(int)}

    tallies = {game: {period: defaultdict(blank) for period in PERIODS} for game in GAMES}
    for winner_id, loser_id, change, loser_change, league_id, seconds in rows:
        league = leagues.get(league_id) or fallback
        if seconds is None or league is None or league.game not in tallies:
            continue
        lost = change if loser_change is None else loser_change
        for period in PERIODS:
            if seconds > lengths[period]:
                continue
            winner = tallies[league.game][period][winner_id]
            winner["points"] += change or 0
            winner["wins"] += 1
            winner["by_league"][league.league_id] += change or 0
            loser = tallies[league.game][period][loser_id]
            loser["points"] -= lost or 0
            loser["losses"] += 1
            loser["by_league"][league.league_id] -= lost or 0
    return tallies


def _rank_period(tally, players, leagues):
    contenders = [
        (user_id, numbers)
        for user_id, numbers in tally.items()
        if user_id in players and numbers["wins"] > 0
    ]
    contenders.sort(key=lambda c: (-c[1]["points"], -c[1]["wins"], c[1]["losses"], c[0]))
    places = []
    for place, (user_id, numbers) in enumerate(contenders[:TOP], start=1):
        # Where they earned it: most points gained, then the league listed first.
        league = max(
            (leagues[league_id] for league_id in numbers["by_league"] if league_id in leagues),
            key=lambda l: (numbers["by_league"][l.league_id], -l.sort_order),
        )
        places.append(
            {
                **_place(place, players[user_id], league),
                "points": numbers["points"],
                "wins": numbers["wins"],
                "losses": numbers["losses"],
            }
        )
    return places


def _best_ratings():
    """
    {game: {user_id: Standing}}: each player's best rating in a league of
    each game, among standings with at least one finished game.
    """
    best = {game: {} for game in GAMES}
    rows = db.session.execute(
        db.select(Standing, League.game)
        .join(League, League.league_id == Standing.league_id)
        .where((Standing.wins + Standing.losses) > 0)
    ).all()
    for standing, game in rows:
        if game not in best:
            continue
        current = best[game].get(standing.user_id)
        if current is None or (standing.elo or 0, standing.wins or 0) > (current.elo or 0, current.wins or 0):
            best[game][standing.user_id] = standing
    return best


def _rank_all_time(best, players, leagues):
    contenders = [standing for user_id, standing in best.items() if user_id in players]
    contenders.sort(key=lambda s: (-(s.elo or 0), -(s.wins or 0), s.losses or 0, s.user_id))
    return [
        {
            **_place(place, players[standing.user_id], leagues[standing.league_id]),
            "elo": standing.elo or 0,
            "wins": standing.wins or 0,
            "losses": standing.losses or 0,
        }
        for place, standing in enumerate(contenders[:TOP], start=1)
    ]


def _place(place, player, league):
    return {
        "place": place,
        "player": player.to_card(league),
        "league_id": league.league_id,
        "league_name": league.name,
        "school": league.school,
    }
