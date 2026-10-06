"""
Many leagues - a school's billiards or ping pong, each with its own
tables, queue, ladder and 4-digit PIN.

What it's for: CCNY's two leagues were the whole app; now John Jay and
Brooklyn College have theirs. Anyone can look at a league; playing there
takes its PIN, entered once. The organiser changes PINs (everyone enters
the new one) and adds, renames and removes tables, and each league's one
queue feeds all of its tables.
"""
import unittest

from tests.conftest_base import PING_PONG_TABLE_ID, ApiTestCase, make_league
from models import (
    BILLIARDS,
    PING_PONG,
    League,
    LeagueAccess,
    Match,
    PinAttempt,
    Player,
    PoolTable,
    QueueEntry,
    Standing,
    db,
)

from logic.leagues import MAX_PIN_FAILURES, PIN_LOCKOUT_SECONDS, grant_access, set_league_pin
from logic.manage_queue import RECENTLY_HERE_SECONDS, attempt_matchmaking, join_queue

PIN = "2468"
# Long enough ago that joining no longer counts as being here.
A_WHILE = RECENTLY_HERE_SECONDS + 240


class LeaguesTestCase(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.dave = self.add_player("dave")
        self.erin = self.add_player("erin")
        # John Jay Ping Pong: two tables, nobody let in yet.
        league = make_league(
            "john-jay-ping-pong", "John Jay Ping Pong", PING_PONG, school="John Jay", order=3
        )
        league.primary_color, league.secondary_color = "#232C64", "#00AEEF"
        self.jj = league.league_id
        db.session.add(PoolTable(table_id=20, table_name="Table 1", league_id=self.jj, league_type=PING_PONG))
        db.session.add(PoolTable(table_id=21, table_name="Table 2", league_id=self.jj, league_type=PING_PONG))
        db.session.commit()

    def make_admin(self, user_id):
        db.session.get(Player, user_id).is_admin = True
        db.session.commit()

    def let_in(self, *user_ids, league=None):
        for user_id in user_ids:
            grant_access(user_id, league or self.jj)

    def set_pin(self, pin=PIN, league=None):
        set_league_pin(league or self.jj, pin)

    def unlock(self, pin, league=None):
        return self.post("/league/unlock", json={"league_id": league or self.jj, "pin": pin})

    def join(self, user_id, league=None):
        self.login_as(user_id)
        return self.post("/queue/join", json={"league_id": league or self.jj})

    def seats(self, table_id):
        db.session.expire_all()
        match = self.active_match(table_id)
        return None if match is None else (match.player_one_id, match.player_two_id)

    def entry(self, user_id, league=None):
        db.session.expire_all()
        return db.session.scalars(
            db.select(QueueEntry).where(
                QueueEntry.user_id == user_id, QueueEntry.league_id == (league or self.jj)
            )
        ).first()


class LookingAtLeagues(LeaguesTestCase):
    def test_anyone_sees_every_league_read_only(self):
        res = self.client.get("/leagues/directory")

        self.assertEqual(res.status_code, 200)
        leagues = {league["slug"]: league for league in res.get_json()["leagues"]}
        self.assertEqual(set(leagues), {"ccny-billiards", "ccny-ping-pong", "john-jay-ping-pong"})
        jj = leagues["john-jay-ping-pong"]
        self.assertEqual((jj["primary_color"], jj["secondary_color"]), ("#232C64", "#00AEEF"))
        self.assertEqual((jj["game"], jj["league_type"], jj["school"]), (PING_PONG, PING_PONG, "John Jay"))
        self.assertEqual([t["table_name"] for t in jj["tables"]], ["Table 1", "Table 2"])
        self.assertTrue(all(league["read_only"] for league in leagues.values()))

    def test_signed_in_it_says_where_you_can_play(self):
        self.login_as(self.alice)
        leagues = {l["slug"]: l for l in self.get("/leagues/directory").get_json()["leagues"]}

        self.assertFalse(leagues["ccny-billiards"]["read_only"], "CCNY players were let in")
        self.assertTrue(leagues["john-jay-ping-pong"]["read_only"])

    def test_an_admin_can_play_anywhere(self):
        self.make_admin(self.alice)
        self.login_as(self.alice)
        leagues = self.get("/leagues/directory").get_json()["leagues"]
        self.assertFalse(any(league["read_only"] for league in leagues))

    def test_one_league(self):
        self.login_as(self.alice)
        body = self.get(f"/leagues/{self.jj}").get_json()["league"]
        self.assertEqual(body["name"], "John Jay Ping Pong")
        self.assertTrue(body["read_only"])
        self.assertEqual(self.client.get("/leagues/999").status_code, 404)

    def test_the_hub_is_public(self):
        """Tables, queue, ladder and games - everything a visitor looks at."""
        self.let_in(self.alice)
        join_queue(self.alice, self.jj)

        tables = self.client.get(f"/leagues/{self.jj}/tables").get_json()["tables"]
        queue = self.client.get(f"/leagues/{self.jj}/queue").get_json()
        ladder = self.client.get(f"/leaderboard?league_id={self.jj}").get_json()
        history = self.client.get(f"/matches/history?league_id={self.jj}").get_json()

        self.assertEqual([t["table_name"] for t in tables], ["Table 1", "Table 2"])
        self.assertEqual([e["username"] for e in queue], ["alice"])
        self.assertEqual([p["username"] for p in ladder], ["alice"], "only who's in the league")
        self.assertEqual((history["league_id"], history["matches"]), (self.jj, []))


class EnteringThePin(LeaguesTestCase):
    def setUp(self):
        super().setUp()
        self.login_as(self.dave)

    def test_no_pin_yet(self):
        res = self.unlock("1234")
        self.assertEqual(res.status_code, 409)
        self.assertIn("organiser", res.get_json()["message"])

    def test_the_right_pin_lets_you_in_for_good(self):
        self.set_pin()

        res = self.unlock(PIN)

        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.get_json()["league"]["read_only"])
        self.assertIsNotNone(db.session.get(LeagueAccess, (self.dave, self.jj)))
        standing = self.standing(self.dave, self.jj)
        self.assertEqual((standing.elo, standing.wins, standing.losses), (0, 0, 0), "on the ladder, at the start")
        again = self.unlock(PIN)
        self.assertEqual((again.status_code, again.get_json()["status"]), (200, "already_unlocked"))

    def test_a_wrong_pin(self):
        self.set_pin()

        res = self.unlock("1111")

        self.assertEqual(res.status_code, 403, "403, never 401 - that would sign the player out")
        self.assertEqual(res.get_json()["field"], "pin")
        self.assertEqual(res.get_json()["tries_left"], MAX_PIN_FAILURES - 1)
        self.assertIsNone(db.session.get(LeagueAccess, (self.dave, self.jj)))

    def test_not_four_digits(self):
        self.set_pin()
        for pin in ("123", "12345", "abcd", "", None, 2468):
            res = self.unlock(pin)
            self.assertEqual((res.status_code, res.get_json().get("field")), (400, "pin"), pin)

    def test_guessing_is_limited(self):
        self.set_pin()
        for _ in range(MAX_PIN_FAILURES):
            self.unlock("0000")

        res = self.unlock(PIN)

        self.assertEqual(res.status_code, 429, "not even the right one, for now")
        self.assertIn("Try again in", res.get_json()["message"])
        self.assertIsNone(db.session.get(LeagueAccess, (self.dave, self.jj)))

        # Once the wait is over, the right PIN works and the count starts again.
        db.session.execute(
            db.text(
                "UPDATE Pin_Attempts SET first_failed_at = datetime('now', :offset) WHERE user_id = :uid"
            ),
            {"offset": f"-{PIN_LOCKOUT_SECONDS + 1} seconds", "uid": self.dave},
        )
        db.session.commit()
        self.assertEqual(self.unlock(PIN).status_code, 200)
        self.assertIsNone(db.session.get(PinAttempt, (self.dave, self.jj)))

    def test_needs_a_login(self):
        self._headers = {}
        self.assertEqual(self.unlock(PIN).status_code, 401)


