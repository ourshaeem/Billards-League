"""
Voting off an absent king.

A king who won and walked off - forgot to give up the table, phone in a
pocket - holds the table for nobody: the next in line is called, says
they're here, and stands at an empty table. Without the organiser there
was no way past it.

So the players waiting can vote them off. Who votes: everyone who could
play at that table next - the challenger already seated against the
king, if there is one, and everyone in the league's queue waiting for
that table or for any table, except those already called to another
table. All of them have to vote: one impatient player can't take the
table from anyone.

Once the vote is unanimous the king gets the same minute as the ready
check (VOTE_GRACE_SECONDS) to say they're here (king_is_here), which
clears every vote. If they don't, matchmaking - the one place that
changes who is at a table - takes them off it, as the organiser would
(manage_queue.take_off_table): a king alone gives the table to the next
in line; a game in progress is called off with nothing recorded, and
the challenger holds the table.

Votes belong to the king's Active match row, so they count for this
reign only. A vote can be taken back; doing so after the vote went
unanimous stops the king's minute. Someone joining the queue after it
went unanimous doesn't stop it - a vote that has passed has passed.
"""
import logging

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from database import retry_on_deadlock, seconds_since
from models import KingVote, Match, PoolTable, QueueEntry, db

log = logging.getLogger(__name__)

# The king's last chance, once everyone has voted: the ready check's minute.
VOTE_GRACE_SECONDS = 60

# cast_vote outcomes.
VOTE_RESULT_VOTED = "voted"
VOTE_RESULT_EVERYONE_VOTED = "everyone_voted"
VOTE_RESULT_ALREADY_VOTED = "already_voted"
VOTE_RESULT_WITHDRAWN = "withdrawn"
VOTE_RESULT_NOT_VOTED = "not_voted"
VOTE_RESULT_NO_KING = "no_king"
VOTE_RESULT_GAME_CHANGED = "game_changed"
VOTE_RESULT_YOU_ARE_KING = "you_are_king"
VOTE_RESULT_NOT_WAITING = "not_waiting"

# king_is_here outcomes.
HERE_RESULT_CLEARED = "cleared"
HERE_RESULT_NO_VOTES = "no_votes"
HERE_RESULT_NOT_KING = "not_king"


