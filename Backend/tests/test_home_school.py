"""
A player's home school: the school of the league they joined first.

What it's for: a CCNY player who wins at Brooklyn is still from CCNY. Every
leaderboard shows the school a player is from by their name - the league
they joined first - and the champions across every school show where
they're from and where they earned it ("CCNY @ Brooklyn College").
"""
import unittest

from tests.conftest_base import ApiTestCase, make_league
from tests.test_top_players import HOUR, WEDNESDAY_EVENING
from database import ensure_schema
from models import BILLIARDS, PING_PONG, League, LeagueAccess, Match, Player, PoolTable, Standing, db

from logic.global_leaderboard import global_leaderboard
from logic.leagues import ensure_standing, set_league_pin

PIN = "2468"
JJ_TABLE, BROOKLYN_TABLE = 30, 40


class HomeSchoolTestCase(ApiTestCase):
    def setUp(self):
        super().setUp()
        jj = make_league("john-jay-billiards", "John Jay Billiards", BILLIARDS, school="John Jay", order=2)
        bk = make_league("brooklyn-billiards", "Brooklyn College Billiards", BILLIARDS, school="Brooklyn College", order=4)
        self.jj, self.brooklyn = jj.league_id, bk.league_id
        db.session.add(PoolTable(table_id=JJ_TABLE, table_name="Table 1", league_id=self.jj, league_type=BILLIARDS))
        db.session.add(PoolTable(table_id=BROOKLYN_TABLE, table_name="Table 1", league_id=self.brooklyn, league_type=BILLIARDS))
        db.session.commit()
        set_league_pin(self.jj, PIN)
        set_league_pin(self.billiards_league_id, PIN)

    def sign_up(self, username):
        """A brand-new account, through the app: in no league yet."""
        res = self.client.post(
            "/register",
            json={
                "username": username,
                "first_name": "New",
                "last_name": "Player",
                "email": f"{username}@example.com",
                "password": "hunter22",
            },
        )
        self.assertEqual(res.status_code, 201, res.get_json())
        return db.session.scalars(db.select(Player.user_id).where(Player.username == username)).one()

    def unlock(self, user_id, league_id):
        self.login_as(user_id)
        res = self.post("/league/unlock", json={"league_id": league_id, "pin": PIN})
        self.assertEqual(res.status_code, 200, res.get_json())

    def home(self, user_id):
        db.session.expire_all()
        return db.session.get(Player, user_id).home_school

    def make_home(self, user_id, league_id):
        db.session.get(Player, user_id).home_league_id = league_id
        db.session.commit()

    def game(self, winner, loser, table_id, change=16, seconds_ago=HOUR):
        match = Match(
            table_id=table_id,
            player_one_id=winner,
            player_two_id=loser,
            winner_id=winner,
            loser_id=loser,
            elo_change=change,
            loser_elo_change=change,
            match_status=Match.STATUS_FINISHED,
        )
        db.session.add(match)
        db.session.commit()
        db.session.execute(
            db.text("UPDATE Matches SET played_at = datetime('now', :offset) WHERE match_id = :id"),
            {"offset": f"-{int(seconds_ago)} seconds", "id": match.match_id},
        )
        db.session.commit()


class TheFirstLeagueJoined(HomeSchoolTestCase):
    def test_a_new_player_has_no_home_until_they_join(self):
        newcomer = self.sign_up("newcomer")

        self.assertIsNone(self.home(newcomer))

    def test_the_first_pin_entered_makes_its_school_home(self):
        newcomer = self.sign_up("newcomer")

        self.unlock(newcomer, self.jj)

        self.assertEqual(self.home(newcomer), "John Jay")

    def test_joining_more_leagues_doesnt_change_it(self):
        newcomer = self.sign_up("newcomer")
        self.unlock(newcomer, self.jj)

        self.unlock(newcomer, self.billiards_league_id)

        self.assertEqual(self.home(newcomer), "John Jay")

    def test_a_first_game_counts_too(self):
        """The organiser plays anywhere without a PIN: their first game is their first league."""
        organiser = self.sign_up("organiser")
        ensure_standing(organiser, self.brooklyn)
        db.session.commit()

        self.assertEqual(self.home(organiser), "Brooklyn College")


