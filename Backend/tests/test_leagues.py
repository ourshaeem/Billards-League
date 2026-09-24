"""
The ping pong league.

What has to hold: a table belongs to one league; requests reach the right
table through league_type; a score is judged by the rules of the game's
own league, whatever the request claims; and ping pong results move ping
pong ratings without touching billiards ones.
"""
import unittest

from tests.conftest_base import PING_PONG_TABLE_ID, ApiTestCase, BaseTestCase
from models import BILLIARDS, PING_PONG, Match, Player, PoolTable, db

from logic.record_match import (
    PING_PONG_K_ESTABLISHED,
    PING_PONG_K_PROVISIONAL,
    PING_PONG_K_TOP,
    calculate_ping_pong_elo_change,
    ping_pong_k_factor,
    record_match_result,
    score_problem,
)
from logic.tables import default_table_for, league_for_table


class TableLeagueTests(BaseTestCase):
    def test_each_table_knows_its_league(self):
        self.assertEqual(league_for_table(1), BILLIARDS)
        self.assertEqual(league_for_table(PING_PONG_TABLE_ID), PING_PONG)

    def test_an_unregistered_table_counts_as_billiards(self):
        self.assertEqual(league_for_table(99), BILLIARDS)

    def test_each_league_has_a_default_table(self):
        self.assertEqual(default_table_for(BILLIARDS), 1)
        self.assertEqual(default_table_for(PING_PONG), PING_PONG_TABLE_ID)


class LeagueRouting(ApiTestCase):
    def test_leagues_lists_both_with_their_tables(self):
        res = self.client.get("/leagues")

        self.assertEqual(res.status_code, 200)
        leagues = {entry["league_type"]: entry for entry in res.get_json()["leagues"]}
        self.assertEqual(leagues[BILLIARDS]["table_id"], 1)
        self.assertEqual(leagues[PING_PONG]["table_id"], PING_PONG_TABLE_ID)
        self.assertEqual(leagues[PING_PONG]["name"], "Ping Pong League")

    def test_joining_by_league_uses_that_leagues_table(self):
        self.login_as(self.alice)

        res = self.post("/queue/join", json={"league_type": "ping_pong"})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.queued_user_ids(PING_PONG_TABLE_ID), [self.alice])
        self.assertEqual(self.queued_user_ids(1), [], "nobody joined the pool table")

    def test_two_ping_pong_players_are_matched_at_the_ping_pong_table(self):
        """The same king-of-the-hill matchmaking, on the other league's table."""
        for player in (self.alice, self.bob):
            self.login_as(player)
            res = self.post("/queue/join", json={"league_type": "ping_pong"})

        self.assertTrue(res.get_json()["match_started"])
        match = self.active_match(PING_PONG_TABLE_ID)
        self.assertEqual({match.player_one_id, match.player_two_id}, {self.alice, self.bob})
        self.assertIsNone(self.active_match(1))

    def test_league_and_table_must_agree(self):
        self.login_as(self.alice)

        res = self.post("/queue/join", json={"table_id": 1, "league_type": "ping_pong"})

        self.assertEqual(res.status_code, 400)
        self.assertIn("Billiards League", res.get_json()["message"])
        self.assertEqual(self.queued_user_ids(1), [])

    def test_an_unknown_league_is_refused(self):
        self.login_as(self.alice)
        res = self.post("/queue/join", json={"league_type": "darts"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("league_type", res.get_json()["message"])

    def test_league_names_are_forgiving_about_case_and_spaces(self):
        self.login_as(self.alice)
        res = self.post("/queue/join", json={"league_type": "  Ping_Pong "})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.queued_user_ids(PING_PONG_TABLE_ID), [self.alice])

    def test_a_league_with_no_table_says_so(self):
        db.session.delete(db.session.get(PoolTable, PING_PONG_TABLE_ID))
        db.session.commit()
        self.login_as(self.alice)

        res = self.post("/queue/join", json={"league_type": "ping_pong"})

        self.assertEqual(res.status_code, 404)
        self.assertIn("doesn't have a table", res.get_json()["message"])

    def test_status_is_per_league(self):
        self.login_as(self.alice)
        self.post("/queue/join", json={"league_type": "ping_pong"})

        ping_pong = self.get("/match/status?league_type=ping_pong").get_json()
        billiards = self.get("/match/status?league_type=billiards").get_json()

        self.assertEqual(ping_pong["status"], "queued")
        self.assertEqual(ping_pong["league_type"], PING_PONG)
        self.assertEqual(billiards, {"status": "idle"})

    def test_status_names_the_league_of_the_game_wherever_you_look(self):
        """Mid-game in ping pong, looking at billiards: still told it's ping pong."""
        self.start_match(self.alice, self.bob, table_id=PING_PONG_TABLE_ID)
        self.login_as(self.alice)

        body = self.get("/match/status?league_type=billiards").get_json()

        self.assertEqual(body["status"], "playing")
        self.assertEqual(body["league_type"], PING_PONG)
        self.assertEqual(body["table_id"], PING_PONG_TABLE_ID)

    def test_leaving_by_league(self):
        self.login_as(self.alice)
        self.post("/queue/join", json={"league_type": "ping_pong"})
        self.backdate_queue_join(self.alice, 60, table_id=PING_PONG_TABLE_ID)

        res = self.post("/queue/leave", json={"league_type": "ping_pong"})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.queued_user_ids(PING_PONG_TABLE_ID), [])


