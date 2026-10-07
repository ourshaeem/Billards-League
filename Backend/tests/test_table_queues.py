"""
Choosing a table: waiting for one table, or for whichever frees up first.

What it's for: at a league with several tables, a player can say "Table 3"
and only ever be called there - or "first available" and go wherever a
seat opens. A table that needs a player takes the next in its own line,
and only when that line is empty the next in the line for any table.
Changing one's mind keeps one's place; it can't take a player away from a
table where their turn has already come. And each table's win record
says whose it is.
"""
import unittest

from tests.conftest_base import BaseTestCase, PING_PONG_TABLE_ID
from tests.test_multi_league import A_WHILE, LeaguesTestCase
from database import ensure_schema
from models import BILLIARDS, PING_PONG, League, Match, PoolTable, QueueEntry, db

from logic.manage_queue import (
    JOIN_RESULT_ALREADY_QUEUED,
    JOIN_RESULT_CALLED_ELSEWHERE,
    JOIN_RESULT_JOINED,
    JOIN_RESULT_NO_SUCH_TABLE,
    JOIN_RESULT_SWITCHED,
    attempt_matchmaking,
    get_queue_status,
    join_queue,
    view_queue,
)
from logic.record_match import record_match_result
from logic.seasons import reset_league_standings
from logic.tables import table_snapshot

TABLE_1, TABLE_2, TABLE_3 = 20, 21, 22


class TableLinesTestCase(LeaguesTestCase):
    """John Jay Ping Pong with three tables, and five players let in."""

    def setUp(self):
        super().setUp()
        db.session.add(PoolTable(table_id=TABLE_3, table_name="Table 3", league_id=self.jj, league_type=PING_PONG))
        db.session.commit()
        self.frank = self.add_player("frank")
        self.let_in(self.alice, self.bob, self.carol, self.dave, self.erin, self.frank)

    def join_for(self, user_id, table_id=None):
        """Join as the apps do, through the route; table_id None = first free table."""
        self.login_as(user_id)
        body = {"league_id": self.jj}
        if table_id is not None:
            body["table_id"] = table_id
        return self.post("/queue/join", json=body)

    def wait(self, user_id, table_id=None):
        """In the queue without matchmaking running, long enough ago to be asked."""
        join_queue(user_id, self.jj, table_id)
        self.backdate_queue_join(user_id, A_WHILE, league=self.jj)

    def target(self, user_id):
        return self.entry(user_id).target_table_id

    def busy(self, table_id):
        """A game in progress there, between two players from outside the league."""
        a, b = self.add_player(f"x{table_id}a"), self.add_player(f"x{table_id}b")
        self.start_match(a, b, table_id=table_id)


