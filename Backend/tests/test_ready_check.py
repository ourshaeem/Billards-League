"""
The ready check: when a player's turn comes they have a minute to say
they're here, or they're taken out of the queue and the next person is up.

What it fixes: a player who joined the queue and wandered off used to be
pulled into a game anyway, leaving the king at the table waiting for
someone who wasn't coming - with no way to move the line on.
"""
import unittest

from tests.conftest_base import ApiTestCase, BaseTestCase
from models import BILLIARDS, Match, QueueEntry, db

from logic.manage_queue import (
    CONFIRM_RESULT_ALREADY_CONFIRMED,
    CONFIRM_RESULT_CONFIRMED,
    CONFIRM_RESULT_NOT_QUEUED,
    CONFIRM_RESULT_NOT_YOUR_TURN,
    CONFIRM_RESULT_TOO_LATE,
    LEAVE_UNLOCK_SECONDS,
    READY_CHECK_SECONDS,
    RECENTLY_HERE_SECONDS,
    attempt_matchmaking,
    confirm_here,
    get_player_status,
    get_queue_status,
    join_queue,
    view_queue,
)

# Long enough ago that joining no longer counts as being here.
A_WHILE = RECENTLY_HERE_SECONDS + 240
TOO_LONG = READY_CHECK_SECONDS + 1


class ReadyCheckTestCase(BaseTestCase):
    def queue_a_while_ago(self, *user_ids, table_id=1):
        for user_id in user_ids:
            join_queue(user_id, table_id)
            self.backdate_queue_join(user_id, A_WHILE, table_id)

    def entry(self, user_id, table_id=1):
        db.session.expire_all()
        return db.session.scalars(
            db.select(QueueEntry).where(
                QueueEntry.user_id == user_id, QueueEntry.table_id == table_id
            )
        ).first()


class YourTurn(ReadyCheckTestCase):
    def test_a_player_who_joined_a_while_ago_is_asked_before_playing(self):
        self.make_king(self.alice)
        self.queue_a_while_ago(self.bob)

        self.assertFalse(attempt_matchmaking(BILLIARDS), "no game until bob says they're here")

        self.assertIsNone(self.active_match().player_two_id)
        status = get_player_status(self.bob, BILLIARDS)
        self.assertEqual(status["status"], "your_turn")
        self.assertFalse(status["confirmed"])
        self.assertTrue(READY_CHECK_SECONDS - 5 <= status["seconds_left"] <= READY_CHECK_SECONDS)
        self.assertEqual(status["opponent"], "alice")
        self.assertEqual(status["opponent_id"], self.alice)
        self.assertTrue(status["opponent_confirmed"], "the king is at the table already")
        self.assertEqual(status["league_type"], "billiards")

    def test_saying_youre_here_starts_the_game(self):
        self.make_king(self.alice)
        self.queue_a_while_ago(self.bob)
        attempt_matchmaking(BILLIARDS)

        self.assertEqual(confirm_here(self.bob, BILLIARDS), CONFIRM_RESULT_CONFIRMED)
        self.assertTrue(attempt_matchmaking(BILLIARDS))

        match = self.active_match()
        self.assertEqual((match.player_one_id, match.player_two_id), (self.alice, self.bob))
        self.assertEqual(self.queued_user_ids(), [])
        self.assertEqual(get_player_status(self.bob, BILLIARDS)["status"], "playing")

    def test_missing_the_minute_takes_you_out_and_the_next_player_is_up(self):
        self.make_king(self.alice)
        self.queue_a_while_ago(self.bob, self.carol)
        attempt_matchmaking(BILLIARDS)
        self.backdate_turn(self.bob, TOO_LONG)

        self.assertFalse(attempt_matchmaking(BILLIARDS))

        self.assertEqual(self.queued_user_ids(), [self.carol], "bob is out of the queue")
        self.assertEqual(get_player_status(self.bob, BILLIARDS), {"status": "idle"})
        carol = get_player_status(self.carol, BILLIARDS)
        self.assertEqual(carol["status"], "your_turn", "carol is up instead")
        self.assertEqual(carol["seconds_left"], READY_CHECK_SECONDS, "with a whole minute of their own")

    def test_nobody_has_to_tap_anything_for_the_line_to_move_on(self):
        """The next player's own status poll is enough to move bob aside."""
        self.make_king(self.alice)
        self.queue_a_while_ago(self.bob, self.carol)
        get_player_status(self.alice, BILLIARDS)
        self.backdate_turn(self.bob, TOO_LONG)

        self.assertEqual(get_player_status(self.carol, BILLIARDS)["status"], "your_turn")
        self.assertEqual(self.queued_user_ids(), [self.carol])

    def test_only_the_front_of_the_line_is_up(self):
        self.make_king(self.alice)
        self.queue_a_while_ago(self.bob, self.carol)
        attempt_matchmaking(BILLIARDS)

        self.assertEqual(get_player_status(self.carol, BILLIARDS)["status"], "queued")
        self.assertEqual(get_player_status(self.carol, BILLIARDS)["queue_position"], 2)

    def test_the_king_sees_who_is_up_and_how_long_they_have(self):
        self.make_king(self.alice)
        self.queue_a_while_ago(self.bob)
        attempt_matchmaking(BILLIARDS)

        status = get_player_status(self.alice, BILLIARDS)

        self.assertEqual(status["status"], "waiting_for_challenger")
        self.assertEqual(status["up_next"], "bob")
        self.assertTrue(0 < status["up_next_seconds_left"] <= READY_CHECK_SECONDS)

    def test_a_king_with_nobody_queued_has_nobody_up_next(self):
        self.make_king(self.alice)
        status = get_player_status(self.alice, BILLIARDS)
        self.assertIsNone(status["up_next"])
        self.assertIsNone(status["up_next_seconds_left"])

    def test_the_queue_shows_whose_turn_it_is(self):
        self.make_king(self.alice)
        self.queue_a_while_ago(self.bob, self.carol)
        attempt_matchmaking(BILLIARDS)

        queue = view_queue(BILLIARDS)

        self.assertEqual([(q["username"], q["called"], q["confirmed"]) for q in queue],
                         [("bob", True, False), ("carol", False, False)])
        self.assertEqual(queue[0]["user_id"], self.bob)


