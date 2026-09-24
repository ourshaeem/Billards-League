"""
Recording a finished match: ELO, ranks, and handing the table over.

Sequence when a score is reported:
  1. The match is closed with a real winner.
  2. Both players' ELO, win/loss counts and ranks are updated.
  3. The winner stays on as king - a new Active match with no challenger.
  4. Matchmaking runs, pulling the next person off the queue if anyone
     is waiting.
  5. Pool_Tables' display cache (king, streaks) is refreshed.

Steps 1-3 happen in one transaction. If anything fails, none of it lands,
so a match can never be half-recorded with one player's ELO moved.
"""
import logging

from database import retry_on_deadlock
from models import STARTING_ELO, Match, PoolTable, Player, Rank, db
from logic.manage_queue import attempt_matchmaking, lock_active_match_for_player

log = logging.getLogger(__name__)

# Standard club-level K-factor: enough that a few games move you, not so
# much that one upset reshuffles the ladder.
ELO_K_FACTOR = 32
DEFAULT_ELO = STARTING_ELO

# report_result outcomes.
REPORT_RESULT_RECORDED = "recorded"
REPORT_RESULT_ALREADY_REPORTED = "already_reported"
REPORT_RESULT_NO_GAME = "no_game"
REPORT_RESULT_NO_OPPONENT = "no_opponent"


def _rating(player):
    """
    A player's rating, treating only a missing value as the default.

    `player.elo_rating or DEFAULT_ELO` - what this used to say - also
    replaces a real rating of 0 with the default, and 0 is where every
    player in this league starts.
    """
    if player is None or player.elo_rating is None:
        return DEFAULT_ELO
    return player.elo_rating


def calculate_elo_change(winner, loser):
    """
    Points the winner gains and the loser drops.

    Real ELO, not the flat 20 the original code awarded: beating someone
    rated above you is worth more than beating someone below you, which is
    the entire point of a ladder. Always at least 1, so a heavily favoured
    win still registers.
    """
    winner_elo = _rating(winner)
    loser_elo = _rating(loser)

    expected_win = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    return max(1, int(round(ELO_K_FACTOR * (1 - expected_win))))


def update_player_rank(player):
    """
    Move a player into whatever rank their current ELO qualifies for.
    Below every tier means no rank at all, shown as "Unranked" - not
    keeping whatever tier they last held.
    """
    rank = Rank.for_elo(_rating(player))
    player.rank_id = rank.rank_id if rank is not None else None


@retry_on_deadlock
def report_result(user_id, my_balls, opp_balls, expected_match_id=None):
    """
    A player reports the score of their game. Scores are already validated.

    Returns (outcome, details): one of the REPORT_RESULT_* and, when
    recorded, {"elo_change": int, "winner_id": int}.

    expected_match_id is the game the player saw when they filled in the
    score. Without it, a report arriving after the game was already
    recorded - both players reporting, which is natural - lands on
    whatever match the sender is in NOW: for a winner, their next game,
    against someone who hasn't played yet.
    """
    try:
        # Locked, so two reports of the same game queue up and the second
        # sees the first's result instead of recording it again.
        match = lock_active_match_for_player(user_id)

        if match is None or (
            expected_match_id is not None and match.match_id != expected_match_id
        ):
            db.session.rollback()
            if expected_match_id is not None:
                return REPORT_RESULT_ALREADY_REPORTED, None
            return REPORT_RESULT_NO_GAME, None

        # A match with no challenger is a king waiting, not a game.
        opponent_id = match.opponent_of(user_id)
        if opponent_id is None:
            db.session.rollback()
            return REPORT_RESULT_NO_OPPONENT, None

        if my_balls > opp_balls:
            winner_id, loser_id = user_id, opponent_id
            winner_balls, loser_balls = my_balls, opp_balls
        else:
            winner_id, loser_id = opponent_id, user_id
            winner_balls, loser_balls = opp_balls, my_balls

        winner = match.player_one if match.player_one_id == winner_id else match.player_two
        loser = match.player_one if match.player_one_id == loser_id else match.player_two
        elo_change = calculate_elo_change(winner, loser)
    except Exception:
        db.session.rollback()
        raise

    record_match_result(match, winner_id, loser_id, elo_change, winner_balls, loser_balls)
    return REPORT_RESULT_RECORDED, {"elo_change": elo_change, "winner_id": winner_id}


