"""
Recording a finished match.

Covers the things most likely to quietly corrupt the ladder: results
stored the wrong way round, ELO drifting, and the king handoff failing to
pull in the next challenger.
"""
import unittest

from tests.conftest_base import BaseTestCase
from models import Match, PoolTable, Player, db

from logic.manage_queue import join_queue
from logic.record_match import (
    calculate_elo_change,
    record_match_result,
    start_new_session,
)


class RecordMatchTests(BaseTestCase):
    def player(self, user_id):
        return db.session.get(Player, user_id)

    def finished_matches(self):
        return list(
            db.session.scalars(
                db.select(Match).where(Match.match_status == Match.STATUS_FINISHED)
            )
        )

    def test_winner_is_recorded_correctly_regardless_of_seat(self):
        """
        alice is player_one purely because she was first in the queue.
        If bob wins, the finished row must say bob - the seat must not
        decide the result. Getting this wrong was a real bug.
        """
        match = self.start_match(self.alice, self.bob)

        record_match_result(match, winner_id=self.bob, loser_id=self.alice, elo_change=20)

        finished = self.finished_matches()
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0].winner_id, self.bob)
        self.assertEqual(finished[0].player_one_id, self.alice, "seats are unchanged")
        self.assertEqual(finished[0].player_two_id, self.bob)

    def test_loser_is_derivable_from_the_row(self):
        match = self.start_match(self.alice, self.bob)
        record_match_result(match, winner_id=self.bob, loser_id=self.alice, elo_change=20)

        finished = self.finished_matches()[0]
        self.assertEqual(finished.loser_id_for(finished.winner_id), self.alice)

    def test_elo_and_win_loss_counts_update(self):
        match = self.start_match(self.alice, self.bob)

        record_match_result(match, winner_id=self.alice, loser_id=self.bob, elo_change=20)

        alice, bob = self.player(self.alice), self.player(self.bob)
        self.assertEqual(alice.elo_rating, 1220)
        self.assertEqual(bob.elo_rating, 1180)
        self.assertEqual(alice.total_wins, 1)
        self.assertEqual(alice.total_losses, 0)
        self.assertEqual(bob.total_wins, 0)
        self.assertEqual(bob.total_losses, 1)

    def test_elo_is_zero_sum(self):
        match = self.start_match(self.alice, self.bob)
        before = self.player(self.alice).elo_rating + self.player(self.bob).elo_rating

        record_match_result(match, winner_id=self.alice, loser_id=self.bob, elo_change=27)

        after = self.player(self.alice).elo_rating + self.player(self.bob).elo_rating
        self.assertEqual(before, after)

    def test_winner_becomes_king_when_queue_is_empty(self):
        match = self.start_match(self.alice, self.bob)

        record_match_result(match, winner_id=self.alice, loser_id=self.bob, elo_change=20)

        active = self.active_match()
        self.assertIsNotNone(active)
        self.assertEqual(active.player_one_id, self.alice)
        self.assertIsNone(active.player_two_id, "king has no challenger yet")
        self.assertIsNone(active.winner_id, "king hasn't won this one yet")

    def test_next_challenger_is_pulled_off_the_queue_automatically(self):
        match = self.start_match(self.alice, self.bob)
        join_queue(self.carol, 1)

        record_match_result(match, winner_id=self.alice, loser_id=self.bob, elo_change=20)

        active = self.active_match()
        self.assertEqual(active.player_one_id, self.alice, "alice stays on")
        self.assertEqual(active.player_two_id, self.carol, "carol is the challenger")
        self.assertEqual(self.queued_user_ids(), [], "carol left the queue")

    def test_rank_is_updated_from_elo(self):
        alice = self.player(self.alice)
        alice.elo_rating = 1290
        db.session.commit()

        match = self.start_match(self.alice, self.bob)
        record_match_result(match, winner_id=self.alice, loser_id=self.bob, elo_change=20)

        # 1290 + 20 = 1310, which crosses the Gold threshold (1300).
        self.assertEqual(self.player(self.alice).rank.rank_name, "Gold")

    def test_start_new_session_is_safe_when_nothing_to_do(self):
        self.assertFalse(start_new_session(1))

    def test_the_full_result_is_stored(self):
        """loser_id and the score used to be left empty on every row."""
        match = self.start_match(self.alice, self.bob)

        record_match_result(
            match, winner_id=self.bob, loser_id=self.alice, elo_change=16,
            winner_balls=8, loser_balls=3,
        )

        finished = self.finished_matches()[0]
        self.assertEqual(finished.loser_id, self.alice)
        self.assertEqual(finished.balls_for(self.bob), 8)
        self.assertEqual(finished.balls_for(self.alice), 3)
        self.assertEqual((finished.player_one_balls, finished.player_two_balls), (3, 8))

    def test_players_rated_zero_are_not_treated_as_unrated(self):
        """
        Everyone starts at 0. `elo_rating or DEFAULT` turned a real 0 into
        the default, so a new player's first win jumped them to 1216.
        """
        for user_id in (self.alice, self.bob):
            self.player(user_id).elo_rating = 0
        db.session.commit()

        match = self.start_match(self.alice, self.bob)
        change = calculate_elo_change(self.player(self.alice), self.player(self.bob))
        record_match_result(match, winner_id=self.alice, loser_id=self.bob, elo_change=change)

        self.assertEqual(change, 16)
        self.assertEqual(self.player(self.alice).elo_rating, 16)
        self.assertEqual(self.player(self.bob).elo_rating, -16)

    def test_dropping_below_every_tier_clears_the_rank(self):
        bob = self.player(self.bob)
        bob.elo_rating = 5
        bob.rank_id = 1  # Bronze, min 0
        db.session.commit()

        match = self.start_match(self.alice, self.bob)
        record_match_result(match, winner_id=self.alice, loser_id=self.bob, elo_change=20)

        self.assertIsNone(self.player(self.bob).rank_id, "-15 is below Bronze's 0")


