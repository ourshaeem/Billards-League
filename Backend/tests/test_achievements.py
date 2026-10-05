"""
Achievements and badges.

Most tests build match history directly and run sync_achievements(),
which is exactly what happens after a real result and on startup. The
API tests at the bottom check the routes the React badge card uses.
"""
import unittest
from datetime import datetime, timedelta
from unittest import mock

from tests.conftest_base import BaseTestCase
from logic.achievements import (
    ACHIEVEMENTS,
    BY_KEY,
    GROUPS,
    PATIENCE_WAIT_SECONDS,
    player_badges,
    sync_achievements,
)
from logic.manage_queue import attempt_matchmaking, join_queue, step_down
from models import Match, Player, PlayerAchievement, QueueEntry, db

# A plain Tuesday afternoon, so time-of-day badges stay out of the way
# unless a test asks for them.
TUESDAY = datetime(2026, 3, 10, 15, 0)


class AchievementTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.clock = TUESDAY
        # Fresh players at the league's real starting rating.
        self.ann = self.add_player("ann", elo=0)
        self.ben = self.add_player("ben", elo=0)
        self.cat = self.add_player("cat", elo=0)

    def game(self, winner, loser, *, seat_one=None, score=(8, 3), change=16, when=None, table_id=1):
        """
        One finished game, stored the way record_match_result stores it:
        ratings moved, scores against the seats. seat_one is the king's
        seat; by default the winner sat there.
        """
        if when is None:
            self.clock += timedelta(minutes=20)
            when = self.clock
        seat_one = seat_one or winner
        seat_two = loser if seat_one == winner else winner
        winner_balls, loser_balls = score
        match = Match(
            table_id=table_id,
            player_one_id=seat_one,
            player_two_id=seat_two,
            winner_id=winner,
            loser_id=loser,
            player_one_balls=winner_balls if seat_one == winner else loser_balls,
            player_two_balls=loser_balls if seat_one == winner else winner_balls,
            match_status=Match.STATUS_FINISHED,
            elo_change=change,
            played_at=when,
        )
        db.session.add(match)
        db.session.get(Player, winner).elo_rating += change
        db.session.get(Player, loser).elo_rating -= change
        db.session.commit()
        return match

    def earned(self, user_id):
        sync_achievements()
        return set(
            db.session.scalars(
                db.select(PlayerAchievement.achievement_key).where(
                    PlayerAchievement.user_id == user_id
                )
            )
        )


class DefinitionTests(unittest.TestCase):
    def test_sixty_four_unique_badges(self):
        self.assertEqual(len(ACHIEVEMENTS), 64)
        self.assertEqual(len(BY_KEY), 64, "every key is unique")
        self.assertEqual(len({a.name for a in ACHIEVEMENTS}), 64, "every name is unique")

    def test_every_badge_is_in_a_known_group_and_tier(self):
        groups = {key for key, _ in GROUPS}
        for a in ACHIEVEMENTS:
            self.assertIn(a.group, groups, a.key)
            self.assertIn(a.tier, {"bronze", "silver", "gold", "legendary"}, a.key)

    def test_keys_fit_the_column(self):
        self.assertTrue(all(len(a.key) <= 40 for a in ACHIEVEMENTS))


class FirstGameTests(AchievementTestCase):
    def test_both_players_get_their_first_badges(self):
        self.game(self.ann, self.ben)

        self.assertTrue({"first_break", "first_blood", "welcome_committee"} <= self.earned(self.ann))
        self.assertTrue({"first_break", "learning_curve", "welcome_committee"} <= self.earned(self.ben))
        self.assertNotIn("first_blood", self.earned(self.ben))

    def test_nothing_before_any_game(self):
        self.assertEqual(self.earned(self.ann), set())