class FreeTable(ReadyCheckTestCase):
    def test_both_players_must_say_theyre_here(self):
        self.queue_a_while_ago(self.alice, self.bob)
        self.assertFalse(attempt_matchmaking(BILLIARDS))

        self.assertEqual(confirm_here(self.alice, BILLIARDS), CONFIRM_RESULT_CONFIRMED)
        self.assertFalse(attempt_matchmaking(BILLIARDS), "bob hasn't said yet")

        alice = get_player_status(self.alice, BILLIARDS)
        self.assertEqual(alice["status"], "your_turn")
        self.assertTrue(alice["confirmed"])
        self.assertIsNone(alice["seconds_left"])
        self.assertEqual(alice["opponent"], "bob")
        self.assertFalse(alice["opponent_confirmed"])
        self.assertTrue(0 < alice["opponent_seconds_left"] <= READY_CHECK_SECONDS)

        confirm_here(self.bob, BILLIARDS)
        self.assertTrue(attempt_matchmaking(BILLIARDS))
        match = self.active_match()
        self.assertEqual({match.player_one_id, match.player_two_id}, {self.alice, self.bob})

    def test_if_the_other_player_misses_their_turn_the_next_one_is_asked(self):
        self.queue_a_while_ago(self.alice, self.bob, self.carol)
        attempt_matchmaking(BILLIARDS)
        confirm_here(self.alice, BILLIARDS)
        self.backdate_turn(self.bob, TOO_LONG)

        attempt_matchmaking(BILLIARDS)

        self.assertEqual(self.queued_user_ids(), [self.alice, self.carol])
        alice = get_player_status(self.alice, BILLIARDS)
        self.assertTrue(alice["confirmed"], "alice doesn't have to say so again")
        self.assertEqual(alice["opponent"], "carol")

    def test_with_nobody_left_to_play_you_wait_at_the_front_again(self):
        self.queue_a_while_ago(self.alice, self.bob)
        attempt_matchmaking(BILLIARDS)
        confirm_here(self.alice, BILLIARDS)
        self.backdate_turn(self.bob, TOO_LONG)

        attempt_matchmaking(BILLIARDS)

        alice = get_player_status(self.alice, BILLIARDS)
        self.assertEqual(alice["status"], "queued")
        self.assertEqual(alice["queue_position"], 1)

    def test_after_a_long_wait_at_the_front_you_are_asked_again(self):
        """Saying you were here an hour ago doesn't mean you still are."""
        self.queue_a_while_ago(self.alice, self.bob)
        attempt_matchmaking(BILLIARDS)
        confirm_here(self.alice, BILLIARDS)
        self.backdate_turn(self.bob, TOO_LONG)
        attempt_matchmaking(BILLIARDS)
        self.backdate_confirmation(self.alice, 3600)

        join_queue(self.carol, BILLIARDS)
        self.assertFalse(attempt_matchmaking(BILLIARDS))

        alice = get_player_status(self.alice, BILLIARDS)
        self.assertEqual(alice["status"], "your_turn")
        self.assertFalse(alice["confirmed"])
        self.assertTrue(get_player_status(self.carol, BILLIARDS)["confirmed"], "carol only just joined")

    def test_saying_you_were_here_moments_ago_still_counts(self):
        self.queue_a_while_ago(self.alice, self.bob)
        attempt_matchmaking(BILLIARDS)
        confirm_here(self.alice, BILLIARDS)
        self.backdate_turn(self.bob, TOO_LONG)
        attempt_matchmaking(BILLIARDS)

        join_queue(self.carol, BILLIARDS)

        self.assertTrue(attempt_matchmaking(BILLIARDS), "alice confirmed seconds ago and carol just joined")


