"""
Queue joining, leaving and matchmaking - ported to the ORM.

The headline test is test_king_waiting_gets_matched_when_someone_joins:
the exact bug that was originally reported, where a player joins, is told
they're already in the queue, and no match ever starts. If that fails
again, the deadlock is back.
"""
import unittest

from tests.conftest_base import BaseTestCase
from models import Match, QueueEntry, db

from logic.manage_queue import (
    JOIN_RESULT_ALREADY_PLAYING,
    JOIN_RESULT_ALREADY_QUEUED,
    JOIN_RESULT_JOINED,
    LEAVE_UNLOCK_SECONDS,
    STEP_DOWN_RESULT_DONE,
    STEP_DOWN_RESULT_IN_GAME,
    STEP_DOWN_RESULT_NOT_HOLDING,
    attempt_matchmaking,
    get_player_status,
    get_queue_status,
    join_queue,
    leave_queue,
    step_down,
    view_queue,
)


class JoinQueueTests(BaseTestCase):
    def test_first_player_joins_at_position_one(self):
        self.assertEqual(join_queue(self.alice, 1), JOIN_RESULT_JOINED)
        self.assertEqual(self.queued_user_ids(), [self.alice])

        entry = db.session.scalars(
            db.select(QueueEntry).where(QueueEntry.user_id == self.alice)
        ).first()
        self.assertEqual(entry.queue_position, 1)

    def test_second_player_joins_behind_the_first(self):
        join_queue(self.alice, 1)
        join_queue(self.bob, 1)
        self.assertEqual(self.queued_user_ids(), [self.alice, self.bob])

    def test_joining_twice_is_reported_distinctly_and_does_not_duplicate(self):
        self.assertEqual(join_queue(self.alice, 1), JOIN_RESULT_JOINED)
        self.assertEqual(join_queue(self.alice, 1), JOIN_RESULT_ALREADY_QUEUED)
        self.assertEqual(self.queued_user_ids(), [self.alice])

    def test_player_in_an_active_match_cannot_join(self):
        self.start_match(self.alice, self.bob)
        self.assertEqual(join_queue(self.alice, 1), JOIN_RESULT_ALREADY_PLAYING)

    def test_joined_at_is_populated_by_the_database(self):
        """
        The INSERT never sets joined_at - MySQL's server_default does.
        If that default goes missing the leave timer silently breaks.
        """
        join_queue(self.alice, 1)
        entry = db.session.scalars(
            db.select(QueueEntry).where(QueueEntry.user_id == self.alice)
        ).first()
        self.assertIsNotNone(entry.joined_at)


class MatchmakingTests(BaseTestCase):
    def test_two_players_in_queue_get_matched(self):
        join_queue(self.alice, 1)
        join_queue(self.bob, 1)

        self.assertTrue(attempt_matchmaking(1))

        match = self.active_match()
        self.assertIsNotNone(match)
        self.assertEqual({match.player_one_id, match.player_two_id}, {self.alice, self.bob})
        self.assertIsNone(match.winner_id, "nobody has won yet")
        self.assertEqual(self.queued_user_ids(), [], "matched players leave the queue")

    def test_single_player_is_not_matched(self):
        join_queue(self.alice, 1)
        self.assertFalse(attempt_matchmaking(1))
        self.assertIsNone(self.active_match())
        self.assertEqual(self.queued_user_ids(), [self.alice])

    def test_king_waiting_gets_matched_when_someone_joins(self):
        """
        THE ORIGINAL BUG.

        alice won her last game so she holds the table with no opponent.
        bob joins. Before the fix, the join route only knew how to pair
        two queued players, so bob waited forever and alice was invisible
        because a king lives in Matches, not Queue.
        """
        self.make_king(self.alice)

        self.assertEqual(join_queue(self.bob, 1), JOIN_RESULT_JOINED)
        self.assertTrue(attempt_matchmaking(1), "a waiting king must take the new joiner")

        match = self.active_match()
        self.assertEqual(match.player_one_id, self.alice)
        self.assertEqual(match.player_two_id, self.bob)
        self.assertIsNone(match.winner_id)
        self.assertEqual(self.queued_user_ids(), [])

    def test_retrying_a_stuck_join_self_heals(self):
        """Anyone stuck from before the fix gets matched by rejoining."""
        self.make_king(self.alice)
        join_queue(self.bob, 1)
        self.assertIsNone(self.active_match().player_two_id)

        self.assertEqual(join_queue(self.bob, 1), JOIN_RESULT_ALREADY_QUEUED)
        self.assertTrue(attempt_matchmaking(1))

        self.assertEqual(self.active_match().player_two_id, self.bob)

    def test_busy_table_does_not_start_another_match(self):
        self.start_match(self.alice, self.bob)
        join_queue(self.carol, 1)

        self.assertFalse(attempt_matchmaking(1))
        self.assertEqual(self.queued_user_ids(), [self.carol])

    def test_matchmaking_is_idempotent(self):
        join_queue(self.alice, 1)
        join_queue(self.bob, 1)

        self.assertTrue(attempt_matchmaking(1))
        self.assertFalse(attempt_matchmaking(1))
        self.assertFalse(attempt_matchmaking(1))

        count = db.session.scalar(
            db.select(db.func.count()).select_from(Match).where(
                Match.match_status == Match.STATUS_ACTIVE
            )
        )
        self.assertEqual(count, 1)

    def test_queues_on_different_tables_do_not_interfere(self):
        join_queue(self.alice, 1)
        join_queue(self.bob, 2)

        self.assertFalse(attempt_matchmaking(1))
        self.assertFalse(attempt_matchmaking(2))
        self.assertEqual(self.queued_user_ids(1), [self.alice])
        self.assertEqual(self.queued_user_ids(2), [self.bob])


