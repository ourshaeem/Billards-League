"""
Adding games that never reached the app - played while the server was
down - so they count as if they had been reported at the time.
"""
import json
import os
import tempfile
import unittest

from tests.conftest_base import PING_PONG_TABLE_ID, BaseTestCase
from models import PING_PONG, Match, Player, db

from logic.corrections import GameProblem, add_past_games
from logic.manage_queue import step_down
from logic.match_history import league_history
from logic.record_match import report_result


class AddGamesTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.dave = self.add_player("dave")

    def numbers(self, user_id):
        db.session.expire_all()
        player = db.session.get(Player, user_id)
        return (player.ping_pong_elo, player.ping_pong_wins, player.ping_pong_losses)

    def finished(self):
        return list(
            db.session.scalars(
                db.select(Match)
                .where(Match.match_status == Match.STATUS_FINISHED)
                .order_by(Match.match_id)
            )
        )


class AddingPastGames(AddGamesTestCase):
    def test_the_ladder_ends_up_as_if_they_had_been_reported_one_by_one(self):
        sequence = [(0, 1, 11, 4), (1, 0, 11, 9), (0, 1, 12, 10)]

        # alice and bob's games added afterwards...
        added = add_past_games(
            PING_PONG,
            [((self.alice, self.bob)[w], (self.alice, self.bob)[l], ws, ls) for w, l, ws, ls in sequence],
        )
        # ...and the same games between carol and dave, reported live.
        live = []
        for w, l, ws, ls in sequence:
            winner, loser = (self.carol, self.dave)[w], (self.carol, self.dave)[l]
            match = self.start_match(winner, loser, table_id=PING_PONG_TABLE_ID)
            _, details = report_result(winner, ws, ls, expected_match_id=match.match_id)
            live.append(details["elo_change"])
            step_down(winner)

        self.assertEqual([game["elo_change"] for game in added], live)
        self.assertEqual(self.numbers(self.alice), self.numbers(self.carol))
        self.assertEqual(self.numbers(self.bob), self.numbers(self.dave))
        self.assertEqual(self.numbers(self.alice)[1:], (2, 1))

    def test_each_game_is_saved_with_its_score_in_order(self):
        add_past_games(PING_PONG, [(self.alice, self.bob, 11, 4), (self.carol, self.alice, 11, 9)])

        games = self.finished()
        self.assertEqual(
            [(g.winner_id, g.loser_id, g.balls_for(g.winner_id), g.balls_for(g.loser_id)) for g in games],
            [(self.alice, self.bob, 11, 4), (self.carol, self.alice, 11, 9)],
        )
        self.assertTrue(all(g.table_id == PING_PONG_TABLE_ID for g in games))
        history = league_history(PING_PONG, limit=10)
        self.assertEqual([g["match_id"] for g in history], [games[1].match_id, games[0].match_id],
                         "newest first, the last one added on top")

    def test_nobody_at_the_table_moves(self):
        self.make_king(self.dave, table_id=PING_PONG_TABLE_ID)

        add_past_games(PING_PONG, [(self.alice, self.bob, 11, 4)])

        active = self.active_match(PING_PONG_TABLE_ID)
        self.assertEqual((active.player_one_id, active.player_two_id), (self.dave, None))

    def test_billiards_is_untouched(self):
        before = db.session.get(Player, self.alice).elo_rating

        add_past_games(PING_PONG, [(self.alice, self.bob, 11, 4)])

        db.session.expire_all()
        self.assertEqual(db.session.get(Player, self.alice).elo_rating, before)

    def test_a_loser_at_zero_stays_there(self):
        bob = db.session.get(Player, self.bob)
        bob.ping_pong_elo = 0
        db.session.commit()

        [game] = add_past_games(PING_PONG, [(self.alice, self.bob, 11, 4)])

        self.assertEqual(self.numbers(self.bob)[0], 0)
        self.assertEqual(game["loser_elo_change"], 0)


class NothingAddedWhenSomethingIsWrong(AddGamesTestCase):
    def assert_refused(self, games):
        before = {p: self.numbers(p) for p in (self.alice, self.bob, self.carol)}
        with self.assertRaises(GameProblem):
            add_past_games(PING_PONG, games)
        self.assertEqual(self.finished(), [])
        self.assertEqual({p: self.numbers(p) for p in before}, before)

    def test_the_winners_score_has_to_come_first(self):
        self.assert_refused([(self.alice, self.bob, 11, 4), (self.bob, self.carol, 4, 11)])

    def test_a_score_that_cant_happen_in_ping_pong(self):
        self.assert_refused([(self.alice, self.bob, 11, 10)])

    def test_a_player_against_themselves(self):
        self.assert_refused([(self.alice, self.alice, 11, 4)])

    def test_a_player_who_doesnt_exist(self):
        self.assert_refused([(self.alice, self.bob, 11, 4), (self.alice, 9999, 11, 4)])


class AddGamesCommand(AddGamesTestCase):
    def setUp(self):
        super().setUp()
        self.runner = self.app.test_cli_runner()
        self.backups = tempfile.mkdtemp()
        db.session.get(Player, self.carol).username = "Tom Holland"
        db.session.commit()

    def run_command(self, *games, answer=None, yes=True):
        args = ["add-games", "ping_pong", "--backup-dir", self.backups]
        for game in games:
            args += ["--game", *game]
        if yes:
            args.append("--yes")
        return self.runner.invoke(args=args, input=answer)

    def test_adds_them_in_order_and_says_what_moved(self):
        result = self.run_command(("alice", "bob", "11-4"), ("bob", "Tom Holland", "11 - 9"))

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("1. alice beat bob 11-4", result.output)
        self.assertIn("2. bob beat Tom Holland 11-9", result.output)
        self.assertIn("alice +", result.output)
        self.assertEqual(len(self.finished()), 2)
        self.assertEqual(self.numbers(self.bob)[1:], (1, 1))

        [backup] = os.listdir(self.backups)
        with open(os.path.join(self.backups, backup)) as f:
            saved = json.load(f)
        self.assertEqual(saved["games"][1], {"winner": "bob", "loser": "Tom Holland", "score": [11, 9]})
        self.assertEqual({p["username"] for p in saved["players_before"]}, {"alice", "bob", "Tom Holland"})

    def test_an_unknown_name_adds_nothing(self):
        result = self.run_command(("alice", "bob", "11-4"), ("alice", "Ricky", "11-7"))

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("no account called 'Ricky'", result.output)
        self.assertEqual(self.finished(), [])
        self.assertEqual(os.listdir(self.backups), [])

    def test_a_bad_score_adds_nothing(self):
        result = self.run_command(("alice", "bob", "4-11"))

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("winner's score first", result.output)
        self.assertEqual(self.finished(), [])

    def test_answering_no_adds_nothing(self):
        result = self.run_command(("alice", "bob", "11-4"), yes=False, answer="n\n")

        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(self.finished(), [])
        self.assertEqual(os.listdir(self.backups), [])


if __name__ == "__main__":
    unittest.main()
