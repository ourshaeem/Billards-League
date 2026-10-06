"""
Joining, leaving, and matchmaking.

The most important property of this module: there is exactly ONE
implementation of "can a match start right now?", `attempt_matchmaking`.
Both joining a queue and finishing a match call it. The original
stuck-queue bug happened because a second, incomplete copy of that logic
lived in the /queue/join route and didn't know about a waiting king. Any
future change to matchmaking belongs here and nowhere else.

Each league has one line, however many tables it has. A player joins the
league's queue, not a table's; when their turn comes, matchmaking calls
them to whichever table needs a player - a king waiting for a challenger
first, then a free table, two at a time - and the queue row says which
(table_id). Every table in a league is matched in one pass, under the
league's lock, so two tables can never call the same player.
"""
import logging
from collections import deque

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from database import retry_on_deadlock, seconds_since
from logic.achievements import PATIENCE_WAIT_SECONDS, award
from logic.tables import active_tables, league_for_table, table_names
from models import League, Match, PoolTable, QueueEntry, db

log = logging.getLogger(__name__)

# How long someone must wait with no match before they may leave on their
# own. Long enough that nobody can dodge a match that's about to start,
# short enough that an accidental join isn't a trap. Once it's their turn
# they may leave at any time: not confirming would take them out anyway.
LEAVE_UNLOCK_SECONDS = 30

# The ready check. When a player's turn comes they have this long to say
# they're here; after that they're taken out of the queue and the next
# person is up. Without it, a player who joined and wandered off kept a
# king waiting at the table for nobody.
READY_CHECK_SECONDS = 60
# A player who joined, or said they were here, this recently isn't asked
# again when their turn comes - they plainly are here. Without it, joining
# a table with room meant tapping Join and then at once tapping again.
RECENTLY_HERE_SECONDS = 60

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

# confirm_here outcomes.
CONFIRM_RESULT_CONFIRMED = "confirmed"
CONFIRM_RESULT_ALREADY_CONFIRMED = "already_confirmed"
CONFIRM_RESULT_NOT_YOUR_TURN = "not_your_turn"
CONFIRM_RESULT_TOO_LATE = "too_late"
CONFIRM_RESULT_NOT_QUEUED = "not_queued"


def _league_id(league):
    """A league_id from a League or any League.of() reference."""
    if isinstance(league, int) and not isinstance(league, bool):
        return league
    resolved = League.of(league)
    if resolved is None:
        raise ValueError(f"No such league: {league!r}")
    return resolved.league_id


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


def _lock_league(league_id):
    """
    Hold this league's Leagues row until the transaction ends.

    Everything that changes who is at a league's tables, or who is up in
    its queue, takes this lock first, so two of those changes queue up
    behind each other instead of interleaving. One lock for the whole
    league, not one per table: the queue is the league's, and matching
    one table decides who is left for the next.

    Row locking is a no-op on SQLite, which the tests run against. That's
    fine - the tests check matchmaking rules, not concurrency.
    """
    db.session.execute(_locked(db.select(League.league_id).where(League.league_id == league_id)))


def _lock_table(table_id):
    """
    The lock for changing who is at a table: its league's (see
    _lock_league), then the table's own Pool_Tables row. Always in that
    order, by everyone, so no two requests can each hold one and wait for
    the other.

    A table with no Pool_Tables row gets no lock, which only matters for
    concurrency - the tests, on SQLite, never lock anything anyway.
    """
    league_id = db.session.scalar(
        db.select(PoolTable.league_id).where(PoolTable.table_id == table_id)
    )
    if league_id is not None:
        _lock_league(league_id)
    db.session.execute(
        _locked(db.select(PoolTable.table_id).where(PoolTable.table_id == table_id))
    )


