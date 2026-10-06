"""
Achievements and badges, in both leagues.

Most tests build match history with the real apply_result - so ratings,
the floor, ranks and the ratings-before-the-game columns are exactly what
a reported game leaves - then run sync_achievements(), which is what
happens after every real result and on startup. The API tests at the
bottom check the routes the web app uses.
"""
import unittest
from datetime import datetime, timedelta
from unittest import mock

from tests.conftest_base import PING_PONG_TABLE_ID, BaseTestCase
from logic.achievements import (
    ACHIEVEMENTS,
    BY_KEY,
    GROUPS,
    PATIENCE_WAIT_SECONDS,
    player_badges,
    sync_achievements,
)
from logic.manage_queue import attempt_matchmaking, confirm_here, join_queue, step_down
from logic.record_match import apply_result
from models import BILLIARDS, PING_PONG, Match, Player, PlayerAchievement, Standing, db

# A plain Tuesday afternoon, so time-of-day badges stay out of the way
# unless a test asks for them.
TUESDAY = datetime(2026, 3, 10, 15, 0)

TABLES = {BILLIARDS: 1, PING_PONG: PING_PONG_TABLE_ID}
WIN = {BILLIARDS: (8, 3), PING_PONG: (11, 6)}


class AchievementTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.clock = TUESDAY
        # New players, at the leagues' real starting rating.
        self.ann = self.add_player("ann", elo=0, ping_pong_elo=0)
        self.ben = self.add_player("ben", elo=0, ping_pong_elo=0)
        self.cat = self.add_player("cat", elo=0, ping_pong_elo=0)

    def game(self, winner, loser, *, league=PING_PONG, seat_one=None, score=None, change=16, when=None):
        """
        One finished game, stored the way a reported one is: apply_result
        moves the ratings (and records them before the game), the score
        sits against the seats. seat_one is the king's seat; by default
        the winner sat there.
        """
        if when is None:
            self.clock += timedelta(minutes=20)
            when = self.clock
        winner_score, loser_score = score or WIN[league]
        seat_one = seat_one or winner
        winner_first = seat_one == winner
        match = Match(
            table_id=TABLES[league],
            player_one_id=seat_one,
            player_two_id=loser if winner_first else winner,
            winner_id=winner,
            loser_id=loser,
            player_one_balls=winner_score if winner_first else loser_score,
            player_two_balls=loser_score if winner_first else winner_score,
            match_status=Match.STATUS_FINISHED,
            elo_change=change,
            played_at=when,
        )
        db.session.add(match)
        league_id = self.league_id(league)
        apply_result(
            match,
            db.session.get(Standing, (winner, league_id)),
            db.session.get(Standing, (loser, league_id)),
            change,
            league,
        )
        db.session.commit()
        return match

    def earned(self, user_id, league=PING_PONG):
        sync_achievements()
        return set(
            db.session.scalars(
                db.select(PlayerAchievement.achievement_key).where(
                    PlayerAchievement.user_id == user_id,
                    PlayerAchievement.league_id == self.league_id(league),
                )
            )
        )


class DefinitionTests(unittest.TestCase):
    def test_sixty_four_unique_badges(self):
        self.assertEqual(len(ACHIEVEMENTS), 64)
        self.assertEqual(len(BY_KEY), 64, "every key is unique")

    def test_names_are_unique_within_each_league(self):
        for league in (BILLIARDS, PING_PONG):
            names = [a.name_in(league) for a in ACHIEVEMENTS]
            self.assertEqual(len(set(names)), 64, league)

    def test_ping_pong_scorelines_have_their_own_rules(self):
        self.assertEqual(BY_KEY["shutout"].name_in(PING_PONG), "Bagel")
        self.assertIn("11-0", BY_KEY["shutout"].description_in(PING_PONG))
        self.assertIn("8-0", BY_KEY["shutout"].description_in(BILLIARDS))

    def test_every_badge_is_in_a_known_group_and_tier(self):
        groups = {key for key, _ in GROUPS}
        for a in ACHIEVEMENTS:
            self.assertIn(a.group, groups, a.key)
            self.assertIn(a.tier, {"bronze", "silver", "gold", "legendary"}, a.key)
            self.assertLessEqual(len(a.key), 40, "fits the column")


