"""
HTTP-level tests.

These matter more than usual for this refactor: they are what proves the
React app still works. Several assert the exact JSON keys, not just the
status code, because a renamed field would break the frontend while every
other test still passed.
"""
import unittest

from unittest import mock

from tests.conftest_base import ApiTestCase
from models import STARTING_ELO, Match, Player, PoolTable, QueueEntry, db

from logic.manage_queue import LEAVE_UNLOCK_SECONDS


class PublicRoutes(ApiTestCase):
    def test_health_check(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "healthy")

    def test_queue_view_is_public_and_empty_by_default(self):
        res = self.client.get("/queue/1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), [])

    def test_leaderboard_shape_is_unchanged(self):
        res = self.client.get("/leaderboard")
        self.assertEqual(res.status_code, 200)

        entry = res.get_json()[0]
        self.assertEqual(
            set(entry.keys()),
            {"username", "elo_rating", "total_wins", "total_losses", "rank_name"},
            "the React leaderboard table reads exactly these keys",
        )

    def test_unranked_players_still_appear(self):
        """Reproduces the old LEFT JOIN: no rank must not mean no row."""
        usernames = [p["username"] for p in self.client.get("/leaderboard").get_json()]
        self.assertIn("alice", usernames)
        self.assertEqual(
            self.client.get("/leaderboard").get_json()[0]["rank_name"], "Unranked"
        )

    def test_protected_routes_reject_missing_tokens(self):
        self.assertEqual(self.client.get("/match/status").status_code, 401)
        self.assertEqual(self.client.post("/queue/join").status_code, 401)

    def test_token_errors_use_the_message_key_like_everything_else(self):
        res = self.client.get("/match/status", headers={"Authorization": "Bearer nonsense"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("message", res.get_json())

    def test_unknown_routes_answer_in_json(self):
        res = self.client.get("/no-such-thing")
        self.assertEqual(res.status_code, 404)
        self.assertIn("message", res.get_json())


class JoinQueueRoute(ApiTestCase):
    def test_first_join_reports_waiting(self):
        self.login_as(self.alice)
        res = self.post("/queue/join", json={"table_id": 1})

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(
            set(body.keys()),
            {"message", "status", "match_started"},
            "App.jsx reads message, status and match_started",
        )
        self.assertFalse(body["match_started"])
        self.assertEqual(body["status"], "joined")

    def test_second_player_triggers_a_match(self):
        self.login_as(self.alice)
        self.post("/queue/join", json={"table_id": 1})

        self.login_as(self.bob)
        res = self.post("/queue/join", json={"table_id": 1})

        self.assertTrue(res.get_json()["match_started"])
        self.assertEqual(self.queued_user_ids(), [])

    def test_rejoining_says_already_queued_rather_than_failing(self):
        self.login_as(self.alice)
        self.post("/queue/join", json={"table_id": 1})
        res = self.post("/queue/join", json={"table_id": 1})

        self.assertEqual(res.status_code, 200, "a duplicate join is not an error")
        self.assertEqual(res.get_json()["status"], "already_queued")

    def test_joining_while_playing_is_rejected(self):
        self.start_match(self.alice, self.bob)
        self.login_as(self.alice)
        self.assertEqual(self.post("/queue/join", json={"table_id": 1}).status_code, 409)

    def test_join_with_no_body_defaults_to_table_one(self):
        """No Content-Type header must not produce a 415."""
        self.login_as(self.alice)
        res = self.post("/queue/join")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.queued_user_ids(1), [self.alice])

    def test_joining_matches_a_waiting_king(self):
        """The original bug, at the HTTP layer."""
        self.make_king(self.alice)
        self.login_as(self.bob)

        res = self.post("/queue/join", json={"table_id": 1})

        self.assertTrue(res.get_json()["match_started"])
        self.assertEqual(self.queued_user_ids(), [])


class ErrorsNeverLeakInternals(ApiTestCase):
    """
    The reported bug: a SQL error, statement and all, shown in a pop-up
    that couldn't be dismissed. Whatever breaks, a person gets a sentence.
    """

    SQL_ERROR = Exception(
        "(mysql.connector.errors.ProgrammingError) 1054 (42S22): Unknown column "
        "'Matches.player_one_id' in 'field list' [SQL: SELECT `Matches`.match_id ...]"
    )

    def assert_readable(self, res, status):
        self.assertEqual(res.status_code, status)
        message = res.get_json()["message"]
        for leak in ("SQL", "SELECT", "Unknown column", "mysql", "Error:"):
            self.assertNotIn(leak, message)
        self.assertLess(len(message), 200)

    def test_join(self):
        self.login_as(self.alice)
        with mock.patch("app.join_queue", side_effect=self.SQL_ERROR):
            self.assert_readable(self.post("/queue/join", json={"table_id": 1}), 500)

    def test_status(self):
        self.login_as(self.alice)
        with mock.patch("app.get_player_status", side_effect=self.SQL_ERROR):
            res = self.get("/match/status")
        self.assert_readable(res, 500)
        self.assertNotIn("status", res.get_json(), "a failure must not claim you're idle")

    def test_record(self):
        self.start_match(self.alice, self.bob)
        self.login_as(self.alice)
        with mock.patch("logic.record_match.record_match_result", side_effect=self.SQL_ERROR):
            self.assert_readable(
                self.post("/match/record", json={"my_balls": 8, "opp_balls": 2}), 500
            )

    def test_leaderboard(self):
        with mock.patch("app.top50_leaderboard", side_effect=self.SQL_ERROR):
            self.assert_readable(self.client.get("/leaderboard"), 500)

    def test_match_history(self):
        with mock.patch("app.league_history", side_effect=self.SQL_ERROR):
            self.assert_readable(self.client.get("/matches/history"), 500)
        with mock.patch("app.player_history", side_effect=self.SQL_ERROR):
            self.assert_readable(self.client.get(f"/players/{self.alice}/matches"), 500)

    def test_profile_update(self):
        self.login_as(self.alice)
        with mock.patch("app.update_profile", side_effect=self.SQL_ERROR):
            self.assert_readable(self.patch("/profile", json={"country_flag": "US"}), 500)

    def test_table_snapshot(self):
        with mock.patch("app.table_snapshot", side_effect=self.SQL_ERROR):
            self.assert_readable(self.client.get("/table/1"), 500)

    def test_a_join_whose_matchmaking_fails_still_counts_as_joined(self):
        """Matchmaking reruns on the next poll, so this isn't the player's problem."""
        self.login_as(self.alice)
        with mock.patch("app.attempt_matchmaking", side_effect=self.SQL_ERROR):
            res = self.post("/queue/join", json={"table_id": 1})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.queued_user_ids(), [self.alice])


class MalformedInput(ApiTestCase):
    """Found by the play-test bot: each of these used to be a 500."""

    def test_json_that_is_not_an_object_is_a_400_everywhere(self):
        self.start_match(self.alice, self.bob)
        self.login_as(self.alice)
        for body in (b"[1, 2, 3]", b'"hello"', b"42"):
            for path in ("/queue/join", "/queue/leave", "/match/record", "/login", "/register"):
                res = self.post(path, data=body, content_type="application/json")
                self.assertLess(res.status_code, 500, f"{path} with {body!r}")
                self.assertIn("message", res.get_json())
            res = self.patch("/profile", data=body, content_type="application/json")
            self.assertEqual(res.status_code, 400, f"/profile with {body!r}")
            self.assertIn("message", res.get_json())

    def test_league_type_that_is_not_text_is_a_400(self):
        self.login_as(self.alice)
        for league in (1, ["ping_pong"], {"a": 1}, True):
            res = self.post("/queue/join", json={"league_type": league})
            self.assertEqual(res.status_code, 400, league)
        self.assertEqual(self.queued_user_ids(), [])

    def test_register_with_numbers_instead_of_text(self):
        res = self.client.post(
            "/register",
            json={"username": 12345, "first_name": 1, "last_name": 2, "password": 123456},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("text", res.get_json()["message"])

    def test_login_with_numbers_instead_of_text(self):
        res = self.client.post("/login", json={"username": 12345, "password": 123456})
        self.assertEqual(res.status_code, 400)

    def test_too_long_fields_say_what_the_limit_is(self):
        cases = {
            "username": ("u" * 51, "50"),
            "first_name": ("f" * 51, "50"),
            "password": ("p" * 73, "72"),
        }
        for field, (value, limit) in cases.items():
            body = {"username": "dave", "first_name": "D", "last_name": "S", "password": "hunter22"}
            body[field] = value
            res = self.client.post("/register", json=body)
            self.assertEqual(res.status_code, 400, field)
            self.assertIn(limit, res.get_json()["message"], field)

    def test_login_with_an_overlong_password_is_just_wrong(self):
        self.client.post(
            "/register",
            json={"username": "dave", "first_name": "D", "last_name": "S", "password": "hunter22"},
        )
        res = self.client.post("/login", json={"username": "dave", "password": "p" * 100})
        self.assertEqual(res.status_code, 401)

    def test_fractional_and_boolean_scores_are_refused(self):
        self.start_match(self.alice, self.bob)
        self.login_as(self.alice)
        for mine, theirs in ((8.5, 2), (True, 0), ("8.0", 2), ([8], 2)):
            res = self.post("/match/record", json={"my_balls": mine, "opp_balls": theirs})
            self.assertEqual(res.status_code, 400, (mine, theirs))
        self.assertIsNotNone(self.active_match(), "nothing was recorded")

    def test_whole_number_floats_and_padded_strings_are_fine(self):
        self.start_match(self.alice, self.bob)
        self.login_as(self.alice)
        res = self.post("/match/record", json={"my_balls": 8.0, "opp_balls": " 3 "})
        self.assertEqual(res.status_code, 200)


class TableValidation(ApiTestCase):
    def test_joining_a_table_that_does_not_exist(self):
        self.login_as(self.alice)
        res = self.post("/queue/join", json={"table_id": 42})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.queued_user_ids(42), [])

    def test_table_id_that_is_not_a_number(self):
        self.login_as(self.alice)
        self.assertEqual(self.post("/queue/join", json={"table_id": "one"}).status_code, 400)


class StepDownRoute(ApiTestCase):
    def test_king_steps_down(self):
        self.make_king(self.alice)
        self.login_as(self.alice)

        res = self.post("/table/step-down")

        self.assertEqual(res.status_code, 200)
        self.assertIn("message", res.get_json())
        self.assertEqual(self.get("/match/status").get_json()["status"], "idle")

    def test_mid_game_is_refused(self):
        self.start_match(self.alice, self.bob)
        self.login_as(self.alice)
        self.assertEqual(self.post("/table/step-down").status_code, 409)

    def test_not_holding_a_table(self):
        self.login_as(self.alice)
        self.assertEqual(self.post("/table/step-down").status_code, 404)

    def test_former_king_can_queue_again(self):
        self.make_king(self.alice)
        self.login_as(self.alice)
        self.post("/table/step-down")

        self.assertEqual(self.post("/queue/join", json={"table_id": 1}).status_code, 200)


class LeaveQueueRoute(ApiTestCase):
    def test_cannot_leave_straight_away(self):
        self.login_as(self.alice)
        self.post("/queue/join", json={"table_id": 1})

        res = self.post("/queue/leave", json={"table_id": 1})

        self.assertEqual(res.status_code, 403)
        self.assertIn("leave_unlocks_in", res.get_json())
        self.assertEqual(self.queued_user_ids(), [self.alice])

    def test_can_leave_once_the_wait_has_passed(self):
        self.login_as(self.alice)
        self.post("/queue/join", json={"table_id": 1})
        self.backdate_queue_join(self.alice, LEAVE_UNLOCK_SECONDS + 5)

        res = self.post("/queue/leave", json={"table_id": 1})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.queued_user_ids(), [])

    def test_leaving_when_not_queued_is_a_404(self):
        self.login_as(self.alice)
        self.assertEqual(self.post("/queue/leave", json={"table_id": 1}).status_code, 404)

    def test_server_enforces_the_wait_even_if_the_button_is_bypassed(self):
        self.login_as(self.alice)
        self.post("/queue/join", json={"table_id": 1})

        for _ in range(3):
            self.assertEqual(
                self.post("/queue/leave", json={"table_id": 1}).status_code, 403
            )

        self.assertEqual(self.queued_user_ids(), [self.alice])