class EloCalculationTests(BaseTestCase):
    def test_equal_ratings_split_the_k_factor(self):
        a = db.session.get(Player, self.alice)
        b = db.session.get(Player, self.bob)
        self.assertEqual(calculate_elo_change(a, b), 16)  # K=32, expected 0.5

    def test_beating_a_stronger_player_is_worth_more(self):
        underdog = db.session.get(Player, self.alice)
        favourite = db.session.get(Player, self.bob)
        favourite.elo_rating = 1600
        db.session.commit()

        upset = calculate_elo_change(underdog, favourite)
        expected = calculate_elo_change(favourite, underdog)

        self.assertGreater(upset, expected)

    def test_change_is_never_zero(self):
        """A heavily favoured win still has to register."""
        strong = db.session.get(Player, self.alice)
        weak = db.session.get(Player, self.bob)
        strong.elo_rating = 3000
        weak.elo_rating = 100
        db.session.commit()

        self.assertGreaterEqual(calculate_elo_change(strong, weak), 1)


class PoolTableCacheTests(BaseTestCase):
    """
    Pool_Tables.current_king_id and the streak columns are a display
    cache. These check it tracks reality - and, just as importantly, that
    matchmaking never depends on it.
    """

    def table(self, table_id=1):
        return db.session.get(PoolTable, table_id)

    def test_king_is_cached_after_a_win(self):
        match = self.start_match(self.alice, self.bob)
        record_match_result(match, winner_id=self.alice, loser_id=self.bob, elo_change=20)

        self.assertEqual(self.table().current_king_id, self.alice)
        self.assertEqual(self.table().current_streak, 1)

    def test_streak_grows_on_repeat_wins(self):
        first = self.start_match(self.alice, self.bob)
        record_match_result(first, winner_id=self.alice, loser_id=self.bob, elo_change=20)

        second = self.start_match(self.alice, self.carol)
        record_match_result(second, winner_id=self.alice, loser_id=self.carol, elo_change=20)

        self.assertEqual(self.table().current_streak, 2)
        self.assertEqual(self.table().table_record_streak, 2)

    def test_streak_resets_when_the_king_is_beaten(self):
        first = self.start_match(self.alice, self.bob)
        record_match_result(first, winner_id=self.alice, loser_id=self.bob, elo_change=20)

        second = self.start_match(self.alice, self.carol)
        record_match_result(second, winner_id=self.carol, loser_id=self.alice, elo_change=20)

        self.assertEqual(self.table().current_king_id, self.carol)
        self.assertEqual(self.table().current_streak, 1)
        self.assertEqual(self.table().table_record_streak, 1)

    def test_matchmaking_works_without_a_pool_table_row(self):
        """
        The cache is optional. A table with no Pool_Tables row must still
        run matches - otherwise the cache has quietly become a dependency.
        """
        match = self.start_match(self.alice, self.bob, table_id=99)
        record_match_result(match, winner_id=self.alice, loser_id=self.bob, elo_change=20)

        active = self.active_match(table_id=99)
        self.assertEqual(active.player_one_id, self.alice)


if __name__ == "__main__":
    unittest.main()
