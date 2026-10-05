"""
Correcting the record by hand: taking back a finished game that
shouldn't count - played by accident, say.

Voiding a game deletes it from the history and reverses exactly what it
did: the winner gives back the points it gave them (never going below
the floor of 0), the loser gets back the points it actually cost them,
and each loses that game from their wins or losses. Both players' ranks
follow their ratings again. Games played since are left as they were -
each was scored against the ratings of its day.

Only for games since the league was last reset (seasons.py): a reset
already wiped out what an older game did.

Run it with the CLI command in app.py:
    flask --app app void-game 33
which shows the game and what will change, asks first, and saves the
game and both players' numbers to a backup file.

The other way round, adding games that never reached the app - played
while the server was down - is add_past_games:
    flask --app app add-games ping_pong --game Mel "Tom Holland" 11-1 ...
"""
from database import retry_on_deadlock, seconds_since
from logic.manage_queue import _lock_table
from logic.record_match import (
    apply_result,
    elo_change_for,
    lowered_rating,
    score_problem,
    update_player_rank,
)
from logic.tables import default_table_for, league_for_table
from models import LEAGUE_NAMES, STARTING_ELO, Match, Player, db


class GameProblem(ValueError):
    """A game that can't be voided; the message says why."""


def _numbers(player, league):
    fields = Player.LEAGUE_FIELDS[league]
    elo = getattr(player, fields["elo"])
    return {
        "user_id": player.user_id,
        "username": player.username,
        "elo": STARTING_ELO if elo is None else elo,
        "wins": getattr(player, fields["wins"]) or 0,
        "losses": getattr(player, fields["losses"]) or 0,
    }


def _finished_game(match_id, lock=False):
    """The finished game, or GameProblem. With lock, held until commit."""
    match = db.session.get(Match, match_id, with_for_update=lock, populate_existing=lock)
    if match is None:
        raise GameProblem(f"There's no game #{match_id}.")
    if match.match_status != Match.STATUS_FINISHED or match.winner_id is None or match.loser_id is None:
        raise GameProblem(
            f"Game #{match_id} hasn't finished, so there's nothing to take back - "
            "report it, or cancel it from the app if both players agree."
        )
    return match


def game_summary(match_id):
    """
    What voiding a game would undo, without changing anything:
    {match_id, league_type, league_name, seconds_ago, elo_change, score,
     winner: {user_id, username, elo, wins, losses}, loser: {...}}
    - the players' numbers as they are now. Raises GameProblem.
    """
    match = _finished_game(match_id)
    league = league_for_table(match.table_id)
    seconds = db.session.scalar(
        db.select(seconds_since(Match.played_at)).where(Match.match_id == match_id)
    )
    return {
        "match_id": match.match_id,
        "league_type": league,
        "league_name": LEAGUE_NAMES[league],
        "seconds_ago": None if seconds is None else max(0, int(seconds)),
        "elo_change": match.elo_change or 0,
        # Less than elo_change when the loser stopped at the floor.
        "loser_elo_change": match.loser_points_lost or 0,
        "score": [match.balls_for(match.winner_id), match.balls_for(match.loser_id)],
        "winner": _numbers(match.winner, league),
        "loser": _numbers(match.loser, league),
    }


@retry_on_deadlock
def void_finished_match(match_id):
    """
    Take back a finished game: delete it, and reverse what it did to both
    players' ratings, records and ranks in its league. Returns
    {"before": game_summary, "after": {winner: numbers, loser: numbers}}.
    Raises GameProblem for a game that doesn't exist or isn't finished.

    Under the table's lock, like recording a game there: two changes to
    the same players' ratings must not interleave, or one would undo the
    other.
    """
    try:
        table_id = _finished_game(match_id).table_id
        _lock_table(table_id)
        match = _finished_game(match_id, lock=True)
        # Locked and re-read, so the numbers changed are the latest ones,
        # not a copy loaded before this request waited for the lock.
        winner = db.session.get(Player, match.winner_id, with_for_update=True, populate_existing=True)
        loser = db.session.get(Player, match.loser_id, with_for_update=True, populate_existing=True)
        before = game_summary(match_id)

        league = before["league_type"]
        fields = Player.LEAGUE_FIELDS[league]
        change = before["elo_change"]

        setattr(winner, fields["elo"], lowered_rating(before["winner"]["elo"], change))
        setattr(winner, fields["wins"], max(0, before["winner"]["wins"] - 1))
        setattr(loser, fields["elo"], before["loser"]["elo"] + before["loser_elo_change"])
        setattr(loser, fields["losses"], max(0, before["loser"]["losses"] - 1))
        update_player_rank(winner, league)
        update_player_rank(loser, league)

        db.session.delete(match)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "before": before,
        "after": {"winner": _numbers(winner, league), "loser": _numbers(loser, league)},
    }


