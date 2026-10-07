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
    verify_jwt_in_request,
)
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from database import configure_app, describe_database, is_production, prepare_database, reset_session
from logic.auth import (
    clean_email,
    find_player,
    hash_password,
    login_user,
    password_problem,
    register_user,
)
from logic.achievements import (
    mark_badges_seen,
    new_badges,
    player_badges,
    set_featured_badge,
)
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
from logic.corrections import (
    GameProblem,
    add_past_games,
    game_summary,
    past_game_problem,
    void_finished_match,
)
from logic.countries import country_list
from logic.global_leaderboard import global_leaderboard
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
    remove_account,
)
from logic.king_votes import (
    HERE_RESULT_NOT_KING,
    VOTE_RESULT_ALREADY_VOTED,
    VOTE_RESULT_EVERYONE_VOTED,
    VOTE_RESULT_GAME_CHANGED,
    VOTE_RESULT_NO_KING,
    VOTE_RESULT_NOT_VOTED,
    VOTE_RESULT_NOT_WAITING,
    VOTE_RESULT_WITHDRAWN,
    VOTE_RESULT_YOU_ARE_KING,
    cast_vote,
    king_is_here,
)
from logic.admin import (
    QUEUE_REMOVE_RESULT_NOT_QUEUED,
    TABLE_REMOVE_RESULT_GAME_CALLED_OFF,
    TABLE_REMOVE_RESULT_GAME_CHANGED,
    TABLE_REMOVE_RESULT_NOT_AT_TABLE,
    is_admin,
    remove_from_queue,
    remove_from_table,
)
from logic.leagues import (
    REMOVE_TABLE_RESULT_BUSY,
    REMOVE_TABLE_RESULT_NOT_FOUND,
    UNLOCK_RESULT_ALREADY,
    UNLOCK_RESULT_BAD_FORMAT,
    UNLOCK_RESULT_NO_PIN,
    UNLOCK_RESULT_TOO_MANY,
    UNLOCK_RESULT_UNLOCKED,
    LeagueProblem,
    add_table,
    has_access,
    league_directory,
    league_summary,
    remove_table,
    rename_table,
    set_league_pin,
    unlock_league,
)
from logic.mailer import MailFailed, MailNotConfigured, mail_configured
from logic.password_reset import (
    CODE_LIFETIME_SECONDS,
    RESET_DONE,
    RESET_EXPIRED,
    RESET_TOO_MANY_TRIES,
    RESET_WRONG_CODE,
    forget_reset_code,
    request_reset,
    reset_password,
)
from logic.pictures import MAX_UPLOAD_BYTES, picture_path, save_uploaded_picture, stored_picture
from logic.privacy import privacy_policy_html
from logic.seasons import league_standings, reset_league_standings
from logic.profile import EDITABLE_FIELDS, get_profile, get_public_profile, set_email, update_profile
from logic.tables import (
    active_tables,
    default_table_for,
    league_for_table,
    league_tables,
    list_leagues,
    table_names,
    table_snapshot,
)
from logic.top_players import top_players
from models import BILLIARDS, GAMES, League, Match, Player, PoolTable, db
from logic.manage_queue import (
    CONFIRM_RESULT_ALREADY_CONFIRMED,
    CONFIRM_RESULT_CONFIRMED,
    CONFIRM_RESULT_NOT_YOUR_TURN,
    CONFIRM_RESULT_TOO_LATE,
    JOIN_RESULT_ALREADY_PLAYING,
    JOIN_RESULT_ALREADY_QUEUED,
    JOIN_RESULT_CALLED_ELSEWHERE,
    JOIN_RESULT_NO_SUCH_TABLE,
    JOIN_RESULT_SWITCHED,
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
    lowered_rating,
    REPORT_RESULT_ALREADY_REPORTED,
    REPORT_RESULT_INVALID_SCORE,
    REPORT_RESULT_NO_ACCESS,
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
NO_SUCH_LEAGUE = "There's no such league."
# What a player who hasn't entered a league's PIN hears on trying to play.
NEEDS_PIN = "Enter this league's 4-digit PIN to play here."
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
    @click.argument("league")
    @click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
    @click.option(
        "--backup-dir",
        default="backups",
        show_default=True,
        help="Where to save everyone's numbers before the reset.",
    )
    def reset_league_command(league, yes, backup_dir):
        """
        Start LEAGUE (a slug like ccny-ping-pong; "billiards" or
        "ping_pong" mean CCNY's) over: everyone's rating to 0, record to
        0-0, rank to the starting rank. Finished games stay in the history;
        every other league is untouched. Everyone's old numbers are saved to
        a JSON file in --backup-dir first, so the reset can be undone.
        """
        with app.app_context():
            league = _league_named(league)
            before = league_standings(league)
            played = sum(1 for p in before if p["wins"] or p["losses"] or p["elo"])
            click.echo(
                f"{league.name}: {len(before)} players, {played} with results, "
                f"on {describe_database(app.config['SQLALCHEMY_DATABASE_URI'])}."
            )
            if not yes:
                click.confirm("Reset everyone's ratings and records in this league?", abort=True)

            os.makedirs(backup_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = os.path.join(backup_dir, f"{league.slug}-standings-{stamp}.json")
            with open(backup_path, "w") as f:
                json.dump({"league": league.slug, "saved_at": stamp, "players": before}, f, indent=2)
            click.echo(f"Saved everyone's numbers to {backup_path}")

            count = reset_league_standings(league)
            click.echo(f"Reset {count} players in {league.name}.")

    @app.cli.command("set-password")
    @click.argument("username")
    @click.password_option(
        prompt="New password for them", confirmation_prompt=True, help="The new password."
    )
    def set_password_command(username, password):
        """
        Give USERNAME (or the account with that email) a new password - for
        a player who's forgotten theirs and can't get a reset email: no
        email on the account, or email isn't set up on the server yet.
        Tell them the new one and ask them to change it.
        """
        with app.app_context():
            player = find_player(username)
            if player is None or player.is_deleted:
                raise click.ClickException(f"There's no account called {username!r}.")
            problem = password_problem(password)
            if problem:
                raise click.ClickException(problem)
            player.password_hash = hash_password(password)
            forget_reset_code(player.user_id)
            db.session.commit()
            click.echo(
                f"{player.username}'s password is changed, on "
                f"{describe_database(app.config['SQLALCHEMY_DATABASE_URI'])}."
            )

    @app.cli.command("delete-player")
    @click.argument("usernames", nargs=-1, required=True)
    @click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
    @click.option(
        "--backup-dir",
        default="backups",
        show_default=True,
        help="Where to save a list of what was removed first.",
    )
    def delete_player_command(usernames, yes, backup_dir):
        """
        Delete the accounts USERNAMES (exact usernames, or emails) - for
        the organiser removing duplicate or joke accounts. Each goes
        exactly as if they'd deleted it themselves: their details wiped,
        out of every queue, a table they hold given up, off the ladders.
        Games they played stay in other players' history as "Deleted
        player", and nobody's points change. A player mid-game is skipped:
        report or cancel the game first. A list of what was removed - no
        personal details - is saved to --backup-dir first.
        """
        with app.app_context():
            players, unknown = [], []
            for name in usernames:
                player = _account_named(name)
                if player is None or player.is_deleted:
                    unknown.append(name)
                elif player.user_id not in {p.user_id for p in players}:
                    players.append(player)
            if unknown:
                raise click.ClickException(
                    "No such account (nothing was deleted): " + ", ".join(repr(n) for n in unknown)
                )

            summary = [_player_summary(player) for player in players]
            click.echo(
                f"Deleting {len(players)} account(s) on "
                f"{describe_database(app.config['SQLALCHEMY_DATABASE_URI'])}:"
            )
            for line in summary:
                click.echo(f"  #{line['user_id']} {line['username']}: {line['note']}")
            if not yes:
                click.confirm("Delete these accounts?", abort=True)

            os.makedirs(backup_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = os.path.join(backup_dir, f"deleted-players-{stamp}.json")
            with open(backup_path, "w") as f:
                json.dump({"deleted_at": stamp, "players": summary}, f, indent=2)
            click.echo(f"Saved the list to {backup_path}")

            for line in summary:
                outcome = remove_account(line["user_id"])
                if outcome == DELETE_RESULT_DELETED:
                    click.echo(f"  deleted {line['username']}")
                elif outcome == DELETE_RESULT_IN_GAME:
                    click.echo(f"  SKIPPED {line['username']}: in a game - report or cancel it first")
                else:
                    click.echo(f"  SKIPPED {line['username']}: already gone")

    @app.cli.command("set-admin")
    @click.argument("username")
    @click.option("--off", is_flag=True, help="Take the organiser's controls away instead.")
    def set_admin_command(username, off):
        """
        Give USERNAME (an exact username, or an email) the organiser's
        controls in the apps - taking any player out of a queue or off a
        table - or, with --off, take them away. The apps show the controls
        once they next load the profile; the server checks on every request.
        """
        with app.app_context():
            player = _account_named(username)
            if player is None or player.is_deleted:
                raise click.ClickException(f"There's no account called {username!r}.")
            player.is_admin = not off
            db.session.commit()
            click.echo(
                f"{player.username} {'is no longer' if off else 'is now'} an admin, on "
                f"{describe_database(app.config['SQLALCHEMY_DATABASE_URI'])}."
            )

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
            lost = game["loser_elo_change"]
            click.echo(
                f"Game #{match_id}, {game['league_name']}, {when}: {winner['username']} beat "
                f"{loser['username']} {score}, moving {change} points.\n"
                f"  {winner['username']}: {winner['elo']} points, {winner['wins']}-{winner['losses']}"
                f" -> {lowered_rating(winner['elo'], change)} points, "
                f"{max(0, winner['wins'] - 1)}-{winner['losses']}\n"
                f"  {loser['username']}: {loser['elo']} points, {loser['wins']}-{loser['losses']}"
                f" -> {loser['elo'] + lost} points, {loser['wins']}-{max(0, loser['losses'] - 1)}\n"
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


    @app.cli.command("add-games")
    @click.argument("league")
    @click.option(
        "--game",
        "games",
        nargs=3,
        multiple=True,
        required=True,
        metavar="WINNER LOSER SCORE",
        help='One game, winner first: --game Mel "Tom Holland" 11-1. '
        "Repeat it for each game, in the order they were played.",
    )
    @click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
    @click.option(
        "--backup-dir",
        default="backups",
        show_default=True,
        help="Where to save the players' numbers first.",
    )
    def add_games_command(league, games, yes, backup_dir):
        """
        Record finished LEAGUE games (a slug like ccny-ping-pong; "billiards"
        or "ping_pong" mean CCNY's) that never reached the app - played
        while the server was down, say. Each moves ratings exactly as if
        it had been reported at the time, against the ratings the game
        before it left, so give them in the order they were played.
        Nobody's place at the table changes. Players are named by exact
        username or email. Shows the games and asks first; if any game is
        wrong, nothing is saved. Take one back with void-game.
        """
        with app.app_context():
            league = _league_named(league)
            parsed, problems = [], []
            for number, (winner_name, loser_name, score) in enumerate(games, start=1):
                winner, loser = _account_named(winner_name), _account_named(loser_name)
                scores = _read_score(score)
                for name, player in ((winner_name, winner), (loser_name, loser)):
                    if player is None or player.is_deleted:
                        problems.append(f"game {number}: there's no account called {name!r}")
                if scores is None:
                    problems.append(f"game {number}: {score!r} isn't a score like 11-4")
                elif past_game_problem(league, *scores):
                    problems.append(f"game {number}: {past_game_problem(league, *scores)}")
                if winner is not None and winner is loser:
                    problems.append(f"game {number}: {winner_name!r} can't play themselves")
                parsed.append((winner, loser, scores))
            if problems:
                raise click.ClickException(
                    "Nothing was added:\n  " + "\n  ".join(problems)
                )

            click.echo(
                f"Adding {len(parsed)} {league.name} game(s), in this order, on "
                f"{describe_database(app.config['SQLALCHEMY_DATABASE_URI'])}:"
            )
            for number, (winner, loser, (won, lost)) in enumerate(parsed, start=1):
                click.echo(f"  {number}. {winner.username} beat {loser.username} {won}-{lost}")
            involved = {p.user_id: p for winner, loser, _ in parsed for p in (winner, loser)}
            click.echo(
                "Points now: "
                + ", ".join(f"{p.username} {p.standing(league)['elo']}" for p in involved.values())
            )
            if not yes:
                click.confirm("Add these games?", abort=True)

            os.makedirs(backup_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = os.path.join(backup_dir, f"added-games-{stamp}.json")
            with open(backup_path, "w") as f:
                json.dump(
                    {
                        "added_at": stamp,
                        "league": league.slug,
                        "games": [
                            {"winner": w.username, "loser": l.username, "score": list(s)}
                            for w, l, s in parsed
                        ],
                        "players_before": [
                            {"user_id": p.user_id, "username": p.username, **p.standing(league)}
                            for p in involved.values()
                        ],
                    },
                    f,
                    indent=2,
                )
            click.echo(f"Saved everyone's numbers from before to {backup_path}")

            try:
                results = add_past_games(
                    league, [(w.user_id, l.user_id, *s) for w, l, s in parsed]
                )
            except GameProblem as e:
                raise click.ClickException(f"Nothing was added: {e}")
            for result in results:
                won, lost = result["score"]
                click.echo(
                    f"  #{result['match_id']} {result['winner']} beat {result['loser']} "
                    f"{won}-{lost}: {result['winner']} +{result['elo_change']} -> "
                    f"{result['winner_elo']}, {result['loser']} -{result['loser_elo_change']} -> "
                    f"{result['loser_elo']}"
                )


def _read_score(text):
    """(winner's, loser's) from "11-4" (or 11:4, 11 - 4), or None."""
    parts = text.replace("–", "-").replace(":", "-").split("-")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return None


def error(message, status, **extra):
    """The one failure shape: {"message": ..., plus any data keys}."""
    return jsonify({"message": message, **extra}), status


def _league_named(ref):
    """The league a command names, or a ClickException listing them all."""
    league = League.of(ref)
    if league is None:
        slugs = ", ".join(db.session.scalars(db.select(League.slug).order_by(League.sort_order)))
        raise click.ClickException(f"There's no league {ref!r}. The leagues: {slugs}.")
    return league


def _account_named(name):
    """
    The account a command names: the exact username first - some
    usernames are email addresses, and someone else could have that as
    their email - then by email. None if there's no such account.
    """
    return db.session.scalars(
        db.select(Player).where(Player.username == name.strip())
    ).first() or find_player(name)


def _player_summary(player):
    """
    What delete-player shows, and keeps in its backup, about an account:
    who it was on the ladder, nothing personal (no names, email, password).
    """
    games = db.session.scalar(
        db.select(db.func.count())
        .select_from(Match)
        .where(
            Match.match_status == Match.STATUS_FINISHED,
            db.or_(Match.winner_id == player.user_id, Match.loser_id == player.user_id),
        )
    )
    at_table = db.session.scalars(
        db.select(Match).where(
            Match.match_status == Match.STATUS_ACTIVE,
            db.or_(Match.player_one_id == player.user_id, Match.player_two_id == player.user_id),
        )
    ).first()
    notes = [f"{games} game(s) played, kept as \"Deleted player\"" if games else "no games"]
    if at_table is not None:
        notes.append(
            "MID-GAME - will be skipped"
            if at_table.is_in_progress
            else f"holding table {at_table.table_id} - gives it up"
        )
    return {
        "user_id": player.user_id,
        "username": player.username,
        "country_flag": player.country_flag,
        "leagues": {
            league.slug: player.standing(league)
            for league in db.session.scalars(db.select(League).order_by(League.sort_order))
            if player.standing_in(league) is not None
        },
        "games": games,
        "note": "; ".join(notes),
    }


def signed_in(user):
    """
    The sign-in answer's data, shared by /login and a password reset:
    {access_token, user_id, username, email, is_admin}. is_admin only
    tells the apps to show the organiser's controls; the token carries
    nothing of it, and every admin request checks the database again.
    """
    return {
        "access_token": create_access_token(identity=str(user["user_id"])),
        "user_id": user["user_id"],
        "username": user["username"],
        "email": user.get("email"),
        "is_admin": bool(user.get("is_admin")),
    }


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
    The league a request is about: (League, None), (None, None) when it
    doesn't say, or (None, error_response).

    league_id names any league. league_type - "billiards" or "ping_pong",
    from apps before there were schools - means CCNY's league of that game;
    sent alongside league_id, it has to be that league's game.
    """
    league = None
    raw_id = source.get("league_id")
    if raw_id is not None and raw_id != "":
        try:
            league_id = read_whole_number(raw_id)
        except ValueError:
            return None, error("league_id must be a whole number.", 400)
        league = db.session.get(League, league_id)
        if league is None:
            return None, error(NO_SUCH_LEAGUE, 404)

    raw = source.get("league_type")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return league, None
    if not (isinstance(raw, str) and raw.strip().lower() in GAMES):
        return None, error(UNKNOWN_LEAGUE, 400)
    game = raw.strip().lower()
    if league is not None:
        if league.game != game:
            return None, error(f"{league.name} isn't a {game.replace('_', ' ')} league.", 400)
        return league, None
    league = League.of(game)
    if league is None:
        return None, error(NO_SUCH_LEAGUE, 404)
    return league, None


def read_table_and_league(source, must_exist=False):
    """
    Which league a request is about, and the table it names (if any):
    (table_id, league, None) or (None, None, error_response).

      - table_id given: that table, and its league. A league named as well
        (league_id or league_type) has to be the table's, so a ping pong
        request can't act on a pool table.
      - only a league: that league, and its first table in use (None if it
        has none).
      - neither: table 1 and its league, as before there were leagues.

    must_exist refuses a table with no Pool_Tables row.
    """
    league, bad = read_league(source)
    if bad:
        return None, None, bad

    if source.get("table_id") is None and league is not None:
        return default_table_for(league), league, None

    table_id, bad = read_table_id(source)
    if bad:
        return None, None, bad

    table = get_pool_table(table_id)
    if table is None and must_exist:
        return None, None, error("That table doesn't exist.", 404)

    table_league = league_for_table(table_id)
    if league is not None and table_league is not None and league.league_id != table_league.league_id:
        table_name = table.table_name if table is not None else f"Table {table_id}"
        return None, None, error(f"{table_name} is in {table_league.name}, not {league.name}.", 400)
    return table_id, table_league, None


def read_table_choice(source, table_id):
    """
    The table a player joining asked to wait for: table_id (already read
    by read_table_and_league), or None for whichever frees up first.

    An app from before tables could be chosen also sends a table_id - its
    league's first table, to say which league - along with league_type
    and never league_id. That isn't a choice, so it joins the line for any
    table, as it always meant to.
    """
    if source.get("table_id") is None:
        return None
    from_before = source.get("league_id") in (None, "") and source.get("league_type") not in (None, "")
    return None if from_before else table_id


def signed_in_user():
    """The signed-in player's user_id, or None - for routes anyone may call."""
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
    except Exception:
        return None
    return int(identity) if identity is not None else None


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


def refuse_unless_admin(user_id):
    """
    None if the signed-in player is an admin, otherwise the 403 to send.
    Read from the database every time: the apps hiding the buttons from
    everyone else is only a courtesy.
    """
    if is_admin(user_id):
        return None
    return error("Only the organiser can do that.", 403)


def read_target_player(source):
    """
    The player an admin request is about, from its user_id:
    (Player, None) or (None, error_response).
    """
    user_id, bad = read_player_id(source, "user_id")
    if bad:
        return None, bad
    if user_id is None:
        return None, error("Say which player: user_id is missing.", 400)
    player = db.session.get(Player, user_id)
    if player is None or player.is_deleted:
        return None, error("There's no such player.", 404)
    return player, None


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
    # 1. LEADERBOARD (Public) - a league's ladder.
    @app.route("/leaderboard", methods=["GET"])
    def get_leaderboard():
        league, bad = read_league(request.args)
        if bad:
            return bad
        return jsonify(top50_leaderboard(league or League.of(BILLIARDS)))

    # 1-. THE CHAMPIONS ACROSS EVERY SCHOOL (Public) - the top 3 in each
    # game this week, this month and of all time, in any league.
    @app.route("/leaderboard/global", methods=["GET"])
    def get_global_leaderboard():
        try:
            return jsonify(global_leaderboard())
        except Exception:
            log.exception("global leaderboard failed")
            return error("Couldn't load the champions just now.", 500)

    # 1a. PLAYERS OF THE DAY, WEEK AND MONTH (Public) - who gained the
    # most points in each, in the league's own calendar.
    @app.route("/top-players", methods=["GET"])
    def get_top_players():
        league, bad = read_league(request.args)
        if bad:
            return bad
        return jsonify(top_players(league or League.of(BILLIARDS)))

    # 1b. CCNY'S TWO LEAGUES AND THEIR FIRST TABLES (Public) - for apps
    # from before there were schools.
    @app.route("/leagues", methods=["GET"])
    def get_leagues():
        return jsonify({"leagues": list_leagues()})

    # 1c. EVERY LEAGUE (Public; says which ones the signed-in player can
    # play in) - each with its colours, its tables and read_only.
    @app.route("/leagues/directory", methods=["GET"])
    def get_league_directory():
        return jsonify({"leagues": league_directory(signed_in_user())})

    # 1d. ONE LEAGUE (Public, like 1c)
    @app.route("/leagues/<int:league_id>", methods=["GET"])
    def get_league(league_id):
        league = db.session.get(League, league_id)
        if league is None:
            return error(NO_SUCH_LEAGUE, 404)
        return jsonify({"league": league_summary(league, signed_in_user())})

    # 1e. EVERY TABLE IN A LEAGUE, AND WHO IS AT EACH (Public)
    @app.route("/leagues/<int:league_id>/tables", methods=["GET"])
    def get_league_tables(league_id):
        league = db.session.get(League, league_id)
        if league is None:
            return error(NO_SUCH_LEAGUE, 404)
        return jsonify({"league_id": league_id, "tables": league_tables(league)})

    # 1f. A LEAGUE'S QUEUE (Public) - one line for all its tables.
    @app.route("/leagues/<int:league_id>/queue", methods=["GET"])
    def get_league_queue(league_id):
        league = db.session.get(League, league_id)
        if league is None:
            return error(NO_SUCH_LEAGUE, 404)
        return jsonify(view_queue(league))

    # 1g. ENTER A LEAGUE'S PIN (Protected) - once, and it's remembered.
    @app.route("/league/unlock", methods=["POST"])
    @jwt_required()
    def unlock():
        user_id = int(get_jwt_identity())
        data = json_body()
        league, bad = read_league(data)
        if bad:
            return bad
        if league is None:
            return error("Say which league: league_id is missing.", 400)

        try:
            outcome, detail = unlock_league(user_id, league, data.get("pin"))
        except Exception:
            log.exception("unlock failed (user %s, league %s)", user_id, league.league_id)
            reset_session()
            return error("Couldn't check the PIN just now. Please try again.", 500)

        if outcome == UNLOCK_RESULT_BAD_FORMAT:
            return error("Enter the league's 4-digit PIN.", 400, field="pin")
        if outcome == UNLOCK_RESULT_NO_PIN:
            return error(
                f"{league.name} doesn't have a PIN yet - ask the organiser to set one.", 409
            )
        if outcome == UNLOCK_RESULT_TOO_MANY:
            minutes = max(1, -(-detail["retry_in"] // 60))
            return error(
                f"Too many wrong PINs. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
                429,
                field="pin",
                retry_in=detail["retry_in"],
            )
        if outcome not in (UNLOCK_RESULT_UNLOCKED, UNLOCK_RESULT_ALREADY):
            left = detail["tries_left"]
            # 403, never 401: to the apps a 401 means "your session ended".
            return error(
                "That PIN isn't right."
                + (f" {left} {'try' if left == 1 else 'tries'} left." if left else ""),
                403,
                field="pin",
                tries_left=left,
            )
        return jsonify(
            {
                "message": (
                    f"You're in - welcome to {league.name}!"
                    if outcome == UNLOCK_RESULT_UNLOCKED
                    else f"You're already in {league.name}."
                ),
                "status": outcome,
                "league": league_summary(league, user_id),
            }
        )

    # 2. A QUEUE, BY ONE OF ITS LEAGUE'S TABLES (Public) - for apps from
    # before leagues had a line of their own.
    @app.route("/queue/<int:table_id>", methods=["GET"])
    def get_queue(table_id):
        if get_pool_table(table_id) is None:
            return jsonify([])
        return jsonify(view_queue(league_for_table(table_id)))

    # 2b. WHO IS AT A TABLE (Public)
    @app.route("/table/<int:table_id>", methods=["GET"])
    def get_table(table_id):
        snapshot = table_snapshot(table_id)
        if snapshot is None:
            return error("That table doesn't exist.", 404)
        return jsonify({"table": snapshot})

    # 3. JOIN A LEAGUE'S QUEUE (Protected, and the league's PIN)
    @app.route("/queue/join", methods=["POST"])
    @jwt_required()
    def join_table_queue():
        user_id = int(get_jwt_identity())

        # league_id picks the league; a table_id picks its league (apps
        # from before send that, with league_type). Any of them together
        # have to agree. table_id is also the table to wait for, if the
        # player chose one; without one they wait for the first free table.
        data = json_body()
        table_id, league, bad = read_table_and_league(data, must_exist=True)
        if bad:
            return bad
        choice = read_table_choice(data, table_id)
        if not has_access(user_id, league):
            return error(NEEDS_PIN, 403, read_only=True, league_id=league.league_id)
        if default_table_for(league) is None:
            return error(f"{league.name} doesn't have a table yet.", 404)

        try:
            result = join_queue(user_id, league, choice)
        except Exception:
            log.exception("join_queue failed (user %s, league %s)", user_id, league.league_id)
            return error("Couldn't add you to the queue just now. Please try again.", 500)

        if result == JOIN_RESULT_ALREADY_PLAYING:
            return error("You're already playing or holding a table.", 409)
        if result == JOIN_RESULT_NO_SUCH_TABLE:
            return error(f"That table isn't in use in {league.name} any more.", 400, field="table_id")
        if result == JOIN_RESULT_CALLED_ELSEWHERE:
            status = get_queue_status(user_id, league) or {}
            called_to = table_names(league).get(status.get("table_id"), "a table")
            return error(
                f"It's your turn at {called_to} - say you're here, or leave the queue "
                "to wait for another table.",
                409,
            )

        if result == JOIN_RESULT_ALREADY_QUEUED:
            # Tapping Join again when it's your turn says you're here, as
            # "I'm here" does. It's the only way an app from before the
            # ready check has to say so: it shows a player whose turn has
            # come the Join button. Too late, and they join again at the
            # back of the line - which is what they asked for.
            try:
                if confirm_here(user_id, league) == CONFIRM_RESULT_TOO_LATE:
                    result = join_queue(user_id, league)
            except Exception:
                log.exception("confirming on a repeat join failed (user %s)", user_id)

        # Always attempt matchmaking, whether this call freshly joined or
        # found the player already waiting. That is what makes the queue
        # self-healing: anyone stuck behind a king from before the fix
        # gets matched simply by tapping Join again.
        try:
            match_started = attempt_matchmaking(league)
        except Exception:
            # The join itself worked. Matchmaking runs again on the next
            # status poll, so this heals itself; say so rather than alarm.
            log.exception("matchmaking after join failed (league %s)", league.league_id)
            match_started = False

        # Named only where there's a choice: a league with one table has one line.
        many = len(active_tables(league)) > 1
        waiting_for = table_names(league).get(choice) if choice and many else None
        if match_started:
            message = "Match found - get to the table!"
        elif result == JOIN_RESULT_SWITCHED:
            message = (
                f"You're waiting for {waiting_for} now - you kept your place."
                if waiting_for
                else "You're waiting for the first free table now - you kept your place."
            )
        elif result == JOIN_RESULT_ALREADY_QUEUED:
            message = "You're already in the queue, waiting for an opponent."
        elif waiting_for:
            message = f"Joined the line for {waiting_for}! Waiting for an opponent..."
        else:
            message = "Joined the queue! Waiting for an opponent..."

        return jsonify(
            {"message": message, "status": result, "match_started": match_started}
        )

    # 3a. "I'M HERE" - THE READY CHECK (Protected, and the league's PIN)
    # When a player's turn comes they have READY_CHECK_SECONDS to say
    # they're here, or they're taken out of the queue.
    @app.route("/queue/confirm", methods=["POST"])
    @jwt_required()
    def confirm_in_queue():
        user_id = int(get_jwt_identity())

        _table_id, league, bad = read_table_and_league(json_body())
        if bad:
            return bad
        if not has_access(user_id, league):
            return error(NEEDS_PIN, 403, read_only=True, league_id=league.league_id)

        try:
            outcome = confirm_here(user_id, league)
        except Exception:
            log.exception("confirm_here failed (user %s, league %s)", user_id, league.league_id)
            reset_session()
            return error("Couldn't confirm just now. Please try again.", 500)

        if outcome == CONFIRM_RESULT_NOT_YOUR_TURN:
            return error("It isn't your turn yet - we'll ask when it is.", 409)
        if outcome == CONFIRM_RESULT_TOO_LATE:
            # The minute was up, so they've been taken out of the queue;
            # the next in line is up instead.
            try:
                attempt_matchmaking(league)
            except Exception:
                log.exception("matchmaking after a late confirm failed (league %s)", league.league_id)
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
            match_started = attempt_matchmaking(league)
        except Exception:
            # Confirmed all the same; the next status poll starts the game.
            log.exception("matchmaking after a confirm failed (league %s)", league.league_id)
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

    # 3b. LEAVE A LEAGUE'S QUEUE (Protected - but never needs the PIN)
    @app.route("/queue/leave", methods=["POST"])
    @jwt_required()
    def leave_table_queue():
        user_id = int(get_jwt_identity())

        _table_id, league, bad = read_table_and_league(json_body())
        if bad:
            return bad

        status = get_queue_status(user_id, league)
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
            removed = leave_queue(user_id, league)
        except Exception:
            log.exception("leave_queue failed (user %s, league %s)", user_id, league.league_id)
            return error("Couldn't take you out of the queue just now. Please try again.", 500)

        if removed:
            # If it was their turn, the next in line is up now rather than
            # at the next status poll.
            if status["called"]:
                try:
                    attempt_matchmaking(league)
                except Exception:
                    log.exception("matchmaking after leaving failed (league %s)", league.league_id)
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

    # 3c2. VOTE THAT A KING ISN'T HERE (Protected) - or take the vote
    # back. Everyone waiting who could play at the table has to vote; then
    # the king has a minute to say they're here (logic/king_votes.py).
    @app.route("/table/vote", methods=["POST"])
    @jwt_required()
    def vote_on_king():
        user_id = int(get_jwt_identity())
        data = json_body()
        if data.get("table_id") is None:
            return error("Say which table: table_id is missing.", 400)
        table_id, bad = read_table_id(data)
        if bad:
            return bad
        if get_pool_table(table_id) is None:
            return error("That table doesn't exist.", 404)
        match_id, bad = read_match_id(data)
        if bad:
            return bad
        remove = data.get("remove", True)
        if not isinstance(remove, bool):
            return error("remove must be true or false.", 400)

        try:
            outcome, summary = cast_vote(user_id, table_id, match_id, remove)
        except Exception:
            log.exception("vote failed (user %s, table %s)", user_id, table_id)
            reset_session()
            return error("Couldn't count your vote just now. Please try again.", 500)

        table_name = get_pool_table(table_id).table_name
        if outcome == VOTE_RESULT_NO_KING:
            return error(f"Nobody is holding {table_name}.", 404)
        if outcome == VOTE_RESULT_GAME_CHANGED:
            return error(f"{table_name} has changed hands since - have another look.", 409)
        if outcome == VOTE_RESULT_YOU_ARE_KING:
            return error(
                "You can't vote yourself off - give up the table instead if you're going.", 409
            )
        if outcome == VOTE_RESULT_NOT_WAITING:
            return error(f"Only players waiting to play at {table_name} can vote.", 403)

        king = table_snapshot(table_id)["king"]
        name = king["username"] if king else "The king"
        if outcome == VOTE_RESULT_EVERYONE_VOTED:
            message = (
                f"Everyone waiting has voted. {name} has a minute to say they're here, "
                f"or they're taken off {table_name}."
            )
        elif outcome == VOTE_RESULT_ALREADY_VOTED:
            message = "You've already voted."
        elif outcome == VOTE_RESULT_WITHDRAWN:
            message = "You took your vote back."
        elif outcome == VOTE_RESULT_NOT_VOTED:
            message = "You hadn't voted."
        else:
            message = (
                f"Your vote is in: {summary['votes']} of {summary['needed']}. "
                "Everyone waiting has to vote."
                if summary
                else "Your vote is in."
            )
        return jsonify({"message": message, "status": outcome, "removal_vote": summary})

    # 3c3. THE KING SAYS THEY'RE HERE (Protected) - clears any vote that
    # they aren't.
    @app.route("/table/here", methods=["POST"])
    @jwt_required()
    def king_here():
        user_id = int(get_jwt_identity())
        try:
            outcome = king_is_here(user_id)
        except Exception:
            log.exception("king_is_here failed (user %s)", user_id)
            reset_session()
            return error("Couldn't tell them you're here just now. Please try again.", 500)
        if outcome == HERE_RESULT_NOT_KING:
            return error("You aren't holding a table.", 404)
        return jsonify({"message": "Got it - you're staying on the table.", "status": outcome})

    # 3d. THE ORGANISER: TAKE A PLAYER OUT OF A QUEUE (Protected, admins)
    # For a player who joined and walked off. Ignores the wait before
    # leaving, which is there to stop players dodging a game.
    @app.route("/admin/queue/remove", methods=["POST"])
    @jwt_required()
    def admin_remove_from_queue():
        admin_id = int(get_jwt_identity())
        refused = refuse_unless_admin(admin_id)
        if refused:
            return refused

        data = json_body()
        target, bad = read_target_player(data)
        if bad:
            return bad
        _table_id, league, bad = read_table_and_league(data)
        if bad:
            return bad

        try:
            outcome = remove_from_queue(target.user_id, league, by=admin_id)
        except Exception:
            log.exception("admin remove_from_queue failed (player %s)", target.user_id)
            reset_session()
            return error("Couldn't take them out of the queue just now. Please try again.", 500)

        if outcome == QUEUE_REMOVE_RESULT_NOT_QUEUED:
            return error(f"{target.username} isn't in this queue any more.", 404)
        return jsonify({"message": f"{target.username} is out of the queue.", "status": outcome})

    # 3e. THE ORGANISER: TAKE A PLAYER OFF A TABLE (Protected, admins)
    # For a king who left without giving the table up, or a game that
    # will never be reported. A game in progress is called off with
    # nothing recorded, and the other player keeps the table.
    @app.route("/admin/table/remove", methods=["POST"])
    @jwt_required()
    def admin_remove_from_table():
        admin_id = int(get_jwt_identity())
        refused = refuse_unless_admin(admin_id)
        if refused:
            return refused

        data = json_body()
        target, bad = read_target_player(data)
        if bad:
            return bad
        table_id, _league, bad = read_table_and_league(data)
        if bad:
            return bad
        match_id, bad = read_match_id(data)
        if bad:
            return bad

        try:
            outcome, other_id = remove_from_table(
                target.user_id, table_id, expected_match_id=match_id, by=admin_id
            )
        except Exception:
            log.exception("admin remove_from_table failed (player %s)", target.user_id)
            reset_session()
            return error("Couldn't take them off the table just now. Please try again.", 500)

        if outcome == TABLE_REMOVE_RESULT_NOT_AT_TABLE:
            return error(f"{target.username} isn't at this table any more.", 404)
        if outcome == TABLE_REMOVE_RESULT_GAME_CHANGED:
            return error(
                "Something changed at the table since you looked - check who's on and try again.",
                409,
            )
        if outcome == TABLE_REMOVE_RESULT_GAME_CALLED_OFF:
            other = db.session.get(Player, other_id)
            message = (
                f"{target.username} is off the table. Their game was called off with nothing "
                f"recorded, and {other.display_name if other else 'the other player'} keeps the table."
            )
        else:
            message = f"{target.username} is off the table. It goes to the next in the queue."
        return jsonify({"message": message, "status": outcome})

    # 3f. THE ORGANISER: A LEAGUE'S PIN (Protected, admins)
    # Everyone who entered the old PIN has to enter the new one.
    @app.route("/admin/leagues/<int:league_id>/pin", methods=["POST"])
    @jwt_required()
    def admin_set_league_pin(league_id):
        refused = refuse_unless_admin(int(get_jwt_identity()))
        if refused:
            return refused
        league = db.session.get(League, league_id)
        if league is None:
            return error(NO_SUCH_LEAGUE, 404)
        try:
            revoked = set_league_pin(league, json_body().get("pin"))
        except LeagueProblem as e:
            return error(str(e), 400, field="pin")
        return jsonify(
            {
                "message": (
                    f"{league.name}'s PIN is changed."
                    + (
                        f" {revoked} player{'s' if revoked != 1 else ''} will need to enter the new one."
                        if revoked
                        else ""
                    )
                ),
                "revoked": revoked,
                "league": league_summary(league, int(get_jwt_identity())),
            }
        )

    # 3g. THE ORGANISER: ADD A TABLE TO A LEAGUE (Protected, admins)
    @app.route("/admin/leagues/<int:league_id>/tables", methods=["POST"])
    @jwt_required()
    def admin_add_table(league_id):
        refused = refuse_unless_admin(int(get_jwt_identity()))
        if refused:
            return refused
        league = db.session.get(League, league_id)
        if league is None:
            return error(NO_SUCH_LEAGUE, 404)
        try:
            table = add_table(league, json_body().get("name"))
        except LeagueProblem as e:
            return error(str(e), 400, field="name")
        return (
            jsonify(
                {
                    "message": f"{table.table_name} is added to {league.name}.",
                    "table": table_snapshot(table.table_id),
                }
            ),
            201,
        )

    # 3h. THE ORGANISER: RENAME OR REMOVE A TABLE (Protected, admins)
    @app.route("/admin/tables/<int:table_id>", methods=["PATCH", "DELETE"])
    @jwt_required()
    def admin_change_table(table_id):
        refused = refuse_unless_admin(int(get_jwt_identity()))
        if refused:
            return refused

        if request.method == "PATCH":
            try:
                table = rename_table(table_id, json_body().get("name"))
            except LeagueProblem as e:
                return error(str(e), 400, field="name")
            if table is None:
                return error("That table doesn't exist.", 404)
            return jsonify(
                {"message": f"Renamed to {table.table_name}.", "table": table_snapshot(table_id)}
            )

        name = getattr(get_pool_table(table_id), "table_name", "That table")
        try:
            outcome, active = remove_table(table_id)
        except Exception:
            log.exception("remove_table failed (table %s)", table_id)
            reset_session()
            return error("Couldn't remove the table just now. Please try again.", 500)
        if outcome == REMOVE_TABLE_RESULT_NOT_FOUND:
            return error("That table doesn't exist.", 404)
        if outcome == REMOVE_TABLE_RESULT_BUSY:
            who = " and ".join(p.display_name for p in (active.player_one, active.player_two) if p)
            return error(
                f"{who} {'are' if active.player_two else 'is'} at {name} - take them off "
                "(or let them finish) first.",
                409,
            )
        return jsonify({"message": f"{name} is removed. Its games stay in the history."})

    # 4. LOGIN (Token Generator)
    # "username" may also be the account's email: anything with an @ is
    # looked up as one. email in the answer is null for an account made
    # before sign-up asked for one - the apps then ask for it.
    @app.route("/login", methods=["POST"])
    def login():
        data = json_body()
        username, password = data.get("username"), data.get("password")

        if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
            return error("Username and password required", 400)

        user = login_user(username, password)

        if user:
            return jsonify({"message": "Login successful", **signed_in(user)}), 200

        return error("Invalid credentials", 401)

    # 4b. FORGOT YOUR PASSWORD? (Public)
    # Step 1: a 6-digit code is emailed to the account with this email.
    # The answer is the same whether or not one exists, so the form can't
    # be used to find out who has an account.
    @app.route("/password/forgot", methods=["POST"])
    def forgot_password():
        if not mail_configured():
            return error(
                "Resetting a password by email isn't set up yet. Ask the league organiser "
                "to reset it for you.",
                503,
            )
        email = json_body().get("email")
        if clean_email(email)[1]:
            return error(clean_email(email)[1], 400, field="email")

        try:
            request_reset(email)
        except (MailNotConfigured, MailFailed):
            reset_session()
            return error("Couldn't send the email just now. Please try again in a minute.", 503)
        except Exception:
            log.exception("password reset request failed")
            reset_session()
            return error("Couldn't send a code just now. Please try again.", 500)

        return jsonify(
            {
                "message": (
                    "If that email belongs to an account, a code is on its way. "
                    f"It works for {CODE_LIFETIME_SECONDS // 60} minutes - check your spam "
                    "folder if it doesn't arrive."
                )
            }
        )

    # 4c. RESET THE PASSWORD WITH THE CODE (Public)
    # Step 2: the emailed code and a new password. Success signs the
    # player straight in, with the same answer as /login.
    @app.route("/password/reset", methods=["POST"])
    def reset_forgotten_password():
        data = json_body()
        email, code, password = data.get("email"), data.get("code"), data.get("password")
        if clean_email(email)[1]:
            return error(clean_email(email)[1], 400, field="email")
        problem = password_problem(password)
        if problem:
            return error(problem, 400, field="password")
        if not isinstance(code, (str, int)) or not str(code).strip():
            return error("Enter the code from the email.", 400, field="code")

        try:
            outcome, player = reset_password(email, str(code), password)
        except Exception:
            log.exception("password reset failed")
            reset_session()
            return error("Couldn't reset your password just now. Please try again.", 500)

        if outcome == RESET_DONE:
            return jsonify(
                {
                    "message": "Password changed - you're signed in.",
                    **signed_in(
                        {
                            "user_id": player.user_id,
                            "username": player.username,
                            "email": player.email,
                            "is_admin": bool(player.is_admin),
                        }
                    ),
                }
            )
        if outcome == RESET_WRONG_CODE:
            return error("That code isn't right. Check the email and try again.", 400, field="code")
        if outcome == RESET_EXPIRED:
            return error("That code has expired. Ask for a new one.", 400, field="code")
        if outcome == RESET_TOO_MANY_TRIES:
            return error("Too many wrong tries for that code. Ask for a new one.", 400, field="code")
        return error("There's no reset code for that email. Ask for one first.", 400, field="code")

    # 5. MATCH STATUS (Protected)
    @app.route("/match/status", methods=["GET"])
    @jwt_required()
    def get_match_status():
        user_id = int(get_jwt_identity())
        _table_id, league, bad = read_table_and_league(request.args)
        if bad:
            return bad

        try:
            # read_only: whether this player still needs the league's PIN to
            # play here - polled, so a changed PIN shows at once.
            return jsonify(
                {**get_player_status(user_id, league), "read_only": not has_access(user_id, league)}
            )
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

        # The league the player thinks this game is in: league_id, or
        # league_type (its game) from apps before schools. Optional; the
        # game's real league is what decides the rules either way.
        league_type = data.get("league_type")
        if league_type is not None and not (
            isinstance(league_type, str) and league_type.strip().lower() in GAMES
        ):
            return error(UNKNOWN_LEAGUE, 400)
        league_type = league_type.strip().lower() if league_type else None
        league_id = None
        if data.get("league_id") is not None:
            try:
                league_id = read_whole_number(data.get("league_id"))
            except ValueError:
                return error("league_id must be a whole number.", 400)

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
                user_id, my_score, opp_score, expected_match_id, league_type, league_id
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
            return error(
                f"That game is in {details['league_name']}, so it wasn't recorded here.",
                409,
                league_type=details["league_type"],
                league_id=details["league_id"],
            )
        if outcome == REPORT_RESULT_NO_ACCESS:
            return error(
                f"{details['league_name']}'s PIN has changed - enter the new one, then report the score.",
                403,
                read_only=True,
                league_id=details["league_id"],
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

        league = league or League.of(BILLIARDS)
        return jsonify(
            {
                "league_type": league.game,
                "league_id": league.league_id,
                "matches": league_history(league, table_id, limit),
            }
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

        league = league or League.of(BILLIARDS)
        body = {
            "user_id": user_id,
            "league_type": league.game,
            "league_id": league.league_id,
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

    # 6c2b. A PLAYER'S BADGES IN ONE LEAGUE, EARNED OR NOT (Public)
    @app.route("/players/<int:user_id>/badges", methods=["GET"])
    def get_player_badges(user_id):
        league, bad = read_league(request.args)
        if bad:
            return bad
        badges = player_badges(user_id, league or League.of(BILLIARDS))
        if badges is None:
            if db.session.get(Player, user_id) is not None:
                return error("This player has deleted their account.", 404)
            return error("That player doesn't exist.", 404)
        return jsonify(badges)

    # 6c2c. CHOOSE THE BADGE A LEAGUE SHOWS BY YOUR NAME (Protected)
    # {"league_id": ... (or "league_type"), "key": "<badge>" or null for automatic}
    @app.route("/me/featured-badge", methods=["POST"])
    @jwt_required()
    def choose_featured_badge():
        user_id = int(get_jwt_identity())
        data = json_body()
        league, bad = read_league(data)
        if bad:
            return bad
        key = data.get("key")
        if key is not None and not isinstance(key, str):
            return error("key must be a badge, or null to pick automatically.", 400)

        problem = set_featured_badge(user_id, league or League.of(BILLIARDS), key)
        if problem:
            return error(problem, 400)
        return jsonify({"message": "Badge updated.", "featured": key})

    # 6c2d. BADGES EARNED BUT NOT YET ANNOUNCED, IN ANY LEAGUE (Protected)
    @app.route("/me/badges/new", methods=["GET"])
    @jwt_required()
    def get_new_badges():
        return jsonify({"badges": new_badges(int(get_jwt_identity()))})

    @app.route("/me/badges/seen", methods=["POST"])
    @jwt_required()
    def badges_seen():
        ids = json_body().get("ids")
        if not isinstance(ids, list):
            return error("ids must be a list of badge ids.", 400)
        return jsonify({"marked": mark_badges_seen(int(get_jwt_identity()), ids)})

    # 6c3. A PLAYER'S RECORD AGAINST EVERYONE THEY'VE PLAYED (Public)
    @app.route("/players/<int:user_id>/opponents", methods=["GET"])
    def get_player_opponents(user_id):
        league, bad = read_league(request.args)
        if bad:
            return bad
        if db.session.get(Player, user_id) is None:
            return error("That player doesn't exist.", 404)

        league = league or League.of(BILLIARDS)
        return jsonify(
            {
                "user_id": user_id,
                "league_type": league.game,
                "league_id": league.league_id,
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

    # 6e1. ADD OR CHANGE YOUR EMAIL (Protected)
    # Body {email, password?}. Adding a first email needs no password;
    # changing one does - see logic/profile.set_email. A wrong password is
    # 403 with field "password" (never 401: that would sign the player out).
    @app.route("/profile/email", methods=["POST"])
    @jwt_required()
    def set_my_email():
        user_id = int(get_jwt_identity())
        data = json_body()
        try:
            problem, profile = set_email(user_id, data.get("email"), data.get("password"))
        except Exception:
            log.exception("setting an email failed (user %s)", user_id)
            reset_session()
            return error("Couldn't save your email just now. Please try again.", 500)

        if problem:
            return error(problem["message"], problem.get("status", 400), field=problem["field"])
        if profile is None:
            return error(ACCOUNT_GONE, 404)
        return jsonify({"message": "Email saved.", "profile": profile})

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
    # An email is required: one account per email is what stops a player
    # who forgot their password making a second account. A refusal names
    # its field, so the form can show it there.
    @app.route("/register", methods=["POST"])
    def register():
        data = json_body()

        if not all(
            key in data for key in ["username", "first_name", "last_name", "password"]
        ):
            return error("All fields are required", 400)
        if "email" not in data:
            # What an app from before emails were asked for sends.
            return error(
                "Signing up needs an email address now. If you don't see an email box, "
                "update the app.",
                400,
                field="email",
            )

        success, message, field = register_user(
            data["username"], data["first_name"], data["last_name"], data["password"], data["email"]
        )

        if success:
            return jsonify({"message": message}), 201
        return error(message, 400, **({"field": field} if field else {}))

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

            if attempt_matchmaking(league_for_table(table_id)):
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
