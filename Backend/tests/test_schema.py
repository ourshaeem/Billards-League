"""
ensure_schema() and check_schema().

The bug these guard: the models described columns (player_one_id,
player_two_id) that the real database never had, and a Matches row from
the original code - seats stored in winner_id/loser_id - sat in the table
looking like a king nobody could see. Every Join then failed with a SQL
error shown straight to the player.
"""
import unittest

from tests.conftest_base import BaseTestCase
from sqlalchemy.exc import DBAPIError, InternalError

from database import MYSQL_DEADLOCK, check_schema, ensure_schema, retry_on_deadlock
from models import PING_PONG, Match, Player, PoolTable, QueueEntry, db


class EnsureSchemaTests(BaseTestCase):
    def insert_legacy_match(self, status, winner_id, loser_id):
        """A row the way the original code wrote it: no king, seats in winner/loser."""
        db.session.execute(
            db.insert(Match).values(
                table_id=1,
                player_one_id=None,
                player_two_id=None,
                winner_id=winner_id,
                loser_id=loser_id,
                match_status=status,
            )
        )
        db.session.commit()

    def only_match(self):
        db.session.expire_all()
        matches = list(db.session.scalars(db.select(Match)))
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_old_active_king_row_becomes_a_king_waiting(self):
        """Exactly the row found in the live database."""
        self.insert_legacy_match(Match.STATUS_ACTIVE, winner_id=self.bob, loser_id=None)

        ensure_schema()

        match = self.only_match()
        self.assertEqual(match.player_one_id, self.bob)
        self.assertIsNone(match.player_two_id)
        self.assertIsNone(match.winner_id, "nobody has won a game that hasn't happened")
        self.assertTrue(match.is_awaiting_challenger)

    def test_old_active_game_keeps_both_players_and_loses_the_fake_result(self):
        self.insert_legacy_match(Match.STATUS_ACTIVE, winner_id=self.alice, loser_id=self.bob)

        ensure_schema()

        match = self.only_match()
        self.assertEqual((match.player_one_id, match.player_two_id), (self.alice, self.bob))
        self.assertIsNone(match.winner_id)
        self.assertIsNone(match.loser_id)

    def test_old_finished_row_keeps_its_result_and_gains_seats(self):
        self.insert_legacy_match(Match.STATUS_FINISHED, winner_id=self.alice, loser_id=self.bob)

        ensure_schema()

        match = self.only_match()
        self.assertEqual((match.winner_id, match.loser_id), (self.alice, self.bob))
        self.assertEqual((match.player_one_id, match.player_two_id), (self.alice, self.bob))

    def test_running_twice_changes_nothing_the_second_time(self):
        self.insert_legacy_match(Match.STATUS_ACTIVE, winner_id=self.bob, loser_id=None)
        ensure_schema()

        # Now a real game gets its result; a second startup must not touch it.
        match = self.only_match()
        match.player_two_id = self.alice
        match.match_status = Match.STATUS_FINISHED
        match.winner_id, match.loser_id = self.alice, self.bob
        db.session.commit()

        ensure_schema()

        match = self.only_match()
        self.assertEqual((match.player_one_id, match.player_two_id), (self.bob, self.alice))
        self.assertEqual(match.winner_id, self.alice)

    def test_converted_king_is_matched_with_the_player_stuck_in_the_queue(self):
        """The whole reported bug, end to end: after startup, the queue moves."""
        self.insert_legacy_match(Match.STATUS_ACTIVE, winner_id=self.bob, loser_id=None)
        db.session.add(QueueEntry(user_id=self.alice, table_id=1, queue_position=1))
        db.session.commit()

        ensure_schema()

        res = self.client.get("/match/status", headers=self.auth_headers(self.alice))
        body = res.get_json()
        self.assertEqual(body["status"], "playing")
        self.assertEqual(body["opponent"], "bob")

    def test_adds_table_one_when_missing(self):
        db.session.delete(db.session.get(PoolTable, 1))
        db.session.commit()

        ensure_schema()

        self.assertIsNotNone(db.session.get(PoolTable, 1))

    def test_columns_added_since_are_added_to_an_older_database(self):
        """A database from before profiles and ping pong gains the columns."""
        for table, column in (
            ("Players", "profile_picture"),
            ("Players", "country_flag"),
            ("Players", "ping_pong_wins"),
            ("Pool_Tables", "league_type"),
        ):
            db.session.execute(db.text(f"ALTER TABLE {table} DROP COLUMN {column}"))
        db.session.commit()
        self.assertFalse(check_schema())

        ensure_schema()

        self.assertTrue(check_schema())
        db.session.expire_all()
        self.assertEqual(db.session.get(PoolTable, 1).league_type, "billiards",
                         "an existing table is a pool table")
        self.assertEqual(db.session.get(Player, self.alice).ping_pong_wins, 0)

    def test_adds_a_ping_pong_table_when_there_is_none(self):
        db.session.execute(db.delete(PoolTable).where(PoolTable.league_type == PING_PONG))
        db.session.commit()

        ensure_schema()
        ensure_schema()

        tables = list(db.session.scalars(db.select(PoolTable).where(PoolTable.league_type == PING_PONG)))
        self.assertEqual(len(tables), 1, "added once, however many times it runs")

    def test_players_new_to_ping_pong_get_the_starting_rank(self):
        newcomer = self.add_player("dave", ping_pong_elo=0)
        veteran = self.add_player("erin", ping_pong_elo=0)
        db.session.get(Player, veteran).ping_pong_losses = 3
        db.session.commit()

        ensure_schema()

        db.session.expire_all()
        self.assertEqual(db.session.get(Player, newcomer).ping_pong_rank.rank_name, "Bronze")
        self.assertIsNone(
            db.session.get(Player, veteran).ping_pong_rank_id,
            "a rank that play produced is left alone",
        )

    def test_duplicate_queue_entries_are_removed_and_the_unique_index_restored(self):
        db.session.execute(db.text("DROP INDEX uq_queue_user_table"))
        for position in (1, 2):
            db.session.add(QueueEntry(user_id=self.alice, table_id=1, queue_position=position))
        db.session.commit()

        ensure_schema()

        self.assertEqual(self.queued_user_ids(), [self.alice])
        indexes = {i["name"] for i in db.inspect(db.engine).get_indexes("Queue")}
        self.assertIn("uq_queue_user_table", indexes)


