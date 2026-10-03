"""
Forgot your password? A code by email, then a new password.

  1. request_reset(email): if an account has that email, a 6-digit code
     is emailed to it. The answer is the same either way, so the form
     can't be used to find out who has an account.
  2. reset_password(email, code, new_password): the right code, within
     CODE_LIFETIME_SECONDS and MAX_ATTEMPTS, sets the new password.

A code rather than a link: typing six digits works the same in the web
app and the phone apps, with nothing to open in the right place.

Only a hash of the code is stored. Each request replaces any earlier
code, and a used code is deleted. Times are measured by the database's
clock, as everything else here is.
"""
import hashlib
import hmac
import logging
import secrets

from sqlalchemy import func

from database import retry_on_deadlock, seconds_since
from logic.auth import clean_email, hash_password, password_problem
from logic.mailer import send_email
from models import PasswordReset, Player, db

log = logging.getLogger(__name__)

CODE_DIGITS = 6
CODE_LIFETIME_SECONDS = 15 * 60
# Six digits is a million codes; five guesses at one is a 1-in-200,000
# chance, and then the code is gone.
MAX_ATTEMPTS = 5
# Asking again sooner than this sends nothing new: the email may simply
# be slow, and the cap keeps anyone from flooding someone's inbox.
RESEND_AFTER_SECONDS = 60

# request_reset outcomes.
RESET_REQUEST_SENT = "sent"
RESET_REQUEST_TOO_SOON = "too_soon"
RESET_REQUEST_NO_ACCOUNT = "no_account"

# reset_password outcomes.
RESET_DONE = "reset"
RESET_WRONG_CODE = "wrong_code"
RESET_EXPIRED = "expired"
RESET_TOO_MANY_TRIES = "too_many_tries"
RESET_NO_CODE = "no_code"
RESET_BAD_PASSWORD = "bad_password"


def _hash(user_id, code):
    # Salted with the account, so one code's hash says nothing about another's.
    return hashlib.sha256(f"{user_id}:{code}".encode("utf-8")).hexdigest()


def _account_for(email):
    cleaned, problem = clean_email(email)
    if problem:
        return None
    player = db.session.scalars(db.select(Player).where(Player.email == cleaned)).first()
    if player is None or player.is_deleted:
        return None
    return player


@retry_on_deadlock
def request_reset(email):
    """
    Email a reset code to the account with this email. Returns one of the
    RESET_REQUEST_* - which the route must not reveal: it answers the same
    way to all three. Raises MailNotConfigured / MailFailed when the email
    can't go; then no code is kept.
    """
    player = _account_for(email)
    if player is None:
        return RESET_REQUEST_NO_ACCOUNT

    try:
        existing = db.session.execute(
            db.select(PasswordReset, seconds_since(PasswordReset.sent_at))
            .where(PasswordReset.user_id == player.user_id)
            .with_for_update()
        ).first()
        if existing is not None:
            row, seconds = existing
            if seconds is not None and seconds < RESEND_AFTER_SECONDS:
                db.session.rollback()
                return RESET_REQUEST_TOO_SOON

        code = f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"
        if existing is None:
            db.session.add(PasswordReset(user_id=player.user_id, code_hash=_hash(player.user_id, code)))
        else:
            row.code_hash = _hash(player.user_id, code)
            row.sent_at = func.now()
            row.attempts = 0
        db.session.flush()

        # Sent before committing: if the email can't go, no code is kept
        # that nobody could ever receive.
        send_email(
            player.email,
            f"Your password reset code: {code}",
            (
                f"Hi {player.username},\n\n"
                f"Your code to reset your Billiards & Ping Pong League password is:\n\n"
                f"    {code}\n\n"
                f"It works for {CODE_LIFETIME_SECONDS // 60} minutes. Your username is "
                f"{player.username}, if you've forgotten that too.\n\n"
                f"If you didn't ask for this, ignore it - your password hasn't changed.\n"
            ),
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    log.info("sent a password reset code to player %s", player.user_id)
    return RESET_REQUEST_SENT


@retry_on_deadlock
def reset_password(email, code, new_password):
    """
    Set a new password with an emailed code. Returns (outcome, player):
    one of the RESET_* and, when done, the player - so the route can sign
    them straight in.
    """
    problem = password_problem(new_password)
    if problem:
        return RESET_BAD_PASSWORD, None

    player = _account_for(email)
    if player is None:
        # Same as "no code": nothing says whether the email has an account.
        return RESET_NO_CODE, None

    try:
        found = db.session.execute(
            db.select(PasswordReset, seconds_since(PasswordReset.sent_at))
            .where(PasswordReset.user_id == player.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if found is None:
            db.session.rollback()
            return RESET_NO_CODE, None

        row, seconds = found
        if seconds is None or seconds >= CODE_LIFETIME_SECONDS:
            db.session.delete(row)
            db.session.commit()
            return RESET_EXPIRED, None
        if row.attempts >= MAX_ATTEMPTS:
            db.session.delete(row)
            db.session.commit()
            return RESET_TOO_MANY_TRIES, None

        given = "".join(ch for ch in str(code or "") if ch.isdigit())
        if not hmac.compare_digest(_hash(player.user_id, given), row.code_hash):
            row.attempts += 1
            if row.attempts >= MAX_ATTEMPTS:
                db.session.delete(row)
                db.session.commit()
                return RESET_TOO_MANY_TRIES, None
            db.session.commit()
            return RESET_WRONG_CODE, None

        player.password_hash = hash_password(new_password)
        db.session.delete(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    log.info("player %s reset their password", player.user_id)
    return RESET_DONE, player


def forget_reset_code(user_id):
    """Delete a player's reset code, if any. Part of the caller's transaction."""
    db.session.execute(db.delete(PasswordReset).where(PasswordReset.user_id == user_id))