class PingPongRecording(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.match = self.start_match(self.alice, self.bob, table_id=PING_PONG_TABLE_ID)
        self.login_as(self.bob)

    def player(self, user_id):
        db.session.expire_all()
        return db.session.get(Player, user_id)

    def report(self, mine, theirs, **extra):
        return self.post("/match/record", json={"my_balls": mine, "opp_balls": theirs, **extra})

    def test_a_win_moves_ping_pong_ratings_and_leaves_billiards_alone(self):
        res = self.report(11, 7, league_type="ping_pong", match_id=self.match.match_id)

        self.assertEqual(res.status_code, 200)
        change = res.get_json()["elo_change"]
        bob, alice = self.player(self.bob), self.player(self.alice)
        self.assertEqual(bob.ping_pong_elo, 1200 + change)
        self.assertEqual(alice.ping_pong_elo, 1200 - change)
        self.assertEqual((bob.ping_pong_wins, alice.ping_pong_losses), (1, 1))
        self.assertEqual((bob.elo_rating, alice.elo_rating), (1200, 1200))
        self.assertEqual((bob.total_wins, alice.total_losses), (0, 0))

    def test_without_league_type_the_games_own_league_decides(self):
        """Old clients don't send league_type; a ping pong game is still ping pong."""
        res = self.report(11, 5)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.player(self.bob).ping_pong_wins, 1)
        self.assertEqual(self.player(self.bob).total_wins, 0)

    def test_a_billiards_score_is_refused_for_a_ping_pong_game(self):
        res = self.report(8, 3)

        self.assertEqual(res.status_code, 400)
        self.assertIn("11", res.get_json()["message"])
        self.assertTrue(self.active_match(PING_PONG_TABLE_ID).is_in_progress, "nothing recorded")

    def test_claiming_the_wrong_league_records_nothing(self):
        res = self.report(8, 3, league_type="billiards")

        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()["league_type"], PING_PONG)
        self.assertIn("Ping Pong League", res.get_json()["message"])
        self.assertTrue(self.active_match(PING_PONG_TABLE_ID).is_in_progress)

    def test_a_deuce_game_is_accepted(self):
        self.assertEqual(self.report(10, 12).status_code, 200)
        self.assertEqual(self.player(self.alice).ping_pong_wins, 1)

    def test_the_winner_holds_the_ping_pong_table(self):
        self.report(11, 4)

        king = self.active_match(PING_PONG_TABLE_ID)
        self.assertEqual(king.player_one_id, self.bob)
        self.assertTrue(king.is_awaiting_challenger)
        self.assertIsNone(self.active_match(1), "the pool table is untouched")

    def test_the_ping_pong_rank_follows_the_ping_pong_rating(self):
        bob = self.player(self.bob)
        bob.ping_pong_elo = 1290
        db.session.commit()

        self.report(11, 0)

        bob = self.player(self.bob)
        self.assertEqual(bob.ping_pong_rank.rank_name, "Gold", "1290 + at least 10 crosses 1300")
        self.assertIsNone(bob.rank_id, "the billiards rank isn't recalculated")

    def test_ratings_stay_zero_sum(self):
        before = self.player(self.alice).ping_pong_elo + self.player(self.bob).ping_pong_elo
        self.report(11, 3)
        after = self.player(self.alice).ping_pong_elo + self.player(self.bob).ping_pong_elo
        self.assertEqual(before, after)