def _active_match_for_table(table_id, lock=False):
    """
    The one Active match at a table, if any.

    With lock=True the row is held with SELECT ... FOR UPDATE until the
    transaction ends, so two players tapping Join at the same instant
    can't both decide the table is free and create two matches.
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

    Takes the league's and table's locks before the match's, the same
    order matchmaking uses. Two requests that lock the same rows in
    opposite orders can each end up waiting on the other forever; MySQL
    then kills one of them.
    """
    match = _active_match_for_player(user_id)
    if match is None:
        return None
    _lock_table(match.table_id)
    # Re-read under the lock: the match may have been finished, or a king
    # given a challenger, in the moment before the lock was ours.
    return _active_match_for_player(user_id, lock=True)


@retry_on_deadlock
def join_queue(user_id, league):
    """
    Add a player to a league's queue.

    Returns JOIN_RESULT_JOINED / JOIN_RESULT_ALREADY_QUEUED /
    JOIN_RESULT_ALREADY_PLAYING.

    Deliberately does NOT try to form a match - call attempt_matchmaking()
    afterwards. Keeping the two apart is what stops a second copy of the
    matchmaking rules growing inside the join path again.
    """
    league_id = _league_id(league)
    try:
        already_queued = db.session.scalars(
            db.select(QueueEntry).where(
                QueueEntry.user_id == user_id,
                QueueEntry.league_id == league_id,
            )
        ).first()
        if already_queued:
            return JOIN_RESULT_ALREADY_QUEUED

        # At ANY table, not just this league's: someone mid-game or holding
        # a table can't also be waiting for another.
        if _active_match_for_player(user_id):
            return JOIN_RESULT_ALREADY_PLAYING

        highest = db.session.scalar(
            db.select(func.max(QueueEntry.queue_position)).where(
                QueueEntry.league_id == league_id
            )
        )
        next_position = (highest + 1) if highest is not None else 1

        # joined_at is left unset on purpose so MySQL fills it from its own
        # clock, matching the NOW() the wait is measured against later.
        db.session.add(
            QueueEntry(user_id=user_id, league_id=league_id, queue_position=next_position)
        )
        db.session.commit()
        return JOIN_RESULT_JOINED

    except IntegrityError:
        # The unique (user_id, league_id) index caught a second join racing
        # the first - a double tap. The first one won; report it as such.
        db.session.rollback()
        return JOIN_RESULT_ALREADY_QUEUED

    except Exception:
        db.session.rollback()
        raise


@retry_on_deadlock
def leave_queue(user_id, league):
    """
    Remove a player from a league's queue.
    Returns True if a row went, False if they weren't queued at all.
    """
    league_id = _league_id(league)
    try:
        # One DELETE rather than read-then-delete. If matchmaking takes this
        # player off the queue in between, the delete simply finds nothing,
        # instead of failing because the row it read has gone.
        removed = db.session.execute(
            db.delete(QueueEntry).where(
                QueueEntry.user_id == user_id,
                QueueEntry.league_id == league_id,
            )
        ).rowcount
        db.session.commit()
        return removed > 0

    except Exception:
        db.session.rollback()
        raise


@retry_on_deadlock
def leave_all_queues(user_id):
    """
    Take a player out of every queue at once, with no waiting period.
    Returns how many entries went. For account deletion: an account that
    no longer exists must not be pulled into a game.
    """
    try:
        removed = db.session.execute(
            db.delete(QueueEntry).where(QueueEntry.user_id == user_id)
        ).rowcount
        db.session.commit()
        return removed
    except Exception:
        db.session.rollback()
        raise


