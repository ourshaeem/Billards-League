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
"""
from database import retry_on_deadlock, seconds_since
from logic.manage_queue import _lock_table
from logic.record_match import lowered_rating, update_player_rank
from logic.tables import league_for_table
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
