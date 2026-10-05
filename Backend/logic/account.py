"""
Deleting an account.

Both app stores require that anyone who can create an account in the app
can also delete it from the app. What deleting does:

  - Every personal detail on the Players row is wiped: username, first
    and last name, email, flag, picture and password - and an uploaded
    photo and any password reset code are deleted outright. The username
    becomes a random placeholder, so the real one is free to be taken
    again, and other players see the account as "Deleted player".
  - The account can't sign in again, and login tokens already issued for
    it stop working at once (see register_jwt_errors in app.py).
  - The player leaves every queue and gives up any table they hold, and
    drops off the ladder.
  - Finished games stay. They are other people's history as much as this
    player's, and with the personal details gone they no longer say who
    it was.

Refused while a game is in progress - the same rule as giving up the
table: the game has to be reported first, or the opponent is left with a
result nobody can record.
"""
import logging
import secrets

from sqlalchemy import func

from database import retry_on_deadlock
from logic.auth import password_matches
from logic.manage_queue import STEP_DOWN_RESULT_IN_GAME, leave_all_queues, step_down
from logic.password_reset import forget_reset_code
from logic.pictures import forget_uploaded_picture
from models import Player, db

log = logging.getLogger(__name__)

# delete_account outcomes.
DELETE_RESULT_DELETED = "deleted"
DELETE_RESULT_WRONG_PASSWORD = "wrong_password"
DELETE_RESULT_IN_GAME = "in_game"
DELETE_RESULT_NOT_FOUND = "not_found"

# Not a bcrypt hash, so no password can ever match it.
WIPED_PASSWORD = "!deleted"


def delete_account(user_id, password):
    """
    Delete a player's account. `password` is asked for again, so a phone
    left signed in can't be used to delete someone's account.

    Returns one of the DELETE_RESULT_*.
    """
    player = db.session.get(Player, user_id)
    if player is None or player.is_deleted:
        return DELETE_RESULT_NOT_FOUND
    if not password_matches(player, password):
        return DELETE_RESULT_WRONG_PASSWORD
    return _delete(user_id)


def remove_account(user_id):
    """
    The organiser deleting an account - a duplicate or a joke one - with
    no password: exactly what deleting your own does, and nothing more.
    Run from the CLI (`flask --app app delete-player`), never an endpoint.
    Returns one of the DELETE_RESULT_* (never WRONG_PASSWORD).
    """
    player = db.session.get(Player, user_id)
    if player is None or player.is_deleted:
        return DELETE_RESULT_NOT_FOUND
    return _delete(user_id)


def _delete(user_id):
    """The deletion itself, once it's allowed. Returns a DELETE_RESULT_*."""
    # Out of every queue first, so matchmaking can't pull the player into
    # a new game while the rest of this runs.
    leave_all_queues(user_id)

    # A king waiting for a challenger gives the table up, which also hands
    # it to the next two in line. A game in progress refuses.
    if step_down(user_id) == STEP_DOWN_RESULT_IN_GAME:
        return DELETE_RESULT_IN_GAME

    _wipe(user_id)
    log.info("account %s deleted", user_id)
    return DELETE_RESULT_DELETED


@retry_on_deadlock
def _wipe(user_id):
    """Remove every personal detail from the player's row."""
    try:
        player = db.session.get(Player, user_id, populate_existing=True)
        # Random, so it can't collide with anyone's real username - or with
        # anyone registering "deleted-<id>" first.
        player.username = f"deleted-{player.user_id}-{secrets.token_hex(4)}"
        player.first_name = "Deleted"
        player.last_name = "Player"
        player.password_hash = WIPED_PASSWORD
        player.email = None
        player.country_flag = None
        player.profile_picture = None
        player.is_admin = False
        # The photo itself, if they uploaded one - not just the link to it.
        forget_uploaded_picture(user_id)
        forget_reset_code(user_id)
        player.deleted_at = func.now()
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
