"""
Nobody's rating goes below 0. A loser who would drop under it stops at
it; the winner still gains the full amount, so beating a new player is
worth the same as ever. The game remembers what the loser really lost.
"""
import unittest

from tests.conftest_base import PING_PONG_TABLE_ID, ApiTestCase
from models import BILLIARDS, PING_PONG, Match, Player, Rank, db

from database import ensure_schema
from logic.corrections import void_finished_match
from logic.match_history import league_history, player_history
from logic.record_match import record_match_result


class FloorTestCase(ApiTestCase):
    def play(self, winner, loser, change, table_id=1, league=BILLIARDS):
        match = self.start_match(winner, loser, table_id=table_id)
        record_match_result(match, winner, loser, change, 8, 2, league=league)
        from logic.manage_queue import step_down

        step_down(winner)
        return match.match_id


class LosingAtTheBottom(FloorTestCase):
    def test_the_loser_stops_at_zero_and_the_winner_gains_it_all(self):
        self.set_rating(self.bob, 10)
        alice_before = self.rating(self.alice)

        game = self.play(self.alice, self.bob, change=32)

        self.assertEqual(self.rating(self.bob), 0)
        self.assertEqual(self.rating(self.alice), alice_before + 32)
        match = db.session.get(Match, game)
        self.assertEqual((match.elo_change, match.loser_elo_change), (32, 10))

    def test_at_zero_a_loss_costs_nothing(self):
        self.set_rating(self.bob, 0)
        self.play(self.alice, self.bob, change=16)
        self.assertEqual(self.rating(self.bob), 0)

    def test_an_ordinary_loss_is_unchanged(self):
        self.set_rating(self.bob, 500)
        game = self.play(self.alice, self.bob, change=16)
        self.assertEqual(self.rating(self.bob), 484)
        self.assertEqual(db.session.get(Match, game).loser_elo_change, 16)

    def test_ping_pong_too(self):
        self.set_rating(self.bob, 5, PING_PONG)
        self.play(self.alice, self.bob, change=40, table_id=PING_PONG_TABLE_ID, league=PING_PONG)
        self.assertEqual(self.rating(self.bob, PING_PONG), 0)


class SayingWhatWasLost(FloorTestCase):
    def test_the_history_says_what_the_loser_really_lost(self):
        self.set_rating(self.bob, 10)
        self.play(self.alice, self.bob, change=32)

        entry = league_history(BILLIARDS)[0]
        bobs = player_history(self.bob, BILLIARDS)[0]

        self.assertEqual((entry["elo_change"], entry["loser_elo_change"]), (32, 10))
        self.assertEqual((bobs["result"], bobs["loser_elo_change"]), ("lost", 10))

    def test_games_from_before_the_floor_lost_the_whole_change(self):
        game = self.play(self.alice, self.bob, change=16)
        db.session.get(Match, game).loser_elo_change = None
        db.session.commit()

        self.assertEqual(league_history(BILLIARDS)[0]["loser_elo_change"], 16)

    def test_reporting_a_loss_says_what_it_cost(self):
        # Close ratings, so the game is worth more than bob has.
        self.set_rating(self.alice, 0)
        self.set_rating(self.bob, 3)
        self.start_match(self.alice, self.bob)
        self.login_as(self.bob)

        body = self.post("/match/record", json={"my_balls": 2, "opp_balls": 8}).get_json()

        self.assertEqual(body["loser_elo_change"], 3)
        self.assertGreater(body["elo_change"], 3)


class TakingBackAGameAtTheBottom(FloorTestCase):
    def test_the_loser_gets_back_only_what_they_lost(self):
        self.set_rating(self.bob, 10)
        alice_before = self.rating(self.alice)
        game = self.play(self.alice, self.bob, change=32)

        void_finished_match(game)

        self.assertEqual(self.rating(self.bob), 10, "not 32")
        self.assertEqual(self.rating(self.alice), alice_before)

    def test_giving_back_points_stops_at_zero_too(self):
        self.set_rating(self.alice, 0)
        game = self.play(self.alice, self.bob, change=16)  # alice: 16
        self.set_rating(self.alice, 5)  # then lost most of it

        void_finished_match(game)

        self.assertEqual(self.rating(self.alice), 0)


class RatingsAlreadyBelowZero(FloorTestCase):
    def test_ensure_schema_raises_them_to_zero_with_the_rank_that_earns(self):
        self.set_rating(self.bob, -38, PING_PONG)
        self.set_rating(self.carol, -5)
        self.set_rating(self.alice, 12, PING_PONG)

        ensure_schema()

        self.assertEqual(self.rating(self.bob, PING_PONG), 0)
        self.assertEqual(self.rating(self.carol), 0)
        self.assertEqual(self.rating(self.alice, PING_PONG), 12, "left alone")
        floor_rank = Rank.for_elo(0)
        self.assertEqual(self.standing(self.bob, PING_PONG).rank_id, floor_rank.rank_id)

    def test_running_it_again_changes_nothing(self):
        self.set_rating(self.bob, -1)
        ensure_schema()
        ensure_schema()
        self.assertEqual(self.rating(self.bob), 0)


if __name__ == "__main__":
    unittest.main()