def record_match_result(match, winner_id, loser_id, elo_change, winner_balls=None, loser_balls=None):
    """
    Close out a match and hand the table to the winner.

    Takes the Match object rather than a table_id. The old raw-SQL version
    re-found the match with a WHERE clause listing both player orderings,
    which was fragile; the caller already has the row, so it passes it in.
    The caller is also expected to have locked that row (see
    /match/record), so two reports of one game can't both land.
    """
    try:
        winner = db.session.get(Player, winner_id)
        loser = db.session.get(Player, loser_id)

        if winner is None or loser is None:
            raise ValueError("Both players must exist to record a result.")

        # 1. Close the match. winner_id now means the winner and nothing
        #    else, so no seat-shuffling is needed.
        match.match_status = Match.STATUS_FINISHED
        match.winner_id = winner_id
        match.loser_id = loser_id
        match.elo_change = elo_change

        # The score, stored against the seats rather than winner/loser so
        # the row reads the same way as while the game was on.
        if winner_balls is not None and loser_balls is not None:
            winner_is_player_one = winner_id == match.player_one_id
            match.player_one_balls = winner_balls if winner_is_player_one else loser_balls
            match.player_two_balls = loser_balls if winner_is_player_one else winner_balls

        # 2. Ratings and records. Zero-sum: the ladder stays balanced.
        winner.total_wins = (winner.total_wins or 0) + 1
        winner.elo_rating = _rating(winner) + elo_change

        loser.total_losses = (loser.total_losses or 0) + 1
        loser.elo_rating = _rating(loser) - elo_change

        update_player_rank(winner)
        update_player_rank(loser)

        # 3. The winner stays on as king: Active, no challenger yet.
        db.session.add(
            Match(
                table_id=match.table_id,
                player_one_id=winner_id,
                player_two_id=None,
                match_status=Match.STATUS_ACTIVE,
            )
        )

        db.session.commit()

    except Exception:
        db.session.rollback()
        raise

    # 4. Find the king a challenger, if anyone is waiting. Outside the
    #    transaction above: the result is already safely recorded, and a
    #    matchmaking hiccup must not roll back somebody's ELO.
    try:
        attempt_matchmaking(match.table_id)
    except Exception:
        log.exception("result saved, but matchmaking failed (table %s)", match.table_id)

    # 5. Refresh the display cache. Never read for decisions, so a failure
    #    here is cosmetic and must not surface to the player.
    try:
        refresh_table_state(match.table_id, winner_id)
    except Exception:
        log.exception("could not refresh the Pool_Tables cache (table %s)", match.table_id)


def start_new_session(table_id):
    """
    Kept for compatibility with the old module layout: matchmaking after a
    match ends. Delegates to the single implementation in manage_queue.
    """
    try:
        return attempt_matchmaking(table_id)
    except Exception:
        log.exception("error starting a new session (table %s)", table_id)
        return False


def refresh_table_state(table_id, latest_winner_id):
    """
    Update Pool_Tables' denormalized columns: current_king_id,
    current_streak, table_record_streak.

    These are a DISPLAY CACHE. Matches remains the source of truth for who
    holds the table, and nothing in matchmaking reads these columns. That
    separation is deliberate - the original stuck-queue bug came from one
    rule having two homes that drifted apart, and a second writable copy
    of "who is king" would be the same mistake.

    Because of that, this is also safe to delete outright if you'd rather
    leave those columns alone. Nothing depends on it.
    """
    table = db.session.get(PoolTable, table_id)
    if table is None:
        # The venue hasn't registered this table; nothing to cache.
        return

    try:
        if table.current_king_id == latest_winner_id:
            table.current_streak = (table.current_streak or 0) + 1
        else:
            table.current_king_id = latest_winner_id
            table.current_streak = 1

        if (table.current_streak or 0) > (table.table_record_streak or 0):
            table.table_record_streak = table.current_streak

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