def league_queue(league_id, lock=False):
    """A league's queue entries, in order - the people who might vote."""
    stmt = (
        db.select(QueueEntry)
        .where(QueueEntry.league_id == league_id)
        .order_by(QueueEntry.queue_position, QueueEntry.queue_id)
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return list(db.session.scalars(stmt))


def electorate(match, entries):
    """
    Who votes on the king of `match`: the challenger seated against them,
    and everyone in `entries` (the league's queue) who could play at this
    table next - waiting for it or for any table, and not already called
    to another one. Player ids, in line order after the challenger.
    """
    table_id = match.table_id
    voters = []
    if match.player_two_id is not None:
        voters.append(match.player_two_id)
    for entry in entries:
        if entry.user_id in (match.player_one_id, match.player_two_id):
            continue
        if entry.target_table_id not in (None, table_id):
            continue
        if entry.is_called and entry.table_id != table_id:
            continue
        voters.append(entry.user_id)
    return voters


def _votes(match_id):
    return set(db.session.scalars(db.select(KingVote.voter_id).where(KingVote.match_id == match_id)))


def _seconds_left(match):
    """The king's time left to say they're here, or None before everyone has voted."""
    if match.removal_vote_at is None:
        return None
    since = db.session.scalar(
        db.select(seconds_since(Match.removal_vote_at)).where(Match.match_id == match.match_id)
    )
    return max(0, VOTE_GRACE_SECONDS - max(0, int(since or 0)))


def summary(match, entries=None):
    """
    Where a vote on this king stands, for anyone watching:
        {votes, needed, voters, electorate, seconds_left}
    or None when there's no king or nobody who could vote. voters and
    electorate are player ids; seconds_left is the king's time to say
    they're here once everyone has voted (None until then).
    """
    if match is None or not match.is_active or match.player_one_id is None:
        return None
    if entries is None:
        entries = league_queue(_league_id_of(match))
    people = electorate(match, entries)
    if not people:
        return None
    voted = _votes(match.match_id)
    voters = [user_id for user_id in people if user_id in voted]
    return {
        "votes": len(voters),
        "needed": len(people),
        "voters": voters,
        "electorate": people,
        "seconds_left": _seconds_left(match),
    }


def for_player(match, user_id):
    """
    The vote, as the status of a player at the table sees it:
        {votes, needed, seconds_left, you_voted, you_can_vote}
    or None when nobody could vote.
    """
    found = summary(match)
    if found is None:
        return None
    return {
        "votes": found["votes"],
        "needed": found["needed"],
        "seconds_left": found["seconds_left"],
        "you_voted": user_id in found["voters"],
        "you_can_vote": user_id in found["electorate"],
    }


def vote_due(match, entries):
    """
    For matchmaking, under the league's lock: whether this king's minute
    after a unanimous vote is up, so they come off the table now. Starts
    the minute if the vote has just become unanimous - by a vote, or by
    someone who hadn't voted leaving the queue.
    """
    if match is None or not match.is_active or match.player_one_id is None:
        return False
    if match.removal_vote_at is None:
        people = electorate(match, entries)
        if people and set(people) <= _votes(match.match_id):
            match.removal_vote_at = func.now()
            log.info("everyone waiting voted %r's king off; their minute starts", match)
        return False
    return _seconds_left(match) == 0


def forget_votes(match_id):
    """Every vote on a king's reign, once it's over."""
    db.session.execute(db.delete(KingVote).where(KingVote.match_id == match_id))


def _league_id_of(match):
    return db.session.scalar(db.select(PoolTable.league_id).where(PoolTable.table_id == match.table_id))


@retry_on_deadlock
def cast_vote(user_id, table_id, match_id=None, remove=True):
    """
    Vote that the king at table_id isn't here (remove=True), or take that
    vote back (remove=False). match_id is the king's game as the voter saw
    it; if the table has changed hands since, nothing happens.

    Returns (outcome, summary): one of the VOTE_RESULT_*, and where the
    vote now stands (summary()), or None.
    """
    # Imported here: manage_queue reads this module's vote_due, so this
    # one can't import it at the top.
    from logic.manage_queue import _active_match_for_table, _lock_table

    try:
        _lock_table(table_id)
        match = _active_match_for_table(table_id, lock=True)
        if match is None or match.player_one_id is None:
            db.session.rollback()
            return VOTE_RESULT_NO_KING, None
        if match_id is not None and match.match_id != match_id:
            db.session.rollback()
            return VOTE_RESULT_GAME_CHANGED, None
        if user_id == match.player_one_id:
            db.session.rollback()
            return VOTE_RESULT_YOU_ARE_KING, None

        entries = league_queue(_league_id_of(match), lock=True)
        people = electorate(match, entries)
        if user_id not in people:
            db.session.rollback()
            return VOTE_RESULT_NOT_WAITING, None

        voted = _votes(match.match_id)
        if remove:
            if user_id in voted:
                outcome = VOTE_RESULT_ALREADY_VOTED
            else:
                db.session.add(KingVote(match_id=match.match_id, voter_id=user_id))
                voted.add(user_id)
                outcome = VOTE_RESULT_VOTED
            if set(people) <= voted:
                outcome = VOTE_RESULT_EVERYONE_VOTED
                if match.removal_vote_at is None:
                    match.removal_vote_at = func.now()
        else:
            removed = db.session.execute(
                db.delete(KingVote).where(
                    KingVote.match_id == match.match_id, KingVote.voter_id == user_id
                )
            ).rowcount
            outcome = VOTE_RESULT_WITHDRAWN if removed else VOTE_RESULT_NOT_VOTED
            # Someone has changed their mind: it isn't unanimous any more.
            if removed:
                match.removal_vote_at = None

        db.session.commit()
    except IntegrityError:
        # A double tap: the first vote counted.
        db.session.rollback()
        outcome = VOTE_RESULT_ALREADY_VOTED
    except Exception:
        db.session.rollback()
        raise

    match = _active_match_for_table(table_id)
    return outcome, summary(match)


@retry_on_deadlock
def king_is_here(user_id):
    """
    The king says they're here: every vote on their reign is cleared,
    and the minute stops. Returns one of the HERE_RESULT_*.
    """
    from logic.manage_queue import lock_active_match_for_player

    try:
        match = lock_active_match_for_player(user_id)
        if match is None or match.player_one_id != user_id:
            db.session.rollback()
            return HERE_RESULT_NOT_KING
        had_votes = bool(_votes(match.match_id)) or match.removal_vote_at is not None
        forget_votes(match.match_id)
        match.removal_vote_at = None
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return HERE_RESULT_CLEARED if had_votes else HERE_RESULT_NO_VOTES