class StreakTests(AchievementTestCase):
    def test_hat_trick_needs_three_in_a_row(self):
        self.game(self.ann, self.ben)
        self.game(self.ann, self.cat)
        self.assertNotIn("hat_trick", self.earned(self.ann))

        self.game(self.ann, self.ben)
        self.assertIn("hat_trick", self.earned(self.ann))

    def test_a_loss_breaks_the_streak(self):
        self.game(self.ann, self.ben)
        self.game(self.ann, self.cat)
        self.game(self.ben, self.ann)
        self.game(self.ann, self.ben)
        self.assertNotIn("hat_trick", self.earned(self.ann))
        self.assertIn("bounce_back", self.earned(self.ann))

    def test_phoenix_rises_after_five_losses(self):
        for _ in range(5):
            self.game(self.ben, self.ann)
        self.game(self.ann, self.ben)
        self.assertIn("phoenix", self.earned(self.ann))


class ScorelineTests(AchievementTestCase):
    def test_shutout_nail_biter_and_so_close(self):
        self.game(self.ann, self.ben, score=(8, 0))
        self.game(self.ann, self.cat, score=(8, 7))

        self.assertTrue({"shutout", "nail_biter"} <= self.earned(self.ann))
        self.assertIn("so_close", self.earned(self.cat))
        self.assertNotIn("so_close", self.earned(self.ben))

    def test_games_without_a_score_still_count(self):
        """Old rows have no score; they mustn't crash the replay."""
        self.game(self.ann, self.ben, score=(None, None))
        self.assertIn("first_blood", self.earned(self.ann))


class KingOfTheHillTests(AchievementTestCase):
    def test_kingslayer_ends_a_three_game_reign(self):
        self.game(self.ann, self.ben)  # ann takes the table
        self.game(self.ann, self.cat)
        self.game(self.ann, self.ben)  # three in a row
        self.game(self.cat, self.ann, seat_one=self.ann)

        cat = self.earned(self.cat)
        self.assertTrue({"crowned", "kingslayer"} <= cat)
        self.assertNotIn("tyrant_toppler", cat)

    def test_beating_a_fresh_pairing_is_not_dethroning(self):
        """The first player off the queue sits in seat one but isn't king."""
        self.game(self.ben, self.ann, seat_one=self.ann)
        self.assertNotIn("crowned", self.earned(self.ben))

    def test_record_breaker_at_three(self):
        self.game(self.ann, self.ben)
        self.game(self.ann, self.cat)
        self.assertNotIn("record_breaker", self.earned(self.ann))
        self.game(self.ann, self.ben)
        self.assertIn("record_breaker", self.earned(self.ann))


class RatingTests(AchievementTestCase):
    def test_giant_killer_uses_the_rating_at_the_time(self):
        strong = self.add_player("strong", elo=150)
        self.game(self.ann, strong, change=24)

        self.assertIn("giant_killer", self.earned(self.ann))
        self.assertNotIn("david_vs_goliath", self.earned(self.ann), "150 above isn't 250")

    def test_big_payday_needs_twenty_five(self):
        self.game(self.ann, self.ben, change=24)
        self.assertNotIn("big_payday", self.earned(self.ann))
        self.game(self.ann, self.cat, change=25)
        self.assertIn("big_payday", self.earned(self.ann))

    def test_in_the_black_after_going_negative(self):
        self.game(self.ben, self.ann, change=10)  # ann -10
        self.game(self.ann, self.ben, change=10)  # back to 0
        self.assertIn("in_the_black", self.earned(self.ann))

    def test_rank_badges_follow_the_ranks_table(self):
        # Seeded tiers: Silver 1100, Gold 1300, Platinum 1500.
        self.game(self.ann, self.ben, change=1100)
        earned = self.earned(self.ann)
        self.assertIn("rank_silver", earned)
        self.assertNotIn("rank_gold", earned)

    def test_starting_ratings_are_worked_back_from_today(self):
        """A player who started at 1200 (the old default) isn't treated as 0."""
        veteran = self.add_player("veteran", elo=1200)
        self.game(veteran, self.ann)
        self.assertIn("rank_silver", self.earned(veteran))
        self.assertNotIn("giant_killer", self.earned(veteran))


