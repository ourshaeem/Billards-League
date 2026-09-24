"""
Joining, leaving, and matchmaking.

The most important property of this module: there is exactly ONE
implementation of "can a match start right now?", `attempt_matchmaking`.
Both joining a queue and finishing a match call it. The original
stuck-queue bug happened because a second, incomplete copy of that logic
lived in the /queue/join route and didn't know about a waiting king. Any
future change to matchmaking belongs here and nowhere else.
"""
import logging

from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError

from database import retry_on_deadlock
from models import Match, PoolTable, QueueEntry, db

log = logging.getLogger(__name__)

# How long someone must wait with no match before they may leave on their
# own. Long enough that nobody can dodge a match that's about to start,
# short enough that an accidental join isn't a trap.
LEAVE_UNLOCK_SECONDS = 30

# join_queue outcomes. Named strings rather than True/False so callers can
# tell "you were already waiting" apart from "you just joined" - collapsing
# those into one boolean is what let the original bug hide.
JOIN_RESULT_JOINED = "joined"
JOIN_RESULT_ALREADY_QUEUED = "already_queued"
JOIN_RESULT_ALREADY_PLAYING = "already_playing"

# step_down outcomes, named for the same reason.
STEP_DOWN_RESULT_DONE = "stepped_down"
STEP_DOWN_RESULT_NOT_HOLDING = "not_holding"
STEP_DOWN_RESULT_IN_GAME = "in_game"


def _locked(stmt):
    """
    SELECT ... FOR UPDATE that also refreshes rows already in the session.

    The refresh matters as much as the lock. Without populate_existing,
    SQLAlchemy hands back the copy of a row it loaded earlier in this
    request - before we waited for the lock - so the code would see, say,
    a king still waiting when another request has just given them a
    challenger, and overwrite that challenger.
    """
    return stmt.with_for_update().execution_options(populate_existing=True)


def _lock_table(table_id):
    """
    Hold this table's Pool_Tables row until the transaction ends.

    Everything that changes who is at a table takes this lock first, so
    two of those changes on one table queue up behind each other instead
    of interleaving. Locking the Matches rows alone isn't enough: when
    the table is free there is no Active row to lock, and two players
    joining at the same instant could each create a match.

    A table with no Pool_Tables row gets no lock, which only matters for
    concurrency - the tests, on SQLite, never lock anything anyway.
    """
    db.session.execute(
        _locked(db.select(PoolTable.table_id).where(PoolTable.table_id == table_id))
    )


def _active_match_for_table(table_id, lock=False):
    """
    The one Active match at a table, if any.

    With lock=True the row is held with SELECT ... FOR UPDATE until the
    transaction ends. Matchmaking uses that so two players tapping Join at
    the same instant can't both decide the table is free and create two
    matches. The raw-SQL version had that race; this closes it.

    Row locking is a no-op on SQLite, which the tests run against. That's
    fine - the tests check matchmaking rules, not concurrency.
    """
    stmt = db.select(Match).where(
        Match.table_id == table_id,
        Match.match_status == Match.STATUS_ACTIVE,
    )
    if lock:
        stmt = _locked(stmt)
    return db.session.scalars(stmt.limit(1)).first()


def _active_match_for_player(user_id, table_id=None, lock=False):
    """Any Active match this player is part of, optionally at one table."""
    stmt = db.select(Match).where(
        Match.match_status == Match.STATUS_ACTIVE,
        db.or_(Match.player_one_id == user_id, Match.player_two_id == user_id),
    )
    if table_id is not None:
        stmt = stmt.where(Match.table_id == table_id)
    if lock:
        stmt = _locked(stmt)
    return db.session.scalars(stmt.order_by(Match.match_id.desc()).limit(1)).first()


def lock_active_match_for_player(user_id):
    """
    This player's Active match, locked for changing, or None.

    Takes the table's lock before the match's, the same order matchmaking
    uses. Two requests that lock the same rows in opposite orders can each
    end up waiting on the other forever; MySQL then kills one of them.
    """
    match = _active_match_for_player(user_id)
    if match is None:
        return None
    _lock_table(match.table_id)
    # Re-read under the lock: the match may have been finished, or a king
    # given a challenger, in the moment before the lock was ours.
    return _active_match_for_player(user_id, lock=True)


