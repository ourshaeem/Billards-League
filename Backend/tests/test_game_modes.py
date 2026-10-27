"""
8-ball, 9-ball and 10-ball: three games in every billiards league, each
with its own rating and ladder.

What it's for: players say which game it was when they report the score.
Points won at 8-ball never move a 9-ball or 10-ball rating, or the other
way round, and each game has a ladder of its own. Apps from before modes
send none, which is 8-ball - the game every rating so far was for.
"""
import unittest

from tests.conftest_base import PING_PONG_TABLE_ID, ApiTestCase
from tests.test_top_players import HOUR, WEDNESDAY_EVENING
from models import BILLIARDS, NINE_BALL, PING_PONG, STANDARD, TEN_BALL, Match, PlayerAchievement, Standing, db

from logic.corrections import void_finished_match
from logic.global_leaderboard import global_leaderboard
from logic.seasons import reset_league_standings
from logic.top_players import top_players


class GameModesTestCase(ApiTestCase):
    def report(self, winner, loser, mine=8, theirs=3, mode=None, table_id=1, league_id=None):
        """winner reports their win over loser, as the apps do."""
        match = self.start_match(winner, loser, table_id=table_id)
        self.login_as(winner)
        body = {
            "my_balls": mine,
            "opp_balls": theirs,
            "match_id": match.match_id,
            "league_id": league_id or self.billiards_league_id,
        }
        if mode is not None:
            body["mode"] = mode
        return self.post("/match/record", json=body)

    def numbers(self, user_id, mode=STANDARD, league=BILLIARDS):
        """(rating, wins, losses) at one mode, or None with no standing there."""
        db.session.expire_all()
        standing = db.session.get(Standing, (user_id, self.league_id(league), mode))
        return None if standing is None else (standing.elo, standing.wins, standing.losses)

    def finish_old_king(self):
        # Every report leaves its winner holding Table 1; clear it so the
        # next game in a test can start there.
        db.session.execute(db.delete(Match).where(Match.match_status == Match.STATUS_ACTIVE))
        db.session.commit()


class EachGameItsOwnRating(GameModesTestCase):
    def test_a_nine_ball_game_moves_only_nine_ball_numbers(self):
        before = self.numbers(self.alice), self.numbers(self.bob)

        res = self.report(self.alice, self.bob, 9, 4, mode=NINE_BALL)

        self.assertEqual(res.status_code, 200, res.get_json())
        change = res.get_json()["elo_change"]
        self.assertEqual((self.numbers(self.alice), self.numbers(self.bob)), before, "8-ball untouched")
        self.assertEqual(self.numbers(self.alice, NINE_BALL), (change, 1, 0))
        self.assertEqual(self.numbers(self.bob, NINE_BALL), (0, 0, 1))
        self.assertIsNone(self.numbers(self.alice, TEN_BALL), "no 10-ball yet")

    def test_ten_ball_is_its_own_too(self):
        self.report(self.alice, self.bob, 9, 2, mode=NINE_BALL)
        self.finish_old_king()

        self.report(self.bob, self.alice, 10, 6, mode=TEN_BALL)

        self.assertEqual(self.numbers(self.alice, NINE_BALL)[1:], (1, 0), "her 9-ball record stands")
        self.assertEqual(self.numbers(self.bob, TEN_BALL)[1:], (1, 0))
        self.assertEqual(self.numbers(self.alice, TEN_BALL)[1:], (0, 1))

    def test_no_mode_is_eight_ball(self):
        """What every app from before modes sends."""
        rating = self.numbers(self.alice)[0]

        res = self.report(self.alice, self.bob, 8, 2)

        self.assertEqual(self.numbers(self.alice)[0], rating + res.get_json()["elo_change"])
        self.assertIsNone(self.numbers(self.alice, NINE_BALL))
        db.session.expire_all()
        self.assertEqual(db.session.scalars(db.select(Match.mode).where(Match.winner_id == self.alice)).one(), STANDARD)

    def test_the_game_remembers_its_mode(self):
        self.report(self.alice, self.bob, 9, 1, mode=NINE_BALL)

        entry = self.client.get(f"/matches/history?league_id={self.billiards_league_id}").get_json()["matches"][0]

        self.assertEqual(entry["mode"], NINE_BALL)
        self.assertEqual((entry["winner_score"], entry["loser_score"]), (9, 1))


