"""
Taking back a finished game that shouldn't count - played by accident,
say: the game leaves the history and its points go back where they
came from.
"""
import json
import os
import tempfile
import unittest

from tests.conftest_base import PING_PONG_TABLE_ID, BaseTestCase
from models import PING_PONG, Match, Player, db

from logic.corrections import GameProblem, game_summary, void_finished_match
from logic.match_history import player_history
from logic.record_match import report_result


class VoidTestCase(BaseTestCase):
    def numbers(self, user_id, league=PING_PONG):
        db.session.expire_all()
        player = db.session.get(Player, user_id)
        fields = Player.LEAGUE_FIELDS[league]
        rank = getattr(player, fields["rank"])
        return (
            getattr(player, fields["elo"]),
            getattr(player, fields["wins"]),
            getattr(player, fields["losses"]),
            rank.rank_name if rank else None,
        )

    def ping_pong_game(self, winner, loser, points=(11, 3)):
        """A finished ping pong game, reported by the winner. Returns its match_id."""
        match = self.start_match(winner, loser, table_id=PING_PONG_TABLE_ID)
        outcome, _ = report_result(winner, *points, expected_match_id=match.match_id, league_type=PING_PONG)
        self.assertEqual(outcome, "recorded")
        # The winner stays on as king; clear the table for the next game.
        from logic.manage_queue import step_down

        step_down(winner)
        return match.match_id


class VoidingAGame(VoidTestCase):
    def test_the_points_go_back_and_the_game_leaves_the_history(self):
        alice_before, bob_before = self.numbers(self.alice), self.numbers(self.bob)
        game = self.ping_pong_game(self.alice, self.bob)
        self.assertNotEqual(self.numbers(self.alice), alice_before)

        result = void_finished_match(game)

        # Points and record as they were; the rank is the one that rating
        # earns (the test players start with none recorded).
        self.assertEqual(self.numbers(self.alice)[:3], alice_before[:3])
        self.assertEqual(self.numbers(self.bob)[:3], bob_before[:3])
        self.assertEqual(self.numbers(self.alice)[3], "Silver")
        self.assertIsNone(db.session.get(Match, game))
        self.assertEqual(player_history(self.alice, PING_PONG), [])
        self.assertEqual(result["before"]["score"], [11, 3])

    def test_the_rank_follows_the_rating_back(self):
        """bob starts at Silver (1100+); the game drops him to Bronze, the void restores it."""
        bob = db.session.get(Player, self.bob)
        bob.ping_pong_elo = 1110
        db.session.commit()
        from logic.record_match import update_player_rank

        update_player_rank(db.session.get(Player, self.bob), PING_PONG)
        db.session.commit()
        game = self.ping_pong_game(self.alice, self.bob)
        self.assertEqual(self.numbers(self.bob)[3], "Bronze")

        void_finished_match(game)

        self.assertEqual(self.numbers(self.bob), (1110, 0, 0, "Silver"))

    def test_games_played_since_stay_as_they_were(self):
        first = self.ping_pong_game(self.alice, self.bob)
        second = self.ping_pong_game(self.carol, self.bob)
        second_change = db.session.get(Match, second).elo_change
        bob_now = self.numbers(self.bob)
        first_change = db.session.get(Match, first).elo_change

        void_finished_match(first)

        self.assertIsNotNone(db.session.get(Match, second))
        self.assertEqual(db.session.get(Match, second).elo_change, second_change)
        bob_after = self.numbers(self.bob)
        self.assertEqual(bob_after[0], bob_now[0] + first_change)
        self.assertEqual((bob_after[1], bob_after[2]), (0, 1), "still lost to carol")

    def test_the_other_league_is_untouched(self):
        billiards_before = self.numbers(self.alice, league="billiards")
        game = self.ping_pong_game(self.alice, self.bob)

        void_finished_match(game)

        self.assertEqual(self.numbers(self.alice, league="billiards"), billiards_before)

    def test_a_record_never_goes_below_zero(self):
        """After a league reset, an older game's win is already gone."""
        game = self.ping_pong_game(self.alice, self.bob)
        alice = db.session.get(Player, self.alice)
        alice.ping_pong_wins = 0
        db.session.commit()

        void_finished_match(game)

        self.assertEqual(self.numbers(self.alice)[1], 0)


class NothingToVoid(VoidTestCase):
    def test_an_unknown_game(self):
        with self.assertRaises(GameProblem) as caught:
            void_finished_match(999)
        self.assertIn("no game #999", str(caught.exception))

    def test_a_game_still_going(self):
        match = self.start_match(self.alice, self.bob, table_id=PING_PONG_TABLE_ID)
        with self.assertRaises(GameProblem) as caught:
            game_summary(match.match_id)
        self.assertIn("hasn't finished", str(caught.exception))
        self.assertIsNotNone(db.session.get(Match, match.match_id), "left alone")


class VoidGameCommand(VoidTestCase):
    def setUp(self):
        super().setUp()
        self.game = self.ping_pong_game(self.alice, self.bob)
        self.backups = tempfile.mkdtemp()
        self.runner = self.app.test_cli_runner()

    def run_command(self, *args, **kwargs):
        return self.runner.invoke(args=["void-game", *map(str, args), "--backup-dir", self.backups], **kwargs)

    def test_shows_the_change_backs_up_then_voids(self):
        result = self.run_command(self.game, "--yes")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("alice beat bob 11-3", result.output)
        files = os.listdir(self.backups)
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.backups, files[0])) as f:
            saved = json.load(f)
        self.assertEqual(saved["game"]["match_id"], self.game)
        self.assertEqual(saved["game"]["winner"]["username"], "alice")
        db.session.expire_all()
        self.assertIsNone(db.session.get(Match, self.game))

    def test_answering_no_changes_nothing(self):
        result = self.run_command(self.game, input="n\n")

        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(os.listdir(self.backups), [])
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(Match, self.game))

    def test_an_unknown_game_says_so(self):
        result = self.run_command(999, "--yes")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("no game #999", result.output)
        self.assertEqual(os.listdir(self.backups), [])


if __name__ == "__main__":
    unittest.main()
