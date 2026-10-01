"""
Starting a league over (a new season): ratings, records and ranks in one
league back to a new player's, with a backup first.
"""
import json
import os
import tempfile
import unittest

from tests.conftest_base import PING_PONG_TABLE_ID, BaseTestCase
from models import PING_PONG, Match, Player, PoolTable, db

from logic.record_match import record_match_result
from logic.seasons import league_standings, reset_league_standings


class ResetLeague(BaseTestCase):
    def setUp(self):
        super().setUp()
        # A ping pong game and a billiards game, so both leagues have results.
        record_match_result(
            self.start_match(self.alice, self.bob, table_id=PING_PONG_TABLE_ID),
            self.alice, self.bob, 20, 11, 5, league=PING_PONG,
        )
        record_match_result(self.start_match(self.carol, self.bob), self.carol, self.bob, 16, 8, 2)
        table = db.session.get(PoolTable, PING_PONG_TABLE_ID)
        table.table_record_streak = 4
        db.session.commit()

    def player(self, user_id):
        db.session.expire_all()
        return db.session.get(Player, user_id)

    def test_everyone_starts_the_league_again_at_zero(self):
        count = reset_league_standings(PING_PONG)

        self.assertEqual(count, 3)
        for user_id in (self.alice, self.bob, self.carol):
            p = self.player(user_id)
            self.assertEqual((p.ping_pong_elo, p.ping_pong_wins, p.ping_pong_losses), (0, 0, 0))
            self.assertEqual(p.ping_pong_rank.rank_name, "Bronze", "the rank a rating of 0 earns")

    def test_the_other_league_is_untouched(self):
        before = (self.player(self.carol).elo_rating, self.player(self.carol).total_wins)
        reset_league_standings(PING_PONG)
        after = (self.player(self.carol).elo_rating, self.player(self.carol).total_wins)
        self.assertEqual(before, after)
        self.assertEqual(after[1], 1)

    def test_finished_games_stay_in_the_history(self):
        reset_league_standings(PING_PONG)
        finished = db.session.scalar(
            db.select(db.func.count()).select_from(Match).where(Match.match_status == Match.STATUS_FINISHED)
        )
        self.assertEqual(finished, 2)

    def test_the_tables_streaks_start_over(self):
        reset_league_standings(PING_PONG)
        db.session.expire_all()
        table = db.session.get(PoolTable, PING_PONG_TABLE_ID)
        self.assertEqual((table.current_streak, table.table_record_streak), (0, 0))
        self.assertEqual(db.session.get(PoolTable, 1).current_streak, 1, "billiards keeps its streak")

    def test_the_backup_has_everyones_old_numbers(self):
        alice = next(p for p in league_standings(PING_PONG) if p["user_id"] == self.alice)
        self.assertEqual((alice["elo"], alice["wins"], alice["losses"]), (1220, 1, 0))

    def test_an_unknown_league_is_refused(self):
        with self.assertRaises(ValueError):
            reset_league_standings("darts")


class ResetLeagueCommand(BaseTestCase):
    def setUp(self):
        super().setUp()
        record_match_result(
            self.start_match(self.alice, self.bob, table_id=PING_PONG_TABLE_ID),
            self.alice, self.bob, 20, 11, 5, league=PING_PONG,
        )
        self.backups = tempfile.mkdtemp()
        self.runner = self.app.test_cli_runner()

    def test_backs_up_then_resets(self):
        result = self.runner.invoke(args=["reset-league", "ping_pong", "--yes", "--backup-dir", self.backups])

        self.assertEqual(result.exit_code, 0, result.output)
        files = os.listdir(self.backups)
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.backups, files[0])) as f:
            saved = json.load(f)
        self.assertEqual(saved["league"], "ping_pong")
        self.assertIn(1220, [p["elo"] for p in saved["players"]])
        db.session.expire_all()
        self.assertEqual(db.session.get(Player, self.alice).ping_pong_elo, 0)

    def test_answering_no_changes_nothing(self):
        result = self.runner.invoke(
            args=["reset-league", "ping_pong", "--backup-dir", self.backups], input="n\n"
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(os.listdir(self.backups), [])
        db.session.expire_all()
        self.assertEqual(db.session.get(Player, self.alice).ping_pong_elo, 1220)

    def test_only_real_leagues(self):
        result = self.runner.invoke(args=["reset-league", "chess", "--yes", "--backup-dir", self.backups])
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(os.listdir(self.backups), [])


if __name__ == "__main__":
    unittest.main()