class PlayingNeedsThePin(LeaguesTestCase):
    def test_joining_and_confirming_are_refused(self):
        res = self.join(self.dave)

        self.assertEqual(res.status_code, 403)
        self.assertTrue(res.get_json()["read_only"])
        self.assertEqual(res.get_json()["league_id"], self.jj)
        self.assertIsNone(self.entry(self.dave))
        confirm = self.post("/queue/confirm", json={"league_id": self.jj})
        self.assertEqual(confirm.status_code, 403)

    def test_after_the_pin_joining_works(self):
        self.set_pin()
        self.login_as(self.dave)
        self.unlock(PIN)

        self.assertEqual(self.join(self.dave).status_code, 200)
        self.assertIsNotNone(self.entry(self.dave))

    def test_status_says_read_only(self):
        self.login_as(self.dave)
        body = self.get(f"/match/status?league_id={self.jj}").get_json()
        self.assertEqual(body["status"], "idle")
        self.assertTrue(body["read_only"])

    def test_leaving_never_needs_it(self):
        self.let_in(self.dave)
        self.join(self.dave)
        self.backdate_queue_join(self.dave, 60, league=self.jj)
        self.set_pin("1357")  # everyone's access goes

        self.login_as(self.dave)
        res = self.post("/queue/leave", json={"league_id": self.jj})

        self.assertEqual(res.status_code, 200)

    def test_a_changed_pin_mid_game_asks_for_the_new_one_before_reporting(self):
        self.let_in(self.dave, self.erin)
        match = self.start_match(self.dave, self.erin, table_id=20)
        self.set_pin("1357")
        self.login_as(self.dave)

        refused = self.post("/match/record", json={"my_balls": 11, "opp_balls": 4, "match_id": match.match_id})
        self.assertEqual(refused.status_code, 403)
        self.assertIn("PIN has changed", refused.get_json()["message"])
        self.assertTrue(self.active_match(20).is_in_progress, "nothing recorded")

        self.unlock("1357")
        res = self.post("/match/record", json={"my_balls": 11, "opp_balls": 4, "match_id": match.match_id})
        self.assertEqual(res.status_code, 200)

    def test_an_app_from_before_still_plays_ccny(self):
        """Old apps send table_id and league_type, and CCNY players are already in."""
        self.login_as(self.alice)
        res = self.post("/queue/join", json={"table_id": 1, "league_type": "billiards"})
        self.assertEqual(res.status_code, 200)
        legacy = {l["league_type"]: l for l in self.client.get("/leagues").get_json()["leagues"]}
        self.assertEqual((legacy[BILLIARDS]["table_id"], legacy[PING_PONG]["table_id"]), (1, PING_PONG_TABLE_ID))
        self.assertEqual([e["username"] for e in self.client.get("/queue/1").get_json()], ["alice"])