class JoiningForATable(TableLinesTestCase):
    def test_a_chosen_table_is_kept(self):
        res = self.join_for(self.alice, TABLE_2)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], JOIN_RESULT_JOINED)
        self.assertIn("Table 2", res.get_json()["message"])
        self.assertEqual(self.target(self.alice), TABLE_2)
        queue = self.client.get(f"/leagues/{self.jj}/queue").get_json()
        self.assertEqual((queue[0]["target_table_id"], queue[0]["target_table_name"]), (TABLE_2, "Table 2"))

    def test_no_table_means_the_first_free_one(self):
        self.join_for(self.alice)

        self.assertIsNone(self.target(self.alice))

    def test_another_leagues_table_is_refused(self):
        res = self.join_for(self.alice, 1)

        self.assertEqual(res.status_code, 400)
        self.assertIsNone(self.entry(self.alice))

    def test_a_removed_table_is_refused(self):
        db.session.get(PoolTable, TABLE_3).is_active = False
        db.session.commit()

        res = self.join_for(self.alice, TABLE_3)

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["field"], "table_id")
        self.assertIsNone(self.entry(self.alice))
        self.assertEqual(join_queue(self.alice, self.jj, TABLE_3), JOIN_RESULT_NO_SUCH_TABLE)

    def test_a_league_with_one_table_has_one_line(self):
        """Choosing the only table would otherwise jump everyone who didn't."""
        self.login_as(self.alice)
        self.post("/queue/join", json={"league_id": self.billiards_league_id, "table_id": 1})

        self.assertIsNone(self.entry(self.alice, league=self.billiards_league_id).target_table_id)

    def test_an_app_from_before_joins_the_line_for_any_table(self):
        """Old apps send their league's first table with league_type, to say which league."""
        db.session.add(PoolTable(table_id=11, table_name="Table 2", league_id=self.ping_pong_league_id, league_type=PING_PONG))
        db.session.commit()
        self.busy(PING_PONG_TABLE_ID)  # so neither is matched before we look
        self.login_as(self.alice)
        self.post("/queue/join", json={"table_id": PING_PONG_TABLE_ID, "league_type": PING_PONG})
        self.login_as(self.bob)
        self.post("/queue/join", json={"table_id": PING_PONG_TABLE_ID, "league_id": self.ping_pong_league_id})

        self.assertIsNone(self.entry(self.alice, league=self.ping_pong_league_id).target_table_id)
        self.assertEqual(self.entry(self.bob, league=self.ping_pong_league_id).target_table_id, PING_PONG_TABLE_ID)


class ChangingYourMind(TableLinesTestCase):
    def test_switching_tables_keeps_your_place(self):
        self.busy(TABLE_1), self.busy(TABLE_2), self.busy(TABLE_3)
        self.join_for(self.alice)
        self.join_for(self.bob)
        self.join_for(self.carol, TABLE_2)

        res = self.join_for(self.alice, TABLE_2)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], JOIN_RESULT_SWITCHED)
        self.assertIn("kept your place", res.get_json()["message"])
        self.assertEqual(self.target(self.alice), TABLE_2)
        self.assertEqual(get_queue_status(self.alice, self.jj)["queue_position"], 1, "ahead of carol: she joined first")
        self.assertEqual(get_queue_status(self.bob, self.jj)["queue_position"], 1, "bob is first for any table now")

    def test_back_to_any_table(self):
        join_queue(self.alice, self.jj, TABLE_2)

        self.assertEqual(join_queue(self.alice, self.jj), JOIN_RESULT_SWITCHED)
        self.assertIsNone(self.target(self.alice))

    def test_the_same_choice_again(self):
        join_queue(self.alice, self.jj, TABLE_2)

        self.assertEqual(join_queue(self.alice, self.jj, TABLE_2), JOIN_RESULT_ALREADY_QUEUED)

    def test_not_away_from_a_table_where_your_turn_has_come(self):
        self.make_king(self.erin, table_id=TABLE_1)
        self.wait(self.alice)
        attempt_matchmaking(self.jj)
        self.assertEqual(self.entry(self.alice).table_id, TABLE_1)

        res = self.join_for(self.alice, TABLE_2)

        self.assertEqual(res.status_code, 409)
        self.assertIn("It's your turn at Table 1", res.get_json()["message"])
        self.assertEqual(join_queue(self.alice, self.jj, TABLE_2), JOIN_RESULT_CALLED_ELSEWHERE)
        entry = self.entry(self.alice)
        self.assertIsNone(entry.target_table_id)
        self.assertEqual(entry.table_id, TABLE_1, "still up there")

    def test_but_choosing_that_same_table_is_fine(self):
        self.make_king(self.erin, table_id=TABLE_1)
        self.wait(self.alice)
        attempt_matchmaking(self.jj)

        self.assertEqual(join_queue(self.alice, self.jj, TABLE_1), JOIN_RESULT_SWITCHED)
        attempt_matchmaking(self.jj)
        self.assertEqual(self.entry(self.alice).table_id, TABLE_1)