@retry_on_deadlock
def confirm_here(user_id, league):
    """
    A player whose turn has come says they're here. Returns one of the
    CONFIRM_RESULT_*.

    Like join_queue, this doesn't start the game itself: call
    attempt_matchmaking() afterwards, which starts it once everyone whose
    turn it is at that table has confirmed.

    Taken under the league's lock, so it can't cross with matchmaking
    deciding the same player has run out of time. A confirmation that
    arrives after the minute is up counts for nothing even if nobody has
    removed the player yet: it removes them, as matchmaking would have.
    """
    league_id = _league_id(league)
    try:
        _lock_league(league_id)
        row = db.session.execute(
            _locked(
                db.select(QueueEntry, seconds_since(QueueEntry.called_at)).where(
                    QueueEntry.user_id == user_id,
                    QueueEntry.league_id == league_id,
                )
            )
        ).first()

        if row is None:
            outcome = CONFIRM_RESULT_NOT_QUEUED
        else:
            entry, seconds_called = row
            if not entry.is_called:
                outcome = CONFIRM_RESULT_NOT_YOUR_TURN
            elif entry.is_confirmed:
                outcome = CONFIRM_RESULT_ALREADY_CONFIRMED
            elif _turn_has_run_out(seconds_called):
                log.info("%r confirmed too late; taking them out of the queue", entry)
                db.session.delete(entry)
                outcome = CONFIRM_RESULT_TOO_LATE
            else:
                entry.confirmed_at = func.now()
                outcome = CONFIRM_RESULT_CONFIRMED

        db.session.commit()
        return outcome

    except Exception:
        db.session.rollback()
        raise


def _turn_has_run_out(seconds_called):
    """True once a player's minute to say they're here is over."""
    return seconds_called is not None and seconds_called >= READY_CHECK_SECONDS


def _seconds_left(seconds_called):
    """How long a player whose turn has come still has to say they're here."""
    return max(0, READY_CHECK_SECONDS - max(0, int(seconds_called or 0)))


def get_queue_status(user_id, league):
    """
    None if the player isn't in the league's queue, otherwise:
        {queue_position, seconds_waiting, can_leave, leave_unlocks_in,
         called, confirmed, seconds_left, table_id}

    called / confirmed / seconds_left are the ready check: whether the
    player's turn has come, whether they've said they're here, and how
    long they have left to (None once they have, or before their turn).
    table_id is the table they're called to (None before their turn). A
    player whose turn has come may always leave.

    The elapsed time is computed BY THE DATABASE, not in Python. Both
    timestamps then come from one clock in one timezone.

    Doing this subtraction in Python is a trap worth restating, because an
    ORM makes it very natural to write: joined_at is written by MySQL's
    CURRENT_TIMESTAMP in the MySQL server's timezone, while a Python
    datetime.now() uses the app server's. Run MySQL in UTC and the app in
    New York and joined_at reads hours into the future, the remaining wait
    goes negative, and the leave button never unlocks.
    """
    league_id = _league_id(league)
    try:
        row = db.session.execute(
            db.select(
                QueueEntry,
                seconds_since(QueueEntry.joined_at),
                seconds_since(QueueEntry.called_at),
            ).where(
                QueueEntry.user_id == user_id,
                QueueEntry.league_id == league_id,
            )
        ).first()
    except Exception as e:
        # Only reachable on a database seconds_since doesn't know. Letting
        # people leave beats trapping them, but it switches the wait rule
        # off, so it's logged loudly rather than passed over.
        log.error("wait timer unavailable, letting players leave freely: %s", e)
        db.session.rollback()
        entry = db.session.scalars(
            db.select(QueueEntry).where(
                QueueEntry.user_id == user_id,
                QueueEntry.league_id == league_id,
            )
        ).first()
        if entry is None:
            return None
        return {
            "queue_position": _place_in_line(entry.queue_id, entry.queue_position, league_id),
            "seconds_waiting": LEAVE_UNLOCK_SECONDS,
            "can_leave": True,
            "leave_unlocks_in": 0,
            "called": entry.is_called,
            "confirmed": entry.is_confirmed,
            "seconds_left": None if entry.is_confirmed or not entry.is_called else READY_CHECK_SECONDS,
            "table_id": entry.table_id if entry.is_called else None,
        }

    if row is None:
        return None

    entry, seconds_waiting, seconds_called = row
    queue_position = _place_in_line(entry.queue_id, entry.queue_position, league_id)

    if seconds_waiting is None:
        # Row predates joined_at being populated. Don't trap someone in a
        # queue they can never leave.
        seconds_waiting = LEAVE_UNLOCK_SECONDS

    seconds_waiting = max(0, int(seconds_waiting))
    leave_unlocks_in = 0 if entry.is_called else max(0, LEAVE_UNLOCK_SECONDS - seconds_waiting)

    return {
        "queue_position": queue_position,
        "seconds_waiting": seconds_waiting,
        "can_leave": leave_unlocks_in == 0,
        "leave_unlocks_in": leave_unlocks_in,
        "called": entry.is_called,
        "confirmed": entry.is_confirmed,
        "seconds_left": (
            _seconds_left(seconds_called) if entry.is_called and not entry.is_confirmed else None
        ),
        "table_id": entry.table_id if entry.is_called else None,
    }