class ScoresForEachGame(GameModesTestCase):
    def test_nine_ball_goes_to_nine(self):
        self.assertEqual(self.report(self.alice, self.bob, 9, 8, mode=NINE_BALL).status_code, 200)

    def test_but_no_further(self):
        res = self.report(self.alice, self.bob, 10, 2, mode=NINE_BALL)

        self.assertEqual(res.status_code, 400)
        self.assertIn("between 0 and 9", res.get_json()["message"])

    def test_ten_ball_goes_to_ten(self):
        self.assertEqual(self.report(self.alice, self.bob, 10, 0, mode=TEN_BALL).status_code, 200)

    def test_eight_ball_still_stops_at_eight(self):
        res = self.report(self.alice, self.bob, 9, 2)

        self.assertEqual(res.status_code, 400)
        self.assertIn("between 0 and 8", res.get_json()["message"])

    def test_a_tie_names_the_ball(self):
        res = self.report(self.alice, self.bob, 4, 4, mode=TEN_BALL)

        self.assertEqual(res.status_code, 400)
        self.assertIn("sank the 10", res.get_json()["message"])

    def test_ping_pong_has_no_nine_ball(self):
        res = self.report(
            self.alice, self.bob, 11, 5, mode=NINE_BALL,
            table_id=PING_PONG_TABLE_ID, league_id=self.ping_pong_league_id,
        )

        self.assertEqual(res.status_code, 400)
        self.assertIsNone(self.numbers(self.alice, NINE_BALL, PING_PONG))

    def test_an_unknown_mode_is_refused(self):
        res = self.report(self.alice, self.bob, 8, 2, mode="straight_pool")

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["field"], "mode")


class EachGameItsOwnLadder(GameModesTestCase):
    def ladder(self, mode=None, league_id=None):
        url = f"/leaderboard?league_id={league_id or self.billiards_league_id}"
        if mode:
            url += f"&mode={mode}"
        return self.client.get(url)

    def test_the_nine_ball_ladder_has_only_nine_ball_players(self):
        self.report(self.alice, self.bob, 9, 3, mode=NINE_BALL)

        rows = self.ladder(NINE_BALL).get_json()

        self.assertEqual([r["username"] for r in rows], ["alice", "bob"])
        self.assertEqual((rows[0]["total_wins"], rows[1]["total_losses"]), (1, 1))

    def test_without_a_mode_its_eight_ball(self):
        self.report(self.alice, self.bob, 9, 3, mode=NINE_BALL)

        rows = self.ladder().get_json()

        self.assertEqual({r["username"] for r in rows}, {"alice", "bob", "carol"})
        self.assertTrue(all(r["total_wins"] == 0 for r in rows), "the 9-ball win isn't on it")

    def test_a_ping_pong_ladder_has_no_modes(self):
        self.assertEqual(self.ladder(TEN_BALL, self.ping_pong_league_id).status_code, 400)

    def test_profiles_list_them_apart(self):
        self.report(self.alice, self.bob, 9, 3, mode=NINE_BALL)

        player = self.client.get(f"/players/{self.alice}").get_json()["player"]

        self.assertTrue(all("mode" not in st for st in player["standings"]), "8-ball as before")
        self.assertEqual(
            [(st["name"], st["mode"], st["mode_name"], st["wins"]) for st in player["mode_standings"]],
            [("CCNY Billiards", NINE_BALL, "9-ball", 1)],
        )


class OnlyEightBallElsewhere(GameModesTestCase):
    """The champions, the podium and the badges are 8-ball's (and ping pong's)."""

    def test_champions_and_podium_dont_count_nine_ball(self):
        self.report(self.alice, self.bob, 9, 3, mode=NINE_BALL)

        champions = global_leaderboard(now=WEDNESDAY_EVENING)["sports"][BILLIARDS]
        podium = top_players(BILLIARDS, now=WEDNESDAY_EVENING)

        self.assertEqual((champions["week"], champions["all_time"]), ([], []))
        self.assertIsNone(podium["day"])

    def test_badges_dont_count_nine_ball(self):
        self.report(self.alice, self.bob, 9, 3, mode=NINE_BALL)

        earned = set(
            db.session.scalars(
                db.select(PlayerAchievement.achievement_key).where(PlayerAchievement.user_id == self.alice)
            )
        )
        self.assertFalse({"first_break", "first_blood"} & earned, "her only game was 9-ball")


class TakingItBack(GameModesTestCase):
    def test_voiding_a_nine_ball_game_undoes_nine_ball_numbers(self):
        eight = self.numbers(self.alice)
        self.report(self.alice, self.bob, 9, 3, mode=NINE_BALL)
        game = db.session.scalars(db.select(Match.match_id).where(Match.mode == NINE_BALL)).one()

        result = void_finished_match(game)

        self.assertEqual(result["before"]["mode"], NINE_BALL)
        self.assertEqual(self.numbers(self.alice, NINE_BALL), (0, 0, 0))
        self.assertEqual(self.numbers(self.bob, NINE_BALL), (0, 0, 0))
        self.assertEqual(self.numbers(self.alice), eight)

    def test_a_season_reset_resets_every_mode(self):
        self.report(self.alice, self.bob, 9, 3, mode=NINE_BALL)

        reset_league_standings(BILLIARDS)

        self.assertEqual(self.numbers(self.alice, NINE_BALL), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