class MatchStatusRoute(ApiTestCase):
    def test_idle_when_nothing_is_happening(self):
        self.login_as(self.alice)
        self.assertEqual(self.get("/match/status").get_json()["status"], "idle")

    def test_queued_status_includes_the_leave_timer(self):
        self.login_as(self.alice)
        self.post("/queue/join", json={"table_id": 1})

        body = self.get("/match/status").get_json()

        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["queue_position"], 1)
        self.assertFalse(body["can_leave"])
        self.assertGreater(body["leave_unlocks_in"], 0)

    def test_playing_status_shape_is_unchanged(self):
        self.start_match(self.alice, self.bob)
        self.login_as(self.bob)

        body = self.get("/match/status").get_json()

        self.assertEqual(
            set(body.keys()),
            {"status", "opponent", "opponent_id", "match_id", "table_id", "league_type"},
            "StatusPanel.jsx reads exactly these keys",
        )
        self.assertEqual(body["status"], "playing")
        self.assertEqual(body["opponent"], "alice")
        self.assertEqual(body["opponent_id"], self.alice)
        self.assertEqual(body["league_type"], "billiards")

    def test_opponent_resolves_from_either_seat(self):
        """Whichever seat you're in, the opponent is the other player."""
        self.start_match(self.alice, self.bob)

        self.login_as(self.alice)
        self.assertEqual(self.get("/match/status").get_json()["opponent"], "bob")

        self.login_as(self.bob)
        self.assertEqual(self.get("/match/status").get_json()["opponent"], "alice")

    def test_king_is_reported_as_waiting_not_idle(self):
        self.make_king(self.alice)
        self.login_as(self.alice)

        self.assertEqual(
            self.get("/match/status").get_json()["status"], "waiting_for_challenger"
        )


