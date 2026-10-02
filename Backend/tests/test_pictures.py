"""
Uploading a profile picture from a phone or computer, rather than giving
a link.

Most of what's checked here is privacy: a photo from a phone carries the
place it was taken, and what the league stores and shows must not.
"""
import base64
import os
import unittest
from io import BytesIO
from unittest import mock

from PIL import ExifTags, Image

from tests.conftest_base import ApiTestCase
from models import Player, PlayerPicture, db

from logic import pictures
from logic.pictures import PICTURE_SIZE

LONG_SECRET = "a-production-signing-key-that-is-long-enough"


def photo(fmt="JPEG", size=(800, 400), exif=None, mode="RGB", color=(220, 20, 20)):
    """An image file's bytes: red on the left half, blue on the right."""
    image = Image.new(mode, size, color if mode == "RGB" else (0, 0, 0, 0))
    if mode == "RGB":
        image.paste((20, 20, 220), (size[0] // 2, 0, size[0], size[1]))
    out = BytesIO()
    image.save(out, fmt, **({"exif": exif} if exif is not None else {}))
    return out.getvalue()


def as_upload(raw, data_url=False):
    text = base64.b64encode(raw).decode()
    return f"data:image/jpeg;base64,{text}" if data_url else text


def phone_photo_exif():
    """What a phone writes: which way up the photo is, and where it was taken."""
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6  # turn 90 degrees clockwise to view
    exif[ExifTags.Base.Make] = "PhoneCo"
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (40.0, 26.0, 46.0)
    gps[ExifTags.GPS.GPSLongitudeRef] = "W"
    gps[ExifTags.GPS.GPSLongitude] = (79.0, 58.0, 56.0)
    return exif


class UploadTestCase(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login_as(self.alice)

    def upload(self, raw, **kwargs):
        return self.post("/profile/picture", json={"image": as_upload(raw, **kwargs)})

    def stored(self):
        db.session.expire_all()
        return db.session.get(PlayerPicture, self.alice)

    def stored_image(self):
        return Image.open(BytesIO(self.stored().image))


class Uploading(UploadTestCase):
    def test_a_photo_becomes_the_players_picture(self):
        res = self.upload(photo())

        self.assertEqual(res.status_code, 200)
        link = res.get_json()["profile"]["profile_picture"]
        self.assertTrue(link.startswith(f"http://localhost/players/{self.alice}/picture?v="), link)
        image = self.stored_image()
        self.assertEqual((image.format, image.size), ("JPEG", (PICTURE_SIZE, PICTURE_SIZE)))

    def test_the_picture_link_serves_the_picture_and_can_be_cached_for_good(self):
        link = self.upload(photo()).get_json()["profile"]["profile_picture"]

        res = self.client.get(link.replace("http://localhost", ""))

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "image/jpeg")
        self.assertIn("immutable", res.headers["Cache-Control"])
        self.assertEqual(res.data, self.stored().image)

    def test_an_old_link_is_not_cached_for_good(self):
        res = self.client.get(f"/players/{self.alice}/picture?v=old")
        self.assertEqual(res.status_code, 404)

        self.upload(photo())
        res = self.client.get(f"/players/{self.alice}/picture?v=old")
        self.assertEqual(res.headers["Cache-Control"], "no-cache")

    def test_a_new_picture_gets_a_new_link(self):
        first = self.upload(photo()).get_json()["profile"]["profile_picture"]
        second = self.upload(photo(color=(20, 200, 20))).get_json()["profile"]["profile_picture"]
        self.assertNotEqual(first, second)

    def test_other_players_see_it_on_cards_and_the_ladder(self):
        link = self.upload(photo()).get_json()["profile"]["profile_picture"]

        ladder = self.client.get("/leaderboard").get_json()
        profile = self.client.get(f"/players/{self.alice}").get_json()["player"]

        self.assertIn(link, [row["profile_picture"] for row in ladder])
        self.assertEqual(profile["profile_picture"], link)

    def test_a_data_url_is_fine_too(self):
        self.assertEqual(self.upload(photo(), data_url=True).status_code, 200)

    def test_png_with_see_through_parts_goes_on_white(self):
        res = self.upload(photo("PNG", size=(300, 300), mode="RGBA"))

        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.stored_image().getpixel((10, 10)), (255, 255, 255))

    def test_a_wide_photo_is_cropped_to_its_middle(self):
        self.upload(photo(size=(1200, 400)))
        image = self.stored_image()
        left, right = image.getpixel((5, 256)), image.getpixel((506, 256))
        self.assertGreater(left[0], 150, "red half still on the left")
        self.assertGreater(right[2], 150, "blue half still on the right")


class PrivacyOfPhotos(UploadTestCase):
    def test_where_the_photo_was_taken_is_not_kept(self):
        self.upload(photo(exif=phone_photo_exif()))

        image = self.stored_image()
        exif = image.getexif()
        self.assertEqual(dict(exif), {}, "no EXIF at all")
        self.assertEqual(dict(exif.get_ifd(ExifTags.IFD.GPSInfo)), {})
        self.assertNotIn(b"PhoneCo", self.stored().image)

    def test_a_sideways_photo_is_stored_the_right_way_up(self):
        """Orientation 6 means "turn clockwise": red (left) ends up on top."""
        self.upload(photo(exif=phone_photo_exif()))

        image = self.stored_image()
        top, bottom = image.getpixel((256, 10)), image.getpixel((256, 500))
        self.assertGreater(top[0], 150)
        self.assertGreater(bottom[2], 150)


class Refusals(UploadTestCase):
    def assertRefused(self, res, words):
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertEqual(body["field"], "profile_picture")
        self.assertIn(words, body["message"])
        self.assertIsNone(self.stored(), "nothing saved")

    def test_a_file_that_is_not_a_picture(self):
        self.assertRefused(self.upload(b"%PDF-1.7 definitely not a photo"), "isn't a picture")

    def test_text_that_is_not_base64(self):
        res = self.post("/profile/picture", json={"image": "not base64 at all!!"})
        self.assertRefused(res, "isn't a picture")

    def test_no_picture_sent(self):
        self.assertRefused(self.post("/profile/picture", json={}), "Choose a picture")

    def test_a_picture_that_is_too_big(self):
        with mock.patch.object(pictures, "MAX_UPLOAD_BYTES", 1000):
            self.assertRefused(self.upload(photo()), "too big")

    def test_a_tiny_file_claiming_to_be_enormous(self):
        """A few KB of PNG can claim 60 million pixels; decoding it would eat the server."""
        bomb = Image.new("1", (10000, 6000))
        out = BytesIO()
        bomb.save(out, "PNG")
        self.assertLess(len(out.getvalue()), 100_000)

        self.assertRefused(self.upload(out.getvalue()), "too big")

    def test_a_request_too_large_to_read_says_so_in_words(self):
        res = self.post(
            "/profile/picture",
            data=b"x" * (self.app.config["MAX_CONTENT_LENGTH"] + 1),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 413)
        self.assertIn("too big", res.get_json()["message"])

    def test_needs_a_login(self):
        res = self.client.post("/profile/picture", json={"image": as_upload(photo())})
        self.assertEqual(res.status_code, 401)


class OnePictureAtATime(UploadTestCase):
    def test_uploading_replaces_a_link(self):
        linked = self.patch("/profile", json={"profile_picture": "https://example.com/me.png"})
        self.assertFalse(linked.get_json()["profile"]["picture_uploaded"])

        profile = self.upload(photo()).get_json()["profile"]

        self.assertIn("/picture?v=", profile["profile_picture"])
        self.assertTrue(profile["picture_uploaded"], "the form needs to know it's a photo, not a link")

    def test_a_link_replaces_an_upload_and_the_photo_is_deleted(self):
        self.upload(photo())

        res = self.patch("/profile", json={"profile_picture": "https://example.com/me.png"})

        self.assertEqual(res.get_json()["profile"]["profile_picture"], "https://example.com/me.png")
        self.assertIsNone(self.stored())

    def test_removing_the_picture_deletes_the_photo(self):
        self.upload(photo())

        self.patch("/profile", json={"profile_picture": None})

        self.assertIsNone(self.stored())
        self.assertEqual(self.client.get(f"/players/{self.alice}/picture").status_code, 404)

    def test_changing_only_the_flag_keeps_the_photo(self):
        self.upload(photo())
        self.patch("/profile", json={"country_flag": "CA"})
        self.assertIsNotNone(self.stored())

    def test_deleting_the_account_deletes_the_photo(self):
        from logic.account import delete_account

        db.session.get(Player, self.alice).password_hash = _hash("hunter22")
        db.session.commit()
        self.upload(photo())

        delete_account(self.alice, "hunter22")

        self.assertIsNone(self.stored())


class BehindTheHostsProxy(UploadTestCase):
    """
    The host's proxy speaks plain http to the app. A picture link built
    from that would start http://, which a https:// page won't load.
    """

    def production_app(self):
        from app import create_app

        with mock.patch.dict(os.environ, {"APP_ENV": "production", "JWT_SECRET_KEY": LONG_SECRET}):
            return create_app()

    def picture_link_seen(self, app, headers):
        # The production app has its own (empty, in-memory) database.
        with app.app_context():
            db.create_all()
            player = Player(
                username="zed",
                first_name="Z",
                last_name="Z",
                password_hash="x",
                profile_picture="/players/1/picture?v=abc",
            )
            db.session.add(player)
            db.session.commit()
            res = app.test_client().get(f"/players/{player.user_id}", headers=headers)
            db.session.remove()
            db.drop_all()
        return res.get_json()["player"]["profile_picture"]

    def test_links_are_https_when_the_player_connected_over_https(self):
        link = self.picture_link_seen(self.production_app(), {"X-Forwarded-Proto": "https"})
        self.assertEqual(link, "https://localhost/players/1/picture?v=abc")

    def test_without_a_proxy_the_header_is_not_trusted(self):
        link = self.picture_link_seen(self.app, {"X-Forwarded-Proto": "https"})
        self.assertTrue(link.startswith("http://localhost/"), link)


def _hash(password):
    import bcrypt

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()


if __name__ == "__main__":
    unittest.main()
