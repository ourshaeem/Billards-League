"""
Recording a finished match: ELO, ranks, and handing the table over.

Sequence when a score is reported:
  1. The match is closed with a real winner.
  2. Both players' ELO, win/loss counts and ranks are updated.
  3. The winner stays on as king - a new Active match with no challenger.
  4. Matchmaking runs, pulling the next person off the queue if anyone
     is waiting.
  5. Pool_Tables' display cache (king, streaks) is refreshed.
  6. Achievements in the game's league are awarded.

Steps 1-3 happen in one transaction. If anything fails, none of it lands,
so a match can never be half-recorded with one player's ELO moved.

Every league runs through the same sequence. What differs is the game:
how a score is judged valid and how many points it moves - see
score_problem() and the two calculate_* functions. Ratings live in
Standings, one row per player per league, so a result moves only its own
league's numbers.
"""
import logging

from sqlalchemy import func

from database import retry_on_deadlock
from logic.achievements import sync_achievements
from logic.leagues import ensure_standing, has_access
from logic.tables import league_for_table
from models import BILLIARDS, ELO_FLOOR, GAMES, PING_PONG, STARTING_ELO, League, Match, PoolTable, Player, Rank, db
from logic.manage_queue import attempt_matchmaking, lock_active_match_for_player

log = logging.getLogger(__name__)

# --- Billiards ---
# Standard club-level K-factor: enough that a few games move you, not so
# much that one upset reshuffles the ladder.
ELO_K_FACTOR = 32
DEFAULT_ELO = STARTING_ELO
# Highest number of balls a player can have sunk in a reported game.
MAX_BALLS = 8

# --- Ping pong ---
# One game to 11, won by two clear points (ITTF rules). The K-factor
# follows the tiered scheme competitive rating systems use - new players
# move fast until their rating means something, the top of the ladder
# moves slowly - with values sized for a single short game rather than a
# chess-length one.
PING_PONG_GAME_POINT = 11
PING_PONG_MAX_POINTS = 99  # far past any real deuce; stops nonsense scores
PING_PONG_K_PROVISIONAL = 40  # fewer than PING_PONG_PROVISIONAL_GAMES played
PING_PONG_K_ESTABLISHED = 24
PING_PONG_K_TOP = 16  # rated PING_PONG_TOP_RATING or more
PING_PONG_PROVISIONAL_GAMES = 10
PING_PONG_TOP_RATING = 1200
# A game to 11 says how one-sided it was. 11-9 or a deuce game is close
# to a coin flip and moves the base amount; an 11-0 moves half as much
# again. The bonus grows evenly across the margins in between (2 to 11).
PING_PONG_MAX_MARGIN_BONUS = 0.5

# report_result outcomes.
REPORT_RESULT_RECORDED = "recorded"
REPORT_RESULT_ALREADY_REPORTED = "already_reported"
REPORT_RESULT_NO_GAME = "no_game"
REPORT_RESULT_NO_OPPONENT = "no_opponent"
REPORT_RESULT_WRONG_LEAGUE = "wrong_league"
REPORT_RESULT_INVALID_SCORE = "invalid_score"
REPORT_RESULT_NO_ACCESS = "no_access"


def game_of(league):
    """The game a league plays, from a League, "billiards"/"ping_pong", or any League.of() reference."""
    if isinstance(league, str) and league in GAMES:
        return league
    resolved = League.of(league)
    return resolved.game if resolved is not None else BILLIARDS


def _rating(standing):
    """
    A player's rating in a league, from their Standing, treating only a
    missing value as the default.

    `rating or DEFAULT_ELO` - what this used to say - also replaces a real
    rating of 0 with the default, and 0 is where every player starts.
    """
    if standing is None or standing.elo is None:
        return DEFAULT_ELO
    return standing.elo


def _games_played(standing):
    return 0 if standing is None else (standing.wins or 0) + (standing.losses or 0)


def _expected_win(winner_elo, loser_elo):
    """The standard Elo expectation that the winner would win."""
    return 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))


def score_problem(league, my_score, opp_score):
    """
    Why a reported score can't be right for this league's game, or None if
    it can.

    The message is shown to the player as-is. Scores are already whole
    numbers by the time they get here.
    """
    if game_of(league) == PING_PONG:
        winner, loser = max(my_score, opp_score), min(my_score, opp_score)
        if min(my_score, opp_score) < 0 or winner > PING_PONG_MAX_POINTS:
            return f"Scores must be between 0 and {PING_PONG_MAX_POINTS}."
        if my_score == opp_score:
            return "Scores can't be a tie - a game is won by two clear points."
        if winner < PING_PONG_GAME_POINT:
            return "A game goes to 11 - the winner needs at least 11 points."
        if loser < PING_PONG_GAME_POINT - 1 and winner != PING_PONG_GAME_POINT:
            return "Unless it went to 10-10, the game ends as soon as someone reaches 11."
        if loser >= PING_PONG_GAME_POINT - 1 and winner != loser + 2:
            return "After 10-10 the game is won by two clear points, like 12-10."
        return None

    if not (0 <= my_score <= MAX_BALLS) or not (0 <= opp_score <= MAX_BALLS):
        return f"Scores must be between 0 and {MAX_BALLS}."
    if my_score == opp_score:
        return "Scores can't be a tie - somebody sank the 8."
    return None