class LeagueSeparationTests(AchievementTestCase):
    def test_each_league_earns_its_own_badges(self):
        self.game(self.ann, self.ben, league=PING_PONG)
        self.assertIn("first_blood", self.earned(self.ann, PING_PONG))
        self.assertNotIn("first_blood", self.earned(self.ann, BILLIARDS))

    def test_streaks_dont_cross_leagues(self):
        self.game(self.ann, self.ben, league=PING_PONG)
        self.game(self.ann, self.ben, league=BILLIARDS)
        self.game(self.ann, self.ben, league=PING_PONG)
        self.assertNotIn("hat_trick", self.earned(self.ann, PING_PONG))
        self.assertNotIn("hat_trick", self.earned(self.ann, BILLIARDS))


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


class PingPongScorelineTests(AchievementTestCase):
    def test_bagel_is_eleven_love(self):
        self.game(self.ann, self.ben, score=(11, 0))
        self.assertIn("shutout", self.earned(self.ann))

    def test_deuce_games(self):
        self.game(self.ann, self.ben, score=(12, 10))
        self.assertIn("nail_biter", self.earned(self.ann))
        self.assertIn("so_close", self.earned(self.ben))

    def test_eleven_nine_is_not_a_deuce(self):
        self.game(self.ann, self.ben, score=(11, 9))
        self.assertNotIn("nail_biter", self.earned(self.ann))
        self.assertNotIn("so_close", self.earned(self.ben))

    def test_dominator_needs_seven_point_wins(self):
        for _ in range(5):
            self.game(self.ann, self.ben, score=(11, 5))  # by 6: not enough
        self.assertNotIn("dominator", self.earned(self.ann))
        for _ in range(5):
            self.game(self.ann, self.ben, score=(11, 4))
        self.assertIn("dominator", self.earned(self.ann))


class BilliardsScorelineTests(AchievementTestCase):
    def test_shutout_nail_biter_and_so_close(self):
        self.game(self.ann, self.ben, league=BILLIARDS, score=(8, 0))
        self.game(self.ann, self.cat, league=BILLIARDS, score=(8, 7))
        earned = self.earned(self.ann, BILLIARDS)
        self.assertTrue({"shutout", "nail_biter"} <= earned)
        self.assertIn("so_close", self.earned(self.cat, BILLIARDS))
        self.assertNotIn("so_close", self.earned(self.ben, BILLIARDS))

    def test_games_without_a_score_still_count(self):
        """Old rows have no score; they mustn't break the replay."""
        self.game(self.ann, self.ben, league=BILLIARDS, score=(None, None))
        self.assertIn("first_blood", self.earned(self.ann, BILLIARDS))


class KingOfTheHillTests(AchievementTestCase):
    def test_kingslayer_ends_a_three_game_reign(self):
        self.game(self.ann, self.ben)
        self.game(self.ann, self.cat)
        self.game(self.ann, self.ben)
        self.game(self.cat, self.ann, seat_one=self.ann)
        cat = self.earned(self.cat)
        self.assertTrue({"crowned", "kingslayer"} <= cat)
        self.assertNotIn("tyrant_toppler", cat)

    def test_beating_a_fresh_pairing_is_not_dethroning(self):
        self.game(self.ben, self.ann, seat_one=self.ann)
        self.assertNotIn("crowned", self.earned(self.ben))

    def test_record_breaker_at_three(self):
        self.game(self.ann, self.ben)
        self.game(self.ann, self.cat)
        self.assertNotIn("record_breaker", self.earned(self.ann))
        self.game(self.ann, self.ben)
        self.assertIn("record_breaker", self.earned(self.ann))