class EachTableItsOwnLineFirst(TableLinesTestCase):
    def test_a_waiting_king_gets_the_next_who_chose_that_table(self):
        self.busy(TABLE_1), self.busy(TABLE_3)
        self.make_king(self.erin, table_id=TABLE_2)
        self.wait(self.alice)  # first in line, for any table
        self.wait(self.bob, TABLE_2)

        attempt_matchmaking(self.jj)

        self.assertEqual(self.entry(self.bob).table_id, TABLE_2)
        self.assertFalse(self.entry(self.alice).is_called, "alice waits: Table 2's own line came first")

    def test_with_nobody_waiting_for_it_the_any_line_steps_up(self):
        self.busy(TABLE_1), self.busy(TABLE_3)
        self.make_king(self.erin, table_id=TABLE_2)
        self.wait(self.bob, TABLE_1)  # Table 1 is taken
        self.wait(self.alice)

        attempt_matchmaking(self.jj)

        self.assertEqual(self.entry(self.alice).table_id, TABLE_2)
        self.assertFalse(self.entry(self.bob).is_called, "bob only plays at Table 1")

    def test_after_a_game_the_tables_own_line_first(self):
        self.busy(TABLE_1), self.busy(TABLE_3)
        match = self.start_match(self.alice, self.bob, table_id=TABLE_2)
        self.wait(self.carol)
        self.wait(self.dave, TABLE_2)

        record_match_result(match, self.alice, self.bob, 16)

        dave = self.entry(self.dave)
        self.assertTrue(dave.is_called, "dave is up against the king")
        self.assertEqual(dave.table_id, TABLE_2)
        self.assertFalse(self.entry(self.carol).is_called)

    def test_a_free_table_takes_its_own_line_then_any(self):
        self.busy(TABLE_1), self.busy(TABLE_2)
        self.wait(self.alice)
        self.wait(self.bob, TABLE_3)
        self.wait(self.carol)

        attempt_matchmaking(self.jj)

        self.assertEqual(self.entry(self.bob).table_id, TABLE_3)
        self.assertEqual(self.entry(self.alice).table_id, TABLE_3)
        self.assertFalse(self.entry(self.carol).is_called)

    def test_every_table_filled_from_the_right_lines(self):
        for player, table in ((self.alice, None), (self.bob, None), (self.carol, TABLE_3), (self.dave, None)):
            join_queue(player, self.jj, table)

        attempt_matchmaking(self.jj)

        self.assertEqual(self.seats(TABLE_1), (self.alice, self.bob))
        self.assertEqual(self.seats(TABLE_3), (self.carol, self.dave), "dave, alone at Table 2, goes to carol's")
        self.assertIsNone(self.seats(TABLE_2))

    def test_someone_who_chose_a_busy_table_isnt_sent_elsewhere(self):
        self.busy(TABLE_1), self.busy(TABLE_3)
        self.wait(self.alice, TABLE_1)
        self.wait(self.bob)

        self.assertFalse(attempt_matchmaking(self.jj))
        self.assertFalse(self.entry(self.alice).is_called)
        self.assertFalse(self.entry(self.bob).is_called, "alone at Table 2: nobody to play")

    def test_two_who_chose_different_tables_dont_meet(self):
        self.busy(TABLE_3)
        self.wait(self.alice, TABLE_1)
        self.wait(self.bob, TABLE_2)

        self.assertFalse(attempt_matchmaking(self.jj))
        self.assertIsNone(self.seats(TABLE_1))
        self.assertIsNone(self.seats(TABLE_2))