class JustJoined(ReadyCheckTestCase):
    def test_joining_a_table_with_room_starts_at_once(self):
        """Having just tapped Join, nobody is asked to tap again."""
        self.make_king(self.alice)
        join_queue(self.bob, BILLIARDS)

        self.assertTrue(attempt_matchmaking(BILLIARDS))
        self.assertEqual(self.active_match().player_two_id, self.bob)

    def test_two_people_joining_together_start_at_once(self):
        join_queue(self.alice, BILLIARDS)
        join_queue(self.bob, BILLIARDS)
        self.assertTrue(attempt_matchmaking(BILLIARDS))

    def test_only_the_player_who_just_joined_counts_as_here(self):
        self.queue_a_while_ago(self.alice)
        join_queue(self.bob, BILLIARDS)

        self.assertFalse(attempt_matchmaking(BILLIARDS))

        self.assertTrue(get_player_status(self.bob, BILLIARDS)["confirmed"])
        self.assertFalse(get_player_status(self.alice, BILLIARDS)["confirmed"])


class Confirming(ReadyCheckTestCase):
    def test_not_in_the_queue(self):
        self.assertEqual(confirm_here(self.alice, BILLIARDS), CONFIRM_RESULT_NOT_QUEUED)

    def test_before_your_turn(self):
        self.queue_a_while_ago(self.alice)
        attempt_matchmaking(BILLIARDS)
        self.assertEqual(confirm_here(self.alice, BILLIARDS), CONFIRM_RESULT_NOT_YOUR_TURN)

    def test_twice(self):
        self.queue_a_while_ago(self.alice, self.bob)
        attempt_matchmaking(BILLIARDS)
        confirm_here(self.alice, BILLIARDS)
        self.assertEqual(confirm_here(self.alice, BILLIARDS), CONFIRM_RESULT_ALREADY_CONFIRMED)

    def test_too_late_counts_for_nothing_even_before_anyone_noticed(self):
        self.make_king(self.alice)
        self.queue_a_while_ago(self.bob)
        attempt_matchmaking(BILLIARDS)
        self.backdate_turn(self.bob, TOO_LONG)

        self.assertEqual(confirm_here(self.bob, BILLIARDS), CONFIRM_RESULT_TOO_LATE)

        self.assertEqual(self.queued_user_ids(), [])
        self.assertFalse(attempt_matchmaking(BILLIARDS))
        self.assertIsNone(self.active_match().player_two_id)

    def test_with_seconds_to_spare(self):
        self.make_king(self.alice)
        self.queue_a_while_ago(self.bob)
        attempt_matchmaking(BILLIARDS)
        self.backdate_turn(self.bob, READY_CHECK_SECONDS - 5)

        self.assertEqual(confirm_here(self.bob, BILLIARDS), CONFIRM_RESULT_CONFIRMED)
        self.assertTrue(attempt_matchmaking(BILLIARDS))

    def test_your_turn_lets_you_leave_at_once(self):
        """Not wanting to play is allowed; it's quicker than running the clock out."""
        self.queue_a_while_ago(self.alice)
        join_queue(self.bob, BILLIARDS)
        attempt_matchmaking(BILLIARDS)

        status = get_queue_status(self.bob, BILLIARDS)

        self.assertLess(status["seconds_waiting"], LEAVE_UNLOCK_SECONDS)
        self.assertTrue(status["can_leave"])