class RatingTests(AchievementTestCase):
    def test_giant_killer_uses_the_ratings_before_the_game(self):
        strong = self.add_player("strong", elo=0, ping_pong_elo=150)
        self.game(self.ann, strong, change=30)
        self.assertIn("giant_killer", self.earned(self.ann))
        self.assertNotIn("david_vs_goliath", self.earned(self.ann), "150 above isn't 250")

    def test_a_season_reset_doesnt_fool_it(self):
        """Ratings now are all 0 after a reset; the game's own record still knows."""
        strong = self.add_player("strong", elo=0, ping_pong_elo=150)
        self.game(self.ann, strong, change=30)
        db.session.execute(
            db.update(Standing).where(Standing.league_id == self.ping_pong_league_id).values(elo=0)
        )
        db.session.commit()
        self.assertIn("giant_killer", self.earned(self.ann))

    def test_old_games_without_ratings_skip_rating_badges_only(self):
        strong = self.add_player("strong", elo=0, ping_pong_elo=150)
        match = self.game(self.ann, strong, change=30)
        match.winner_elo_before = match.loser_elo_before = None
        db.session.commit()
        earned = self.earned(self.ann)
        self.assertNotIn("giant_killer", earned)
        self.assertIn("first_blood", earned)

    def test_big_payday_differs_by_league(self):
        self.game(self.ann, self.ben, league=BILLIARDS, change=25)
        self.game(self.ann, self.ben, league=PING_PONG, change=25)
        self.assertIn("big_payday", self.earned(self.ann, BILLIARDS))
        self.assertNotIn("big_payday", self.earned(self.ann, PING_PONG))
        self.game(self.ann, self.ben, league=PING_PONG, change=35)
        self.assertIn("big_payday", self.earned(self.ann, PING_PONG))

    def test_big_day(self):
        self.game(self.ann, self.ben, change=30)
        self.assertNotIn("big_day", self.earned(self.ann))
        self.game(self.ann, self.cat, change=30)
        self.assertIn("big_day", self.earned(self.ann))

    def test_rank_badges_follow_the_ranks_table(self):
        # Seeded tiers in the tests: Silver 1100, Gold 1300, Platinum 1500.
        self.game(self.ann, self.ben, change=1100)
        earned = self.earned(self.ann)
        self.assertIn("rank_silver", earned)
        self.assertNotIn("rank_gold", earned)

    def test_current_standing_counts_too(self):
        """A rating reached before ratings were recorded per game still counts."""
        veteran = self.add_player("veteran", elo=0, ping_pong_elo=1200)
        self.game(veteran, self.ann)
        match = db.session.scalars(db.select(Match)).first()
        match.winner_elo_before = match.loser_elo_before = None
        db.session.commit()
        self.assertTrue({"century", "rank_silver"} <= self.earned(veteran))


class LadderTests(AchievementTestCase):
    def test_podium_and_number_one_need_ten_games(self):
        for _ in range(9):
            self.game(self.ann, self.ben, change=30)
        self.assertNotIn("number_one", self.earned(self.ann))
        self.game(self.ann, self.ben, change=30)
        earned = self.earned(self.ann)
        # alice, bob and carol from the base setup are rated 1200.
        self.assertNotIn("podium", earned)
        for user_id in (self.alice, self.bob, self.carol):
            self.set_rating(user_id, 0, PING_PONG)
        self.assertTrue({"podium", "number_one"} <= self.earned(self.ann))


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
        self.assertTrue({"night_owl", "early_bird"} <= self.earned(self.ann))

    def test_holidays(self):
        self.game(self.ann, self.ben, when=datetime(2026, 10, 31, 20, 0))
        self.game(self.ann, self.ben, when=datetime(2026, 12, 25, 20, 0))
        self.assertTrue({"spooky", "ho_ho_ho"} <= self.earned(self.ann))
        self.assertNotIn("fresh_start", self.earned(self.ann))

    def test_friday_the_13th_needs_a_win(self):
        self.game(self.ann, self.ben, when=datetime(2026, 2, 13, 20, 0))
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
        self.assertEqual(row.league_type, PING_PONG)

    def test_deleted_players_earn_nothing(self):
        db.session.get(Player, self.ben).deleted_at = datetime(2026, 1, 1)
        db.session.commit()
        self.game(self.ann, self.ben)
        self.assertEqual(self.earned(self.ben), set())
        self.assertIn("first_blood", self.earned(self.ann))