class ChangingThePin(LeaguesTestCase):
    def setUp(self):
        super().setUp()
        self.make_admin(self.alice)
        self.login_as(self.alice)

    def change(self, pin, league=None):
        return self.post(f"/admin/leagues/{league or self.jj}/pin", json={"pin": pin})

    def test_everyone_has_to_enter_the_new_one(self):
        self.let_in(self.dave, self.erin)
        before = self.standing(self.dave, self.jj).elo

        res = self.change("9753")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["revoked"], 2)
        self.assertIsNone(db.session.get(LeagueAccess, (self.dave, self.jj)))
        self.assertEqual(self.standing(self.dave, self.jj).elo, before, "their place on the ladder stays")
        self.login_as(self.dave)
        self.assertEqual(self.unlock("9753").status_code, 200)

    def test_other_leagues_are_untouched(self):
        self.change("9753")
        self.assertIsNotNone(db.session.get(LeagueAccess, (self.dave, self.billiards_league_id)))

    def test_the_old_pin_stops_working(self):
        self.change("1111")
        self.change("2222")
        self.login_as(self.dave)
        self.assertEqual(self.unlock("1111").status_code, 403)

    def test_four_digits_only(self):
        res = self.change("12")
        self.assertEqual((res.status_code, res.get_json()["field"]), (400, "pin"))

    def test_the_pin_is_never_stored_as_itself(self):
        self.change("9753")
        self.assertNotIn("9753", db.session.get(League, self.jj).pin_hash)

    def test_only_the_organiser(self):
        self.login_as(self.dave)
        self.assertEqual(self.change("9753").status_code, 403)
        self.assertIsNone(db.session.get(League, self.jj).pin_hash)


