"""
Billiards League API.

Every route returns JSON, and every failure returns
{"message": "<something a person can read>"} - the frontend shows that
text as-is. Exception details go to the server log, never into a response:
a SQL statement in a pop-up tells a player nothing, and tells anyone
probing the server a great deal.
"""
import json
import logging
import os
from datetime import datetime, timedelta

import click
from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from database import configure_app, describe_database, is_production, prepare_database, reset_session
from logic.auth import login_user, register_user
from logic.cancel_match import (
    CANCEL_RESULT_ALREADY_REQUESTED,
    CANCEL_RESULT_CANCELLED,
    CANCEL_RESULT_GAME_OVER,
    CANCEL_RESULT_NO_OPPONENT,
    CANCEL_RESULT_REQUESTED,
    KEEP_RESULT_GAME_OVER,
    KEEP_RESULT_KEPT,
    KEEP_RESULT_NOTHING_TO_KEEP,
    keep_playing,
    request_cancel,
)
from logic.corrections import GameProblem, game_summary, void_finished_match
from logic.countries import country_list
from logic.leaderboard import top50_leaderboard
from logic.match_history import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    league_history,
    player_history,
    player_opponents,
)
from logic.account import (
    DELETE_RESULT_DELETED,
    DELETE_RESULT_IN_GAME,
    DELETE_RESULT_WRONG_PASSWORD,
    delete_account,
)
from logic.pictures import MAX_UPLOAD_BYTES, picture_path, save_uploaded_picture, stored_picture
from logic.privacy import privacy_policy_html
from logic.seasons import league_standings, reset_league_standings
from logic.profile import EDITABLE_FIELDS, get_profile, get_public_profile, update_profile
from logic.tables import default_table_for, list_leagues, table_snapshot
from models import BILLIARDS, LEAGUE_NAMES, LEAGUE_TYPES, Player, db
from logic.manage_queue import (
    CONFIRM_RESULT_ALREADY_CONFIRMED,
    CONFIRM_RESULT_CONFIRMED,
    CONFIRM_RESULT_NOT_YOUR_TURN,
    CONFIRM_RESULT_TOO_LATE,
    JOIN_RESULT_ALREADY_PLAYING,
    JOIN_RESULT_ALREADY_QUEUED,
    READY_CHECK_SECONDS,
    STEP_DOWN_RESULT_IN_GAME,
    STEP_DOWN_RESULT_NOT_HOLDING,
    attempt_matchmaking,
    confirm_here,
    get_player_status,
    get_pool_table,
    get_queue_status,
    join_queue,
    leave_queue,
    step_down,
    view_queue,
)
from logic.record_match import (
    REPORT_RESULT_ALREADY_REPORTED,
    REPORT_RESULT_INVALID_SCORE,
    REPORT_RESULT_NO_OPPONENT,
    REPORT_RESULT_RECORDED,
    REPORT_RESULT_WRONG_LEAGUE,
    report_result,
)

log = logging.getLogger("billiards")

GENERIC_ERROR = "Something went wrong on our side. Please try again in a moment."

# Signs login tokens when JWT_SECRET_KEY isn't set - local development
# only. It is in this repo's history, so anyone could forge a login with
# it; a production start without a real key is refused (see create_app).
DEV_JWT_SECRET = "super-secret-pool-key-change-in-production"
# HS256 wants a key at least as long as its 256-bit output.
MIN_JWT_SECRET_LENGTH = 32
UNKNOWN_LEAGUE = "league_type must be 'billiards' or 'ping_pong'."
ACCOUNT_GONE = "We couldn't find your account. Please sign in again."


def create_app():
    """
    Build the Flask app.

    A factory rather than a module-level app so the tests can build an
    app pointed at in-memory SQLite. That is most of why testing gets
    easier after this refactor.
    """
    app = Flask(__name__)

    app.config["JWT_SECRET_KEY"] = jwt_secret()
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)
    # The largest request accepted: a picture upload at its limit, as
    # base64 (a third bigger), with room for the JSON around it. Anything
    # larger is refused before it's read.
    app.config["MAX_CONTENT_LENGTH"] = (MAX_UPLOAD_BYTES * 4) // 3 + 64 * 1024

    if is_production():
        # The host's proxy talks to this app over plain http and passes on
        # how the player connected in X-Forwarded-Proto. Without this the
        # links built for uploaded pictures would start http://, which
        # the apps won't load from a https:// page. Only in production:
        # with no proxy in front, anyone could set that header.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)

    register_jwt_errors(JWTManager(app))
    CORS(app, origins=cors_origins())

    configure_app(app)
    register_error_handlers(app)
    register_routes(app)
    register_commands(app)

    return app


