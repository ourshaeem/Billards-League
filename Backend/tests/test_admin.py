"""
The organiser's controls: an admin can take any player out of a queue or
off a table, from the apps.

What it's for: a player who joined and walked off, a king who left the
table without giving it up, or a game nobody will ever report used to
hold everyone else up until someone ran SQL by hand.
"""
import unittest

from tests.conftest_base import ApiTestCase, BaseTestCase, PING_PONG_TABLE_ID
from models import Match, Player, PoolTable, QueueEntry, db

from logic.manage_queue import RECENTLY_HERE_SECONDS, attempt_matchmaking, join_queue

# Long enough ago that joining no longer counts as being here.
A_WHILE = RECENTLY_HERE_SECONDS + 240


class AdminTestCase(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.dave = self.add_player("dave")
        self.make_admin(self.alice)
        self.login_as(self.alice)

    def make_admin(self, user_id, admin=True):
        db.session.get(Player, user_id).is_admin = admin
        db.session.commit()

    def remove_from_queue(self, user_id, **body):
        return self.post("/admin/queue/remove", json={"user_id": user_id, **body})

    def remove_from_table(self, user_id, **body):
        return self.post("/admin/table/remove", json={"user_id": user_id, **body})

    def entry(self, user_id, table_id=1):
        db.session.expire_all()
        return db.session.scalars(
            db.select(QueueEntry).where(
                QueueEntry.user_id == user_id, QueueEntry.table_id == table_id
            )
        ).first()

    def seats(self, table_id=1):
        db.session.expire_all()
        match = self.active_match(table_id)
        return None if match is None else (match.player_one_id, match.player_two_id)

    def ratings(self):
        db.session.expire_all()
        return {
            p.user_id: (p.elo_rating, p.total_wins, p.total_losses)
            for p in db.session.scalars(db.select(Player))
        }

    def finished_games(self):
        return db.session.scalar(
            db.select(db.func.count())
            .select_from(Match)
            .where(Match.match_status == Match.STATUS_FINISHED)
        )


class OnlyTheOrganiser(AdminTestCase):
    def test_a_player_who_isnt_an_admin_is_refused(self):
        join_queue(self.bob, 1)
        self.make_king(self.carol)
        self.login_as(self.dave)

        for res in (self.remove_from_queue(self.bob), self.remove_from_table(self.carol)):
            self.assertEqual(res.status_code, 403)
            self.assertIn("organiser", res.get_json()["message"])
        self.assertIsNotNone(self.entry(self.bob), "bob is still waiting")
        self.assertEqual(self.seats(), (self.carol, None), "carol still holds the table")

    def test_taking_the_right_away_works_at_once(self):
        """Checked against the database on every request, not the login token."""
        join_queue(self.bob, 1)
        self.make_admin(self.alice, admin=False)

        self.assertEqual(self.remove_from_queue(self.bob).status_code, 403)

    def test_needs_a_login(self):
        self._headers = {}
        self.assertEqual(self.remove_from_queue(self.bob).status_code, 401)
        self.assertEqual(self.remove_from_table(self.bob).status_code, 401)

    def test_the_profile_and_sign_in_say_who_is_an_admin(self):
        from logic.auth import hash_password

        self.assertTrue(self.get("/profile").get_json()["profile"]["is_admin"])
        self.login_as(self.bob)
        self.assertFalse(self.get("/profile").get_json()["profile"]["is_admin"])

        alice = db.session.get(Player, self.alice)
        alice.password_hash = hash_password("hunter22")
        db.session.commit()
        res = self.client.post("/login", json={"username": "alice", "password": "hunter22"})
        self.assertTrue(res.get_json()["is_admin"])

    def test_a_deleted_account_is_no_admin(self):
        from logic.account import remove_account

        remove_account(self.alice)

        db.session.expire_all()
        self.assertFalse(db.session.get(Player, self.alice).is_admin)

    def test_the_player_must_be_named_and_exist(self):
        join_queue(self.bob, 1)

        missing = self.post("/admin/queue/remove", json={"table_id": 1})
        not_a_number = self.remove_from_queue("bob")
        unknown = self.remove_from_queue(9999)

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(not_a_number.status_code, 400)
        self.assertEqual(unknown.status_code, 404)
        self.assertIsNotNone(self.entry(self.bob))


class TakingSomeoneOutOfTheQueue(AdminTestCase):
    def test_out_at_once_however_short_their_wait(self):
        """The wait before leaving binds players, not the organiser."""
        join_queue(self.bob, 1)
        join_queue(self.carol, 1)
        self.make_king(self.dave)
        # Bob is up against the king; carol waits behind him.
        self.backdate_queue_join(self.bob, A_WHILE)
        attempt_matchmaking(1)

        res = self.remove_from_queue(self.carol, table_id=1)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "removed")
        self.assertIn("carol", res.get_json()["message"])
        self.assertEqual(self.queued_user_ids(), [self.bob])

    def test_when_it_was_their_turn_the_next_in_line_is_up(self):
        self.make_king(self.dave)
        for player in (self.bob, self.carol):
            join_queue(player, 1)
            self.backdate_queue_join(player, A_WHILE)
        attempt_matchmaking(1)
        self.assertTrue(self.entry(self.bob).is_called, "bob is up, and hasn't said he's here")

        self.remove_from_queue(self.bob)

        self.assertIsNone(self.entry(self.bob))
        self.assertTrue(self.entry(self.carol).is_called, "carol is up now")
        self.assertEqual(self.seats(), (self.dave, None), "no game until carol says she's here")

    def test_the_league_picks_the_queue(self):
        join_queue(self.bob, PING_PONG_TABLE_ID)

        res = self.remove_from_queue(self.bob, league_type="ping_pong")

        self.assertEqual(res.status_code, 200)
        self.assertIsNone(self.entry(self.bob, PING_PONG_TABLE_ID))

    def test_someone_not_in_the_queue(self):
        res = self.remove_from_queue(self.bob, table_id=1)

        self.assertEqual(res.status_code, 404)
        self.assertIn("bob", res.get_json()["message"])