def calculate_elo_change(winner, loser):
    """
    Billiards: points the winner gains and the loser drops. winner and
    loser are their Standings in the league (None for no games yet).

    Real ELO, not the flat 20 the original code awarded: beating someone
    rated above you is worth more than beating someone below you, which is
    the entire point of a ladder. Always at least 1, so a heavily favoured
    win still registers.
    """
    expected_win = _expected_win(_rating(winner), _rating(loser))
    return max(1, int(round(ELO_K_FACTOR * (1 - expected_win))))


def ping_pong_k_factor(standing):
    """A player's K-factor in a ping pong league: provisional, established or top."""
    if _games_played(standing) < PING_PONG_PROVISIONAL_GAMES:
        return PING_PONG_K_PROVISIONAL
    if _rating(standing) >= PING_PONG_TOP_RATING:
        return PING_PONG_K_TOP
    return PING_PONG_K_ESTABLISHED


def calculate_ping_pong_elo_change(winner, loser, winner_points, loser_points):
    """
    Ping pong: points the winner gains and the loser drops. winner and
    loser are their Standings in the league.

    Standard Elo expectation, scaled by two things billiards doesn't use:

    - Each player's K-factor (ping_pong_k_factor). The game uses the mean
      of the two, which keeps the ladder zero-sum - whatever one player
      gains the other loses, as in billiards - while still letting a
      newcomer's games count for more than a regular's.
    - The margin. 11-2 is stronger evidence than 11-9, so it moves more,
      up to PING_PONG_MAX_MARGIN_BONUS extra for a shutout.

    Always at least 1, so a heavily favoured win still registers.
    """
    k = (ping_pong_k_factor(winner) + ping_pong_k_factor(loser)) / 2
    expected_win = _expected_win(_rating(winner), _rating(loser))

    margin = winner_points - loser_points
    closest, widest = 2, PING_PONG_GAME_POINT
    spread = min(max(margin - closest, 0), widest - closest) / (widest - closest)
    margin_multiplier = 1 + PING_PONG_MAX_MARGIN_BONUS * spread

    return max(1, int(round(k * margin_multiplier * (1 - expected_win))))


def elo_change_for(league, winner, loser, winner_score, loser_score):
    """
    The points a game moves, by its league's game's formula, from the
    players' Standings now.
    """
    if game_of(league) == PING_PONG:
        return calculate_ping_pong_elo_change(winner, loser, winner_score, loser_score)
    return calculate_elo_change(winner, loser)


def apply_result(match, winner, loser, elo_change, league):
    """
    Move the numbers a finished game moves, in its league only: the
    winner's and loser's ratings, wins, losses and ranks, and the game's
    loser_elo_change. Zero-sum, except at the floor: nobody's rating goes
    below ELO_FLOOR, and a loser who reaches it loses only what they had.
    Returns what the loser actually lost.

    The one place a result changes ratings - a reported game
    (record_match_result) and a game added afterwards by the organiser
    (corrections.add_past_games) both come here. winner and loser are the
    players' Standings in the game's league, locked by the caller.
    Doesn't commit.
    """
    # Before anything moves: achievements judge upsets by these.
    match.winner_elo_before = _rating(winner)
    match.loser_elo_before = _rating(loser)
    winner.wins = (winner.wins or 0) + 1
    winner.elo = _rating(winner) + elo_change

    loser_before = _rating(loser)
    loser_after = lowered_rating(loser_before, elo_change)
    loser_change = loser_before - loser_after
    match.loser_elo_change = loser_change
    loser.losses = (loser.losses or 0) + 1
    loser.elo = loser_after

    update_player_rank(winner)
    update_player_rank(loser)
    return loser_change


def lowered_rating(rating, points):
    """
    A rating after losing `points`, stopping at ELO_FLOOR. A rating already
    below the floor (from before there was one) doesn't drop further, and
    isn't raised either - ensure_schema() lifts those once.
    """
    return max(rating - points, min(rating, ELO_FLOOR))


def update_player_rank(standing):
    """
    Move a player into whatever rank their rating in a league (their
    Standing there) qualifies for. Below every tier means no rank at all,
    shown as "Unranked" - not keeping whatever tier they last held.
    """
    rank = Rank.for_elo(_rating(standing))
    standing.rank_id = rank.rank_id if rank else None
    standing.rank = rank


