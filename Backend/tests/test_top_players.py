"""
The players of the day, the week and the month: whoever gained the most
rating points in each, in the league's own calendar.
"""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from tests.conftest_base import PING_PONG_TABLE_ID, ApiTestCase, BaseTestCase
from models import BILLIARDS, PING_PONG, Match, Player, db

from logic.top_players import period_lengths, top_players

NEW_YORK = ZoneInfo("America/New_York")
HOUR, DAY = 3600, 86400

# A Wednesday evening: today began 18.5 hours ago, the week (Monday) two
# days before that, the month (the 1st) six days before that.
WEDNESDAY_EVENING = datetime(2026, 10, 7, 18, 30, tzinfo=NEW_YORK)


class PeriodLengths(unittest.TestCase):
    def test_today_this_week_and_this_month(self):
        lengths = period_lengths(WEDNESDAY_EVENING)

        self.assertEqual(lengths["day"], 18.5 * HOUR)
        self.assertEqual(lengths["week"], 2 * DAY + 18.5 * HOUR)
        self.assertEqual(lengths["month"], 6 * DAY + 18.5 * HOUR)

    def test_the_clocks_going_back_inside_the_month(self):
        """Clocks went back an hour at 2am on Sunday 1 November 2026."""
        lengths = period_lengths(datetime(2026, 11, 2, 12, 0, tzinfo=NEW_YORK))

        self.assertEqual(lengths["day"], 12 * HOUR, "Monday: the week and the day began at midnight")
        self.assertEqual(lengths["week"], 12 * HOUR)
        self.assertEqual(lengths["month"], DAY + 12 * HOUR + HOUR, "the 1st was 25 hours long")

    def test_on_a_monday_the_week_is_today(self):
        lengths = period_lengths(datetime(2026, 10, 5, 9, 0, tzinfo=NEW_YORK))
        self.assertEqual(lengths["week"], lengths["day"])


class TopPlayersTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.dave = self.add_player("dave")

    def game(self, winner, loser, change, seconds_ago, loser_change="same", table_id=PING_PONG_TABLE_ID):
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

    def winners(self, league=PING_PONG):
        result = top_players(league, now=WEDNESDAY_EVENING)
        return {
            period: (result[period]["player"]["username"] if result[period] else None)
            for period in ("day", "week", "month")
        }


class WhoTakesEachPeriod(TopPlayersTestCase):
    def test_each_period_counts_only_its_own_games(self):
        self.game(self.bob, self.carol, 10, HOUR)  # today
        self.game(self.alice, self.dave, 20, 2 * DAY)  # Monday
        self.game(self.carol, self.dave, 50, 5 * DAY)  # the 2nd
        self.game(self.dave, self.alice, 100, 10 * DAY)  # last month

        self.assertEqual(self.winners(), {"day": "bob", "week": "alice", "month": "carol"})

    def test_points_gained_not_wins(self):
        self.game(self.alice, self.bob, 5, HOUR)
        self.game(self.alice, self.carol, 5, HOUR)
        self.game(self.dave, self.bob, 30, HOUR)

        self.assertEqual(self.winners()["day"], "dave", "one big upset beats two small wins")

    def test_a_loss_costs_only_what_it_really_cost(self):
        # bob lost to alice at the floor of 0, which cost him nothing.
        self.game(self.alice, self.bob, 10, HOUR, loser_change=0)
        self.game(self.bob, self.carol, 15, HOUR)

        result = top_players(PING_PONG, now=WEDNESDAY_EVENING)["day"]
        self.assertEqual(result["player"]["username"], "bob")
        self.assertEqual((result["points"], result["wins"], result["losses"]), (15, 1, 1))

    def test_a_game_from_before_the_floor_costs_its_full_change(self):
        self.game(self.alice, self.bob, 10, HOUR, loser_change=None)
        self.game(self.bob, self.carol, 8, HOUR)

        self.assertEqual(self.winners()["day"], "alice", "bob is at -2 for the day")

    def test_a_tie_goes_to_more_wins(self):
        self.game(self.alice, self.bob, 12, HOUR)
        self.game(self.carol, self.dave, 6, HOUR)
        self.game(self.carol, self.dave, 6, HOUR)

        self.assertEqual(self.winners()["day"], "carol")

    def test_deleted_accounts_are_left_out(self):
        self.game(self.alice, self.bob, 30, HOUR)
        self.game(self.carol, self.dave, 10, HOUR)
        db.session.get(Player, self.alice).deleted_at = db.func.now()
        db.session.commit()

        self.assertEqual(self.winners()["day"], "carol")

    def test_nobody_yet(self):
        self.game(self.alice, self.bob, 30, 10 * DAY)

        self.assertEqual(self.winners(), {"day": None, "week": None, "month": None})

    def test_the_other_leagues_games_dont_count(self):
        self.game(self.alice, self.bob, 30, HOUR, table_id=1)

        self.assertEqual(self.winners(PING_PONG)["day"], None)
        self.assertEqual(self.winners(BILLIARDS)["day"], "alice")


class TopPlayersRoute(TopPlayersTestCase, ApiTestCase):
    def test_the_shape(self):
        # Just now, by the real clock (the route has no fixed `now`): an
        # hour ago would be yesterday for a test run just after midnight.
        self.game(self.bob, self.carol, 10, 0)

        res = self.client.get("/top-players?league_type=ping_pong")

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(set(body), {"league_type", "timezone", "day", "week", "month"})
        self.assertEqual(body["league_type"], "ping_pong")
        self.assertEqual(body["timezone"], "America/New_York")
        self.assertEqual(set(body["day"]), {"player", "points", "wins", "losses"})
        self.assertEqual(
            set(body["day"]["player"]),
            set(db.session.get(Player, self.bob).to_card(PING_PONG)),
            "the player is a card, like everywhere else",
        )

    def test_an_unknown_league(self):
        self.assertEqual(self.client.get("/top-players?league_type=chess").status_code, 400)

    def test_no_league_means_billiards(self):
        self.assertEqual(self.client.get("/top-players").get_json()["league_type"], "billiards")


if __name__ == "__main__":
    unittest.main()