class TakingSomeoneOffTheTable(AdminTestCase):
    def test_a_king_alone_gives_the_table_to_the_next_two(self):
        self.make_king(self.bob)
        # Queued but not yet matched: the king had a challenger seat for
        # only one of them.
        for player in (self.carol, self.dave):
            db.session.add(QueueEntry(user_id=player, table_id=1, queue_position=player))
        db.session.commit()

        res = self.remove_from_table(self.bob, table_id=1)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "table_freed")
        self.assertEqual(self.seats(), (self.carol, self.dave), "the first two play")

    def test_a_king_alone_with_nobody_waiting_leaves_the_table_free(self):
        self.make_king(self.bob)

        self.remove_from_table(self.bob)

        self.assertIsNone(self.seats())
        self.assertEqual(self.get("/table/1").get_json()["table"]["state"], "free")

    def test_mid_game_the_game_is_called_off_and_the_other_player_keeps_the_table(self):
        match = self.start_match(self.bob, self.carol)
        before = self.ratings()

        res = self.remove_from_table(self.bob, match_id=match.match_id)

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "game_called_off")
        self.assertIn("carol keeps the table", body["message"])
        self.assertEqual(self.seats(), (self.carol, None))
        self.assertEqual(self.ratings(), before, "nothing recorded, no rating moved")
        self.assertEqual(self.finished_games(), 0)

        self.login_as(self.bob)
        self.assertEqual(self.get("/match/status?table_id=1").get_json()["status"], "idle")

    def test_taking_off_the_challenger_leaves_the_king_and_their_streak(self):
        self.start_match(self.bob, self.carol)
        table = db.session.get(PoolTable, 1)
        table.current_king_id, table.current_streak = self.bob, 3
        db.session.commit()

        self.remove_from_table(self.carol)

        self.assertEqual(self.seats(), (self.bob, None))
        self.assertEqual(self.get("/table/1").get_json()["table"]["king_streak"], 3)

    def test_a_removed_kings_streak_ends(self):
        self.start_match(self.bob, self.carol)
        table = db.session.get(PoolTable, 1)
        table.current_king_id, table.current_streak = self.bob, 3
        db.session.commit()

        self.remove_from_table(self.bob)

        snapshot = self.get("/table/1").get_json()["table"]
        self.assertEqual(snapshot["king"]["user_id"], self.carol)
        self.assertEqual(snapshot["king_streak"], 0)

    def test_the_next_in_line_is_up_against_whoever_stays(self):
        self.start_match(self.bob, self.carol)
        join_queue(self.dave, 1)

        self.remove_from_table(self.bob)

        self.assertEqual(self.seats(), (self.carol, self.dave), "dave just joined, so he's here")

    def test_a_score_sent_for_the_called_off_game_lands_nowhere(self):
        match = self.start_match(self.bob, self.carol)
        before = self.ratings()
        self.remove_from_table(self.bob)

        self.login_as(self.carol)
        res = self.post(
            "/match/record", json={"my_balls": 8, "opp_balls": 3, "match_id": match.match_id}
        )

        self.assertNotEqual(res.status_code, 200)
        self.assertEqual(self.ratings(), before)
        self.assertEqual(self.seats(), (self.carol, None))

    def test_nothing_happens_if_the_game_has_changed_since(self):
        match = self.start_match(self.bob, self.carol)

        res = self.remove_from_table(self.bob, match_id=match.match_id + 100)

        self.assertEqual(res.status_code, 409)
        self.assertEqual(self.seats(), (self.bob, self.carol))

    def test_someone_not_at_this_table(self):
        self.start_match(self.bob, self.carol, table_id=PING_PONG_TABLE_ID)

        res = self.remove_from_table(self.bob, table_id=1)

        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.seats(PING_PONG_TABLE_ID), (self.bob, self.carol))


class SetAdminCommand(BaseTestCase):
    def run_command(self, *args):
        return self.app.test_cli_runner().invoke(args=["set-admin", *args])

    def test_grants_and_takes_away(self):
        result = self.run_command("bob")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("bob is now an admin", result.output)
        db.session.expire_all()
        self.assertTrue(db.session.get(Player, self.bob).is_admin)

        self.run_command("bob", "--off")
        db.session.expire_all()
        self.assertFalse(db.session.get(Player, self.bob).is_admin)

    def test_an_unknown_name(self):
        result = self.run_command("nobody")

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("no account", result.output)


if __name__ == "__main__":
    unittest.main()