@retry_on_deadlock
def report_result(
    user_id, my_score, opp_score, expected_match_id=None, league_type=None, league_id=None
):
    """
    A player reports the score of their game. The scores are whole numbers;
    whether they make sense is judged here, against the league of the game
    actually being played - never the one the request claims.

    Returns (outcome, details): one of the REPORT_RESULT_* and, when
    recorded, {"elo_change": int, "loser_elo_change": int, "winner_id":
    int} - the loser's change being less when they hit the floor. For WRONG_LEAGUE the
    details are {"league_type": <the game's league>}, and for
    INVALID_SCORE {"problem": <a sentence to show the player>}.

    expected_match_id is the game the player saw when they filled in the
    score. Without it, a report arriving after the game was already
    recorded - both players reporting, which is natural - lands on
    whatever match the sender is in NOW: for a winner, their next game,
    against someone who hasn't played yet.

    league_id is the league the player thinks the game is in (league_type,
    its game, from apps before schools). Optional; when sent and wrong,
    nothing is recorded, and WRONG_LEAGUE's details carry the game's real
    league_type and league_id.

    Reporting takes access to the game's league (NO_ACCESS): a player
    whose access went when the organiser changed the PIN enters the new
    one first.
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

        league = league_for_table(match.table_id)
        if (league_type is not None and league_type != league.game) or (
            league_id is not None and league_id != league.league_id
        ):
            db.session.rollback()
            return REPORT_RESULT_WRONG_LEAGUE, {
                "league_type": league.game,
                "league_id": league.league_id,
                "league_name": league.name,
            }

        if not has_access(user_id, league):
            db.session.rollback()
            return REPORT_RESULT_NO_ACCESS, {"league_id": league.league_id, "league_name": league.name}

        problem = score_problem(league, my_score, opp_score)
        if problem:
            db.session.rollback()
            return REPORT_RESULT_INVALID_SCORE, {"problem": problem}

        if my_score > opp_score:
            winner_id, loser_id = user_id, opponent_id
            winner_score, loser_score = my_score, opp_score
        else:
            winner_id, loser_id = opponent_id, user_id
            winner_score, loser_score = opp_score, my_score

        winner = ensure_standing(winner_id, league, lock=True)
        loser = ensure_standing(loser_id, league, lock=True)
        elo_change = elo_change_for(league, winner, loser, winner_score, loser_score)
    except Exception:
        db.session.rollback()
        raise

    loser_change = record_match_result(
        match, winner_id, loser_id, elo_change, winner_score, loser_score, league=league
    )
    return REPORT_RESULT_RECORDED, {
        "elo_change": elo_change,
        "loser_elo_change": loser_change,
        "winner_id": winner_id,
    }


def record_match_result(
    match, winner_id, loser_id, elo_change, winner_balls=None, loser_balls=None, league=None
):
    """
    Close out a match and hand the table to the winner.

    Takes the Match object rather than a table_id. The old raw-SQL version
    re-found the match with a WHERE clause listing both player orderings,
    which was fragile; the caller already has the row, so it passes it in.
    The caller is also expected to have locked that row (see
    /match/record), so two reports of one game can't both land.

    `league` is the league whose numbers move (by default the table's);
    every other league is left alone. winner_balls / loser_balls are the
    score in its game's units - balls sunk, or points.

    The winner gains elo_change. The loser loses it too, unless that would
    take them below ELO_FLOOR, where they stop. Returns what the loser
    actually lost.
    """
    league = League.of(league) if league is not None else league_for_table(match.table_id)
    try:
        if db.session.get(Player, winner_id) is None or db.session.get(Player, loser_id) is None:
            raise ValueError("Both players must exist to record a result.")
        winner = ensure_standing(winner_id, league, lock=True)
        loser = ensure_standing(loser_id, league, lock=True)

        # 1. Close the match. winner_id now means the winner and nothing
        #    else, so no seat-shuffling is needed.
        match.match_status = Match.STATUS_FINISHED
        match.winner_id = winner_id
        match.loser_id = loser_id
        match.elo_change = elo_change
        # When the game finished, which is what the history feeds show.
        # The row was created when the game was set up - for a king, that
        # can be long before a challenger arrived.
        match.played_at = func.now()

        # The score, stored against the seats rather than winner/loser so
        # the row reads the same way as while the game was on.
        if winner_balls is not None and loser_balls is not None:
            winner_is_player_one = winner_id == match.player_one_id
            match.player_one_balls = winner_balls if winner_is_player_one else loser_balls
            match.player_two_balls = loser_balls if winner_is_player_one else winner_balls

        # 2. Ratings and records, in this league only.
        loser_change = apply_result(match, winner, loser, elo_change, league)

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
        attempt_matchmaking(league.league_id)
    except Exception:
        log.exception("result saved, but matchmaking failed (table %s)", match.table_id)

    # 5. Refresh the display cache. Never read for decisions, so a failure
    #    here is cosmetic and must not surface to the player.
    try:
        refresh_table_state(match.table_id, winner_id)
    except Exception:
        log.exception("could not refresh the Pool_Tables cache (table %s)", match.table_id)

    # 6. Badges. Like the cache, never allowed to undo a recorded result.
    try:
        sync_achievements(league)
    except Exception:
        log.exception("result saved, but awarding achievements failed (match %s)", match.match_id)

    return loser_change


def start_new_session(table_id):
    """
    Kept for compatibility with the old module layout: matchmaking after a
    match ends. Delegates to the single implementation in manage_queue.
    """
    try:
        return attempt_matchmaking(league_for_table(table_id).league_id)
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