def _place_in_line(queue_id, stored_position, league_id):
    """
    1 for the front of the line, 2 behind them, and so on.

    The stored queue_position is a sort key, not a place: it only ever
    counts up (new joiners get the highest plus one) and nothing renumbers
    it as people are matched or leave. Shown as-is, a player eleventh in
    line after a busy evening read "You're number 253 in line".
    """
    ahead = db.session.scalar(
        db.select(func.count()).select_from(QueueEntry).where(
            QueueEntry.league_id == league_id,
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


@retry_on_deadlock
def attempt_matchmaking(league):
    """
    Start every match a league's tables can start right now. Returns True
    if at least one started.

    THE SINGLE SOURCE OF TRUTH for matchmaking. For each of the league's
    tables in use:

      1. A king is holding it (Active match, no challenger yet): the table
         needs one player, to challenge them.
      2. It's free: it needs two, to play each other.
      3. A game is on: it needs nobody.

    The league's one line fills those seats from the front: whoever is
    already up keeps their table while it still has room, then the next in
    line go to kings waiting for a challenger, then to free tables, two at
    a time. A free table never starts with one: a player left alone is
    paired with one left alone at another free table, or goes back to
    waiting at the front of the line.

    Case 1 is the one the old /queue/join route didn't handle, which is
    why players piled up in the queue behind a king and no match ever
    started. Every caller - joining, confirming, finishing or giving up a
    match, a waiting player's status poll - comes through here, so the
    cases can't drift apart again.

    The ready check: being up isn't enough to play. Each player who is up
    has READY_CHECK_SECONDS to say they're here (confirm_here); a table's
    game starts once everyone up for it has. Anyone who lets the time run
    out is taken out of the queue, and the next in line is up in their
    place. A player who joined or confirmed in the last
    RECENTLY_HERE_SECONDS is taken to be here without being asked.
    """
    league_id = _league_id(league)
    try:
        _lock_league(league_id)

        needs, kings = {}, {}
        for table in active_tables(league_id):
            active = _active_match_for_table(table.table_id, lock=True)
            if active is None:
                needs[table.table_id] = 2
            elif active.is_awaiting_challenger:
                needs[table.table_id] = 1
                kings[table.table_id] = active

        clocks = _turn_clocks(league_id)
        waiting = _without_missed_turns(_eligible_queue(league_id), clocks)
        plan = _plan(waiting, needs)

        # Anyone not given a table isn't up, whatever was true a moment ago.
        seated = {entry.queue_id for entries in plan.values() for entry in entries}
        for entry in waiting:
            if entry.queue_id not in seated:
                entry.called_at = None
                entry.table_id = None

        started, patient = False, []
        for table_id, entries in plan.items():
            for entry in entries:
                entry.table_id = table_id
            if not _call_up(entries, clocks):
                continue

            patient += _waited_long(entries)
            king = kings.get(table_id)
            if king is not None:
                # --- Case 1: a king is waiting for a challenger ---
                king.player_two_id = entries[0].user_id
                db.session.delete(entries[0])
            else:
                # --- Case 2: free table, pair the two who are up ---
                first, second = entries
                db.session.add(
                    Match(
                        table_id=table_id,
                        player_one_id=first.user_id,
                        player_two_id=second.user_id,
                        match_status=Match.STATUS_ACTIVE,
                    )
                )
                db.session.delete(first)
                db.session.delete(second)
            started = True

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    _award_patience(patient, league_id)
    return started


def _plan(waiting, needs):
    """
    Which players go to which table: {table_id: [entries]}, in line
    order. `needs` is {table_id: players it can take} - 1 for a king
    waiting, 2 for a free table. See attempt_matchmaking for the rules.
    """
    plan = {table_id: [] for table_id, need in needs.items() if need > 0}
    taken = set()

    # Whoever is up already keeps their table while it still has room, so
    # nobody's minute restarts because someone else joined.
    for entry in waiting:
        table_id = entry.table_id if entry.is_called else None
        if table_id in plan and len(plan[table_id]) < needs[table_id]:
            plan[table_id].append(entry)
            taken.add(entry.queue_id)

    line = deque(entry for entry in waiting if entry.queue_id not in taken)

    # Kings first: one player and a game starts.
    for table_id in sorted(plan):
        if needs[table_id] == 1 and not plan[table_id] and line:
            plan[table_id].append(line.popleft())

    # Then free tables, two at a time.
    for table_id in sorted(plan):
        if needs[table_id] == 2:
            while len(plan[table_id]) < 2 and line:
                plan[table_id].append(line.popleft())

    # A free table can't start with one. Pair up players left alone at
    # different free tables; anyone still alone goes back to waiting.
    alone = [t for t in sorted(plan) if needs[t] == 2 and len(plan[t]) == 1]
    while len(alone) >= 2:
        keep, merge = alone.pop(0), alone.pop(0)
        plan[keep].append(plan[merge].pop())
    for table_id in alone:
        plan[table_id] = []

    return {table_id: entries for table_id, entries in plan.items() if entries}


def _waited_long(entries):
    """
    Which of these players waited long enough in the queue to earn
    Patience. Read before their queue rows go, since that's the only place
    the wait is recorded; measured by the database's clock (seconds_since).
    """
    try:
        rows = db.session.execute(
            db.select(QueueEntry.user_id, seconds_since(QueueEntry.joined_at)).where(
                QueueEntry.queue_id.in_([e.queue_id for e in entries])
            )
        ).all()
    except Exception:
        # A badge isn't worth failing a game over.
        log.exception("could not read queue waits for patience")
        return []
    return [uid for uid, seconds in rows if seconds is not None and seconds >= PATIENCE_WAIT_SECONDS]


def _award_patience(user_ids, league_id):
    # After the game is committed, and never allowed to undo it.
    for uid in user_ids:
        try:
            award(uid, league_id, "patience")
        except Exception:
            log.exception("could not award patience (user %s)", uid)


def _turn_clocks(league_id):
    """
    For each queue entry in a league: (seconds since their turn came,
    seconds since they last showed they were here). Either is None when
    there is no such moment.

    A locked read, like _eligible_queue's: a plain read could answer from
    a snapshot taken before this request waited for the league's lock, and
    time a turn that has since been taken back and given again.
    """
    last_here = func.coalesce(QueueEntry.confirmed_at, QueueEntry.joined_at)
    rows = db.session.execute(
        db.select(
            QueueEntry.queue_id,
            seconds_since(QueueEntry.called_at),
            seconds_since(last_here),
        )
        .where(QueueEntry.league_id == league_id)
        .with_for_update()
    )
    return {queue_id: (called, here) for queue_id, called, here in rows}


def _without_missed_turns(waiting, clocks):
    """
    The queue minus anyone whose turn came and went without them saying
    they were here. Those entries are deleted: the player is out of the
    queue, and everyone behind them moves up.
    """
    still_waiting = []
    for entry in waiting:
        seconds_called, _ = clocks.get(entry.queue_id, (None, None))
        if entry.is_called and not entry.is_confirmed and _turn_has_run_out(seconds_called):
            log.info("%r didn't confirm in time; taking them out of the queue", entry)
            db.session.delete(entry)
            continue
        still_waiting.append(entry)
    return still_waiting


def _call_up(entries, clocks):
    """
    Make it these players' turn. Returns True if every one of them has
    said they're here, so the game can start.

    A player newly up who joined or confirmed recently counts as here
    already; anyone else is asked, and has READY_CHECK_SECONDS from now.
    """
    everyone_here = True
    for entry in entries:
        if not entry.is_called:
            _, seconds_since_here = clocks.get(entry.queue_id, (None, None))
            recently_here = (
                seconds_since_here is not None and seconds_since_here < RECENTLY_HERE_SECONDS
            )
            entry.called_at = func.now()
            entry.confirmed_at = func.now() if recently_here else None
            if not recently_here:
                everyone_here = False
        elif not entry.is_confirmed:
            everyone_here = False
    return everyone_here


def _eligible_queue(league_id):
    """
    The league's queue in order, locked, with stale entries removed.

    A stale entry is someone who is already in an Active match - at any
    table, in any league - or a second entry for the same person. Neither
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
                .where(QueueEntry.league_id == league_id)
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


def get_player_status(user_id, league):
    """
    The /match/status payload: exactly one of idle / queued / your_turn /
    waiting_for_challenger / playing (see AGENTS.md).

    `league` is the league the player is looking at. A game or a held
    table is reported wherever it is - a player plays one game at a time,
    whichever league's screen they're on - with its own league_id.

    Also the queue's safety net. If this player is waiting - in the queue,
    or holding a table - it gives matchmaking a chance first. A queue that
    got stuck (a crash between join and matchmaking, rows left by an old
    bug, a server restart) then heals within one poll, instead of waiting
    for someone new to tap Join. It calls the one attempt_matchmaking(),
    so this is not a second copy of the rules.
    """
    league = League.of(league)
    league_id = league.league_id
    match = _active_match_for_player(user_id)
    queued = match is None and _is_queued(user_id, league_id)

    if (match is not None and match.is_awaiting_challenger) or queued:
        heal = league_for_table(match.table_id) if match is not None else league
        try:
            attempt_matchmaking(heal.league_id)
        except Exception:
            log.exception("matchmaking during a status check failed (league %s)", heal.league_id)
        match = _active_match_for_player(user_id)

    if match is not None:
        game_league = league_for_table(match.table_id)
        name = table_names(game_league).get(match.table_id)
        if match.is_in_progress:
            return match.to_playing_dict(user_id, game_league, name)
        return {**match.to_waiting_dict(game_league, name), **_up_next(match.table_id)}

    queue_status = get_queue_status(user_id, league_id)
    if queue_status is None:
        return {"status": "idle"}

    names = table_names(league)
    if queue_status["called"]:
        table_id = queue_status["table_id"]
        return {
            "status": "your_turn",
            "table_id": table_id,
            "table_name": names.get(table_id),
            "league_type": league.game,
            "league_id": league_id,
            "confirmed": queue_status["confirmed"],
            "seconds_left": queue_status["seconds_left"],
            **_opponent_when_up(user_id, table_id),
        }
    tables = active_tables(league)
    return {
        "status": "queued",
        # The league's first table, for apps from before there were more.
        "table_id": tables[0].table_id if tables else None,
        "league_type": league.game,
        "league_id": league_id,
        "queue_position": queue_status["queue_position"],
        "seconds_waiting": queue_status["seconds_waiting"],
        "can_leave": queue_status["can_leave"],
        "leave_unlocks_in": queue_status["leave_unlocks_in"],
    }


def _turns(table_id):
    """
    Everyone whose turn it is at a table, front of the line first, as
    (entry, seconds left to say they're here - None once they have).
    """
    rows = db.session.execute(
        db.select(QueueEntry, seconds_since(QueueEntry.called_at))
        .where(QueueEntry.table_id == table_id, QueueEntry.called_at.isnot(None))
        .order_by(QueueEntry.queue_position.asc(), QueueEntry.queue_id.asc())
    ).all()
    return [
        (entry, None if entry.is_confirmed else _seconds_left(seconds_called))
        for entry, seconds_called in rows
    ]


def _up_next(table_id):
    """
    For a king waiting at the table: who is up to challenge them, and how
    long they have left to say they're here.
    """
    turns = _turns(table_id)
    if not turns:
        return {"up_next": None, "up_next_seconds_left": None}
    entry, seconds_left = turns[0]
    return {"up_next": entry.player.username, "up_next_seconds_left": seconds_left}


def _opponent_when_up(user_id, table_id):
    """
    Who a player whose turn has come will play: the king holding the
    table, or the other player up at a free one - and whether they're
    ready. The king always is: they're at the table already.
    """
    active = _active_match_for_table(table_id) if table_id is not None else None
    if active is not None and active.player_one is not None:
        return {
            "opponent": active.player_one.username,
            "opponent_id": active.player_one_id,
            "opponent_confirmed": True,
            "opponent_seconds_left": None,
        }
    turns = _turns(table_id) if table_id is not None else []
    other = next(((e, left) for e, left in turns if e.user_id != user_id), None)
    if other is None:
        return {
            "opponent": None,
            "opponent_id": None,
            "opponent_confirmed": False,
            "opponent_seconds_left": None,
        }
    entry, seconds_left = other
    return {
        "opponent": entry.player.username,
        "opponent_id": entry.user_id,
        "opponent_confirmed": entry.is_confirmed,
        "opponent_seconds_left": seconds_left,
    }


def _is_queued(user_id, league_id):
    return (
        db.session.scalar(
            db.select(QueueEntry.queue_id).where(
                QueueEntry.user_id == user_id, QueueEntry.league_id == league_id
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

    league = league_for_table(table_id)
    try:
        award(user_id, league.league_id, "abdication")
    except Exception:
        log.exception("could not award abdication (user %s)", user_id)

    # The table is free now; the next two waiting (if any) can play.
    try:
        attempt_matchmaking(league.league_id)
    except Exception:
        log.exception("stepped down, but matchmaking failed (table %s)", table_id)

    return STEP_DOWN_RESULT_DONE


def _queue_in_order(league_id, limit=None):
    # queue_id breaks ties: two people joining in the same instant can be
    # given the same position, and the order must not flicker between polls.
    stmt = (
        db.select(QueueEntry)
        .where(QueueEntry.league_id == league_id)
        .order_by(QueueEntry.queue_position.asc(), QueueEntry.queue_id.asc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.session.scalars(stmt))


def view_queue(league):
    """
    A league's queue as the apps expect it:
        [{queue_position, user_id, username, called, confirmed,
          table_id, table_name}, ...]

    queue_position is each player's place in line, 1 upwards - see
    _place_in_line for why the stored column can't be shown directly.
    table_id / table_name say which table a player whose turn has come is
    called to.

    QueueEntry.player is lazy="joined", so this is one query rather than
    one per waiting player.
    """
    league_id = _league_id(league)
    names = table_names(league_id)
    return [
        entry.to_dict(place=place, table_names=names)
        for place, entry in enumerate(_queue_in_order(league_id), start=1)
    ]


def get_pool_table(table_id):
    """The PoolTable row, or None if the venue hasn't registered it."""
    return db.session.get(PoolTable, table_id)
