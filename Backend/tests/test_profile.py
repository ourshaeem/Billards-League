"""
A player's profile: their flag and picture, and their standing in both
leagues.

The picture link is shown in an <img> on every other player's screen, so
the tests that matter most are the ones proving only web links get saved.
"""
import unittest

from tests.conftest_base import ApiTestCase
from models import Player, db


class ProfileRoutes(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login_as(self.alice)

    def saved(self):
        db.session.expire_all()
        return db.session.get(Player, self.alice)

    def test_signing_in_is_required(self):
        self.assertEqual(self.client.get("/profile").status_code, 401)
        self.assertEqual(self.client.patch("/profile", json={"country_flag": "US"}).status_code, 401)

    def test_the_profile_shows_both_leagues(self):
        res = self.get("/profile")

        self.assertEqual(res.status_code, 200)
        profile = res.get_json()["profile"]
        self.assertEqual(profile["username"], "alice")
        self.assertIsNone(profile["country_flag"])
        self.assertEqual(set(profile["leagues"]), {"billiards", "ping_pong"})
        self.assertEqual(
            profile["leagues"]["ping_pong"],
            {"elo": 1200, "rank_name": "Unranked", "wins": 0, "losses": 0},
        )

    def test_setting_a_flag_and_a_picture(self):
        res = self.patch(
            "/profile",
            json={"country_flag": "ca", "profile_picture": " https://example.com/me.png "},
        )

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertIn("message", body)
        self.assertEqual(body["profile"]["country_flag"], "CA", "codes are stored upper-case")
        self.assertEqual(self.saved().profile_picture, "https://example.com/me.png")

    def test_changing_one_field_leaves_the_other(self):
        self.patch("/profile", json={"country_flag": "US", "profile_picture": "https://x.io/a.jpg"})

        self.patch("/profile", json={"profile_picture": ""})

        self.assertIsNone(self.saved().profile_picture, "blank clears the picture")
        self.assertEqual(self.saved().country_flag, "US")

    def test_null_clears_a_flag(self):
        self.patch("/profile", json={"country_flag": "US"})
        self.patch("/profile", json={"country_flag": None})
        self.assertIsNone(self.saved().country_flag)

    def test_an_unknown_country_is_refused_and_names_its_field(self):
        res = self.patch("/profile", json={"country_flag": "ZZ"})

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["field"], "country_flag")
        self.assertIsNone(self.saved().country_flag)

    def test_only_web_links_are_accepted_as_pictures(self):
        for link in (
            "javascript:alert(1)",
            "data:image/png;base64,iVBORw0KGgo=",
            "ftp://example.com/me.png",
            "example.com/me.png",
            "https://",
            "https://exa mple.com/me.png",
            12345,
        ):
            res = self.patch("/profile", json={"profile_picture": link})
            self.assertEqual(res.status_code, 400, link)
            self.assertEqual(res.get_json()["field"], "profile_picture", link)
        self.assertIsNone(self.saved().profile_picture)

    def test_an_overlong_link_says_what_the_limit_is(self):
        res = self.patch("/profile", json={"profile_picture": "https://x.io/" + "a" * 600})
        self.assertEqual(res.status_code, 400)
        self.assertIn("512", res.get_json()["message"])

    def test_one_bad_field_means_nothing_is_saved(self):
        res = self.patch(
            "/profile", json={"country_flag": "US", "profile_picture": "javascript:alert(1)"}
        )
        self.assertEqual(res.status_code, 400)
        self.assertIsNone(self.saved().country_flag)

    def test_a_request_with_nothing_to_change_is_refused(self):
        res = self.patch("/profile", json={"username": "mallory"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.saved().username, "alice", "only the flag and picture are editable")

    def test_the_flag_and_picture_appear_to_other_players(self):
        self.patch("/profile", json={"country_flag": "JP", "profile_picture": "https://x.io/a.png"})
        self.start_match(self.alice, self.bob)

        king = self.client.get("/table/1").get_json()["table"]["king"]

        self.assertEqual(king["country_flag"], "JP")
        self.assertEqual(king["profile_picture"], "https://x.io/a.png")


class CountriesRoute(ApiTestCase):
    def test_the_picker_list_is_sorted_by_name(self):
        countries = self.client.get("/countries").get_json()["countries"]

        self.assertIn({"code": "US", "name": "United States"}, countries)
        names = [c["name"] for c in countries]
        self.assertEqual(names, sorted(names))


if __name__ == "__main__":
    unittest.main()