@retry_on_deadlock
def join_queue(user_id, table_id):
    """
    Add a player to a table's queue.

    Returns JOIN_RESULT_JOINED / JOIN_RESULT_ALREADY_QUEUED /
    JOIN_RESULT_ALREADY_PLAYING.

    Deliberately does NOT try to form a match - call attempt_matchmaking()
    afterwards. Keeping the two apart is what stops a second copy of the
    matchmaking rules growing inside the join path again.
    """
    try:
        already_queued = db.session.scalars(
            db.select(QueueEntry).where(
                QueueEntry.user_id == user_id,
                QueueEntry.table_id == table_id,
            )
        ).first()
        if already_queued:
            return JOIN_RESULT_ALREADY_QUEUED

        # At ANY table, not just this one: someone mid-game or holding a
        # table can't also be waiting for another.
        if _active_match_for_player(user_id):
            return JOIN_RESULT_ALREADY_PLAYING

        highest = db.session.scalar(
            db.select(func.max(QueueEntry.queue_position)).where(
                QueueEntry.table_id == table_id
            )
        )
        next_position = (highest + 1) if highest is not None else 1

        # joined_at is left unset on purpose so MySQL fills it from its own
        # clock, matching the NOW() the wait is measured against later.
        db.session.add(
            QueueEntry(user_id=user_id, table_id=table_id, queue_position=next_position)
        )
        db.session.commit()
        return JOIN_RESULT_JOINED

    except IntegrityError:
        # The unique (user_id, table_id) index caught a second join racing
        # the first - a double tap. The first one won; report it as such.
        db.session.rollback()
        return JOIN_RESULT_ALREADY_QUEUED

    except Exception:
        db.session.rollback()
        raise


@retry_on_deadlock
def leave_queue(user_id, table_id):
    """
    Remove a player from a queue.
    Returns True if a row went, False if they weren't queued at all.
    """
    try:
        # One DELETE rather than read-then-delete. If matchmaking takes this
        # player off the queue in between, the delete simply finds nothing,
        # instead of failing because the row it read has gone.
        removed = db.session.execute(
            db.delete(QueueEntry).where(
                QueueEntry.user_id == user_id,
                QueueEntry.table_id == table_id,
            )
        ).rowcount
        db.session.commit()
        return removed > 0

    except Exception:
        db.session.rollback()
        raise


def get_queue_status(user_id, table_id):
    """
    None if the player isn't queued, otherwise:
        {queue_position, seconds_waiting, can_leave, leave_unlocks_in}

    The elapsed time is computed BY THE DATABASE, not in Python. Both
    timestamps then come from one clock in one timezone.

    Doing this subtraction in Python is a trap worth restating, because an
    ORM makes it very natural to write: joined_at is written by MySQL's
    CURRENT_TIMESTAMP in the MySQL server's timezone, while a Python
    datetime.now() uses the app server's. Run MySQL in UTC and the app in
    New York and joined_at reads hours into the future, the remaining wait
    goes negative, and the leave button never unlocks.
    """
    try:
        seconds_expr = _seconds_since(QueueEntry.joined_at).label("seconds_waiting")

        row = db.session.execute(
            db.select(QueueEntry.queue_id, QueueEntry.queue_position, seconds_expr).where(
                QueueEntry.user_id == user_id,
                QueueEntry.table_id == table_id,
            )
        ).first()
    except Exception as e:
        # Only reachable on a database _seconds_since doesn't know. Letting
        # people leave beats trapping them, but it switches the wait rule
        # off, so it's logged loudly rather than passed over.
        log.error("wait timer unavailable, letting players leave freely: %s", e)
        db.session.rollback()
        entry = db.session.scalars(
            db.select(QueueEntry).where(
                QueueEntry.user_id == user_id,
                QueueEntry.table_id == table_id,
            )
        ).first()
        if entry is None:
            return None
        return {
            "queue_position": _place_in_line(entry.queue_id, entry.queue_position, table_id),
            "seconds_waiting": LEAVE_UNLOCK_SECONDS,
            "can_leave": True,
            "leave_unlocks_in": 0,
        }

    if row is None:
        return None

    queue_id, stored_position, seconds_waiting = row
    queue_position = _place_in_line(queue_id, stored_position, table_id)

    if seconds_waiting is None:
        # Row predates joined_at being populated. Don't trap someone in a
        # queue they can never leave.
        seconds_waiting = LEAVE_UNLOCK_SECONDS

    seconds_waiting = max(0, int(seconds_waiting))
    leave_unlocks_in = max(0, LEAVE_UNLOCK_SECONDS - seconds_waiting)

    return {
        "queue_position": queue_position,
        "seconds_waiting": seconds_waiting,
        "can_leave": leave_unlocks_in == 0,
        "leave_unlocks_in": leave_unlocks_in,
    }