class ReadyCheckRoutes(ApiTestCase):
    def queue_a_while_ago(self, user_id):
        join_queue(user_id, BILLIARDS)
        self.backdate_queue_join(user_id, A_WHILE)

    def setUp(self):
        super().setUp()
        self.make_king(self.alice)
        self.queue_a_while_ago(self.bob)
        attempt_matchmaking(BILLIARDS)
        self.login_as(self.bob)

    def test_status_says_its_your_turn(self):
        body = self.get("/match/status").get_json()

        self.assertEqual(
            set(body.keys()),
            {
                "status",
                "table_id",
                "table_name",
                "league_type",
                "league_id",
                "read_only",
                "confirmed",
                "seconds_left",
                "opponent",
                "opponent_id",
                "opponent_confirmed",
                "opponent_seconds_left",
            },
        )
        self.assertEqual(body["status"], "your_turn")

    def test_confirming_starts_the_game(self):
        res = self.post("/queue/confirm", json={"league_type": "billiards"})

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "confirmed")
        self.assertTrue(body["match_started"])
        self.assertIn("table", body["message"])
        self.assertEqual(self.get("/match/status").get_json()["status"], "playing")

    def test_before_your_turn_is_a_409(self):
        self.queue_a_while_ago(self.carol)
        self.login_as(self.carol)

        res = self.post("/queue/confirm", json={})

        self.assertEqual(res.status_code, 409)
        self.assertIn("isn't your turn", res.get_json()["message"])

    def test_not_queued_is_a_404(self):
        self.login_as(self.carol)
        res = self.post("/queue/confirm", json={})
        self.assertEqual(res.status_code, 404)
        self.assertIn("join again", res.get_json()["message"])

    def test_too_late_is_a_409_and_the_next_player_is_up(self):
        self.queue_a_while_ago(self.carol)
        self.backdate_turn(self.bob, TOO_LONG)

        res = self.post("/queue/confirm", json={})

        self.assertEqual(res.status_code, 409)
        self.assertIn(f"{READY_CHECK_SECONDS} seconds", res.get_json()["message"])
        self.login_as(self.carol)
        self.assertEqual(self.get("/match/status").get_json()["status"], "your_turn")

    def test_needs_a_login(self):
        self.login_as(None)
        self._headers = {}
        self.assertEqual(self.post("/queue/confirm", json={}).status_code, 401)

    def test_tapping_join_again_on_your_turn_says_youre_here(self):
        """How an app from before the ready check confirms: it shows Join."""
        res = self.post("/queue/join", json={})

        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["match_started"])
        self.assertEqual(self.active_match().player_two_id, self.bob)

    def test_tapping_join_after_missing_your_turn_puts_you_at_the_back(self):
        self.queue_a_while_ago(self.carol)
        self.backdate_turn(self.bob, TOO_LONG)

        res = self.post("/queue/join", json={})

        self.assertEqual(res.get_json()["status"], "joined")
        self.assertEqual(self.queued_user_ids(), [self.carol, self.bob])

    def test_leaving_on_your_turn_puts_the_next_player_up_straight_away(self):
        self.queue_a_while_ago(self.carol)

        res = self.post("/queue/leave", json={})

        self.assertEqual(res.status_code, 200)
        self.assertTrue(self.entry_for(self.carol).is_called)

    def test_the_queue_list_shows_whose_turn_it_is(self):
        queue = self.client.get("/queue/1").get_json()
        self.assertEqual(queue, [
            {"queue_position": 1, "user_id": self.bob, "username": "bob",
             "called": True, "confirmed": False, "table_id": 1, "table_name": "Table 1"},
        ])

    def entry_for(self, user_id):
        db.session.expire_all()
        return db.session.scalars(db.select(QueueEntry).where(QueueEntry.user_id == user_id)).first()


class StatusFallsBackSafely(ApiTestCase):
    def test_a_finished_match_does_not_leave_anyone_up(self):
        """After a game, the winner holds the table and the next player is asked."""
        from logic.record_match import record_match_result

        match = self.start_match(self.alice, self.bob)
        join_queue(self.carol, BILLIARDS)
        self.backdate_queue_join(self.carol, A_WHILE)

        record_match_result(match, self.alice, self.bob, 16)

        self.login_as(self.carol)
        body = self.get("/match/status").get_json()
        self.assertEqual(body["status"], "your_turn")
        self.assertEqual(body["opponent"], "alice")
        king = db.session.scalars(
            db.select(Match).where(Match.match_status == Match.STATUS_ACTIVE)
        ).one()
        self.assertIsNone(king.player_two_id)


if __name__ == "__main__":
    unittest.main()