def past_game_problem(league, winner_score, loser_score):
    """
    Why a game to be added can't be right, or None. The winner's score
    comes first, and has to be the higher one - the league's own rules
    (score_problem) do the rest.
    """
    if winner_score <= loser_score:
        return (
            f"{winner_score}-{loser_score}: give the winner's score first - "
            "it has to be the higher one."
        )
    return score_problem(league, winner_score, loser_score)


@retry_on_deadlock
def add_past_games(league, games):
    """
    Record finished games that never reached the app - played while the
    server was down, say. `games` is a list of (winner_id, loser_id,
    winner_score, loser_score), in the order they were played. Each is
    scored against the ratings the one before it left, by the same
    formula and the same apply_result as a reported game, so the ladder
    ends up exactly as if they had been reported at the time.

    Unlike a reported game, nobody's place at the table changes: these
    games are over, and whoever is at the table now stays. Their time in
    the history is when they were added.

    All or nothing, in one transaction under the league's table lock (as
    recording a game there takes it). Raises GameProblem, saving nothing,
    for a score that doesn't fit, a player listed against themselves, or
    a player who doesn't exist. Returns one dict per game, in order:
    {match_id, winner, loser, score, elo_change, loser_elo_change,
     winner_elo, loser_elo} - the ratings being those after the game.
    """
    if not games:
        raise GameProblem("No games to add.")
    for winner_id, loser_id, winner_score, loser_score in games:
        if winner_id == loser_id:
            raise GameProblem("A game needs two different players.")
        problem = past_game_problem(league, winner_score, loser_score)
        if problem:
            raise GameProblem(problem)

    table_id = default_table_for(league)
    if table_id is None:
        raise GameProblem(f"The {LEAGUE_NAMES[league]} has no table to record games at.")

    try:
        _lock_table(table_id)
        # Every player locked and read once, up front, in id order: each
        # game then changes the same in-memory rows the next one reads.
        players = {}
        for user_id in sorted({p for game in games for p in game[:2]}):
            player = db.session.get(Player, user_id, with_for_update=True, populate_existing=True)
            if player is None or player.is_deleted:
                raise GameProblem(f"There's no player #{user_id}.")
            players[user_id] = player

        fields = Player.LEAGUE_FIELDS[league]
        results = []
        for winner_id, loser_id, winner_score, loser_score in games:
            winner, loser = players[winner_id], players[loser_id]
            elo_change = elo_change_for(league, winner, loser, winner_score, loser_score)
            match = Match(
                table_id=table_id,
                player_one_id=winner_id,
                player_two_id=loser_id,
                player_one_balls=winner_score,
                player_two_balls=loser_score,
                winner_id=winner_id,
                loser_id=loser_id,
                elo_change=elo_change,
                match_status=Match.STATUS_FINISHED,
            )
            db.session.add(match)
            loser_change = apply_result(match, winner, loser, elo_change, league)
            db.session.flush()
            results.append(
                {
                    "match_id": match.match_id,
                    "winner": winner.username,
                    "loser": loser.username,
                    "score": [winner_score, loser_score],
                    "elo_change": elo_change,
                    "loser_elo_change": loser_change,
                    "winner_elo": getattr(winner, fields["elo"]),
                    "loser_elo": getattr(loser, fields["elo"]),
                }
            )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return results
