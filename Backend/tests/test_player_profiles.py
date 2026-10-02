"""
Looking at another player: their profile, their games, their record
against everyone they've played, and their games against you.
"""
import unittest

from tests.conftest_base import PING_PONG_TABLE_ID, ApiTestCase
from models import PING_PONG, Player, db

from logic.record_match import record_match_result


class PlayerProfileTestCase(ApiTestCase):
    def play(self, winner, loser, table_id=1, league=None, scores=(8, 3)):
        match = self.start_match(winner, loser, table_id=table_id)
        kwargs = {"league": league} if league else {}
        record_match_result(match, winner, loser, 10, *scores, **kwargs)
        # The winner stays on as king; clear the table for the next game.
        from logic.manage_queue import step_down

        step_down(winner)


class PublicProfile(PlayerProfileTestCase):
    def test_anyone_can_see_a_players_profile(self):
        player = db.session.get(Player, self.bob)
        player.country_flag = "CA"
        db.session.commit()

        res = self.client.get(f"/players/{self.bob}")

        self.assertEqual(res.status_code, 200)
        profile = res.get_json()["player"]
        self.assertEqual(profile["username"], "bob")
        self.assertEqual(profile["country_flag"], "CA")
        self.assertEqual(set(profile["leagues"]), {"billiards", "ping_pong"})
        self.assertEqual(
            set(profile["leagues"]["billiards"]), {"elo", "rank_name", "wins", "losses"}
        )

    def test_a_real_name_is_never_shown_to_other_people(self):
        profile = self.client.get(f"/players/{self.bob}").get_json()["player"]
        self.assertNotIn("first_name", profile)
        self.assertNotIn("last_name", profile)

    def test_an_unknown_player(self):
        res = self.client.get("/players/999")
        self.assertEqual(res.status_code, 404)
        self.assertIn("doesn't exist", res.get_json()["message"])

    def test_a_deleted_account_has_no_profile(self):
        from sqlalchemy import func

        db.session.get(Player, self.bob).deleted_at = func.now()
        db.session.commit()

        res = self.client.get(f"/players/{self.bob}")

        self.assertEqual(res.status_code, 404)
        self.assertIn("deleted their account", res.get_json()["message"])


class RecordAgainstEveryone(PlayerProfileTestCase):
    def setUp(self):
        super().setUp()
        self.play(self.alice, self.bob)
        self.play(self.alice, self.bob)
        self.play(self.bob, self.alice)
        self.play(self.carol, self.alice)

    def opponents(self, user_id, league=None):
        url = f"/players/{user_id}/opponents" + (f"?league_type={league}" if league else "")
        return self.client.get(url).get_json()["opponents"]

    def test_the_record_against_each_opponent_from_the_players_side(self):
        records = [
            (o["opponent"]["username"], o["wins"], o["losses"]) for o in self.opponents(self.alice)
        ]
        self.assertEqual(records, [("bob", 2, 1), ("carol", 0, 1)], "most games first")

    def test_the_same_games_from_the_other_side(self):
        self.assertEqual(
            [(o["opponent"]["username"], o["wins"], o["losses"]) for o in self.opponents(self.bob)],
            [("alice", 1, 2)],
        )

    def test_opponents_come_as_player_cards(self):
        card = self.opponents(self.alice)[0]["opponent"]
        self.assertEqual(
            set(card),
            {"user_id", "username", "country_flag", "profile_picture", "league_type",
             "elo", "rank_name", "wins", "losses"},
        )

    def test_each_league_is_its_own_record(self):
        self.play(self.bob, self.alice, table_id=PING_PONG_TABLE_ID, league=PING_PONG, scores=(11, 4))

        ping_pong = self.opponents(self.alice, "ping_pong")

        self.assertEqual([(o["opponent"]["username"], o["wins"], o["losses"]) for o in ping_pong],
                         [("bob", 0, 1)])
        self.assertEqual(ping_pong[0]["opponent"]["league_type"], "ping_pong")

    def test_nobody_played_yet(self):
        dave = self.add_player("dave")
        self.assertEqual(self.opponents(dave), [])

    def test_an_unknown_player_or_league(self):
        self.assertEqual(self.client.get("/players/999/opponents").status_code, 404)
        self.assertEqual(
            self.client.get(f"/players/{self.alice}/opponents?league_type=darts").status_code, 400
        )


class HeadToHead(PlayerProfileTestCase):
    def setUp(self):
        super().setUp()
        self.play(self.alice, self.bob)
        self.play(self.carol, self.alice)
        self.play(self.bob, self.alice)

    def games(self, user_id, query=""):
        return self.client.get(f"/players/{user_id}/matches?{query}")

    def test_only_the_games_between_the_two(self):
        res = self.games(self.alice, f"opponent_id={self.bob}")

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["opponent_id"], self.bob)
        pairs = {
            frozenset((m["winner"]["username"], m["loser"]["username"])) for m in body["matches"]
        }
        self.assertEqual(pairs, {frozenset(("alice", "bob"))})
        self.assertEqual([m["result"] for m in body["matches"]], ["lost", "won"], "newest first")

    def test_without_an_opponent_it_is_everything(self):
        self.assertEqual(len(self.games(self.alice).get_json()["matches"]), 3)

    def test_against_yourself_is_nothing(self):
        self.assertEqual(self.games(self.alice, f"opponent_id={self.alice}").get_json()["matches"], [])

    def test_an_opponent_id_that_is_not_a_player_id(self):
        for bad in ("bob", "0", "-3", "1.5"):
            res = self.games(self.alice, f"opponent_id={bad}")
            self.assertEqual(res.status_code, 400, bad)
            self.assertIn("opponent_id", res.get_json()["message"])


class LadderOpensProfiles(PlayerProfileTestCase):
    def test_each_ladder_row_says_who_it_is(self):
        rows = self.client.get("/leaderboard").get_json()
        by_name = {row["username"]: row for row in rows}
        self.assertEqual(by_name["bob"]["user_id"], self.bob)
        self.assertIn("country_flag", by_name["bob"])
        self.assertIn("profile_picture", by_name["bob"])


if __name__ == "__main__":
    unittest.main()
