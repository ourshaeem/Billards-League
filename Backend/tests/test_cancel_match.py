"""
Calling a game off when both players agree - and only then.

The case it's for: the challenger came off the queue, then found they
don't have time to finish. Without it, the only way out of a game was to
report a score that never happened.
"""
import unittest

from tests.conftest_base import ApiTestCase, BaseTestCase
from models import BILLIARDS, Match, Player, Standing, db

from logic.cancel_match import (
    CANCEL_RESULT_ALREADY_REQUESTED,
    CANCEL_RESULT_CANCELLED,
    CANCEL_RESULT_GAME_OVER,
    CANCEL_RESULT_NO_GAME,
    CANCEL_RESULT_NO_OPPONENT,
    CANCEL_RESULT_REQUESTED,
    KEEP_RESULT_GAME_OVER,
    KEEP_RESULT_KEPT,
    KEEP_RESULT_NOTHING_TO_KEEP,
    keep_playing,
    request_cancel,
)
from logic.manage_queue import get_player_status, join_queue
from logic.record_match import (
    REPORT_RESULT_ALREADY_REPORTED,
    record_match_result,
    report_result,
)


class CancelTestCase(BaseTestCase):
    def ratings(self):
        db.session.expire_all()
        return {
            (st.user_id, st.league_id): (st.elo, st.wins, st.losses)
            for st in db.session.scalars(db.select(Standing))
        }

    def finished_games(self):
        return db.session.scalar(
            db.select(db.func.count())
            .select_from(Match)
            .where(Match.match_status == Match.STATUS_FINISHED)
        )

    def king_with_challenger(self):
        """alice won the last game here and stayed on; carol came off the queue to play."""
        record_match_result(self.start_match(self.alice, self.bob), self.alice, self.bob, 16)
        join_queue(self.carol, BILLIARDS)
        from logic.manage_queue import attempt_matchmaking

        attempt_matchmaking(BILLIARDS)
        match = self.active_match()
        self.assertEqual((match.player_one_id, match.player_two_id), (self.alice, self.carol))
        return match


class AskingAndAgreeing(CancelTestCase):
    def test_one_player_asking_changes_nothing_yet(self):
        match = self.start_match(self.alice, self.bob)

        self.assertEqual(request_cancel(self.bob, match.match_id), CANCEL_RESULT_REQUESTED)

        self.assertEqual(self.active_match().match_id, match.match_id, "the game is still on")
        self.assertEqual(get_player_status(self.bob, BILLIARDS)["cancel_requested_by"], "you")
        self.assertEqual(get_player_status(self.alice, BILLIARDS)["cancel_requested_by"], "opponent")

    def test_both_agreeing_calls_the_game_off_with_nothing_recorded(self):
        match = self.start_match(self.alice, self.bob)
        before = self.ratings()

        request_cancel(self.bob, match.match_id)
        self.assertEqual(request_cancel(self.alice, match.match_id), CANCEL_RESULT_CANCELLED)

        self.assertEqual(self.ratings(), before, "nobody's rating or record moved")
        self.assertEqual(self.finished_games(), 0, "nothing in the history")
        self.assertIsNone(self.active_match())
        self.assertEqual(get_player_status(self.alice, BILLIARDS), {"status": "idle"})
        self.assertEqual(get_player_status(self.bob, BILLIARDS), {"status": "idle"})

    def test_asking_twice_is_not_agreeing(self):
        match = self.start_match(self.alice, self.bob)
        request_cancel(self.bob, match.match_id)

        self.assertEqual(request_cancel(self.bob, match.match_id), CANCEL_RESULT_ALREADY_REQUESTED)
        self.assertIsNotNone(self.active_match(), "one player can never cancel alone")

    def test_old_apps_that_send_no_match_id_still_work(self):
        self.start_match(self.alice, self.bob)
        request_cancel(self.bob)
        self.assertEqual(request_cancel(self.alice), CANCEL_RESULT_CANCELLED)


class WhatHappensToTheTable(CancelTestCase):
    def test_a_king_keeps_the_table_and_the_challenger_goes(self):
        match = self.king_with_challenger()

        request_cancel(self.carol, match.match_id)
        request_cancel(self.alice, match.match_id)

        king = self.active_match()
        self.assertEqual((king.player_one_id, king.player_two_id), (self.alice, None))
        self.assertNotEqual(king.match_id, match.match_id, "a fresh row, so old reports can't land on it")
        self.assertEqual(get_player_status(self.alice, BILLIARDS)["status"], "waiting_for_challenger")
        self.assertEqual(get_player_status(self.carol, BILLIARDS), {"status": "idle"})

    def test_the_next_in_line_is_up_against_the_king(self):
        match = self.king_with_challenger()
        dave = self.add_player("dave")
        join_queue(dave, BILLIARDS)

        request_cancel(self.alice, match.match_id)
        request_cancel(self.carol, match.match_id)

        self.assertEqual(self.active_match().player_two_id, dave, "dave only just joined, so plays at once")

    def test_two_players_off_the_queue_both_go_and_the_table_is_free(self):
        record_match_result(self.start_match(self.alice, self.bob), self.alice, self.bob, 16)
        from logic.manage_queue import step_down

        step_down(self.alice)  # alice goes home; bob and carol pair off the queue
        match = self.start_match(self.bob, self.carol)

        request_cancel(self.bob, match.match_id)
        request_cancel(self.carol, match.match_id)

        self.assertIsNone(self.active_match())

    def test_the_king_keeps_their_streak(self):
        from models import PoolTable

        match = self.king_with_challenger()
        streak = db.session.get(PoolTable, 1).current_streak

        request_cancel(self.alice, match.match_id)
        request_cancel(self.carol, match.match_id)

        db.session.expire_all()
        self.assertEqual(db.session.get(PoolTable, 1).current_streak, streak)

    def test_a_score_sent_for_the_cancelled_game_is_refused(self):
        match = self.king_with_challenger()
        request_cancel(self.alice, match.match_id)
        request_cancel(self.carol, match.match_id)

        outcome, _ = report_result(self.alice, 8, 2, expected_match_id=match.match_id)

        self.assertEqual(outcome, REPORT_RESULT_ALREADY_REPORTED)
        self.assertEqual(self.finished_games(), 1, "only the game alice really won")


