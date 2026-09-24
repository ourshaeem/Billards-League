"""
Billiards League API.

Every route returns JSON, and every failure returns
{"message": "<something a person can read>"} - the frontend shows that
text as-is. Exception details go to the server log, never into a response:
a SQL statement in a pop-up tells a player nothing, and tells anyone
probing the server a great deal.
"""
import logging
import os
from datetime import timedelta

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from werkzeug.exceptions import HTTPException

from database import check_schema, configure_app, ensure_schema, reset_session
from logic.auth import login_user, register_user
from logic.leaderboard import top50_leaderboard
from logic.manage_queue import (
    JOIN_RESULT_ALREADY_PLAYING,
    JOIN_RESULT_ALREADY_QUEUED,
    STEP_DOWN_RESULT_IN_GAME,
    STEP_DOWN_RESULT_NOT_HOLDING,
    attempt_matchmaking,
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
    REPORT_RESULT_NO_OPPONENT,
    REPORT_RESULT_RECORDED,
    report_result,
)

log = logging.getLogger("billiards")

# Highest number of balls a player can have sunk in a reported game.
MAX_BALLS = 8

GENERIC_ERROR = "Something went wrong on our side. Please try again in a moment."


def create_app():
    """
    Build the Flask app.

    A factory rather than a module-level app so the tests can build an
    app pointed at in-memory SQLite. That is most of why testing gets
    easier after this refactor.
    """
    app = Flask(__name__)

    app.config["JWT_SECRET_KEY"] = os.environ.get(
        "JWT_SECRET_KEY", "super-secret-pool-key-change-in-production"
    )
    if app.config["JWT_SECRET_KEY"] == "super-secret-pool-key-change-in-production":
        print(
            "WARNING: JWT_SECRET_KEY is using the default baked into app.py. "
            "Set a real one in Backend/.env (see Backend/.env.example)."
        )
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)

    register_jwt_errors(JWTManager(app))
    CORS(app, origins=["http://localhost:5173", "http://127.0.0.1:5173"])

    configure_app(app)
    register_error_handlers(app)
    register_routes(app)

    return app


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


def register_error_handlers(app):
    """Anything a route didn't handle still leaves as readable JSON."""

    @app.errorhandler(HTTPException)
    def http_error(e):
        friendly = {
            404: "That page or action doesn't exist.",
            405: "That action isn't allowed here.",
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


def register_routes(app):
    # 1. LEADERBOARD (Public)
    @app.route("/leaderboard", methods=["GET"])
    def get_leaderboard():
        return jsonify(top50_leaderboard())

    # 2. QUEUE (Public)
    @app.route("/queue/<int:table_id>", methods=["GET"])
    def get_queue(table_id):
        return jsonify(view_queue(table_id))

    # 3. JOIN QUEUE (Protected)
    @app.route("/queue/join", methods=["POST"])
    @jwt_required()
    def join_table_queue():
        user_id = int(get_jwt_identity())

        data = json_body()
        table_id, bad = read_table_id(data)
        if bad:
            return bad

        # Queue and Matches both have foreign keys to Pool_Tables, so an
        # unknown table would fail deep inside the INSERT. Say so plainly.
        if get_pool_table(table_id) is None:
            return error("That table doesn't exist.", 404)

        try:
            result = join_queue(user_id, table_id)
        except Exception:
            log.exception("join_queue failed (user %s, table %s)", user_id, table_id)
            return error("Couldn't add you to the queue just now. Please try again.", 500)

        if result == JOIN_RESULT_ALREADY_PLAYING:
            return error("You're already playing or holding a table.", 409)

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

    # 3b. LEAVE QUEUE (Protected)
    @app.route("/queue/leave", methods=["POST"])
    @jwt_required()
    def leave_table_queue():
        user_id = int(get_jwt_identity())

        data = json_body()
        table_id, bad = read_table_id(data)
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
        table_id, bad = read_table_id(request.args)
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

        # Scores can legitimately arrive as strings from a form, or null.
        # Coerce once here so the comparison below can't raise a TypeError.
        try:
            my_balls = read_whole_number(data.get("my_balls"))
            opp_balls = read_whole_number(data.get("opp_balls"))
        except ValueError:
            return error("Both scores are required, as whole numbers.", 400)

        if not (0 <= my_balls <= MAX_BALLS) or not (0 <= opp_balls <= MAX_BALLS):
            return error(f"Scores must be between 0 and {MAX_BALLS}.", 400)

        if my_balls == opp_balls:
            return error("Scores can't be a tie - somebody sank the 8.", 400)

        # Which game the player is reporting - see report_result.
        expected_match_id = data.get("match_id")
        if expected_match_id is not None:
            try:
                expected_match_id = read_whole_number(expected_match_id)
            except ValueError:
                return error("match_id must be a whole number.", 400)

        try:
            outcome, details = report_result(user_id, my_balls, opp_balls, expected_match_id)
        except Exception:
            log.exception("recording a match failed (user %s)", user_id)
            reset_session()
            return error("Couldn't save the result just now. Please try again.", 500)

        if outcome == REPORT_RESULT_RECORDED:
            return jsonify({"message": "Match recorded.", **details})
        if outcome == REPORT_RESULT_ALREADY_REPORTED:
            return error("That game has already been reported, so this score wasn't saved.", 409)
        if outcome == REPORT_RESULT_NO_OPPONENT:
            return error("You don't have an opponent yet - waiting on the queue.", 409)
        return error("You don't have a game in progress to report.", 404)

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

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

    with app.app_context():
        ensure_schema()
        check_schema()

    debug_mode = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug_mode, port=int(os.environ.get("PORT", 5000)))
