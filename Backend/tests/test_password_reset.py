"""
Forgot your password? A code by email, then a new password - and, for
when email can't help, the organiser's set-password command.

No email is really sent: send_email is replaced, and the code is read out
of what would have been sent.
"""
import re
import unittest
from unittest import mock

from tests.conftest_base import ApiTestCase
from models import PasswordReset, Player, db

from logic.auth import hash_password, password_matches
from logic.mailer import MailFailed
from logic.password_reset import CODE_LIFETIME_SECONDS, MAX_ATTEMPTS, RESEND_AFTER_SECONDS

OLD_PASSWORD = "hunter22"
NEW_PASSWORD = "brand-new-1"


class ResetTestCase(ApiTestCase):
    def setUp(self):
        super().setUp()
        alice = db.session.get(Player, self.alice)
        alice.email = "alice@example.com"
        alice.password_hash = hash_password(OLD_PASSWORD)
        db.session.commit()
        self.sent = []
        patcher = mock.patch(
            "logic.password_reset.send_email",
            side_effect=lambda to, subject, text: self.sent.append((to, subject, text)),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def forgot(self, email="alice@example.com"):
        return self.client.post("/password/forgot", json={"email": email})

    def reset(self, code, password=NEW_PASSWORD, email="alice@example.com"):
        return self.client.post("/password/reset", json={"email": email, "code": code, "password": password})

    def last_code(self):
        return re.search(r"\b(\d{6})\b", self.sent[-1][2]).group(1)

    def backdate_code(self, seconds):
        db.session.execute(
            db.text("UPDATE Password_Resets SET sent_at = datetime('now', :o)"), {"o": f"-{seconds} seconds"}
        )
        db.session.commit()

    def password_is(self, password):
        db.session.expire_all()
        return password_matches(db.session.get(Player, self.alice), password)


class AskingForACode(ResetTestCase):
    def test_a_code_is_emailed_to_the_account(self):
        res = self.forgot("  ALICE@example.com ")

        self.assertEqual(res.status_code, 200)
        self.assertIn("If that email belongs to an account", res.get_json()["message"])
        to, subject, text = self.sent[0]
        self.assertEqual(to, "alice@example.com")
        code = self.last_code()
        self.assertIn(code, subject)
        self.assertIn("alice", text, "the email reminds them of their username too")
        stored = db.session.get(PasswordReset, self.alice)
        self.assertNotIn(code, stored.code_hash, "only a hash of the code is kept")

    def test_an_unknown_email_gets_the_same_answer_and_no_email(self):
        known = self.forgot().get_json()
        unknown = self.forgot("nobody@example.com")

        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(unknown.get_json(), known, "nothing says whether the email has an account")
        self.assertEqual(len(self.sent), 1)

    def test_asking_again_straight_away_sends_nothing_new(self):
        self.forgot()
        self.forgot()
        self.assertEqual(len(self.sent), 1)

    def test_asking_again_later_sends_a_new_code_and_the_old_one_stops_working(self):
        self.forgot()
        old = self.last_code()
        self.backdate_code(RESEND_AFTER_SECONDS + 1)

        self.forgot()

        self.assertEqual(len(self.sent), 2)
        if self.last_code() != old:
            self.assertEqual(self.reset(old).status_code, 400)

    def test_a_malformed_email_is_said_so(self):
        res = self.forgot("not-an-email")
        self.assertEqual((res.status_code, res.get_json()["field"]), (400, "email"))

    def test_when_email_isnt_set_up_the_organiser_is_mentioned(self):
        with mock.patch("app.mail_configured", return_value=False):
            res = self.forgot()
        self.assertEqual(res.status_code, 503)
        self.assertIn("organiser", res.get_json()["message"])

    def test_when_the_email_cant_go_no_code_is_kept(self):
        with mock.patch("logic.password_reset.send_email", side_effect=MailFailed("down")):
            res = self.forgot()
        self.assertEqual(res.status_code, 503)
        self.assertIn("try again", res.get_json()["message"].lower())
        self.assertIsNone(db.session.get(PasswordReset, self.alice))


class ResettingThePassword(ResetTestCase):
    def setUp(self):
        super().setUp()
        self.forgot()
        self.code = self.last_code()

    def test_the_right_code_sets_the_password_and_signs_in(self):
        res = self.reset(self.code)

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(set(body), {"message", "access_token", "user_id", "username", "email", "is_admin"})
        self.assertTrue(self.password_is(NEW_PASSWORD))
        self.assertFalse(self.password_is(OLD_PASSWORD))
        self.assertIsNone(db.session.get(PasswordReset, self.alice), "a code works once")
        signed_in = self.client.get("/profile", headers={"Authorization": f"Bearer {body['access_token']}"})
        self.assertEqual(signed_in.status_code, 200)

    def test_a_code_works_once(self):
        self.reset(self.code)
        again = self.reset(self.code, password="yet-another-2")
        self.assertEqual((again.status_code, again.get_json()["field"]), (400, "code"))
        self.assertTrue(self.password_is(NEW_PASSWORD))

    def test_a_wrong_code(self):
        wrong = "000000" if self.code != "000000" else "111111"

        res = self.reset(wrong)

        self.assertEqual((res.status_code, res.get_json()["field"]), (400, "code"))
        self.assertIn("isn't right", res.get_json()["message"])
        self.assertTrue(self.password_is(OLD_PASSWORD))

    def test_enough_wrong_guesses_and_the_code_stops_working(self):
        wrong = "000000" if self.code != "000000" else "111111"
        for _ in range(MAX_ATTEMPTS):
            last = self.reset(wrong)
        self.assertIn("Too many", last.get_json()["message"])

        res = self.reset(self.code)

        self.assertEqual(res.status_code, 400, "even the right code is no use now")
        self.assertTrue(self.password_is(OLD_PASSWORD))

    def test_an_old_code_has_expired(self):
        self.backdate_code(CODE_LIFETIME_SECONDS + 1)

        res = self.reset(self.code)

        self.assertIn("expired", res.get_json()["message"])
        self.assertTrue(self.password_is(OLD_PASSWORD))

    def test_a_too_short_new_password_keeps_the_code(self):
        res = self.reset(self.code, password="123")

        self.assertEqual((res.status_code, res.get_json()["field"]), (400, "password"))
        self.assertEqual(self.reset(self.code).status_code, 200, "the code still works")

    def test_spaces_in_the_code_are_fine(self):
        spaced = f"{self.code[:3]} {self.code[3:]}"
        self.assertEqual(self.reset(spaced).status_code, 200)

    def test_without_asking_for_a_code(self):
        res = self.reset("123456", email="bob@example.com")
        self.assertEqual((res.status_code, res.get_json()["field"]), (400, "code"))

    def test_a_deleted_account_cannot_be_reset(self):
        self.login_as(self.alice)
        self.post("/profile/delete", json={"password": OLD_PASSWORD})

        res = self.reset(self.code)

        self.assertEqual(res.status_code, 400)


class OrganiserSetsAPassword(ResetTestCase):
    def setUp(self):
        super().setUp()
        self.runner = self.app.test_cli_runner()

    def run_command(self, who, password):
        return self.runner.invoke(args=["set-password", who], input=f"{password}\n{password}\n")

    def test_by_username_or_email(self):
        result = self.run_command("alice", NEW_PASSWORD)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(self.password_is(NEW_PASSWORD))

        result = self.run_command("ALICE@example.com", "third-one-3")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(self.password_is("third-one-3"))

    def test_an_unknown_player(self):
        result = self.run_command("nobody", NEW_PASSWORD)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("no account", result.output)

    def test_a_too_short_password(self):
        result = self.run_command("alice", "123")
        self.assertNotEqual(result.exit_code, 0)
        self.assertTrue(self.password_is(OLD_PASSWORD))


if __name__ == "__main__":
    unittest.main()