class WhereYouStand(TableLinesTestCase):
    def test_places_are_counted_in_your_own_line(self):
        for player, table in ((self.alice, None), (self.bob, TABLE_2), (self.carol, None), (self.dave, TABLE_2)):
            join_queue(player, self.jj, table)

        places = [(e["username"], e["queue_position"], e["target_table_id"]) for e in view_queue(self.jj)]

        self.assertEqual(
            places,
            [("alice", 1, None), ("bob", 1, TABLE_2), ("carol", 2, None), ("dave", 2, TABLE_2)],
        )
        self.assertEqual(get_queue_status(self.dave, self.jj)["queue_position"], 2)

    def test_status_says_which_table_youre_waiting_for(self):
        self.busy(TABLE_2)
        self.join_for(self.alice, TABLE_2)

        body = self.get(f"/match/status?league_id={self.jj}").get_json()

        self.assertEqual(body["status"], "queued")
        self.assertEqual((body["target_table_id"], body["target_table_name"]), (TABLE_2, "Table 2"))
        self.assertEqual(body["queue_position"], 1)


class WhenTablesGo(TableLinesTestCase):
    def setUp(self):
        super().setUp()
        self.make_admin(self.erin)

    def remove(self, table_id):
        self.login_as(self.erin)
        return self.client.delete(f"/admin/tables/{table_id}", headers=self._headers)

    def test_a_removed_tables_line_waits_for_any_table(self):
        self.busy(TABLE_1), self.busy(TABLE_2)
        join_queue(self.alice, self.jj, TABLE_3)
        join_queue(self.bob, self.jj, TABLE_2)

        self.assertEqual(self.remove(TABLE_3).status_code, 200)

        self.assertIsNone(self.target(self.alice))
        self.assertEqual(self.target(self.bob), TABLE_2, "Table 2's line is untouched")

    def test_down_to_one_table_its_one_line(self):
        self.busy(TABLE_1)
        join_queue(self.alice, self.jj, TABLE_1)
        join_queue(self.bob, self.jj, TABLE_2)

        self.remove(TABLE_2)
        self.remove(TABLE_3)

        self.assertIsNone(self.target(self.alice))
        self.assertIsNone(self.target(self.bob))


class TableRecordHolder(BaseTestCase):
    """CCNY's billiards table: whose is the record."""

    def game(self, winner, loser):
        match = db.session.scalars(
            db.select(Match).where(Match.table_id == 1, Match.match_status == Match.STATUS_ACTIVE)
        ).first()
        if match is None or match.player_two_id is not None:
            match = self.start_match(winner, loser)
        else:
            match.player_two_id = loser if match.player_one_id == winner else winner
            db.session.commit()
        record_match_result(match, winner, loser, 16)

    def holder(self):
        db.session.expire_all()
        snapshot = table_snapshot(1)
        holder = snapshot["table_record_holder"]
        return snapshot["table_record_streak"], (holder["username"] if holder else None)

    def test_the_first_to_set_it(self):
        self.game(self.alice, self.bob)
        self.game(self.alice, self.carol)

        self.assertEqual(self.holder(), (2, "alice"))

    def test_the_card_has_their_picture_and_name(self):
        self.game(self.alice, self.bob)

        card = table_snapshot(1)["table_record_holder"]
        self.assertEqual(card["user_id"], self.alice)
        self.assertIn("profile_picture", card)
        self.assertIn("country_flag", card)

    def test_a_longer_run_takes_it(self):
        self.game(self.alice, self.bob)
        self.game(self.alice, self.carol)
        self.game(self.bob, self.alice)
        self.game(self.bob, self.carol)
        self.assertEqual(self.holder(), (2, "alice"), "equalling it isn't taking it")

        self.game(self.bob, self.alice)

        self.assertEqual(self.holder(), (3, "bob"))

    def test_a_new_season_clears_it(self):
        self.game(self.alice, self.bob)

        reset_league_standings(BILLIARDS)

        self.assertEqual(self.holder(), (0, None))

    def test_records_from_before_are_given_their_holder(self):
        self.game(self.alice, self.bob)
        self.game(self.alice, self.carol)
        self.game(self.bob, self.alice)
        table = db.session.get(PoolTable, 1)
        table.table_record_holder_id = None
        db.session.commit()

        ensure_schema()
        ensure_schema()

        self.assertEqual(self.holder(), (2, "alice"))


if __name__ == "__main__":
    unittest.main()
