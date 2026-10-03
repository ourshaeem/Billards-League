"""
Accounts and emails: signing up needs one, one account per email, and
signing in takes the username or the email.

What it's for: a player who forgot their password used to make a second
account. Now signing up again with their email is refused, and the email
gets them a reset code instead (test_password_reset.py).
"""
import unittest

from tests.conftest_base import ApiTestCase
from models import Player, db

PASSWORD = "hunter22"


def signup(**overrides):
    body = {
        "username": "dave",
        "first_name": "Dave",
        "last_name": "Smith",
        "password": PASSWORD,
        "email": "dave@example.com",
    }
    body.update(overrides)
    return body


class SignUpWithEmail(ApiTestCase):
    def register(self, **overrides):
        return self.client.post("/register", json=signup(**overrides))

    def test_an_email_is_needed(self):
        body = signup()
        del body["email"]

        res = self.client.post("/register", json=body)

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["field"], "email")
        self.assertIn("update the app", res.get_json()["message"], "what an older app hears")

    def test_a_blank_or_malformed_email(self):
        for email in ("", "   ", "dave", "dave@", "@example.com", "dave@example", "da ve@example.com"):
            res = self.register(email=email)
            self.assertEqual(res.status_code, 400, email)
            self.assertEqual(res.get_json()["field"], "email", email)

    def test_one_account_per_email_whatever_the_capitals(self):
        self.assertEqual(self.register().status_code, 201)

        res = self.register(username="dave2", email="  Dave@Example.COM ")

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["field"], "email")
        self.assertIn("reset your password", res.get_json()["message"])
        self.assertEqual(
            db.session.scalar(db.select(db.func.count()).select_from(Player).where(Player.username == "dave2")),
            0,
        )

    def test_the_email_is_kept_trimmed_and_lowercased(self):
        self.register(email="  Dave@Example.COM ")
        dave = db.session.scalars(db.select(Player).where(Player.username == "dave")).one()
        self.assertEqual(dave.email, "dave@example.com")

    def test_usernames_cannot_contain_at(self):
        """Sign-in reads anything with an @ as an email."""
        res = self.register(username="dave@home")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["field"], "username")

    def test_each_refusal_names_its_field(self):
        self.register()
        res = self.register(email="other@example.com")
        self.assertEqual(res.get_json()["field"], "username", "the username is taken")

        res = self.register(username="eve", email="eve@example.com", password="123")
        self.assertEqual(res.get_json()["field"], "password")


class SignInWithEmail(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.client.post("/register", json=signup())

    def login(self, identifier, password=PASSWORD):
        return self.client.post("/login", json={"username": identifier, "password": password})

    def test_with_the_email_in_any_capitals(self):
        res = self.login(" DAVE@example.com ")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["username"], "dave")
        self.assertEqual(res.get_json()["email"], "dave@example.com")

    def test_with_the_username_as_before(self):
        self.assertEqual(self.login("dave").status_code, 200)

    def test_a_wrong_password_by_email_is_refused(self):
        self.assertEqual(self.login("dave@example.com", "wrong-one").status_code, 401)

    def test_an_older_account_whose_username_is_an_email_still_signs_in(self):
        """Some players used their email address as their username."""
        from logic.auth import hash_password

        bob = db.session.get(Player, self.bob)
        bob.username = "Bob@Example.com"
        bob.password_hash = hash_password(PASSWORD)
        db.session.commit()

        res = self.login("Bob@Example.com")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["username"], "Bob@Example.com")

    def test_an_email_beats_a_username_that_looks_the_same(self):
        """An account's email wins over another account named with it."""
        from logic.auth import hash_password

        bob = db.session.get(Player, self.bob)
        bob.username = "dave@example.com"
        bob.password_hash = hash_password("bobs-pass-1")
        db.session.commit()

        self.assertEqual(self.login("dave@example.com").get_json()["username"], "dave")

    def test_an_account_from_before_emails_signs_in_with_none(self):
        # The base fixtures' players have no email, as older accounts don't.
        bob = db.session.get(Player, self.bob)
        from logic.auth import hash_password

        bob.password_hash = hash_password(PASSWORD)
        db.session.commit()

        res = self.login("bob")

        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.get_json()["email"], "the apps ask for one when this is null")


class ChangingYourEmail(ApiTestCase):
    def setUp(self):
        super().setUp()
        from logic.auth import hash_password

        alice = db.session.get(Player, self.alice)
        alice.password_hash = hash_password(PASSWORD)
        db.session.commit()
        self.login_as(self.alice)

    def set_email(self, email, password=None):
        body = {"email": email}
        if password is not None:
            body["password"] = password
        return self.post("/profile/email", json=body)

    def test_the_profile_shows_the_email(self):
        self.assertIsNone(self.get("/profile").get_json()["profile"]["email"])
        self.set_email("alice@example.com")
        self.assertEqual(self.get("/profile").get_json()["profile"]["email"], "alice@example.com")

    def test_adding_a_first_email_needs_no_password(self):
        res = self.set_email("Alice@Example.com")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["profile"]["email"], "alice@example.com")

    def test_changing_an_email_needs_the_password(self):
        self.set_email("alice@example.com")

        missing = self.set_email("new@example.com")
        wrong = self.set_email("new@example.com", password="not-it")
        right = self.set_email("new@example.com", password=PASSWORD)

        self.assertEqual((missing.status_code, missing.get_json()["field"]), (400, "password"))
        self.assertEqual((wrong.status_code, wrong.get_json()["field"]), (403, "password"),
                         "403, never 401 - that would sign the player out")
        self.assertEqual(right.status_code, 200)
        self.assertEqual(right.get_json()["profile"]["email"], "new@example.com")

    def test_saving_the_same_email_again_is_fine(self):
        self.set_email("alice@example.com")
        self.assertEqual(self.set_email("ALICE@example.com").status_code, 200)

    def test_an_email_someone_else_uses_is_refused(self):
        bob = db.session.get(Player, self.bob)
        bob.email = "bob@example.com"
        db.session.commit()

        res = self.set_email("bob@example.com")

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["field"], "email")

    def test_a_malformed_email(self):
        res = self.set_email("not an email")
        self.assertEqual((res.status_code, res.get_json()["field"]), (400, "email"))

    def test_needs_a_login(self):
        self._headers = {}
        self.assertEqual(self.post("/profile/email", json={"email": "a@b.co"}).status_code, 401)

    def test_deleting_the_account_frees_the_email(self):
        self.set_email("alice@example.com")
        self.post("/profile/delete", json={"password": PASSWORD})
        db.session.expire_all()

        self.assertIsNone(db.session.get(Player, self.alice).email)
        res = self.client.post("/register", json=signup(email="alice@example.com"))
        self.assertEqual(res.status_code, 201)


if __name__ == "__main__":
    unittest.main()