class BilliardsStillBilliards(ApiTestCase):
    def test_a_ping_pong_score_is_refused_for_a_billiards_game(self):
        self.start_match(self.alice, self.bob)
        self.login_as(self.bob)

        res = self.post("/match/record", json={"my_balls": 11, "opp_balls": 7})

        self.assertEqual(res.status_code, 400)
        self.assertIn("8", res.get_json()["message"])

    def test_a_billiards_result_leaves_ping_pong_alone(self):
        match = self.start_match(self.alice, self.bob)
        record_match_result(match, self.alice, self.bob, 16, 8, 2)

        alice = db.session.get(Player, self.alice)
        self.assertEqual(alice.elo_rating, 1216)
        self.assertEqual((alice.ping_pong_elo, alice.ping_pong_wins), (1200, 0))


class PingPongScoreRules(unittest.TestCase):
    """One game to 11, won by two clear points."""

    def test_possible_scores(self):
        for mine, theirs in ((11, 0), (11, 9), (0, 11), (12, 10), (10, 12), (15, 13)):
            self.assertIsNone(score_problem(PING_PONG, mine, theirs), (mine, theirs))

    def test_impossible_scores(self):
        cases = {
            (11, 10): "two clear points",
            (13, 10): "two clear points",
            (10, 8): "at least 11",
            (12, 9): "reaches 11",
            (11, 11): "tie",
            (-1, 11): "between 0 and",
            (101, 99): "between 0 and",
        }
        for (mine, theirs), wording in cases.items():
            problem = score_problem(PING_PONG, mine, theirs)
            self.assertIsNotNone(problem, (mine, theirs))
            self.assertIn(wording, problem, (mine, theirs))

    def test_billiards_rules_are_unchanged(self):
        self.assertIsNone(score_problem(BILLIARDS, 8, 3))
        self.assertIn("tie", score_problem(BILLIARDS, 4, 4))
        self.assertIn("between 0 and 8", score_problem(BILLIARDS, 11, 7))


class PingPongEloTests(BaseTestCase):
    def player(self, user_id, rating=1000, games=0):
        player = db.session.get(Player, user_id)
        player.ping_pong_elo = rating
        player.ping_pong_wins = games
        db.session.commit()
        return player

    def test_k_factor_tiers(self):
        self.assertEqual(ping_pong_k_factor(self.player(self.alice, games=0)), PING_PONG_K_PROVISIONAL)
        self.assertEqual(ping_pong_k_factor(self.player(self.alice, games=10)), PING_PONG_K_ESTABLISHED)
        self.assertEqual(
            ping_pong_k_factor(self.player(self.alice, rating=1200, games=10)), PING_PONG_K_TOP
        )

    def test_new_players_evenly_matched_in_a_close_game(self):
        a, b = self.player(self.alice), self.player(self.bob)
        self.assertEqual(calculate_ping_pong_elo_change(a, b, 11, 9), 20)  # 40 x 0.5

    def test_a_blowout_moves_more_than_a_close_game(self):
        a, b = self.player(self.alice), self.player(self.bob)
        close = calculate_ping_pong_elo_change(a, b, 11, 9)
        shutout = calculate_ping_pong_elo_change(a, b, 11, 0)

        self.assertGreater(shutout, close)
        self.assertEqual(shutout, 30, "half as much again for an 11-0")

    def test_a_deuce_game_counts_as_close(self):
        a, b = self.player(self.alice), self.player(self.bob)
        self.assertEqual(
            calculate_ping_pong_elo_change(a, b, 14, 12),
            calculate_ping_pong_elo_change(a, b, 11, 9),
        )

    def test_established_players_move_less_and_top_players_least(self):
        a, b = self.player(self.alice, games=20), self.player(self.bob, games=20)
        self.assertEqual(calculate_ping_pong_elo_change(a, b, 11, 9), 12)  # 24 x 0.5

        a, b = self.player(self.alice, 1300, 20), self.player(self.bob, 1300, 20)
        self.assertEqual(calculate_ping_pong_elo_change(a, b, 11, 9), 8)  # 16 x 0.5

    def test_an_upset_is_worth_more(self):
        underdog = self.player(self.alice, rating=800, games=20)
        favourite = self.player(self.bob, rating=1100, games=20)

        upset = calculate_ping_pong_elo_change(underdog, favourite, 11, 9)
        expected = calculate_ping_pong_elo_change(favourite, underdog, 11, 9)

        self.assertGreater(upset, expected)

    def test_the_change_is_never_zero(self):
        strong = self.player(self.alice, rating=3000, games=50)
        weak = self.player(self.bob, rating=0, games=50)
        self.assertGreaterEqual(calculate_ping_pong_elo_change(strong, weak, 11, 9), 1)


