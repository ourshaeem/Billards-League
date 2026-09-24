"""
Match history: the latest games in a league, and one player's games.

The feeds draw each player's avatar, flag and hover card straight from
these entries, so the entry shape is guarded like the other contracts.
"""
import unittest

from tests.conftest_base import PING_PONG_TABLE_ID, ApiTestCase
from models import BILLIARDS, PING_PONG, Match, Player, db

from logic.record_match import record_match_result

ENTRY_KEYS = {
    "match_id", "table_id", "league_type", "winner", "loser",
    "winner_score", "loser_score", "elo_change", "seconds_ago",
}
CARD_KEYS = {
    "user_id", "username", "country_flag", "profile_picture",
    "league_type", "elo", "rank_name", "wins", "losses",
}


class HistoryTestCase(ApiTestCase):
    def play(self, winner, loser, table_id=1, score=(8, 3), change=16):
        """
        A finished game, with the table cleared afterwards so the next
        game can start from scratch. The winner sits in seat two, so any
        entry that reads the score by seat rather than by result is caught.
        """
        league = PING_PONG if table_id == PING_PONG_TABLE_ID else BILLIARDS
        match = self.start_match(loser, winner, table_id=table_id)
        record_match_result(match, winner, loser, change, *score, league=league)
        db.session.execute(db.delete(Match).where(Match.match_status == Match.STATUS_ACTIVE))
        db.session.commit()
        return match.match_id

    def history(self, query=""):
        res = self.client.get(f"/matches/history{query}")
        self.assertEqual(res.status_code, 200, res.get_json())
        return res.get_json()["matches"]


class LeagueHistory(HistoryTestCase):
    def test_newest_first_with_both_players(self):
        first = self.play(self.alice, self.bob)
        second = self.play(self.carol, self.alice)

        matches = self.history("?league_type=billiards")

        self.assertEqual([m["match_id"] for m in matches], [second, first])
        self.assertEqual(set(matches[0].keys()), ENTRY_KEYS)
        self.assertEqual(set(matches[0]["winner"].keys()), CARD_KEYS)
        self.assertEqual(matches[0]["winner"]["username"], "carol")
        self.assertEqual(matches[0]["loser"]["username"], "alice")

    def test_scores_read_from_the_winners_side(self):
        self.play(self.alice, self.bob, score=(8, 3))

        entry = self.history()[0]

        self.assertEqual((entry["winner_score"], entry["loser_score"]), (8, 3))
        self.assertEqual(entry["elo_change"], 16)

    def test_leagues_are_kept_apart(self):
        billiards = self.play(self.alice, self.bob)
        ping_pong = self.play(self.bob, self.alice, table_id=PING_PONG_TABLE_ID, score=(11, 6))

        self.assertEqual([m["match_id"] for m in self.history("?league_type=billiards")], [billiards])
        self.assertEqual([m["match_id"] for m in self.history("?league_type=ping_pong")], [ping_pong])

    def test_no_league_means_billiards(self):
        billiards = self.play(self.alice, self.bob)
        self.play(self.bob, self.alice, table_id=PING_PONG_TABLE_ID, score=(11, 6))
        self.assertEqual([m["match_id"] for m in self.history()], [billiards])

    def test_cards_carry_the_current_rating_in_that_league(self):
        self.play(self.bob, self.alice, table_id=PING_PONG_TABLE_ID, score=(11, 6), change=20)

        winner = self.history("?league_type=ping_pong")[0]["winner"]

        bob = db.session.get(Player, self.bob)
        self.assertEqual(winner["elo"], bob.ping_pong_elo)
        self.assertEqual(winner["league_type"], PING_PONG)
        self.assertEqual((winner["wins"], winner["losses"]), (1, 0))

    def test_games_still_being_played_are_not_history(self):
        self.start_match(self.alice, self.bob)
        self.make_king(self.carol, table_id=PING_PONG_TABLE_ID)
        self.assertEqual(self.history(), [])
        self.assertEqual(self.history("?league_type=ping_pong"), [])

    def test_filtering_to_one_table(self):
        self.play(self.alice, self.bob)
        self.assertEqual(len(self.history("?table_id=1")), 1)
        self.assertEqual(self.history(f"?table_id={PING_PONG_TABLE_ID}"), [])

    def test_a_table_and_a_league_that_disagree(self):
        res = self.client.get("/matches/history?table_id=1&league_type=ping_pong")
        self.assertEqual(res.status_code, 400)

    def test_an_unknown_table(self):
        self.assertEqual(self.client.get("/matches/history?table_id=42").status_code, 404)

    def test_an_unknown_league(self):
        self.assertEqual(self.client.get("/matches/history?league_type=golf").status_code, 400)

    def test_limit(self):
        for _ in range(3):
            self.play(self.alice, self.bob)

        self.assertEqual(len(self.history("?limit=2")), 2)
        for bad in ("0", "51", "two", "1.5"):
            res = self.client.get(f"/matches/history?limit={bad}")
            self.assertEqual(res.status_code, 400, bad)

    def test_seconds_ago_is_measured_from_when_the_game_finished(self):
        """
        The row is created when the game is set up - for a king, possibly
        hours before a challenger arrives. The feed must show when it ended.
        """
        match = self.start_match(self.alice, self.bob)
        db.session.execute(
            db.text("UPDATE Matches SET played_at = datetime('now', '-3 hours') WHERE match_id = :m"),
            {"m": match.match_id},
        )
        db.session.commit()

        self.login_as(self.alice)
        self.post("/match/record", json={"my_balls": 8, "opp_balls": 1})

        seconds_ago = self.history()[0]["seconds_ago"]
        self.assertIsInstance(seconds_ago, int)
        self.assertLess(seconds_ago, 60)


class PlayerHistory(HistoryTestCase):
    def matches(self, user_id, query=""):
        res = self.client.get(f"/players/{user_id}/matches{query}")
        self.assertEqual(res.status_code, 200)
        return res.get_json()["matches"]

    def test_each_game_says_whether_they_won(self):
        won = self.play(self.alice, self.bob)
        lost = self.play(self.carol, self.alice)

        matches = self.matches(self.alice)

        self.assertEqual(
            [(m["match_id"], m["result"]) for m in matches], [(lost, "lost"), (won, "won")]
        )

    def test_only_their_own_games(self):
        self.play(self.bob, self.carol)
        self.assertEqual(self.matches(self.alice), [])

    def test_one_league_at_a_time(self):
        self.play(self.alice, self.bob)
        ping_pong = self.play(self.alice, self.bob, table_id=PING_PONG_TABLE_ID, score=(11, 2))

        matches = self.matches(self.alice, "?league_type=ping_pong")

        self.assertEqual([m["match_id"] for m in matches], [ping_pong])
        self.assertEqual(matches[0]["league_type"], PING_PONG)

    def test_an_unknown_player(self):
        res = self.client.get("/players/9999/matches")
        self.assertEqual(res.status_code, 404)
        self.assertIn("message", res.get_json())


if __name__ == "__main__":
    unittest.main()