class EventTests(AchievementTestCase):
    def test_abdication_in_the_tables_league(self):
        self.make_king(self.ann, table_id=PING_PONG_TABLE_ID)
        step_down(self.ann)
        self.assertIn("abdication", self.earned(self.ann, PING_PONG))
        self.assertNotIn("abdication", self.earned(self.ann, BILLIARDS))

    def test_patience_after_a_long_wait(self):
        join_queue(self.ann, PING_PONG)
        self.backdate_queue_join(self.ann, PATIENCE_WAIT_SECONDS + 60, PING_PONG)
        join_queue(self.ben, PING_PONG)  # just arrived

        attempt_matchmaking(PING_PONG)  # ann is asked if they're here
        confirm_here(self.ann, PING_PONG)
        self.assertTrue(attempt_matchmaking(PING_PONG), "the game starts")
        self.assertIn("patience", self.earned(self.ann))
        self.assertNotIn("patience", self.earned(self.ben))


class PlayerViewTests(AchievementTestCase):
    def test_secrets_stay_secret_until_earned(self):
        badges = {b["key"]: b for b in player_badges(self.ann, PING_PONG)["badges"]}
        self.assertEqual(badges["spooky"]["name"], "???")
        self.assertIsNone(badges["spooky"]["progress"])

        self.game(self.ann, self.ben, when=datetime(2026, 10, 31, 20, 0))
        sync_achievements()
        badges = {b["key"]: b for b in player_badges(self.ann, PING_PONG)["badges"]}
        self.assertEqual(badges["spooky"]["name"], "Spooky")

    def test_names_follow_the_league(self):
        bp = {b["key"]: b for b in player_badges(self.ann, PING_PONG)["badges"]}
        bb = {b["key"]: b for b in player_badges(self.ann, BILLIARDS)["badges"]}
        self.assertEqual(bp["shutout"]["name"], "Bagel")
        self.assertEqual(bb["shutout"]["name"], "Shutout")

    def test_locked_badges_show_progress(self):
        for _ in range(4):
            self.game(self.ann, self.ben)
        sync_achievements()
        badges = {b["key"]: b for b in player_badges(self.ann, PING_PONG)["badges"]}
        self.assertEqual(badges["regular"]["progress"], {"current": 4, "target": 10})
        self.assertIsNone(badges["first_break"]["progress"], "earned badges have no bar")

    def test_unknown_or_deleted_player(self):
        self.assertIsNone(player_badges(99999, PING_PONG))
        db.session.get(Player, self.ben).deleted_at = datetime(2026, 1, 1)
        db.session.commit()
        self.assertIsNone(player_badges(self.ben, PING_PONG))


