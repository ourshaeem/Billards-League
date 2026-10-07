"""
The champions across every school: the top 3 in each game this week,
this month and of all time, whichever league they play in - shown before
anyone has chosen a league.
"""
import unittest

from tests.conftest_base import PING_PONG_TABLE_ID, ApiTestCase, make_league
from tests.test_top_players import DAY, HOUR, WEDNESDAY_EVENING
from models import BILLIARDS, PING_PONG, Match, Player, PoolTable, Standing, db

from logic.global_leaderboard import global_leaderboard

JJ_TABLE = 30


class GlobalTestCase(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.dave = self.add_player("dave")
        self.erin = self.add_player("erin")
        jj = make_league("john-jay-billiards", "John Jay Billiards", BILLIARDS, school="John Jay", order=2)
        self.jj = jj.league_id
        db.session.add(PoolTable(table_id=JJ_TABLE, table_name="Table 1", league_id=jj.league_id, league_type=BILLIARDS))
        db.session.commit()

    def game(self, winner, loser, change, seconds_ago=HOUR, table_id=1, loser_change="same"):
        match = Match(
            table_id=table_id,
            player_one_id=winner,
            player_two_id=loser,
            winner_id=winner,
            loser_id=loser,
            elo_change=change,
            loser_elo_change=change if loser_change == "same" else loser_change,
            match_status=Match.STATUS_FINISHED,
        )
        db.session.add(match)
        db.session.commit()
        db.session.execute(
            db.text("UPDATE Matches SET played_at = datetime('now', :offset) WHERE match_id = :id"),
            {"offset": f"-{int(seconds_ago)} seconds", "id": match.match_id},
        )
        db.session.commit()

    def board(self):
        return global_leaderboard(now=WEDNESDAY_EVENING)["sports"]

    def names(self, places):
        return [place["player"]["username"] for place in places]


class ThisWeekAndThisMonth(GlobalTestCase):
    def test_points_gained_in_every_league_of_the_game_add_up(self):
        self.game(self.alice, self.bob, 10)  # CCNY
        self.game(self.alice, self.carol, 10, table_id=JJ_TABLE)  # John Jay
        self.game(self.dave, self.erin, 15)

        week = self.board()[BILLIARDS]["week"]

        self.assertEqual(self.names(week), ["alice", "dave"], "20 across two schools beats 15")
        self.assertEqual((week[0]["points"], week[0]["wins"], week[0]["losses"]), (20, 2, 0))

    def test_each_period_counts_only_its_own_games(self):
        self.game(self.alice, self.bob, 10, seconds_ago=HOUR)  # this week
        self.game(self.carol, self.dave, 30, seconds_ago=5 * DAY)  # this month, before Monday
        self.game(self.erin, self.alice, 50, seconds_ago=10 * DAY)  # last month

        board = self.board()[BILLIARDS]

        self.assertEqual(self.names(board["week"]), ["alice"])
        self.assertEqual(self.names(board["month"]), ["carol", "alice"])

    def test_only_three(self):
        for winner, loser, change in (
            (self.alice, self.bob, 40), (self.carol, self.bob, 30), (self.dave, self.bob, 20), (self.erin, self.bob, 10)
        ):
            self.game(winner, loser, change)

        self.assertEqual(self.names(self.board()[BILLIARDS]["week"]), ["alice", "carol", "dave"])

    def test_the_sports_are_kept_apart(self):
        self.game(self.alice, self.bob, 10)
        self.game(self.carol, self.dave, 12, table_id=PING_PONG_TABLE_ID)

        board = self.board()

        self.assertEqual(self.names(board[BILLIARDS]["week"]), ["alice"])
        self.assertEqual(self.names(board[PING_PONG]["week"]), ["carol"])

    def test_a_place_says_where_it_was_earned(self):
        self.game(self.alice, self.bob, 5)
        self.game(self.alice, self.carol, 25, table_id=JJ_TABLE)

        first = self.board()[BILLIARDS]["week"][0]

        self.assertEqual((first["league_name"], first["school"]), ("John Jay Billiards", "John Jay"))
        self.assertEqual(first["player"]["league_id"], self.jj)

    def test_a_win_is_needed_to_place(self):
        self.game(self.alice, self.bob, 10)

        self.assertNotIn("bob", self.names(self.board()[BILLIARDS]["week"]))

    def test_ties_go_to_more_wins_then_the_earlier_player(self):
        self.game(self.alice, self.dave, 10)
        self.game(self.alice, self.dave, 10)
        self.game(self.erin, self.alice, 10)  # alice: 10 points, 2-1
        self.game(self.bob, self.dave, 10)  # bob: 10 points, 1-0, joined before erin
        self.game(self.carol, self.dave, 20)

        week = self.board()[BILLIARDS]["week"]

        self.assertEqual(self.names(week), ["carol", "alice", "bob"])

    def test_deleted_accounts_are_left_out(self):
        self.game(self.alice, self.bob, 10)
        db.session.get(Player, self.alice).deleted_at = db.func.now()
        db.session.commit()

        self.assertEqual(self.board()[BILLIARDS]["week"], [])


class AllTime(GlobalTestCase):
    def test_the_best_rating_in_any_league_of_the_game(self):
        self.set_rating(self.alice, 900, wins=9, losses=1)
        self.set_rating(self.bob, 1100, wins=3, losses=3)
        db.session.add(Standing(user_id=self.carol, league_id=self.jj, elo=1300, wins=8, losses=0))
        self.set_rating(self.carol, 100, wins=1, losses=5)
        db.session.commit()

        all_time = self.board()[BILLIARDS]["all_time"]

        self.assertEqual(self.names(all_time), ["carol", "bob", "alice"])
        self.assertEqual((all_time[0]["elo"], all_time[0]["school"]), (1300, "John Jay"))
        self.assertEqual((all_time[0]["wins"], all_time[0]["losses"]), (8, 0))

    def test_only_players_who_have_played(self):
        # Everyone starts at 1200 in these fixtures, without a game.
        self.set_rating(self.alice, 300, wins=1, losses=0)

        self.assertEqual(self.names(self.board()[BILLIARDS]["all_time"]), ["alice"])


class GlobalRoute(GlobalTestCase):
    def test_public_and_shaped_for_the_apps(self):
        self.game(self.alice, self.bob, 10)
        self.set_rating(self.alice, 1210, wins=1, losses=0)

        res = self.client.get("/leaderboard/global")

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(set(body["sports"]), {BILLIARDS, PING_PONG})
        for sport in body["sports"].values():
            self.assertEqual(set(sport), {"week", "month", "all_time"})
        first = body["sports"][BILLIARDS]["all_time"][0]
        self.assertEqual(
            set(first),
            {"place", "player", "league_id", "league_name", "school", "elo", "wins", "losses"},
        )
        self.assertIn("profile_picture", first["player"])


if __name__ == "__main__":
    unittest.main()