class RivalryTests(AchievementTestCase):
    def test_revenge(self):
        self.game(self.ben, self.ann)
        self.game(self.ann, self.ben)
        self.assertIn("revenge", self.earned(self.ann))

    def test_deja_vu_is_three_in_a_row_against_one_opponent(self):
        self.game(self.ann, self.ben)
        self.game(self.ben, self.ann)
        self.assertNotIn("deja_vu", self.earned(self.ann))
        self.game(self.ann, self.ben)
        self.assertIn("deja_vu", self.earned(self.ann))


class TimeTests(AchievementTestCase):
    def test_night_owl_and_early_bird(self):
        self.game(self.ann, self.ben, when=datetime(2026, 3, 11, 2, 30))
        self.game(self.ann, self.ben, when=datetime(2026, 3, 11, 7, 0))
        earned = self.earned(self.ann)
        self.assertTrue({"night_owl", "early_bird"} <= earned)

    def test_holidays(self):
        self.game(self.ann, self.ben, when=datetime(2026, 10, 31, 20, 0))
        self.game(self.ann, self.ben, when=datetime(2026, 12, 25, 20, 0))
        self.assertTrue({"spooky", "ho_ho_ho"} <= self.earned(self.ann))
        self.assertNotIn("fresh_start", self.earned(self.ann))

    def test_friday_the_13th_needs_a_win(self):
        friday = datetime(2026, 2, 13, 20, 0)
        self.game(self.ann, self.ben, when=friday)
        self.assertIn("friday_13th", self.earned(self.ann))
        self.assertNotIn("friday_13th", self.earned(self.ben))

    def test_loyal_is_four_weeks_running(self):
        for week in range(4):
            self.game(self.ann, self.ben, when=TUESDAY + timedelta(weeks=week))
        self.assertIn("loyal", self.earned(self.ann))

    def test_welcome_back_after_a_month_away(self):
        self.game(self.ann, self.ben, when=TUESDAY)
        self.game(self.ann, self.ben, when=TUESDAY + timedelta(days=31))
        self.assertIn("welcome_back", self.earned(self.ann))


class SyncTests(AchievementTestCase):
    def test_past_games_are_credited_once(self):
        self.game(self.ann, self.ben)
        self.assertGreater(sync_achievements(), 0)
        self.assertEqual(sync_achievements(), 0, "running again awards nothing new")

    def test_earned_at_is_when_the_game_was_played(self):
        match = self.game(self.ann, self.ben)
        sync_achievements()
        row = db.session.scalars(
            db.select(PlayerAchievement).where(
                PlayerAchievement.user_id == self.ann,
                PlayerAchievement.achievement_key == "first_blood",
            )
        ).one()
        self.assertEqual(row.earned_at, match.played_at)
        self.assertEqual(row.match_id, match.match_id)


class EventTests(AchievementTestCase):
    def test_abdication_on_giving_up_the_table(self):
        self.make_king(self.ann)
        step_down(self.ann)
        self.assertIn("abdication", self.earned(self.ann))

    def test_patience_after_a_long_wait(self):
        join_queue(self.ann, 1)
        join_queue(self.ben, 1)
        self.backdate_queue_join(self.ann, PATIENCE_WAIT_SECONDS + 60)
        self.backdate_queue_join(self.ben, 60)

        attempt_matchmaking(1)

        self.assertIn("patience", self.earned(self.ann))
        self.assertNotIn("patience", self.earned(self.ben))