class RecordMatchRoute(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.start_match(self.alice, self.bob)

    def test_recording_a_win(self):
        self.login_as(self.bob)
        res = self.post("/match/record", json={"my_balls": 8, "opp_balls": 3})

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(set(body.keys()), {"message", "elo_change", "winner_id"})
        self.assertEqual(body["winner_id"], self.bob)

    def test_losing_is_recorded_against_the_right_player(self):
        self.login_as(self.bob)
        self.post("/match/record", json={"my_balls": 2, "opp_balls": 8})

        finished = db.session.scalars(
            db.select(Match).where(Match.match_status == Match.STATUS_FINISHED)
        ).first()
        self.assertEqual(finished.winner_id, self.alice)

    def test_scores_sent_as_strings_are_accepted(self):
        self.login_as(self.bob)
        res = self.post("/match/record", json={"my_balls": "8", "opp_balls": "3"})
        self.assertEqual(res.status_code, 200)

    def test_missing_scores_are_rejected_cleanly(self):
        self.login_as(self.bob)
        self.assertEqual(self.post("/match/record", json={}).status_code, 400)

    def test_tied_scores_are_rejected(self):
        self.login_as(self.bob)
        res = self.post("/match/record", json={"my_balls": 4, "opp_balls": 4})
        self.assertEqual(res.status_code, 400)

    def test_out_of_range_scores_are_rejected(self):
        self.login_as(self.bob)
        res = self.post("/match/record", json={"my_balls": 99, "opp_balls": 0})
        self.assertEqual(res.status_code, 400)

    def test_both_players_reporting_records_the_game_once(self):
        """
        The loser reports, then the winner reports the same game. Without
        match_id the winner's report landed on their NEXT game - against
        carol, who'd just been pulled off the queue and hadn't played.
        """
        match_id = self.active_match().match_id
        join_queue_as = self.auth_headers(self.carol)
        self.client.post("/queue/join", json={"table_id": 1}, headers=join_queue_as)

        self.login_as(self.bob)
        first = self.post(
            "/match/record", json={"my_balls": 2, "opp_balls": 8, "match_id": match_id}
        )
        self.assertEqual(first.status_code, 200)

        self.login_as(self.alice)
        second = self.post(
            "/match/record", json={"my_balls": 8, "opp_balls": 2, "match_id": match_id}
        )
        self.assertEqual(second.status_code, 409)
        self.assertIn("already been reported", second.get_json()["message"])

        finished = db.session.scalars(
            db.select(Match).where(Match.match_status == Match.STATUS_FINISHED)
        ).all()
        self.assertEqual(len(finished), 1)
        live = self.active_match()
        self.assertEqual((live.player_one_id, live.player_two_id), (self.alice, self.carol))
        self.assertIsNone(live.winner_id, "alice vs carol hasn't been played")

    def test_match_id_must_be_a_number(self):
        self.login_as(self.bob)
        res = self.post("/match/record", json={"my_balls": 8, "opp_balls": 2, "match_id": "x"})
        self.assertEqual(res.status_code, 400)

    def test_score_is_saved_against_the_right_seats(self):
        self.login_as(self.bob)  # bob is player two
        self.post("/match/record", json={"my_balls": 8, "opp_balls": 3})

        finished = db.session.scalars(
            db.select(Match).where(Match.match_status == Match.STATUS_FINISHED)
        ).first()
        self.assertEqual(finished.balls_for(self.bob), 8)
        self.assertEqual(finished.balls_for(self.alice), 3)
        self.assertEqual(finished.loser_id, self.alice)

    def test_recording_with_no_opponent_is_rejected(self):
        db.session.execute(db.delete(Match))
        db.session.commit()
        self.make_king(self.alice)

        self.login_as(self.alice)
        res = self.post("/match/record", json={"my_balls": 8, "opp_balls": 0})
        self.assertEqual(res.status_code, 409)


class AuthRoutes(ApiTestCase):
    def test_register_requires_all_fields(self):
        self.assertEqual(self.client.post("/register", json={"username": "x"}).status_code, 400)

    def test_register_then_login(self):
        res = self.client.post(
            "/register",
            json={
                "username": "dave",
                "first_name": "Dave",
                "last_name": "Smith",
                "password": "hunter22",
            },
        )
        self.assertEqual(res.status_code, 201)

        res = self.client.post("/login", json={"username": "dave", "password": "hunter22"})
        self.assertEqual(res.status_code, 200)

        body = res.get_json()
        self.assertEqual(
            set(body.keys()),
            {"message", "access_token", "user_id", "username"},
            "App.jsx reads access_token, user_id and username",
        )

    def test_duplicate_username_says_so(self):
        payload = {
            "username": "dave",
            "first_name": "Dave",
            "last_name": "Smith",
            "password": "hunter22",
        }
        self.client.post("/register", json=payload)
        res = self.client.post("/register", json=payload)

        self.assertEqual(res.status_code, 400)
        self.assertIn("taken", res.get_json()["message"].lower())

    def test_short_password_is_rejected_with_a_reason(self):
        res = self.client.post(
            "/register",
            json={"username": "eve", "first_name": "E", "last_name": "V", "password": "123"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("password", res.get_json()["message"].lower())

    def test_wrong_password_is_rejected(self):
        self.client.post(
            "/register",
            json={
                "username": "dave",
                "first_name": "Dave",
                "last_name": "Smith",
                "password": "hunter22",
            },
        )
        res = self.client.post("/login", json={"username": "dave", "password": "wrong"})
        self.assertEqual(res.status_code, 401)

    def test_login_requires_credentials(self):
        self.assertEqual(self.client.post("/login", json={}).status_code, 400)

    def test_new_players_start_where_the_ladder_starts(self):
        self.client.post(
            "/register",
            json={"username": "dave", "first_name": "D", "last_name": "S", "password": "hunter22"},
        )
        dave = db.session.scalars(db.select(Player).where(Player.username == "dave")).one()

        self.assertEqual(dave.elo_rating, STARTING_ELO)
        self.assertEqual(dave.rank.rank_name, "Bronze", "the tier whose min_elo is 0")


class FullMatchFlow(ApiTestCase):
    """One end-to-end pass through the king-of-the-hill cycle."""

    def test_two_players_play_and_the_winner_holds_the_table(self):
        self.login_as(self.alice)
        self.post("/queue/join", json={"table_id": 1})

        self.login_as(self.bob)
        self.assertTrue(self.post("/queue/join", json={"table_id": 1}).get_json()["match_started"])

        # bob wins
        self.post("/match/record", json={"my_balls": 8, "opp_balls": 5})

        # bob now holds the table
        self.assertEqual(
            self.get("/match/status").get_json()["status"], "waiting_for_challenger"
        )

        # alice is idle and can queue again
        self.login_as(self.alice)
        self.assertEqual(self.get("/match/status").get_json()["status"], "idle")

        # carol challenges and is matched with bob immediately
        self.login_as(self.carol)
        self.assertTrue(self.post("/queue/join", json={"table_id": 1}).get_json()["match_started"])
        self.assertEqual(self.get("/match/status").get_json()["opponent"], "bob")


if __name__ == "__main__":
    unittest.main()