class LeaderboardByLeague(ApiTestCase):
    def test_each_league_has_its_own_ladder(self):
        db.session.get(Player, self.carol).ping_pong_elo = 1500
        db.session.get(Player, self.alice).elo_rating = 1500
        db.session.commit()

        ping_pong = self.client.get("/leaderboard?league_type=ping_pong").get_json()
        billiards = self.client.get("/leaderboard?league_type=billiards").get_json()

        self.assertEqual(ping_pong[0]["username"], "carol")
        self.assertEqual(ping_pong[0]["elo_rating"], 1500)
        self.assertEqual(billiards[0]["username"], "alice")
        self.assertEqual(
            set(ping_pong[0].keys()),
            {"username", "elo_rating", "total_wins", "total_losses", "rank_name"},
            "the ladder has the same shape in both leagues",
        )

    def test_no_league_means_billiards(self):
        db.session.get(Player, self.alice).elo_rating = 1500
        db.session.commit()
        self.assertEqual(self.client.get("/leaderboard").get_json()[0]["username"], "alice")

    def test_an_unknown_league_is_refused(self):
        self.assertEqual(self.client.get("/leaderboard?league_type=chess").status_code, 400)


class TableSnapshotRoute(ApiTestCase):
    def snapshot(self, table_id):
        res = self.client.get(f"/table/{table_id}")
        self.assertEqual(res.status_code, 200)
        return res.get_json()["table"]

    def test_a_free_table(self):
        table = self.snapshot(1)
        self.assertEqual(table["state"], "free")
        self.assertIsNone(table["king"])
        self.assertEqual(table["league_type"], BILLIARDS)

    def test_a_game_in_progress_shows_both_players_with_their_league_numbers(self):
        db.session.get(Player, self.alice).ping_pong_elo = 1350
        db.session.commit()
        self.start_match(self.alice, self.bob, table_id=PING_PONG_TABLE_ID)

        table = self.snapshot(PING_PONG_TABLE_ID)

        self.assertEqual(table["state"], "playing")
        self.assertEqual(table["king"]["username"], "alice")
        self.assertEqual(table["king"]["elo"], 1350, "the ping pong rating, not billiards")
        self.assertEqual(table["challenger"]["username"], "bob")
        self.assertEqual(
            set(table["king"].keys()),
            {
                "user_id", "username", "country_flag", "profile_picture",
                "league_type", "elo", "rank_name", "wins", "losses",
            },
        )

    def test_a_king_waiting_with_a_streak(self):
        table = db.session.get(PoolTable, 1)
        table.current_king_id, table.current_streak = self.alice, 3
        self.make_king(self.alice)

        snapshot = self.snapshot(1)

        self.assertEqual(snapshot["state"], "waiting_for_challenger")
        self.assertIsNone(snapshot["challenger"])
        self.assertEqual(snapshot["king_streak"], 3)

    def test_a_stale_streak_is_not_shown(self):
        """The cache still names bob, but alice holds the table."""
        table = db.session.get(PoolTable, 1)
        table.current_king_id, table.current_streak = self.bob, 5
        self.make_king(self.alice)

        self.assertEqual(self.snapshot(1)["king_streak"], 0)

    def test_an_unknown_table(self):
        res = self.client.get("/table/42")
        self.assertEqual(res.status_code, 404)
        self.assertIn("message", res.get_json())


if __name__ == "__main__":
    unittest.main()