class PlayerViewTests(AchievementTestCase):
    def test_secrets_stay_secret_until_earned(self):
        badges = {b["key"]: b for b in player_badges("ann")["badges"]}
        self.assertEqual(badges["spooky"]["name"], "???")
        self.assertIsNone(badges["spooky"]["progress"])

        self.game(self.ann, self.ben, when=datetime(2026, 10, 31, 20, 0))
        sync_achievements()
        badges = {b["key"]: b for b in player_badges("ann")["badges"]}
        self.assertEqual(badges["spooky"]["name"], "Spooky")
        self.assertTrue(badges["spooky"]["earned"])

    def test_locked_badges_show_progress(self):
        for _ in range(4):
            self.game(self.ann, self.ben)
        sync_achievements()
        badges = {b["key"]: b for b in player_badges("ann")["badges"]}
        self.assertEqual(badges["regular"]["progress"], {"current": 4, "target": 10})
        self.assertIsNone(badges["first_break"]["progress"], "earned badges have no bar")

    def test_unknown_player(self):
        self.assertIsNone(player_badges("nobody"))


class BadgeRoutes(AchievementTestCase):
    def headers(self, user_id):
        return self.auth_headers(user_id)

    def test_recording_a_result_awards_and_announces(self):
        self.start_match(self.ann, self.ben)
        res = self.client.post(
            "/match/record",
            json={"my_balls": 8, "opp_balls": 0},
            headers=self.headers(self.ann),
        )
        self.assertEqual(res.status_code, 200)

        new = self.client.get("/me/badges/new", headers=self.headers(self.ann)).get_json()
        keys = {b["key"] for b in new["badges"]}
        self.assertTrue({"first_blood", "shutout"} <= keys)

        self.client.post(
            "/me/badges/seen", json={"keys": list(keys)}, headers=self.headers(self.ann)
        )
        again = self.client.get("/me/badges/new", headers=self.headers(self.ann)).get_json()
        self.assertEqual(again["badges"], [])

    def test_a_badge_failure_never_loses_a_result(self):
        self.start_match(self.ann, self.ben)
        with mock.patch("logic.record_match.sync_achievements", side_effect=RuntimeError):
            res = self.client.post(
                "/match/record",
                json={"my_balls": 8, "opp_balls": 3},
                headers=self.headers(self.ann),
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(db.session.get(Player, self.ann).total_wins, 1)

    def test_player_badges_route(self):
        res = self.client.get("/players/ann/badges")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["total"], 64)
        self.assertEqual(len(body["badges"]), 64)
        self.assertEqual(self.client.get("/players/nobody/badges").status_code, 404)

    def test_featured_badge_defaults_to_the_best(self):
        self.game(self.ann, self.ben, score=(8, 0))  # shutout is silver
        sync_achievements()
        board = {p["username"]: p for p in self.client.get("/leaderboard").get_json()}
        self.assertEqual(board["ann"]["badge"]["key"], "shutout")
        self.assertIsNone(board["cat"]["badge"], "no games, no badge")

    def test_choosing_a_featured_badge(self):
        self.game(self.ann, self.ben, score=(8, 0))
        sync_achievements()

        res = self.client.post(
            "/me/featured-badge", json={"key": "first_break"}, headers=self.headers(self.ann)
        )
        self.assertEqual(res.status_code, 200)
        board = {p["username"]: p for p in self.client.get("/leaderboard").get_json()}
        self.assertEqual(board["ann"]["badge"]["key"], "first_break")
        self.assertEqual(player_badges("ann")["chosen"], "first_break")

        # Back to automatic.
        self.client.post("/me/featured-badge", json={"key": None}, headers=self.headers(self.ann))
        self.assertEqual(player_badges("ann")["featured"], "shutout")

    def test_cannot_feature_an_unearned_or_unknown_badge(self):
        for key in ("untouchable", "not_a_badge"):
            res = self.client.post(
                "/me/featured-badge", json={"key": key}, headers=self.headers(self.ann)
            )
            self.assertEqual(res.status_code, 400, key)

    def test_king_banner_carries_the_kings_badge(self):
        self.start_match(self.ann, self.ben)
        self.client.post(
            "/match/record", json={"my_balls": 8, "opp_balls": 3}, headers=self.headers(self.ann)
        )
        table = self.client.get("/table/1").get_json()
        self.assertEqual(table["current_king"], "ann")
        self.assertIsNotNone(table["current_king_badge"])


if __name__ == "__main__":
    unittest.main()