class ChangingYourMind(CancelTestCase):
    def test_the_player_who_asked_can_take_it_back(self):
        match = self.start_match(self.alice, self.bob)
        request_cancel(self.bob, match.match_id)

        self.assertEqual(keep_playing(self.bob, match.match_id), KEEP_RESULT_KEPT)

        self.assertIsNone(get_player_status(self.bob, BILLIARDS)["cancel_requested_by"])
        self.assertEqual(request_cancel(self.alice, match.match_id), CANCEL_RESULT_REQUESTED,
                         "alice asking now is a new request, not agreement")

    def test_the_other_player_can_say_no(self):
        match = self.start_match(self.alice, self.bob)
        request_cancel(self.bob, match.match_id)

        self.assertEqual(keep_playing(self.alice, match.match_id), KEEP_RESULT_KEPT)
        self.assertIsNone(get_player_status(self.alice, BILLIARDS)["cancel_requested_by"])

    def test_nothing_to_take_back(self):
        match = self.start_match(self.alice, self.bob)
        self.assertEqual(keep_playing(self.alice, match.match_id), KEEP_RESULT_NOTHING_TO_KEEP)

    def test_reporting_the_score_ends_a_request_with_the_game(self):
        match = self.start_match(self.alice, self.bob)
        request_cancel(self.bob, match.match_id)

        report_result(self.alice, 8, 3, expected_match_id=match.match_id)

        self.assertEqual(keep_playing(self.bob, match.match_id), KEEP_RESULT_GAME_OVER)
        self.assertEqual(request_cancel(self.bob, match.match_id), CANCEL_RESULT_GAME_OVER)


class NothingToCancel(CancelTestCase):
    def test_no_game_at_all(self):
        self.assertEqual(request_cancel(self.alice), CANCEL_RESULT_NO_GAME)

    def test_a_king_alone_has_no_game_to_cancel(self):
        self.make_king(self.alice)
        self.assertEqual(request_cancel(self.alice), CANCEL_RESULT_NO_OPPONENT)

    def test_a_request_for_a_game_that_is_over_does_nothing(self):
        old = self.start_match(self.alice, self.bob)
        report_result(self.alice, 8, 3, expected_match_id=old.match_id)
        join_queue(self.carol, BILLIARDS)
        from logic.manage_queue import attempt_matchmaking

        attempt_matchmaking(BILLIARDS)

        self.assertEqual(request_cancel(self.alice, old.match_id), CANCEL_RESULT_GAME_OVER)
        self.assertIsNone(self.active_match().cancel_requested_by, "alice's new game is untouched")


class CancelRoutes(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.match = self.start_match(self.alice, self.bob)

    def test_ask_then_agree(self):
        self.login_as(self.bob)
        asked = self.post("/match/cancel", json={"match_id": self.match.match_id})
        self.assertEqual(asked.status_code, 200)
        self.assertEqual(asked.get_json()["status"], "requested")
        self.assertIn("once your opponent agrees", asked.get_json()["message"])

        self.login_as(self.alice)
        self.assertEqual(self.get("/match/status").get_json()["cancel_requested_by"], "opponent")
        agreed = self.post("/match/cancel", json={"match_id": self.match.match_id})

        self.assertEqual(agreed.status_code, 200)
        self.assertEqual(agreed.get_json()["status"], "cancelled")
        self.assertEqual(self.get("/match/status").get_json()["status"], "idle")

    def test_keep_playing(self):
        self.login_as(self.bob)
        self.post("/match/cancel", json={"match_id": self.match.match_id})

        self.login_as(self.alice)
        res = self.post("/match/keep", json={"match_id": self.match.match_id})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "kept")
        self.assertIsNone(self.get("/match/status").get_json()["cancel_requested_by"])

    def test_no_game_is_a_404(self):
        self.login_as(self.carol)
        self.assertEqual(self.post("/match/cancel", json={}).status_code, 404)
        self.assertEqual(self.post("/match/keep", json={}).status_code, 404)

    def test_a_finished_game_is_a_409(self):
        self.login_as(self.alice)
        self.post("/match/record", json={"my_balls": 8, "opp_balls": 1, "match_id": self.match.match_id})

        res = self.post("/match/cancel", json={"match_id": self.match.match_id})

        self.assertEqual(res.status_code, 409)
        self.assertIn("already finished", res.get_json()["message"])

    def test_a_king_alone_is_a_409_that_says_what_to_do(self):
        self.login_as(self.alice)
        self.post("/match/record", json={"my_balls": 8, "opp_balls": 1, "match_id": self.match.match_id})

        res = self.post("/match/cancel", json={})

        self.assertEqual(res.status_code, 409)
        self.assertIn("give up the table", res.get_json()["message"])

    def test_a_match_id_that_is_not_a_number(self):
        self.login_as(self.alice)
        res = self.post("/match/cancel", json={"match_id": "soon"})
        self.assertEqual(res.status_code, 400)

    def test_needs_a_login(self):
        self.assertEqual(self.client.post("/match/cancel", json={}).status_code, 401)
        self.assertEqual(self.client.post("/match/keep", json={}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