class StaleQueueEntryTests(BaseTestCase):
    """
    A queue row for someone already playing should never exist, but a
    double-tapped Join or an old bug can leave one. Matchmaking must not
    turn it into a player facing themselves.
    """

    def queue_directly(self, user_id, position, table_id=1):
        db.session.add(QueueEntry(user_id=user_id, table_id=table_id, queue_position=position))
        db.session.commit()

    def test_king_is_never_matched_against_themselves(self):
        self.make_king(self.alice)
        self.queue_directly(self.alice, 1)
        self.queue_directly(self.bob, 2)

        self.assertTrue(attempt_matchmaking(1))

        match = self.active_match()
        self.assertEqual((match.player_one_id, match.player_two_id), (self.alice, self.bob))
        self.assertEqual(self.queued_user_ids(), [], "the stale row was cleared too")

    def test_player_mid_game_elsewhere_is_skipped(self):
        self.start_match(self.alice, self.bob, table_id=2)
        self.queue_directly(self.alice, 1)
        self.queue_directly(self.carol, 2)

        self.assertFalse(attempt_matchmaking(1), "carol alone can't start a game")
        self.assertEqual(self.queued_user_ids(), [self.carol])

    def test_cannot_queue_while_playing_at_another_table(self):
        self.start_match(self.alice, self.bob, table_id=2)
        self.assertEqual(join_queue(self.alice, 1), JOIN_RESULT_ALREADY_PLAYING)

    def test_same_position_ties_break_by_who_joined_first(self):
        self.queue_directly(self.bob, 1)
        self.queue_directly(self.alice, 1)
        self.assertEqual([q["username"] for q in view_queue(1)], ["bob", "alice"])


class StatusSelfHealTests(BaseTestCase):
    """
    get_player_status gives matchmaking a chance whenever the player asking
    is waiting, so a stuck queue clears on the next poll rather than
    whenever someone new happens to tap Join.
    """

    def queue_without_matchmaking(self, user_id):
        db.session.add(QueueEntry(user_id=user_id, table_id=1, queue_position=1))
        db.session.commit()

    def test_queued_player_polling_gets_matched_with_a_waiting_king(self):
        self.make_king(self.alice)
        self.queue_without_matchmaking(self.bob)

        status = get_player_status(self.bob, 1)

        self.assertEqual(status["status"], "playing")
        self.assertEqual(status["opponent"], "alice")

    def test_king_polling_pulls_in_the_waiting_challenger(self):
        self.make_king(self.alice)
        self.queue_without_matchmaking(self.bob)

        self.assertEqual(get_player_status(self.alice, 1)["status"], "playing")

    def test_idle_player_polling_changes_nothing(self):
        self.make_king(self.alice)
        self.queue_without_matchmaking(self.bob)

        self.assertEqual(get_player_status(self.carol, 1), {"status": "idle"})
        self.assertIsNone(self.active_match().player_two_id)


class StepDownTests(BaseTestCase):
    def test_king_with_no_challenger_can_step_down(self):
        self.make_king(self.alice)

        self.assertEqual(step_down(self.alice), STEP_DOWN_RESULT_DONE)

        self.assertIsNone(self.active_match())
        self.assertEqual(get_player_status(self.alice, 1), {"status": "idle"})

    def test_cannot_walk_away_from_a_game_in_progress(self):
        self.start_match(self.alice, self.bob)

        self.assertEqual(step_down(self.alice), STEP_DOWN_RESULT_IN_GAME)
        self.assertIsNotNone(self.active_match())

    def test_stepping_down_without_holding_a_table(self):
        self.assertEqual(step_down(self.alice), STEP_DOWN_RESULT_NOT_HOLDING)

    def test_the_freed_table_goes_to_the_next_two_in_line(self):
        self.make_king(self.alice)
        db.session.add(QueueEntry(user_id=self.bob, table_id=1, queue_position=1))
        db.session.add(QueueEntry(user_id=self.carol, table_id=1, queue_position=2))
        db.session.commit()
        # A challenger in the queue would normally be matched already; take
        # the king's seat down before matchmaking runs to test the handoff.
        step_down(self.alice)

        match = self.active_match()
        self.assertEqual({match.player_one_id, match.player_two_id}, {self.bob, self.carol})

    def test_the_cached_king_is_cleared(self):
        from models import PoolTable

        table = db.session.get(PoolTable, 1)
        table.current_king_id, table.current_streak = self.alice, 3
        self.make_king(self.alice)

        step_down(self.alice)

        table = db.session.get(PoolTable, 1)
        self.assertIsNone(table.current_king_id)
        self.assertEqual(table.current_streak, 0)