class CheckSchemaTests(BaseTestCase):
    def test_passes_when_the_database_matches_the_models(self):
        self.assertTrue(check_schema())

    def test_reports_a_column_the_models_need_but_the_database_lacks(self):
        db.session.execute(db.text("ALTER TABLE Matches DROP COLUMN challenger_balls"))
        db.session.commit()

        self.assertFalse(check_schema())


class RetryOnDeadlockTests(BaseTestCase):
    """
    Found by the play-test bot: five taps on Join at once made MySQL
    cancel some of them as deadlocks, and those taps got a server error.
    """

    @staticmethod
    def mysql_error(errno):
        class Orig(Exception):
            pass

        orig = Orig("simulated")
        orig.errno = errno
        return InternalError("INSERT ...", {}, orig)

    def test_a_deadlock_is_retried_until_it_succeeds(self):
        calls = []

        @retry_on_deadlock
        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise self.mysql_error(MYSQL_DEADLOCK)
            return "done"

        self.assertEqual(flaky(), "done")
        self.assertEqual(len(calls), 3)

    def test_it_gives_up_eventually(self):
        @retry_on_deadlock
        def always_deadlocks():
            raise self.mysql_error(MYSQL_DEADLOCK)

        with self.assertRaises(DBAPIError):
            always_deadlocks()

    def test_other_database_errors_are_not_retried(self):
        calls = []

        @retry_on_deadlock
        def broken():
            calls.append(1)
            raise self.mysql_error(1054)  # unknown column

        with self.assertRaises(DBAPIError):
            broken()
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
