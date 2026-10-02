"""
Profile pictures people upload from their phone or computer, rather than
link to.

Every upload is decoded and drawn again as a small square JPEG before it
is stored. That isn't a nicety:

  - Only real pictures are kept. Whatever bytes arrive are decoded as an
    image; anything that isn't one is refused, and what's stored is a
    picture this server drew.
  - Nothing else the file carried is kept. Photos from phones carry EXIF
    data - often the GPS position the photo was taken at. A freshly
    encoded JPEG carries none of it.
  - Every picture is the same small size (typically 30-80 KB), whatever
    the phone sent, so the database and the feeds stay quick.

The apps already shrink a picture before sending it; this doesn't rely
on that.
"""
import base64
import binascii
import hashlib
import logging
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from models import Player, PlayerPicture, db

log = logging.getLogger(__name__)

# The stored picture: a square this many pixels across. Avatars are drawn
# at up to 120 points, so this stays sharp on a high-density screen.
PICTURE_SIZE = 512
JPEG_QUALITY = 85

# The largest file accepted, after base64 decoding. The apps send ~100 KB.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
# More pixels than any phone camera takes. Checked before decoding: a tiny
# file can claim enormous dimensions, and decoding it would eat the
# server's memory.
MAX_PIXELS = 50_000_000
# MPO is the JPEG variant some cameras save.
ACCEPTED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP", "GIF"}

NOT_A_PICTURE = "That file isn't a picture we can use. Try a JPEG or PNG photo."
TOO_BIG = f"That picture is too big. Pick one under {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."


class PictureProblem(ValueError):
    """An upload that can't be used; the message is shown to the player."""


def decode_upload(value):
    """
    The uploaded file's bytes, from the base64 text the apps send - with
    or without a "data:image/...;base64," prefix. Raises PictureProblem.
    """
    if not isinstance(value, str) or not value.strip():
        raise PictureProblem("Choose a picture to upload.")
    text = value.strip()
    if text.startswith("data:"):
        _, _, text = text.partition(",")
    # base64 is 4 characters for every 3 bytes; refuse an oversized body
    # before decoding it.
    if len(text) > (MAX_UPLOAD_BYTES * 4) // 3 + 4:
        raise PictureProblem(TOO_BIG)
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise PictureProblem(NOT_A_PICTURE) from None


def prepare_picture(raw):
    """
    The stored form of an uploaded picture: a PICTURE_SIZE square JPEG,
    the right way up, cropped to its middle, with no metadata. Raises
    PictureProblem for anything that isn't a picture.
    """
    if len(raw) > MAX_UPLOAD_BYTES:
        raise PictureProblem(TOO_BIG)
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in ACCEPTED_FORMATS:
                raise PictureProblem(NOT_A_PICTURE)
            width, height = image.size
            if width * height > MAX_PIXELS:
                raise PictureProblem(TOO_BIG)
            image.load()
            # Phones often save a photo sideways with a note to turn it.
            # Turn it now: the note goes with the rest of the metadata.
            upright = ImageOps.exif_transpose(image)
            square = ImageOps.fit(
                _on_white(upright), (PICTURE_SIZE, PICTURE_SIZE), Image.Resampling.LANCZOS
            )
    except PictureProblem:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise PictureProblem(NOT_A_PICTURE) from None

    out = BytesIO()
    square.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out.getvalue()


def _on_white(image):
    """RGB, with any transparent parts on white rather than black."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return image.convert("RGB")


def picture_path(user_id, digest):
    """Where a player's uploaded picture is served from (see app.py)."""
    return f"/players/{user_id}/picture?v={digest[:16]}"


def save_uploaded_picture(user_id, value):
    """
    Make an upload the player's picture, replacing any picture or link
    they had. Returns (problem, profile):
      - (None, profile) when saved;
      - ({"field": "profile_picture", "message": ...}, None) when the
        upload can't be used - nothing is saved;
      - (None, None) if the account doesn't exist.
    """
    player = db.session.get(Player, user_id)
    if player is None or player.is_deleted:
        return None, None

    try:
        image = prepare_picture(decode_upload(value))
    except PictureProblem as e:
        return {"field": "profile_picture", "message": str(e)}, None

    digest = hashlib.sha256(image).hexdigest()
    try:
        stored = db.session.get(PlayerPicture, user_id)
        if stored is None:
            db.session.add(PlayerPicture(user_id=user_id, image=image, digest=digest))
        else:
            stored.image, stored.digest = image, digest
        player.profile_picture = picture_path(user_id, digest)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    log.info("player %s uploaded a picture (%d bytes)", user_id, len(image))
    return None, player.to_profile_dict()


def stored_picture(user_id):
    """A player's uploaded picture as (jpeg bytes, digest), or None."""
    row = db.session.get(PlayerPicture, user_id)
    if row is None:
        return None
    return row.image, row.digest


def forget_uploaded_picture(user_id):
    """
    Delete a player's uploaded picture, if they have one. Part of the
    caller's transaction: commit is theirs.
    """
    db.session.execute(db.delete(PlayerPicture).where(PlayerPicture.user_id == user_id))