class ManagingTables(LeaguesTestCase):
    def setUp(self):
        super().setUp()
        self.make_admin(self.alice)
        self.login_as(self.alice)

    def tables(self, league=None):
        return [t["table_name"] for t in self.client.get(f"/leagues/{league or self.jj}/tables").get_json()["tables"]]

    def test_add_rename_and_remove(self):
        added = self.post(f"/admin/leagues/{self.jj}/tables", json={"name": "  Back   Room "})
        self.assertEqual(added.status_code, 201)
        table_id = added.get_json()["table"]["table_id"]
        self.assertEqual(self.tables(), ["Table 1", "Table 2", "Back Room"])

        renamed = self.client.patch(
            f"/admin/tables/{table_id}", json={"name": "Table 3"}, headers=self._headers
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(self.tables(), ["Table 1", "Table 2", "Table 3"])

        removed = self.client.delete(f"/admin/tables/{table_id}", headers=self._headers)
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.tables(), ["Table 1", "Table 2"])

    def test_names_have_to_be_new_in_the_league(self):
        res = self.post(f"/admin/leagues/{self.jj}/tables", json={"name": "table 2"})
        self.assertEqual((res.status_code, res.get_json()["field"]), (400, "name"))
        self.assertEqual(self.post(f"/admin/leagues/{self.jj}/tables", json={"name": ""}).status_code, 400)
        # Another league's table can have the same name.
        self.assertEqual(
            self.post(f"/admin/leagues/{self.billiards_league_id}/tables", json={"name": "Table 2"}).status_code,
            201,
        )

    def test_a_table_in_use_cant_be_removed(self):
        self.let_in(self.dave, self.erin)
        self.start_match(self.dave, self.erin, table_id=21)

        res = self.client.delete("/admin/tables/21", headers=self._headers)

        self.assertEqual(res.status_code, 409)
        self.assertIn("dave and erin", res.get_json()["message"])
        self.assertEqual(self.tables(), ["Table 1", "Table 2"])

    def test_a_removed_tables_games_stay_in_the_history(self):
        self.let_in(self.dave, self.erin)
        match = self.start_match(self.dave, self.erin, table_id=21)
        self.login_as(self.dave)
        self.post("/match/record", json={"my_balls": 11, "opp_balls": 3, "match_id": match.match_id})
        self.login_as(self.dave)
        self.post("/table/step-down", json={})
        self.login_as(self.alice)

        self.assertEqual(self.client.delete("/admin/tables/21", headers=self._headers).status_code, 200)

        history = self.client.get(f"/matches/history?league_id={self.jj}").get_json()["matches"]
        self.assertEqual([m["match_id"] for m in history], [match.match_id])

    def test_a_new_table_takes_the_next_in_line_at_once(self):
        db.session.get(PoolTable, 21).is_active = False
        db.session.commit()
        self.let_in(self.bob, self.carol, self.dave, self.erin)
        for player in (self.bob, self.carol, self.dave, self.erin):
            join_queue(player, self.jj)
        attempt_matchmaking(self.jj)
        self.assertEqual(self.seats(20), (self.bob, self.carol))

        added = self.post(f"/admin/leagues/{self.jj}/tables", json={"name": "Table 3"})

        new_table = added.get_json()["table"]["table_id"]
        self.assertEqual(self.seats(new_table), (self.dave, self.erin))

    def test_only_the_organiser(self):
        self.login_as(self.dave)
        self.assertEqual(self.post(f"/admin/leagues/{self.jj}/tables", json={"name": "X"}).status_code, 403)
        self.assertEqual(self.client.delete("/admin/tables/20", headers=self._headers).status_code, 403)
        self.assertEqual(
            self.client.patch("/admin/tables/20", json={"name": "X"}, headers=self._headers).status_code, 403
        )