class BadgeRoutes(AchievementTestCase):
    def report(self, user_id, mine, theirs):
        return self.client.post(
            "/match/record",
            json={"my_balls": mine, "opp_balls": theirs, "league_type": PING_PONG},
            headers=self.auth_headers(user_id),
        )

    def test_recording_a_result_awards_and_announces(self):
        self.start_match(self.ann, self.ben, table_id=PING_PONG_TABLE_ID)
        self.assertEqual(self.report(self.ann, 11, 0).status_code, 200)

        new = self.client.get("/me/badges/new", headers=self.auth_headers(self.ann)).get_json()
        keys = {b["key"] for b in new["badges"]}
        self.assertTrue({"first_blood", "shutout"} <= keys)
        bagel = next(b for b in new["badges"] if b["key"] == "shutout")
        self.assertEqual((bagel["name"], bagel["league_type"]), ("Bagel", PING_PONG))

        self.client.post(
            "/me/badges/seen",
            json={"ids": [b["id"] for b in new["badges"]]},
            headers=self.auth_headers(self.ann),
        )
        again = self.client.get("/me/badges/new", headers=self.auth_headers(self.ann)).get_json()
        self.assertEqual(again["badges"], [])

    def test_the_game_records_ratings_before_it(self):
        self.start_match(self.ann, self.ben, table_id=PING_PONG_TABLE_ID)
        self.report(self.ann, 11, 3)
        match = db.session.scalars(
            db.select(Match).where(Match.match_status == Match.STATUS_FINISHED)
        ).one()
        self.assertEqual((match.winner_elo_before, match.loser_elo_before), (0, 0))

    def test_a_badge_failure_never_loses_a_result(self):
        self.start_match(self.ann, self.ben, table_id=PING_PONG_TABLE_ID)
        with mock.patch("logic.record_match.sync_achievements", side_effect=RuntimeError):
            res = self.report(self.ann, 11, 3)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.record(self.ann, PING_PONG), (1, 0))

    def test_player_badges_route(self):
        res = self.client.get(f"/players/{self.ann}/badges?league_type=ping_pong")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual((body["total"], len(body["badges"])), (64, 64))
        self.assertEqual(body["league_type"], PING_PONG)
        self.assertEqual(self.client.get("/players/99999/badges").status_code, 404)
        self.assertEqual(
            self.client.get(f"/players/{self.ann}/badges?league_type=golf").status_code, 400
        )

    def test_featured_badge_defaults_to_the_best(self):
        self.game(self.ann, self.ben, score=(11, 0))  # Bagel is silver
        sync_achievements()
        board = {p["username"]: p for p in self.client.get("/leaderboard?league_type=ping_pong").get_json()}
        self.assertEqual(board["ann"]["badge"]["key"], "shutout")
        self.assertEqual(board["ann"]["badge"]["name"], "Bagel")
        self.assertIsNone(board["cat"]["badge"], "no games, no badge")

        billiards = {p["username"]: p for p in self.client.get("/leaderboard").get_json()}
        self.assertIsNone(billiards["ann"]["badge"], "no billiards badges yet")

    def test_choosing_a_featured_badge_per_league(self):
        self.game(self.ann, self.ben, score=(11, 0))
        sync_achievements()
        res = self.client.post(
            "/me/featured-badge",
            json={"league_type": PING_PONG, "key": "first_break"},
            headers=self.auth_headers(self.ann),
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(player_badges(self.ann, PING_PONG)["chosen"], "first_break")

        # Back to automatic.
        self.client.post(
            "/me/featured-badge",
            json={"league_type": PING_PONG, "key": None},
            headers=self.auth_headers(self.ann),
        )
        self.assertEqual(player_badges(self.ann, PING_PONG)["featured"], "shutout")

    def test_cannot_feature_a_badge_from_the_other_league(self):
        self.game(self.ann, self.ben, score=(11, 0))
        sync_achievements()
        for league, key in ((BILLIARDS, "shutout"), (PING_PONG, "untouchable"), (PING_PONG, "nope")):
            res = self.client.post(
                "/me/featured-badge",
                json={"league_type": league, "key": key},
                headers=self.auth_headers(self.ann),
            )
            self.assertEqual(res.status_code, 400, (league, key))

    def test_table_shows_the_record_and_badges(self):
        self.start_match(self.ann, self.ben, table_id=PING_PONG_TABLE_ID)
        self.report(self.ann, 11, 3)
        table = self.client.get(f"/table/{PING_PONG_TABLE_ID}").get_json()["table"]
        self.assertEqual(table["king"]["username"], "ann")
        self.assertEqual(table["table_record_streak"], 1)
        self.assertIsNotNone(table["king_badge"])
        self.assertIsNone(table["challenger_badge"])


if __name__ == "__main__":
    unittest.main()