class LeaveQueueTests(BaseTestCase):
    def test_cannot_leave_immediately_after_joining(self):
        join_queue(self.alice, 1)
        status = get_queue_status(self.alice, 1)

        self.assertFalse(status["can_leave"])
        self.assertGreater(status["leave_unlocks_in"], 0)
        self.assertLessEqual(status["leave_unlocks_in"], LEAVE_UNLOCK_SECONDS)

    def test_can_leave_after_the_wait_with_no_match(self):
        join_queue(self.alice, 1)
        self.backdate_queue_join(self.alice, LEAVE_UNLOCK_SECONDS + 5)

        status = get_queue_status(self.alice, 1)
        self.assertTrue(status["can_leave"])
        self.assertEqual(status["leave_unlocks_in"], 0)

        self.assertTrue(leave_queue(self.alice, 1))
        self.assertEqual(self.queued_user_ids(), [])

    def test_leaving_when_not_queued_reports_false(self):
        self.assertFalse(leave_queue(self.alice, 1))

    def test_status_is_none_when_not_queued(self):
        self.assertIsNone(get_queue_status(self.alice, 1))

    def test_leaving_does_not_disturb_the_other_players(self):
        join_queue(self.alice, 1)
        join_queue(self.bob, 1)
        join_queue(self.carol, 1)
        self.backdate_queue_join(self.bob, LEAVE_UNLOCK_SECONDS + 5)

        leave_queue(self.bob, 1)

        self.assertEqual(self.queued_user_ids(), [self.alice, self.carol])

    def test_leaving_then_rejoining_puts_you_at_the_back(self):
        join_queue(self.alice, 1)
        join_queue(self.bob, 1)
        self.backdate_queue_join(self.alice, LEAVE_UNLOCK_SECONDS + 5)

        leave_queue(self.alice, 1)
        self.assertEqual(join_queue(self.alice, 1), JOIN_RESULT_JOINED)

        self.assertEqual(
            self.queued_user_ids(), [self.bob, self.alice], "rejoining must not jump the line"
        )


class PlaceInLineTests(BaseTestCase):
    """
    Found in the browser: after a busy evening the panel said "You're
    number 253 in line" to someone eleventh of eleven, because the stored
    queue_position only ever counts up.
    """

    def test_status_and_list_report_the_real_place_after_people_move_on(self):
        dave = self.add_player("dave")
        erin = self.add_player("erin")

        self.start_match(self.alice, self.bob)
        for user_id in (self.carol, dave, erin):
            join_queue(user_id, 1)

        # alice wins; carol comes off the queue to play her.
        from logic.record_match import record_match_result

        record_match_result(self.active_match(), self.alice, self.bob, 16)

        stored = db.session.scalars(
            db.select(QueueEntry.queue_position).where(QueueEntry.user_id == dave)
        ).one()
        self.assertEqual(stored, 2, "the stored key hasn't moved")
        self.assertEqual(get_queue_status(dave, 1)["queue_position"], 1, "but dave is first in line")
        self.assertEqual(get_queue_status(erin, 1)["queue_position"], 2)
        self.assertEqual([q["queue_position"] for q in view_queue(1)], [1, 2])


class ViewQueueTests(BaseTestCase):
    def test_view_queue_returns_usernames_in_order(self):
        join_queue(self.bob, 1)
        join_queue(self.alice, 1)

        queue = view_queue(1)
        self.assertEqual([q["username"] for q in queue], ["bob", "alice"])
        self.assertEqual([q["queue_position"] for q in queue], [1, 2])

    def test_queue_dict_has_exactly_the_keys_the_frontend_reads(self):
        """Guards the API contract: extra or renamed keys break React."""
        join_queue(self.alice, 1)
        self.assertEqual(set(view_queue(1)[0].keys()), {"queue_position", "username"})

    def test_empty_queue_returns_empty_list(self):
        self.assertEqual(view_queue(1), [])


if __name__ == "__main__":
    unittest.main()