class OneLineManyTables(LeaguesTestCase):
    """The league's one queue feeds every table."""

    def setUp(self):
        super().setUp()
        self.let_in(self.alice, self.bob, self.carol, self.dave, self.erin)

    def test_four_players_two_free_tables_two_games(self):
        for player in (self.alice, self.bob, self.carol, self.dave):
            join_queue(player, self.jj)

        attempt_matchmaking(self.jj)

        self.assertEqual(self.seats(20), (self.alice, self.bob))
        self.assertEqual(self.seats(21), (self.carol, self.dave))
        self.assertEqual(self.queued_user_ids(self.jj), [])

    def test_a_waiting_king_gets_the_front_of_the_line(self):
        self.make_king(self.erin, table_id=21)
        for player in (self.alice, self.bob, self.carol):
            join_queue(player, self.jj)

        attempt_matchmaking(self.jj)

        self.assertEqual(self.seats(21), (self.erin, self.alice), "one player and a game starts")
        self.assertEqual(self.seats(20), (self.bob, self.carol))

    def test_one_player_alone_waits(self):
        join_queue(self.alice, self.jj)

        self.assertFalse(attempt_matchmaking(self.jj))
        self.assertIsNone(self.seats(20))
        self.assertFalse(self.entry(self.alice).is_called)

    def test_your_turn_names_the_table(self):
        self.make_king(self.erin, table_id=21)
        join_queue(self.alice, self.jj)
        self.backdate_queue_join(self.alice, A_WHILE, league=self.jj)
        attempt_matchmaking(self.jj)

        self.login_as(self.alice)
        body = self.get(f"/match/status?league_id={self.jj}").get_json()

        self.assertEqual(body["status"], "your_turn")
        self.assertEqual((body["table_id"], body["table_name"]), (21, "Table 2"))
        self.assertEqual(body["opponent"], "erin")
        queue = self.client.get(f"/leagues/{self.jj}/queue").get_json()
        self.assertEqual((queue[0]["table_id"], queue[0]["table_name"]), (21, "Table 2"))

    def test_whoever_is_up_keeps_their_table(self):
        """Someone joining doesn't move a player already called, or restart their minute."""
        for player in (self.alice, self.bob):
            join_queue(player, self.jj)
            self.backdate_queue_join(player, A_WHILE, league=self.jj)
        attempt_matchmaking(self.jj)
        called_to = self.entry(self.alice).table_id
        self.backdate_turn(self.alice, 30, league=self.jj)

        join_queue(self.carol, self.jj)
        attempt_matchmaking(self.jj)

        self.assertEqual(self.entry(self.alice).table_id, called_to)
        self.login_as(self.alice)
        left = self.get(f"/match/status?league_id={self.jj}").get_json()["seconds_left"]
        self.assertLessEqual(left, 31, "the same minute, still running")

    def test_players_left_alone_at_two_tables_are_paired(self):
        for player in (self.alice, self.bob, self.carol, self.dave):
            join_queue(player, self.jj)
            self.backdate_queue_join(player, A_WHILE, league=self.jj)
        attempt_matchmaking(self.jj)  # alice+bob up at 20, carol+dave at 21
        db.session.delete(self.entry(self.bob))
        db.session.delete(self.entry(self.dave))
        db.session.commit()

        attempt_matchmaking(self.jj)

        alice, carol = self.entry(self.alice), self.entry(self.carol)
        self.assertEqual(alice.table_id, carol.table_id, "the two left alone play each other")
        self.assertTrue(alice.is_called and carol.is_called)

    def test_a_removed_table_sends_its_players_elsewhere(self):
        self.make_admin(self.erin)
        for player in (self.alice, self.bob):
            join_queue(player, self.jj)
            self.backdate_queue_join(player, A_WHILE, league=self.jj)
        attempt_matchmaking(self.jj)
        self.assertEqual(self.entry(self.alice).table_id, 20)

        self.login_as(self.erin)
        self.client.delete("/admin/tables/20", headers=self._headers)

        self.assertEqual(self.entry(self.alice).table_id, 21)
        self.assertEqual(self.entry(self.bob).table_id, 21)

    def test_leagues_dont_share_a_line(self):
        join_queue(self.alice, self.jj)
        join_queue(self.bob, PING_PONG)

        self.assertFalse(attempt_matchmaking(self.jj))
        self.assertFalse(attempt_matchmaking(PING_PONG))
        self.assertEqual(self.queued_user_ids(self.jj), [self.alice])