def _place_in_line(queue_id, stored_position, table_id):
    """
    1 for the front of the line, 2 behind them, and so on.

    The stored queue_position is a sort key, not a place: it only ever
    counts up (new joiners get the highest plus one) and nothing renumbers
    it as people are matched or leave. Shown as-is, a player eleventh in
    line after a busy evening read "You're number 253 in line".
    """
    ahead = db.session.scalar(
        db.select(func.count()).select_from(QueueEntry).where(
            QueueEntry.table_id == table_id,
            db.or_(
                QueueEntry.queue_position < stored_position,
                db.and_(
                    QueueEntry.queue_position == stored_position,
                    QueueEntry.queue_id < queue_id,
                ),
            ),
        )
    )
    return (ahead or 0) + 1


def _seconds_since(column):
    """
    Seconds between a timestamp column and now, computed by the database.

    MySQL has TIMESTAMPDIFF; SQLite (the tests) doesn't, and the old code
    treated that failure as "let everyone leave at once" - which switched
    the wait rule off in exactly the place meant to prove it works.
    """
    if db.session.get_bind().dialect.name == "sqlite":
        return db.cast((func.julianday("now") - func.julianday(column)) * 86400, db.Integer)
    return func.timestampdiff(text("SECOND"), column, func.now())


@retry_on_deadlock
def attempt_matchmaking(table_id):
    """
    Start a match at this table if one can start. Returns True if it did.

    THE SINGLE SOURCE OF TRUTH for matchmaking. Two cases:

      1. A king is holding the table (Active match, no challenger yet) and
         somebody is queued -> pull in the next challenger.
      2. The table is free and two or more people are queued -> pair the
         first two.

    Case 1 is the one the old /queue/join route didn't handle, which is
    why players piled up in the queue behind a king and no match ever
    started. Both callers - joining, and finishing a match - come through
    here, so the two cases can't drift apart again.
    """
    try:
        _lock_table(table_id)
        active = _active_match_for_table(table_id, lock=True)

        # --- Table busy with a real game: nothing to do ---
        if active is not None and active.is_in_progress:
            db.session.commit()
            return False

        waiting = _eligible_queue(table_id)

        # --- Case 1: a king is waiting for a challenger ---
        if active is not None:
            if not waiting:
                db.session.commit()
                return False

            challenger = waiting[0]
            active.player_two_id = challenger.user_id
            db.session.delete(challenger)
            db.session.commit()
            return True

        # --- Case 2: free table, pair the first two waiting ---
        if len(waiting) < 2:
            db.session.commit()
            return False

        first, second = waiting[0], waiting[1]
        match = Match(
            table_id=table_id,
            player_one_id=first.user_id,
            player_two_id=second.user_id,
            match_status=Match.STATUS_ACTIVE,
        )
        db.session.add(match)
        db.session.delete(first)
        db.session.delete(second)
        db.session.commit()
        return True

    except Exception:
        db.session.rollback()
        raise


def _eligible_queue(table_id):
    """
    The table's queue in order, locked, with stale entries removed.

    A stale entry is someone who is already in an Active match - at this
    table or another - or a second entry for the same person. Neither
    should exist, but a double-tapped Join or a row left over from an old
    bug can produce one, and pairing it would start a match between a
    player and themselves. Removing them here means matchmaking can't be
    tricked by bad data, whatever put it there.

    Locked reads, not plain ones: a plain read can return a snapshot from
    earlier in the transaction, before another request took these players
    off the queue.
    """
    entries = list(
        db.session.scalars(
            _locked(
                db.select(QueueEntry)
                .where(QueueEntry.table_id == table_id)
                .order_by(QueueEntry.queue_position.asc(), QueueEntry.queue_id.asc())
            )
        )
    )
    if not entries:
        return []

    busy = set()
    for seat_one, seat_two in db.session.execute(
        db.select(Match.player_one_id, Match.player_two_id).where(
            Match.match_status == Match.STATUS_ACTIVE
        )
    ):
        busy.update(p for p in (seat_one, seat_two) if p is not None)

    eligible, seen = [], set()
    for entry in entries:
        if entry.user_id in busy or entry.user_id in seen:
            log.warning("removing stale queue entry %r", entry)
            db.session.delete(entry)
            continue
        seen.add(entry.user_id)
        eligible.append(entry)
    return eligible


