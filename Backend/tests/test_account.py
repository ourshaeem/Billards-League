"""
Deleting an account, and the privacy policy page.

Both app stores require in-app account deletion. What has to hold: every
personal detail goes, the account can't sign in or keep using an old
token, and nobody else's game history breaks.
"""
import os
import unittest
from unittest import mock

import bcrypt

from tests.conftest_base import ApiTestCase
from models import Match, Player, QueueEntry, db

PASSWORD = "hunter22"


class DeleteAccount(ApiTestCase):
    def setUp(self):
        super().setUp()
        # A real (quick) bcrypt hash, so the password check is the real one.
        for user_id in (self.alice, self.bob, self.carol):
            player = db.session.get(Player, user_id)
            player.password_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
            player.country_flag = "CA"
            player.profile_picture = "https://example.com/me.png"
        db.session.commit()
        self.login_as(self.alice)

    def delete(self, password=PASSWORD):
        return self.post("/profile/delete", json={"password": password})

    def alice_row(self):
        db.session.expire_all()
        return db.session.get(Player, self.alice)

    def test_deleting_wipes_every_personal_detail(self):
        res = self.delete()

        self.assertEqual(res.status_code, 200)
        self.assertIn("message", res.get_json())
        alice = self.alice_row()
        self.assertTrue(alice.is_deleted)
        self.assertNotEqual(alice.username, "alice")
        self.assertEqual((alice.first_name, alice.last_name), ("Deleted", "Player"))
        self.assertIsNone(alice.country_flag)
        self.assertIsNone(alice.profile_picture)
        self.assertNotIn("$2", alice.password_hash, "no longer a bcrypt hash of anything")

    def test_the_account_can_no_longer_sign_in(self):
        self.delete()
        res = self.client.post("/login", json={"username": "alice", "password": PASSWORD})
        self.assertEqual(res.status_code, 401)

    def test_old_login_tokens_stop_working_at_once(self):
        self.delete()

        res = self.get("/match/status")

        self.assertEqual(res.status_code, 401)
        self.assertIn("sign in again", res.get_json()["message"])
        self.assertEqual(self.delete().status_code, 401, "deleting twice is just a dead session")

    def test_the_username_is_free_to_register_again(self):
        self.delete()
        res = self.client.post(
            "/register",
            json={"username": "alice", "first_name": "New", "last_name": "Alice", "password": "another1"},
        )
        self.assertEqual(res.status_code, 201)

    def test_deleted_players_leave_the_ladder(self):
        self.delete()
        usernames = [p["username"] for p in self.client.get("/leaderboard").get_json()]
        self.assertEqual(len(usernames), 2)
        self.assertNotIn("alice", usernames)

    def test_games_stay_in_other_players_history_without_the_name(self):
        match = self.start_match(self.alice, self.bob)
        from logic.record_match import record_match_result

        record_match_result(match, self.bob, self.alice, 16, 8, 3)
        # bob holds the table now; alice is free to go.
        self.delete()

        history = self.client.get(f"/players/{self.bob}/matches").get_json()["matches"]
        self.assertEqual(len(history), 1, "bob's win is still on record")
        loser = history[0]["loser"]
        self.assertEqual(loser["username"], "Deleted player")
        self.assertIsNone(loser["country_flag"])
        self.assertIsNone(loser["profile_picture"])

    def test_a_wrong_password_deletes_nothing(self):
        res = self.delete("not-my-password")

        self.assertEqual(res.status_code, 403, "not 401 - that would sign the player out")
        self.assertEqual(res.get_json()["field"], "password")
        self.assertFalse(self.alice_row().is_deleted)

    def test_the_password_is_required(self):
        for body in ({}, {"password": ""}, {"password": 12345}):
            res = self.post("/profile/delete", json=body)
            self.assertEqual(res.status_code, 400, body)
            self.assertEqual(res.get_json()["field"], "password")
        self.assertFalse(self.alice_row().is_deleted)

    def test_refused_mid_game(self):
        self.start_match(self.alice, self.bob)

        res = self.delete()

        self.assertEqual(res.status_code, 409)
        self.assertIn("report the score", res.get_json()["message"])
        self.assertFalse(self.alice_row().is_deleted)

    def test_a_king_hands_the_table_to_the_next_two_in_line(self):
        self.make_king(self.alice)
        db.session.add(QueueEntry(user_id=self.bob, table_id=1, queue_position=1))
        db.session.add(QueueEntry(user_id=self.carol, table_id=1, queue_position=2))
        db.session.commit()

        self.assertEqual(self.delete().status_code, 200)

        match = self.active_match()
        self.assertEqual({match.player_one_id, match.player_two_id}, {self.bob, self.carol})

    def test_leaves_every_queue(self):
        self.post("/queue/join", json={"league_type": "billiards"})
        self.post("/queue/join", json={"league_type": "ping_pong"})

        self.delete()

        remaining = db.session.scalar(
            db.select(db.func.count()).select_from(QueueEntry).where(QueueEntry.user_id == self.alice)
        )
        self.assertEqual(remaining, 0)

    def test_a_failure_says_something_readable(self):
        with mock.patch("app.delete_account", side_effect=Exception("(mysql) 1054 Unknown column")):
            res = self.delete()
        self.assertEqual(res.status_code, 500)
        self.assertNotIn("mysql", res.get_json()["message"])


class TokensForMissingAccounts(ApiTestCase):
    def test_a_token_for_an_account_that_never_existed_is_refused(self):
        self.login_as(9999)
        self.assertEqual(self.get("/match/status").status_code, 401)


class PrivacyPolicy(ApiTestCase):
    def test_the_page_is_public_and_explains_deletion(self):
        res = self.client.get("/privacy")

        self.assertEqual(res.status_code, 200)
        self.assertIn("text/html", res.content_type)
        page = res.get_data(as_text=True)
        self.assertIn("Delete account", page)
        self.assertNotIn("mailto:", page, "no contact address unless one is configured")

    def test_the_contact_address_comes_from_the_environment(self):
        with mock.patch.dict(os.environ, {"PRIVACY_CONTACT_EMAIL": "league@example.com"}):
            page = self.client.get("/privacy").get_data(as_text=True)
        self.assertIn("mailto:league@example.com", page)

    def test_the_contact_address_is_escaped(self):
        with mock.patch.dict(os.environ, {"PRIVACY_CONTACT_EMAIL": '"><script>x</script>'}):
            page = self.client.get("/privacy").get_data(as_text=True)
        self.assertNotIn("<script>", page)


if __name__ == "__main__":
    unittest.main()