class SeparateLadders(LeaguesTestCase):
    def test_a_game_in_one_league_moves_only_its_ladder(self):
        self.let_in(self.alice, self.bob)
        ccny_before = (self.rating(self.alice, PING_PONG), self.rating(self.bob, PING_PONG))
        match = self.start_match(self.alice, self.bob, table_id=20)
        self.login_as(self.alice)

        res = self.post("/match/record", json={"my_balls": 11, "opp_balls": 5, "match_id": match.match_id, "league_id": self.jj})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.standing(self.alice, self.jj).wins, 1)
        self.assertEqual((self.rating(self.alice, PING_PONG), self.rating(self.bob, PING_PONG)), ccny_before)
        jj_ladder = [p["username"] for p in self.client.get(f"/leaderboard?league_id={self.jj}").get_json()]
        self.assertEqual(jj_ladder, ["alice", "bob"])

    def test_badges_are_per_league(self):
        self.let_in(self.alice, self.bob)
        match = self.start_match(self.alice, self.bob, table_id=20)
        self.login_as(self.alice)
        self.post("/match/record", json={"my_balls": 11, "opp_balls": 5, "match_id": match.match_id})

        jj = self.client.get(f"/players/{self.alice}/badges?league_id={self.jj}").get_json()
        ccny = self.client.get(f"/players/{self.alice}/badges?league_type=ping_pong").get_json()

        self.assertIn("first_blood", {b["key"] for b in jj["badges"] if b["earned"]})
        self.assertNotIn("first_blood", {b["key"] for b in ccny["badges"] if b["earned"]})

    def test_the_profile_lists_every_league_youre_in(self):
        self.let_in(self.alice)
        self.login_as(self.alice)
        profile = self.get("/profile").get_json()["profile"]

        self.assertEqual(
            [s["name"] for s in profile["standings"]], ["CCNY Billiards", "CCNY Ping Pong", "John Jay Ping Pong"]
        )
        self.assertEqual(set(profile["leagues"]), {BILLIARDS, PING_PONG}, "CCNY's two, as apps from before read")


class DeletedAccounts(LeaguesTestCase):
    def test_lose_their_access(self):
        from logic.account import remove_account

        self.let_in(self.dave)
        remove_account(self.dave)

        self.assertEqual(
            db.session.scalars(db.select(LeagueAccess).where(LeagueAccess.user_id == self.dave)).all(), []
        )


if __name__ == "__main__":
    unittest.main()