def get_player_status(user_id, table_id):
    """
    The /match/status payload: exactly one of idle / queued /
    waiting_for_challenger / playing (see AGENTS.md).

    Also the queue's safety net. If this player is waiting - in the queue,
    or holding a table - it gives matchmaking a chance first. A queue that
    got stuck (a crash between join and matchmaking, rows left by an old
    bug, a server restart) then heals within one poll, instead of waiting
    for someone new to tap Join. It calls the one attempt_matchmaking(),
    so this is not a second copy of the rules.
    """
    match = _active_match_for_player(user_id)
    queued = match is None and _is_queued(user_id, table_id)

    if (match is not None and match.is_awaiting_challenger) or queued:
        heal_table = match.table_id if match is not None else table_id
        try:
            attempt_matchmaking(heal_table)
        except Exception:
            log.exception("matchmaking during a status check failed (table %s)", heal_table)
        match = _active_match_for_player(user_id)

    if match is not None:
        if match.is_in_progress:
            return match.to_playing_dict(user_id)
        return match.to_waiting_dict()

    queue_status = get_queue_status(user_id, table_id)
    if queue_status:
        return {"status": "queued", "table_id": table_id, **queue_status}

    return {"status": "idle"}


def _is_queued(user_id, table_id):
    return (
        db.session.scalar(
            db.select(QueueEntry.queue_id).where(
                QueueEntry.user_id == user_id, QueueEntry.table_id == table_id
            )
        )
        is not None
    )


@retry_on_deadlock
def step_down(user_id):
    """
    A king gives up the table. Returns one of the STEP_DOWN_RESULT_*.

    Without this, whoever won the last game of the night held the table
    forever: they couldn't queue (they're "playing"), and the next person
    to join the next day was matched against someone who'd gone home.

    Only allowed with no challenger - a game in progress has to be
    reported, not walked away from. The king's Active row is deleted
    rather than marked Finished: it was never a game, and every Finished
    row has a winner.
    """
    try:
        match = lock_active_match_for_player(user_id)
        if match is None:
            db.session.commit()
            return STEP_DOWN_RESULT_NOT_HOLDING
        if match.is_in_progress:
            db.session.commit()
            return STEP_DOWN_RESULT_IN_GAME

        table_id = match.table_id
        db.session.delete(match)

        # The display cache shouldn't keep showing a king who has left.
        table = db.session.get(PoolTable, table_id)
        if table is not None and table.current_king_id == user_id:
            table.current_king_id = None
            table.current_streak = 0

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    # The table is free now; the first two waiting (if any) can play.
    try:
        attempt_matchmaking(table_id)
    except Exception:
        log.exception("stepped down, but matchmaking failed (table %s)", table_id)

    return STEP_DOWN_RESULT_DONE


def _queue_in_order(table_id, limit=None):
    # queue_id breaks ties: two people joining in the same instant can be
    # given the same position, and the order must not flicker between polls.
    stmt = (
        db.select(QueueEntry)
        .where(QueueEntry.table_id == table_id)
        .order_by(QueueEntry.queue_position.asc(), QueueEntry.queue_id.asc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.session.scalars(stmt))


def view_queue(table_id):
    """
    The queue as the frontend expects it:
        [{"queue_position": int, "username": str}, ...]

    queue_position is each player's place in line, 1 upwards - see
    _place_in_line for why the stored column can't be shown directly.

    QueueEntry.player is lazy="joined", so this is one query rather than
    one per waiting player.
    """
    return [
        entry.to_dict(place=place)
        for place, entry in enumerate(_queue_in_order(table_id), start=1)
    ]


def get_pool_table(table_id):
    """The PoolTable row, or None if the venue hasn't registered it."""
    return db.session.get(PoolTable, table_id)