class OnTheLeaderboards(HomeSchoolTestCase):
    def setUp(self):
        super().setUp()
        self.make_home(self.alice, self.billiards_league_id)  # CCNY
        self.make_home(self.bob, self.brooklyn)

    def test_a_ladder_shows_where_each_player_is_from(self):
        ensure_standing(self.alice, self.brooklyn)
        db.session.commit()

        rows = self.client.get(f"/leaderboard?league_id={self.brooklyn}").get_json()

        alice = next(row for row in rows if row["user_id"] == self.alice)
        self.assertEqual(alice["home_school"], "CCNY", "on Brooklyn's ladder, still from CCNY")

    def test_the_champions_say_from_where_and_won_where(self):
        """The case that asked for this: a CCNY player winning at Brooklyn."""
        self.game(self.alice, self.carol, BROOKLYN_TABLE, change=40)
        self.game(self.bob, self.carol, BROOKLYN_TABLE, change=20)

        week = global_leaderboard(now=WEDNESDAY_EVENING)["sports"][BILLIARDS]["week"]

        first, second = week[0], week[1]
        self.assertEqual((first["home_school"], first["school"]), ("CCNY", "Brooklyn College"))
        self.assertEqual((second["home_school"], second["school"]), ("Brooklyn College", "Brooklyn College"))
        self.assertEqual(first["player"]["home_school"], "CCNY")

    def test_cards_and_profiles_carry_it(self):
        self.game(self.alice, self.bob, BROOKLYN_TABLE)

        history = self.client.get(f"/matches/history?league_id={self.brooklyn}").get_json()["matches"]
        profile = self.client.get(f"/players/{self.alice}").get_json()["player"]

        self.assertEqual(history[0]["winner"]["home_school"], "CCNY")
        self.assertEqual(history[0]["loser"]["home_school"], "Brooklyn College")
        self.assertEqual(profile["home_school"], "CCNY")

    def test_a_deleted_account_has_none(self):
        self.login_as(self.alice)
        db.session.get(Player, self.alice).password_hash = _hash("hunter22")
        db.session.commit()

        res = self.post("/profile/delete", json={"password": "hunter22"})

        self.assertEqual(res.status_code, 200, res.get_json())
        db.session.expire_all()
        player = db.session.get(Player, self.alice)
        self.assertIsNone(player.home_league_id)
        self.assertIsNone(player.to_card(BILLIARDS)["home_school"])


class WorkedOutForPlayersFromBefore(HomeSchoolTestCase):
    """ensure_schema, for players who joined before homes were kept."""

    def test_their_first_game_says_where(self):
        # alice played at CCNY first, then at Brooklyn: from CCNY.
        db.session.add(Standing(user_id=self.alice, league_id=self.brooklyn, elo=0))
        db.session.commit()
        self.game(self.alice, self.bob, 1, seconds_ago=10 * 24 * HOUR)
        self.game(self.alice, self.carol, BROOKLYN_TABLE, seconds_ago=HOUR)

        ensure_schema()

        self.assertEqual(self.home(self.alice), "CCNY")

    def test_or_the_first_pin_they_entered(self):
        newcomer = self._without_home(self.sign_up("newcomer"), standings=[self.jj])
        db.session.add(LeagueAccess(user_id=newcomer, league_id=self.jj))
        db.session.commit()

        ensure_schema()

        self.assertEqual(self.home(newcomer), "John Jay")

    def test_whichever_came_first(self):
        newcomer = self._without_home(self.sign_up("newcomer"), standings=[self.jj, self.brooklyn])
        db.session.add(LeagueAccess(user_id=newcomer, league_id=self.jj))
        db.session.commit()
        db.session.execute(
            db.text("UPDATE League_Access SET granted_at = datetime('now', '-1 hours') WHERE user_id = :u"),
            {"u": newcomer},
        )
        db.session.commit()
        self.game(newcomer, self.bob, BROOKLYN_TABLE, seconds_ago=60)

        ensure_schema()

        self.assertEqual(self.home(newcomer), "John Jay", "the PIN an hour before the game")

    def test_else_the_first_league_they_have_a_place_in(self):
        # The fixtures' players have places in CCNY's leagues and nothing else.
        ensure_schema()

        self.assertEqual(self.home(self.carol), "CCNY")

    def test_no_place_anywhere_no_home(self):
        newcomer = self.sign_up("newcomer")

        ensure_schema()

        self.assertIsNone(self.home(newcomer))

    def test_a_home_already_set_is_kept(self):
        self.make_home(self.alice, self.brooklyn)
        self.game(self.alice, self.bob, 1)

        ensure_schema()
        ensure_schema()

        self.assertEqual(self.home(self.alice), "Brooklyn College")

    def _without_home(self, user_id, standings):
        for league_id in standings:
            db.session.add(Standing(user_id=user_id, league_id=league_id, elo=0))
        db.session.commit()
        return user_id


class PrivacyPolicy(HomeSchoolTestCase):
    def test_says_so(self):
        page = self.client.get("/privacy").get_data(as_text=True)

        self.assertIn("home school", page)


def _hash(password):
    import bcrypt

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()


if __name__ == "__main__":
    unittest.main()