def jwt_secret():
    """
    The key login tokens are signed with. In production a missing, known
    or short key stops the app starting: with the development key anyone
    could sign in as anyone, and a warning in a host's log is too easy to
    scroll past.
    """
    secret = os.environ.get("JWT_SECRET_KEY", "").strip()
    if is_production():
        if not secret or secret == DEV_JWT_SECRET or len(secret) < MIN_JWT_SECRET_LENGTH:
            raise RuntimeError(
                f"APP_ENV is production, so JWT_SECRET_KEY must be set to a random "
                f"string of at least {MIN_JWT_SECRET_LENGTH} characters "
                "(see Backend/.env.example)."
            )
        return secret
    if not secret:
        print(
            "WARNING: JWT_SECRET_KEY is using the default baked into app.py. "
            "Set a real one in Backend/.env (see Backend/.env.example)."
        )
        return DEV_JWT_SECRET
    return secret


def cors_origins():
    """
    Which websites' pages may call this API from a browser, from
    CORS_ORIGINS: "*" (any - the default for now) or a comma-separated
    list such as "https://league.example.com,http://localhost:5173".

    "*" is tolerable here because sign-in travels in the Authorization
    header, never a cookie: a page on another site can't make a player's
    browser send their token, so it can't act as them. Native mobile apps
    don't use CORS at all; this only matters to browsers, including the
    React Native app when run as a web page. Narrow it to the web
    frontend's address once that has one.
    """
    raw = os.environ.get("CORS_ORIGINS", "*").strip()
    if not raw or raw == "*":
        return "*"
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def register_commands(app):
    """Commands run with `flask --app app <command>` from Backend/."""

    @app.cli.command("prepare-db")
    def prepare_db_command():
        """
        Create or update the database's tables, then check them.

        gunicorn runs this before starting its workers. It's safe to run
        by hand at any time: every step checks before changing anything.
        Exits with an error if the database can't be reached.
        """
        logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
        try:
            prepare_database(app, require_connection=True)
        except RuntimeError as e:
            raise click.ClickException(str(e))

    @app.cli.command("reset-league")
    @click.argument("league", type=click.Choice(LEAGUE_TYPES))
    @click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
    @click.option(
        "--backup-dir",
        default="backups",
        show_default=True,
        help="Where to save everyone's numbers before the reset.",
    )
    def reset_league_command(league, yes, backup_dir):
        """
        Start LEAGUE over: everyone's rating to 0, record to 0-0, rank to
        the starting rank. Finished games stay in the history; the other
        league is untouched. Everyone's old numbers are saved to a JSON
        file in --backup-dir first, so the reset can be undone.
        """
        with app.app_context():
            before = league_standings(league)
            played = sum(1 for p in before if p["wins"] or p["losses"] or p["elo"])
            click.echo(
                f"{LEAGUE_NAMES[league]}: {len(before)} players, {played} with results, "
                f"on {describe_database(app.config['SQLALCHEMY_DATABASE_URI'])}."
            )
            if not yes:
                click.confirm("Reset everyone's ratings and records in this league?", abort=True)

            os.makedirs(backup_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = os.path.join(backup_dir, f"{league}-standings-{stamp}.json")
            with open(backup_path, "w") as f:
                json.dump({"league": league, "saved_at": stamp, "players": before}, f, indent=2)
            click.echo(f"Saved everyone's numbers to {backup_path}")

            count = reset_league_standings(league)
            click.echo(f"Reset {count} players in the {LEAGUE_NAMES[league]}.")

    @app.cli.command("void-game")
    @click.argument("match_id", type=int)
    @click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
    @click.option(
        "--backup-dir",
        default="backups",
        show_default=True,
        help="Where to save the game and both players' numbers first.",
    )
    def void_game_command(match_id, yes, backup_dir):
        """
        Take back finished game MATCH_ID - one played by accident, say. It
        leaves the history, the winner gives back the points it gave them,
        the loser gets back what it cost them, and each loses the game from
        their record. Games since stay as they were. The game and both
        players' numbers are saved to a JSON file in --backup-dir first.
        (The match_id is in GET /matches/history.)
        """
        with app.app_context():
            try:
                game = game_summary(match_id)
            except GameProblem as e:
                raise click.ClickException(str(e))

            winner, loser, change = game["winner"], game["loser"], game["elo_change"]
            score = "-".join(str(s) for s in game["score"]) if None not in game["score"] else "no score"
            when = (
                f"{round(game['seconds_ago'] / 3600, 1)} hours ago"
                if game["seconds_ago"] is not None
                else "at an unknown time"
            )
            click.echo(
                f"Game #{match_id}, {game['league_name']}, {when}: {winner['username']} beat "
                f"{loser['username']} {score}, moving {change} points.\n"
                f"  {winner['username']}: {winner['elo']} points, {winner['wins']}-{winner['losses']}"
                f" -> {winner['elo'] - change} points, {max(0, winner['wins'] - 1)}-{winner['losses']}\n"
                f"  {loser['username']}: {loser['elo']} points, {loser['wins']}-{loser['losses']}"
                f" -> {loser['elo'] + change} points, {loser['wins']}-{max(0, loser['losses'] - 1)}\n"
                f"On {describe_database(app.config['SQLALCHEMY_DATABASE_URI'])}."
            )
            if not yes:
                click.confirm("Remove this game and undo its points?", abort=True)

            os.makedirs(backup_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = os.path.join(backup_dir, f"voided-game-{match_id}-{stamp}.json")
            with open(backup_path, "w") as f:
                json.dump({"voided_at": stamp, "game": game}, f, indent=2)
            click.echo(f"Saved the game and both players' numbers to {backup_path}")

            try:
                result = void_finished_match(match_id)
            except GameProblem as e:
                raise click.ClickException(str(e))
            after = result["after"]
            click.echo(
                f"Game #{match_id} removed. {after['winner']['username']}: {after['winner']['elo']} "
                f"points, {after['winner']['wins']}-{after['winner']['losses']}. "
                f"{after['loser']['username']}: {after['loser']['elo']} points, "
                f"{after['loser']['wins']}-{after['loser']['losses']}."
            )


def error(message, status, **extra):
    """The one failure shape: {"message": ..., plus any data keys}."""
    return jsonify({"message": message, **extra}), status


def register_jwt_errors(jwt):
    """
    flask-jwt-extended answers bad tokens with {"msg": ...}. Everything
    else in this API says "message", so these make tokens say it too.
    The frontend treats any 401 on a signed-in call as "session ended".
    """

    @jwt.unauthorized_loader
    def missing_token(_reason):
        return error("Please sign in to do that.", 401)

    @jwt.invalid_token_loader
    def bad_token(_reason):
        return error("Your session isn't valid any more. Please sign in again.", 401)

    @jwt.expired_token_loader
    def expired_token(_header, _payload):
        return error("Your session expired. Please sign in again.", 401)

    @jwt.token_in_blocklist_loader
    def account_gone(_header, payload):
        """
        A token for an account that has been deleted - or that never
        existed - is refused at once, rather than honoured until it
        expires a day later. One lookup by primary key per signed-in
        request.
        """
        try:
            user_id = int(payload.get("sub"))
        except (TypeError, ValueError):
            return True
        player = db.session.get(Player, user_id)
        return player is None or player.is_deleted

    @jwt.revoked_token_loader
    def revoked_token(_header, _payload):
        return error("Your session isn't valid any more. Please sign in again.", 401)


def register_error_handlers(app):
    """Anything a route didn't handle still leaves as readable JSON."""

    @app.errorhandler(HTTPException)
    def http_error(e):
        friendly = {
            404: "That page or action doesn't exist.",
            405: "That action isn't allowed here.",
            413: "That's too big to upload. Pick a smaller picture.",
        }
        return error(friendly.get(e.code, e.description or GENERIC_ERROR), e.code)

    @app.errorhandler(Exception)
    def unexpected_error(e):
        log.exception("unhandled error on %s %s", request.method, request.path)
        # A failed transaction left open would poison the next request on
        # the same connection.
        reset_session()
        return error(GENERIC_ERROR, 500)


def json_body():
    """
    The request's JSON object, or {} for anything else.

    get_json(silent=True) rather than request.json: the latter raises 415
    when the Content-Type header is missing, which the frontend can
    neither predict nor explain. And the isinstance check because valid
    JSON needn't be an object - a body of [1, 2] or "hi" used to reach
    data.get() and come back as a 500.
    """
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def read_whole_number(value):
    """
    int(value) for a whole number, else ValueError. Stricter than int():
    int(8.5) is 8 and int(True) is 1, so a score of 8.5 used to be saved
    as 8 without a word.
    """
    if isinstance(value, bool):
        raise ValueError("not a number")
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError("not whole")
        return int(value)
    if isinstance(value, str):
        return int(value.strip())
    if isinstance(value, int):
        return value
    raise ValueError("not a number")


def read_table_id(source):
    """
    table_id from a request body or query string: (table_id, None) or
    (None, error_response). Defaults to table 1, the only table the UI
    offers today.
    """
    raw = source.get("table_id", 1)
    try:
        table_id = read_whole_number(raw)
    except ValueError:
        return None, error("table_id must be a whole number.", 400)
    if table_id < 1:
        return None, error("table_id must be a whole number.", 400)
    return table_id, None


def read_league(source):
    """
    league_type from a request body or query string: (league, None) or
    (None, error_response). (None, None) means the request didn't say.
    """
    raw = source.get("league_type")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, None
    if isinstance(raw, str) and raw.strip().lower() in LEAGUE_TYPES:
        return raw.strip().lower(), None
    return None, error(UNKNOWN_LEAGUE, 400)


def read_table_and_league(source, must_exist=False):
    """
    Which table a request is about, and that table's league:
    (table_id, league, None) or (None, None, error_response).

      - table_id given: that table. If league_type is given as well it
        has to be the table's league, so a ping pong request can't act on
        the pool table.
      - only league_type: that league's table.
      - neither: table 1, as before there were two leagues.

    must_exist refuses a table with no Pool_Tables row. Queue and Matches
    both have foreign keys to Pool_Tables, so joining an unknown table
    would otherwise fail deep inside the INSERT.
    """
    league, bad = read_league(source)
    if bad:
        return None, None, bad

    if source.get("table_id") is None and league is not None:
        table_id = default_table_for(league)
        if table_id is None:
            return None, None, error(f"The {LEAGUE_NAMES[league]} doesn't have a table yet.", 404)
        return table_id, league, None

    table_id, bad = read_table_id(source)
    if bad:
        return None, None, bad

    table = get_pool_table(table_id)
    if table is None and must_exist:
        return None, None, error("That table doesn't exist.", 404)

    table_league = table.league_type if table is not None else BILLIARDS
    if league is not None and league != table_league:
        table_name = table.table_name if table is not None else f"Table {table_id}"
        return None, None, error(
            f"{table_name} is in the {LEAGUE_NAMES[table_league]}, "
            f"not the {LEAGUE_NAMES[league]}.",
            400,
        )
    return table_id, table_league, None


def read_match_id(source):
    """
    The game a request is about, as the player saw it: (match_id or None,
    None) or (None, error_response). Optional - older apps don't send it.
    """
    raw = source.get("match_id")
    if raw is None:
        return None, None
    try:
        return read_whole_number(raw), None
    except ValueError:
        return None, error("match_id must be a whole number.", 400)


def read_player_id(source, key):
    """
    A player id from a query string: (id or None, None) or (None, error).
    None when the request didn't send one.
    """
    raw = source.get(key)
    if raw is None or raw == "":
        return None, None
    try:
        value = read_whole_number(raw)
    except ValueError:
        value = 0
    if value < 1:
        return None, error(f"{key} must be a player's id, a whole number.", 400)
    return value, None


def read_limit(source):
    """How many history entries to return: (limit, None) or (None, error)."""
    problem = f"limit must be a whole number from 1 to {MAX_LIMIT}."
    try:
        limit = read_whole_number(source.get("limit", DEFAULT_LIMIT))
    except ValueError:
        return None, error(problem, 400)
    if not 1 <= limit <= MAX_LIMIT:
        return None, error(problem, 400)
    return limit, None


def register_routes(app):
    # 1. LEADERBOARD (Public)
    @app.route("/leaderboard", methods=["GET"])
    def get_leaderboard():
        league, bad = read_league(request.args)
        if bad:
            return bad
        return jsonify(top50_leaderboard(league or BILLIARDS))

    # 1b. LEAGUES (Public) - each league and the table it plays on.
    @app.route("/leagues", methods=["GET"])
    def get_leagues():
        return jsonify({"leagues": list_leagues()})

    # 2. QUEUE (Public)
    @app.route("/queue/<int:table_id>", methods=["GET"])
    def get_queue(table_id):
        return jsonify(view_queue(table_id))

    # 2b. WHO IS AT A TABLE (Public)
    @app.route("/table/<int:table_id>", methods=["GET"])
    def get_table(table_id):
        snapshot = table_snapshot(table_id)
        if snapshot is None:
            return error("That table doesn't exist.", 404)
        return jsonify({"table": snapshot})

    # 3. JOIN QUEUE (Protected)
    @app.route("/queue/join", methods=["POST"])
    @jwt_required()
    def join_table_queue():
        user_id = int(get_jwt_identity())

        # league_type picks the league's table; table_id picks a table
        # directly. Both, and they have to agree.
        table_id, _league, bad = read_table_and_league(json_body(), must_exist=True)
        if bad:
            return bad

        try:
            result = join_queue(user_id, table_id)
        except Exception:
            log.exception("join_queue failed (user %s, table %s)", user_id, table_id)
            return error("Couldn't add you to the queue just now. Please try again.", 500)

        if result == JOIN_RESULT_ALREADY_PLAYING:
            return error("You're already playing or holding a table.", 409)

        if result == JOIN_RESULT_ALREADY_QUEUED:
            # Tapping Join again when it's your turn says you're here, as
            # "I'm here" does. It's the only way an app from before the
            # ready check has to say so: it shows a player whose turn has
            # come the Join button. Too late, and they join again at the
            # back of the line - which is what they asked for.
            try:
                if confirm_here(user_id, table_id) == CONFIRM_RESULT_TOO_LATE:
                    result = join_queue(user_id, table_id)
            except Exception:
                log.exception("confirming on a repeat join failed (user %s)", user_id)

        # Always attempt matchmaking, whether this call freshly joined or
        # found the player already waiting. That is what makes the queue
        # self-healing: anyone stuck behind a king from before the fix
        # gets matched simply by tapping Join again.
        try:
            match_started = attempt_matchmaking(table_id)
        except Exception:
            # The join itself worked. Matchmaking runs again on the next
            # status poll, so this heals itself; say so rather than alarm.
            log.exception("matchmaking after join failed (table %s)", table_id)
            match_started = False

        if match_started:
            message = "Match found - get to the table!"
        elif result == JOIN_RESULT_ALREADY_QUEUED:
            message = "You're already in the queue, waiting for an opponent."
        else:
            message = "Joined the queue! Waiting for an opponent..."

        return jsonify(
            {"message": message, "status": result, "match_started": match_started}
        )

    # 3a. "I'M HERE" - THE READY CHECK (Protected)
    # When a player's turn comes they have READY_CHECK_SECONDS to say
    # they're here, or they're taken out of the queue.
    @app.route("/queue/confirm", methods=["POST"])
    @jwt_required()
    def confirm_in_queue():
        user_id = int(get_jwt_identity())

        table_id, _league, bad = read_table_and_league(json_body())
        if bad:
            return bad

        try:
            outcome = confirm_here(user_id, table_id)
        except Exception:
            log.exception("confirm_here failed (user %s, table %s)", user_id, table_id)
            reset_session()
            return error("Couldn't confirm just now. Please try again.", 500)

        if outcome == CONFIRM_RESULT_NOT_YOUR_TURN:
            return error("It isn't your turn yet - we'll ask when it is.", 409)
        if outcome == CONFIRM_RESULT_TOO_LATE:
            # The minute was up, so they've been taken out of the queue;
            # the next in line is up instead.
            try:
                attempt_matchmaking(table_id)
            except Exception:
                log.exception("matchmaking after a late confirm failed (table %s)", table_id)
            return error(
                f"Sorry - that was more than {READY_CHECK_SECONDS} seconds, so you were taken "
                "out of the queue. Join again to get back in line.",
                409,
            )
        if outcome not in (CONFIRM_RESULT_CONFIRMED, CONFIRM_RESULT_ALREADY_CONFIRMED):
            return error(
                "You're not in the queue any more. If it was your turn, the time to "
                "confirm may have run out - join again to get back in line.",
                404,
            )

        try:
            match_started = attempt_matchmaking(table_id)
        except Exception:
            # Confirmed all the same; the next status poll starts the game.
            log.exception("matchmaking after a confirm failed (table %s)", table_id)
            match_started = False

        return jsonify(
            {
                "message": (
                    "You're on - get to the table!"
                    if match_started
                    else "Thanks - waiting for your opponent to confirm."
                ),
                "status": outcome,
                "match_started": match_started,
            }
        )

    # 3b. LEAVE QUEUE (Protected)
    @app.route("/queue/leave", methods=["POST"])
    @jwt_required()
    def leave_table_queue():
        user_id = int(get_jwt_identity())

        table_id, _league, bad = read_table_and_league(json_body())
        if bad:
            return bad

        status = get_queue_status(user_id, table_id)
        if status is None:
            return error("You're not currently in the queue.", 404)

        # Enforced here, not just by disabling the button. Anyone can POST
        # to this endpoint directly.
        if not status["can_leave"]:
            return error(
                f"Hang tight - you can leave in {status['leave_unlocks_in']}s "
                "if you haven't matched by then.",
                403,
                leave_unlocks_in=status["leave_unlocks_in"],
            )

        try:
            removed = leave_queue(user_id, table_id)
        except Exception:
            log.exception("leave_queue failed (user %s, table %s)", user_id, table_id)
            return error("Couldn't take you out of the queue just now. Please try again.", 500)

        if removed:
            # If it was their turn, the next in line is up now rather than
            # at the next status poll.
            if status["called"]:
                try:
                    attempt_matchmaking(table_id)
                except Exception:
                    log.exception("matchmaking after leaving failed (table %s)", table_id)
            return jsonify({"message": "You left the queue."})
        # Matchmaking got there first.
        return error("You're not in the queue any more - you may have just been matched.", 404)

    # 3c. STEP DOWN FROM THE TABLE (Protected)
    @app.route("/table/step-down", methods=["POST"])
    @jwt_required()
    def step_down_from_table():
        user_id = int(get_jwt_identity())

        try:
            result = step_down(user_id)
        except Exception:
            log.exception("step_down failed (user %s)", user_id)
            return error("Couldn't give up the table just now. Please try again.", 500)

        if result == STEP_DOWN_RESULT_NOT_HOLDING:
            return error("You aren't holding a table.", 404)
        if result == STEP_DOWN_RESULT_IN_GAME:
            return error(
                "A challenger is already on - finish the game and report the score first.", 409
            )
        return jsonify({"message": "You gave up the table. Thanks for playing!"})

    # 4. LOGIN (Token Generator)
    @app.route("/login", methods=["POST"])
    def login():
        data = json_body()
        username, password = data.get("username"), data.get("password")

        if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
            return error("Username and password required", 400)

        user = login_user(username, password)

        if user:
            access_token = create_access_token(identity=str(user["user_id"]))
            return (
                jsonify(
                    {
                        "message": "Login successful",
                        "access_token": access_token,
                        "user_id": user["user_id"],
                        "username": user["username"],
                    }
                ),
                200,
            )

        return error("Invalid credentials", 401)

    # 5. MATCH STATUS (Protected)
    @app.route("/match/status", methods=["GET"])
    @jwt_required()
    def get_match_status():
        user_id = int(get_jwt_identity())
        table_id, _league, bad = read_table_and_league(request.args)
        if bad:
            return bad

        try:
            return jsonify(get_player_status(user_id, table_id))
        except Exception:
            log.exception("status check failed (user %s)", user_id)
            reset_session()
            # Not {"status": "idle"}: that told the UI to offer a Join
            # button to someone who might be mid-game.
            return error("Couldn't load your status just now.", 500)

    # 6. RECORD MATCH (Protected)
    @app.route("/match/record", methods=["POST"])
    @jwt_required()
    def record_match():
        user_id = int(get_jwt_identity())

        data = json_body()

        # The league the player thinks this game is in. Optional; the
        # game's real league is what decides the rules either way.
        league_type, bad = read_league(data)
        if bad:
            return bad

        # Scores can legitimately arrive as strings from a form, or null.
        # Coerce once here so the comparisons later can't raise a
        # TypeError. my_balls / opp_balls hold the score in the game's own
        # units: balls sunk in billiards, points in ping pong. Whether the
        # score is a possible one is checked against the game's league,
        # under the same lock that records it (see report_result).
        try:
            my_score = read_whole_number(data.get("my_balls"))
            opp_score = read_whole_number(data.get("opp_balls"))
        except ValueError:
            return error("Both scores are required, as whole numbers.", 400)

        # Which game the player is reporting - see report_result.
        expected_match_id, bad = read_match_id(data)
        if bad:
            return bad

        try:
            outcome, details = report_result(
                user_id, my_score, opp_score, expected_match_id, league_type
            )
        except Exception:
            log.exception("recording a match failed (user %s)", user_id)
            reset_session()
            return error("Couldn't save the result just now. Please try again.", 500)

        if outcome == REPORT_RESULT_RECORDED:
            return jsonify({"message": "Match recorded.", **details})
        if outcome == REPORT_RESULT_INVALID_SCORE:
            return error(details["problem"], 400)
        if outcome == REPORT_RESULT_WRONG_LEAGUE:
            actual = details["league_type"]
            return error(
                f"That game is in the {LEAGUE_NAMES[actual]}, so it wasn't recorded here.",
                409,
                league_type=actual,
            )
        if outcome == REPORT_RESULT_ALREADY_REPORTED:
            return error("That game has already been reported, so this score wasn't saved.", 409)
        if outcome == REPORT_RESULT_NO_OPPONENT:
            return error("You don't have an opponent yet - waiting on the queue.", 409)
        return error("You don't have a game in progress to report.", 404)

    # 6a. CALL A GAME OFF - BOTH PLAYERS MUST AGREE (Protected)
    # The first player to ask records a request; the other agreeing (the
    # same call) cancels the game. Nothing is recorded either way.
    @app.route("/match/cancel", methods=["POST"])
    @jwt_required()
    def cancel_match():
        user_id = int(get_jwt_identity())
        expected_match_id, bad = read_match_id(json_body())
        if bad:
            return bad

        try:
            outcome = request_cancel(user_id, expected_match_id)
        except Exception:
            log.exception("cancelling a game failed (user %s)", user_id)
            reset_session()
            return error("Couldn't cancel the game just now. Please try again.", 500)

        if outcome == CANCEL_RESULT_CANCELLED:
            return jsonify({"message": "Game cancelled - nothing was recorded.", "status": outcome})
        if outcome in (CANCEL_RESULT_REQUESTED, CANCEL_RESULT_ALREADY_REQUESTED):
            return jsonify(
                {
                    "message": "Asked to cancel. The game is called off once your opponent agrees.",
                    "status": outcome,
                }
            )
        if outcome == CANCEL_RESULT_GAME_OVER:
            return error("That game has already finished.", 409)
        if outcome == CANCEL_RESULT_NO_OPPONENT:
            return error(
                "You don't have a game to cancel - nobody has challenged you yet. "
                "You can give up the table instead.",
                409,
            )
        return error("You don't have a game in progress to cancel.", 404)

    # 6a2. KEEP PLAYING (Protected)
    # Take back your own request to cancel, or turn down your opponent's.
    @app.route("/match/keep", methods=["POST"])
    @jwt_required()
    def keep_match():
        user_id = int(get_jwt_identity())
        expected_match_id, bad = read_match_id(json_body())
        if bad:
            return bad

        try:
            outcome = keep_playing(user_id, expected_match_id)
        except Exception:
            log.exception("keeping a game failed (user %s)", user_id)
            reset_session()
            return error("Couldn't update the game just now. Please try again.", 500)

        if outcome in (KEEP_RESULT_KEPT, KEEP_RESULT_NOTHING_TO_KEEP):
            return jsonify({"message": "The game is on.", "status": outcome})
        if outcome == KEEP_RESULT_GAME_OVER:
            return error("That game has already finished.", 409)
        return error("You don't have a game in progress.", 404)

    # 6b. MATCH HISTORY (Public)
    # The latest finished games in a league - or at one table, which
    # implies its league.
    @app.route("/matches/history", methods=["GET"])
    def get_match_history():
        table_id = None
        if request.args.get("table_id") is not None:
            table_id, league, bad = read_table_and_league(request.args, must_exist=True)
        else:
            league, bad = read_league(request.args)
        if bad:
            return bad

        limit, bad = read_limit(request.args)
        if bad:
            return bad

        league = league or BILLIARDS
        return jsonify(
            {"league_type": league, "matches": league_history(league, table_id, limit)}
        )

    # 6c. ONE PLAYER'S MATCH HISTORY (Public)
    # opponent_id narrows it to the games between those two: head to head.
    @app.route("/players/<int:user_id>/matches", methods=["GET"])
    def get_player_matches(user_id):
        league, bad = read_league(request.args)
        if bad:
            return bad
        limit, bad = read_limit(request.args)
        if bad:
            return bad
        opponent_id, bad = read_player_id(request.args, "opponent_id")
        if bad:
            return bad

        if db.session.get(Player, user_id) is None:
            return error("That player doesn't exist.", 404)

        league = league or BILLIARDS
        body = {
            "user_id": user_id,
            "league_type": league,
            "matches": player_history(user_id, league, limit, opponent_id),
        }
        if opponent_id is not None:
            body["opponent_id"] = opponent_id
        return jsonify(body)

    # 6c2. A PLAYER'S PROFILE (Public)
    # Their picture, flag and both leagues' standings - never their name.
    @app.route("/players/<int:user_id>", methods=["GET"])
    def get_player_profile(user_id):
        profile = get_public_profile(user_id)
        if profile is None:
            if db.session.get(Player, user_id) is not None:
                return error("This player has deleted their account.", 404)
            return error("That player doesn't exist.", 404)
        return jsonify({"player": profile})

    # 6c3. A PLAYER'S RECORD AGAINST EVERYONE THEY'VE PLAYED (Public)
    @app.route("/players/<int:user_id>/opponents", methods=["GET"])
    def get_player_opponents(user_id):
        league, bad = read_league(request.args)
        if bad:
            return bad
        if db.session.get(Player, user_id) is None:
            return error("That player doesn't exist.", 404)

        league = league or BILLIARDS
        return jsonify(
            {
                "user_id": user_id,
                "league_type": league,
                "opponents": player_opponents(user_id, league),
            }
        )

    # 6c4. AN UPLOADED PROFILE PICTURE (Public, an image)
    # The link carries the picture's version (?v=...), so a new picture
    # has a new link and the old one can be cached for good.
    @app.route("/players/<int:user_id>/picture", methods=["GET"])
    def get_player_picture(user_id):
        picture = stored_picture(user_id)
        if picture is None:
            return error("That player doesn't have an uploaded picture.", 404)
        image, digest = picture
        response = Response(image, mimetype="image/jpeg")
        if request.args.get("v") == picture_path(user_id, digest).rpartition("=")[2]:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    # 6d. YOUR PROFILE (Protected)
    @app.route("/profile", methods=["GET"])
    @jwt_required()
    def get_my_profile():
        profile = get_profile(int(get_jwt_identity()))
        if profile is None:
            return error(ACCOUNT_GONE, 404)
        return jsonify({"profile": profile})

    # 6e. CHANGE YOUR FLAG / PICTURE (Protected)
    # Send either field or both; null or "" clears one. A refusal names
    # the field it's about in "field", so the form can show it there.
    @app.route("/profile", methods=["PATCH"])
    @jwt_required()
    def update_my_profile():
        user_id = int(get_jwt_identity())
        data = json_body()

        if not any(field in data for field in EDITABLE_FIELDS):
            return error("Nothing to change - send a country_flag or a profile_picture.", 400)

        try:
            problem, profile = update_profile(user_id, data)
        except Exception:
            log.exception("updating a profile failed (user %s)", user_id)
            reset_session()
            return error("Couldn't save your profile just now. Please try again.", 500)

        if problem:
            return error(problem["message"], 400, field=problem["field"])
        if profile is None:
            return error(ACCOUNT_GONE, 404)
        return jsonify({"message": "Profile saved.", "profile": profile})

    # 6e2. UPLOAD A PROFILE PICTURE (Protected)
    # Body {"image": "<base64>"} - a data: URL is fine too. The server
    # turns it into a small square JPEG with no metadata (see
    # logic/pictures.py), replacing any picture or link the player had.
    # Removing it is PATCH /profile with profile_picture null.
    @app.route("/profile/picture", methods=["POST"])
    @jwt_required()
    def upload_my_picture():
        user_id = int(get_jwt_identity())
        # Read outside the try: a body over MAX_CONTENT_LENGTH raises 413
        # here, which must reach the error handler as "too big", not be
        # caught below as a failure to save.
        image = json_body().get("image")

        try:
            problem, profile = save_uploaded_picture(user_id, image)
        except Exception:
            log.exception("saving an uploaded picture failed (user %s)", user_id)
            reset_session()
            return error("Couldn't save your picture just now. Please try again.", 500)

        if problem:
            return error(problem["message"], 400, field=problem["field"])
        if profile is None:
            return error(ACCOUNT_GONE, 404)
        return jsonify({"message": "Picture saved.", "profile": profile})

    # 6g. DELETE YOUR ACCOUNT (Protected)
    # Asks for the password again. A wrong one is 403, not 401: to the
    # apps a 401 means "your session ended" and signs the player out.
    @app.route("/profile/delete", methods=["POST"])
    @jwt_required()
    def delete_my_account():
        user_id = int(get_jwt_identity())
        password = json_body().get("password")

        if not isinstance(password, str) or not password:
            return error("Enter your password to delete your account.", 400, field="password")

        try:
            outcome = delete_account(user_id, password)
        except Exception:
            log.exception("deleting account %s failed", user_id)
            reset_session()
            return error("Couldn't delete your account just now. Please try again.", 500)

        if outcome == DELETE_RESULT_DELETED:
            return jsonify({"message": "Your account was deleted."})
        if outcome == DELETE_RESULT_WRONG_PASSWORD:
            return error("That password isn't right.", 403, field="password")
        if outcome == DELETE_RESULT_IN_GAME:
            return error(
                "You're in a game right now - report the score first, then delete your account.",
                409,
            )
        return error(ACCOUNT_GONE, 404)

    # 6h. PRIVACY POLICY (Public, a web page)
    # The app stores link here, and the apps' Profile screens do too.
    @app.route("/privacy", methods=["GET"])
    def privacy_policy():
        return Response(privacy_policy_html(), mimetype="text/html")

    # 6f. COUNTRIES FOR THE FLAG PICKER (Public)
    @app.route("/countries", methods=["GET"])
    def get_countries():
        return jsonify({"countries": country_list()})

    # 7. REGISTER (Public)
    @app.route("/register", methods=["POST"])
    def register():
        data = json_body()

        if not all(
            key in data for key in ["username", "first_name", "last_name", "password"]
        ):
            return error("All fields are required", 400)

        success, message = register_user(
            data["username"], data["first_name"], data["last_name"], data["password"]
        )

        return jsonify({"message": message}), 201 if success else 400

    # 8. HEALTH CHECK (Public)
    @app.route("/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "healthy", "service": "billiards-league-api"})

    # 9. FORCE MATCH START (Debug only)
    # No login requirement, so it only exists when explicitly switched on.
    if os.environ.get("ENABLE_DEBUG_ROUTES") == "1":

        @app.route("/debug/start-match", methods=["POST"])
        def debug_start_match():
            table_id, bad = read_table_id(json_body())
            if bad:
                return bad

            if attempt_matchmaking(table_id):
                return jsonify({"message": "Match created.", "match_started": True})
            return error(
                "Nothing to match - need someone waiting in the queue.", 400, match_started=False
            )

        print("NOTE: debug routes are enabled (ENABLE_DEBUG_ROUTES=1). Turn this off for the real league.")


app = create_app()

# Local development: `python app.py`. The container runs gunicorn
# instead (see gunicorn.conf.py), which prepares the database itself.
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

    prepare_database(app)

    debug_mode = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug_mode, port=int(os.environ.get("PORT", 5000)))
