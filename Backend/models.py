"""
SQLAlchemy models for the Billiards League.

Two rules shaped this file:

1. **The JSON the frontend sees must not change.** Every model carries
   serializer methods producing exactly the shape the React app already
   parses. Serialization lives here, in one place, so a column change
   can't silently reshape an API response.

2. **Each column means one thing.** The original code overloaded
   `winner_id`/`loser_id` to mean "seat one/seat two" while a game was in
   progress and "the result" once it finished. That ambiguity caused two
   separate bugs. The seats now live in the `king_id` / `challenger_id`
   columns the database already had, and `winner_id` / `loser_id` only
   ever hold a result. Old rows are converted by `ensure_schema()` in
   database.py on startup - nobody has to run SQL by hand.

3. **The models describe the database that exists.** Every column below
   is a real column in `ranked_billards`. `check_schema()` compares the
   two on startup, so a model that drifts from the database is reported
   in plain words instead of surfacing as a SQL error in someone's face.

Written in the classic `db.Column` style rather than SQLAlchemy 2.0's
`Mapped[]` annotations: it is compatible across more Flask-SQLAlchemy
versions, which matters because this code could not be executed in the
environment it was written in.
"""
from flask import has_request_context, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy.orm import synonym

db = SQLAlchemy()


def public_url(link):
    """
    A picture link any client can load.

    An uploaded picture is stored as a path on this API
    ("/players/7/picture?v=..."). The web app and the phones live on other
    hosts, where a bare path would point at the wrong server, so a path is
    made absolute against the address the request came in on - which is
    the address that client already reaches this API by. Outside a
    request (scripts, some tests) it stays a path. Anything else - a
    web link, or None - is returned unchanged.
    """
    if link and link.startswith("/") and has_request_context():
        return request.host_url.rstrip("/") + link
    return link

# Where every new player's rating starts. Matches the database's own
# column default and the Ranks table, whose lowest tier begins at 0.
STARTING_ELO = 0
# No rating goes below this. A loss that would take a player under it
# stops at it; the winner still gains the full amount.
ELO_FLOOR = 0

# The two leagues. Each is the value of Pool_Tables.league_type and of the
# `league_type` the API accepts. A table belongs to exactly one league, and
# a match belongs to the league of the table it was played on - so
# matchmaking, which only ever deals in tables, needs no league logic.
BILLIARDS = "billiards"
PING_PONG = "ping_pong"
LEAGUE_TYPES = (BILLIARDS, PING_PONG)
LEAGUE_NAMES = {BILLIARDS: "Billiards League", PING_PONG: "Ping Pong League"}


class Player(db.Model):
    """A registered player. Maps to the existing `Players` table."""

    __tablename__ = "Players"

    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    # Where a password reset code goes, stored lowercased. One account per
    # email (the unique index below), which is what stops someone who
    # forgot their password making a second account instead of resetting.
    # NULL only for accounts made before sign-up asked for one; the apps
    # ask those players to add it.
    email = db.Column(db.String(254), nullable=True)

    # bcrypt hash, not a plain password. Stored as String because that is
    # what the column already is; auth.py handles MySQL handing this back
    # as either str or bytes.
    password_hash = db.Column(db.String(255), nullable=False)

    # --- Billiards standing ---
    # These columns predate the ping pong league, so their names don't say
    # "billiards". billiards_elo / billiards_rank_id are the same columns
    # under the league's name - aliases, not copies. A second pair of
    # columns holding the same rating would be two homes for one fact,
    # which is how this project's worst bugs started.
    elo_rating = db.Column(
        db.Integer, nullable=False, default=STARTING_ELO, server_default=str(STARTING_ELO)
    )
    total_wins = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    total_losses = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    rank_id = db.Column(db.Integer, db.ForeignKey("Ranks.rank_id"), nullable=True)
    rank = db.relationship(
        "Rank", back_populates="players", foreign_keys=[rank_id], lazy="joined"
    )

    billiards_elo = synonym("elo_rating")
    billiards_rank_id = synonym("rank_id")

    # --- Ping pong standing ---
    ping_pong_elo = db.Column(
        db.Integer, nullable=False, default=STARTING_ELO, server_default=str(STARTING_ELO)
    )
    ping_pong_wins = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    ping_pong_losses = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    ping_pong_rank_id = db.Column(db.Integer, db.ForeignKey("Ranks.rank_id"), nullable=True)
    # Loaded on first use rather than joined. Matchmaking reads players
    # under SELECT ... FOR UPDATE, and every joined table there is another
    # set of locked rows. There are only a handful of Ranks, so after the
    # first lookup these come from the session without a query.
    ping_pong_rank = db.relationship("Rank", foreign_keys=[ping_pong_rank_id])

    # --- Profile ---
    # ISO 3166-1 alpha-2 code ("US"), not the emoji itself: a code can be
    # checked against a list, and the flag is drawn from it by the client.
    country_flag = db.Column(db.String(2), nullable=True)
    # Either an http(s) link the player gave, or - for a picture they
    # uploaded - the path it's served from on this API, which carries the
    # picture's version so a new one isn't hidden behind a cached old one.
    # One column for both, so a player has exactly one picture. Read it
    # through picture_url, never directly, when sending it to a client.
    profile_picture = db.Column(db.String(512), nullable=True)

    # When the player deleted their account, or None. The row stays, with
    # every personal detail wiped (see logic/account.py): the games they
    # played are other people's history too, and show them as
    # DELETED_NAME. A deleted player can't sign in, their old login tokens
    # stop working, and they're left off the ladder.
    deleted_at = db.Column(db.DateTime, nullable=True)
    DELETED_NAME = "Deleted player"

    # The organiser: may take any player out of a queue or off a table
    # (logic/admin.py). Granted only from the command line (`flask --app
    # app set-admin`), never by an endpoint, and read from here on every
    # admin request - never from the client or the login token.
    is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    # The badge each league's ladder shows next to this player, by
    # achievement key (see logic/achievements.py). NULL means "my best one,
    # picked automatically".
    billiards_featured_badge = db.Column(db.String(40), nullable=True)
    ping_pong_featured_badge = db.Column(db.String(40), nullable=True)
    FEATURED_BADGE_FIELDS = {
        BILLIARDS: "billiards_featured_badge",
        PING_PONG: "ping_pong_featured_badge",
    }

    __table_args__ = (db.Index("uq_players_email", "email", unique=True),)

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    @property
    def display_name(self):
        """The name other people see: DELETED_NAME once the account is gone."""
        return self.DELETED_NAME if self.is_deleted else self.username

    @property
    def picture_url(self):
        """The player's picture as a link a client can load, or None."""
        return public_url(self.profile_picture)

    # Where each league keeps its numbers, so code that works for either
    # league reads one table instead of branching everywhere.
    LEAGUE_FIELDS = {
        BILLIARDS: {
            "elo": "elo_rating",
            "rank_id": "rank_id",
            "rank": "rank",
            "wins": "total_wins",
            "losses": "total_losses",
        },
        PING_PONG: {
            "elo": "ping_pong_elo",
            "rank_id": "ping_pong_rank_id",
            "rank": "ping_pong_rank",
            "wins": "ping_pong_wins",
            "losses": "ping_pong_losses",
        },
    }

    def standing(self, league=BILLIARDS):
        """This player's numbers in one league."""
        fields = self.LEAGUE_FIELDS[league]
        rank = getattr(self, fields["rank"])
        return {
            "elo": getattr(self, fields["elo"]),
            "rank_name": rank.rank_name if rank else "Unranked",
            "wins": getattr(self, fields["wins"]) or 0,
            "losses": getattr(self, fields["losses"]) or 0,
        }

    def to_leaderboard_dict(self, league=BILLIARDS):
        """
        One row of /leaderboard, the same shape for either league. user_id,
        flag and picture let the ladder draw each player and open their
        profile.

        "Unranked" mirrors the LEFT JOIN in the old SQL: a player whose
        rank hasn't been calculated yet still has to appear on the ladder.
        """
        standing = self.standing(league)
        return {
            "user_id": self.user_id,
            "username": self.username,
            "country_flag": self.country_flag,
            "profile_picture": self.picture_url,
            "elo_rating": standing["elo"],
            "total_wins": standing["wins"],
            "total_losses": standing["losses"],
            "rank_name": standing["rank_name"],
        }

    def to_card(self, league=BILLIARDS):
        """
        A player as other people see them: enough to draw their avatar and
        flag, plus the rank and rating the hover card shows for `league`.
        """
        return {
            "user_id": self.user_id,
            "username": self.display_name,
            "country_flag": self.country_flag,
            "profile_picture": self.picture_url,
            "league_type": league,
            **self.standing(league),
        }

    def to_public_profile_dict(self):
        """
        A player's profile as anyone may see it: both leagues' standings,
        but not their real name - that stays between them and the league.
        """
        return {
            "user_id": self.user_id,
            "username": self.display_name,
            "country_flag": self.country_flag,
            "profile_picture": self.picture_url,
            "leagues": {league: self.standing(league) for league in LEAGUE_TYPES},
        }

    @property
    def has_uploaded_picture(self):
        """The picture is a photo they uploaded, served by this API - not a link."""
        return bool(self.profile_picture) and self.profile_picture.startswith("/")

    def to_profile_dict(self):
        """
        The signed-in player's own profile, with both leagues.
        picture_uploaded says the picture is a photo they uploaded rather
        than a link, so the form doesn't offer the photo's address back to
        them as a link to edit. is_admin tells the apps to show the
        organiser's controls - which the server checks again regardless.
        """
        return {
            **self.to_public_profile_dict(),
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "picture_uploaded": self.has_uploaded_picture,
            "is_admin": bool(self.is_admin),
        }

    def __repr__(self):
        return f"<Player {self.username} ({self.elo_rating})>"


class Rank(db.Model):
    """An ELO tier. Maps to the existing `Ranks` table. Both leagues share it."""

    __tablename__ = "Ranks"

    rank_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    rank_name = db.Column(db.String(50), nullable=False)
    min_elo = db.Column(db.Integer, nullable=False)

    players = db.relationship("Player", back_populates="rank", foreign_keys="Player.rank_id")

    @classmethod
    def for_elo(cls, elo):
        """
        The highest rank a given ELO qualifies for, or None.
        Replaces the correlated subquery in update_player_rank.
        """
        return db.session.scalars(
            db.select(cls).where(cls.min_elo <= elo).order_by(cls.min_elo.desc()).limit(1)
        ).first()

    def __repr__(self):
        return f"<Rank {self.rank_name} (>= {self.min_elo})>"


class PoolTable(db.Model):
    """
    A physical table in the venue. Maps to the existing `Pool_Tables`.

    `current_king_id`, `current_streak` and `table_record_streak` are a
    denormalized cache of facts that `Matches` already holds. They are
    written in exactly one place - `record_match.refresh_table_state()` -
    and never read to decide anything. Matchmaking always derives the
    king from `Matches`.

    That restraint is deliberate: the original stuck-queue bug was caused
    by two copies of one rule drifting apart. A second, writable home for
    "who holds the table" is the same trap, so these columns are treated
    as a display cache and nothing more.
    """

    # Exact case matters: MySQL on Linux treats table names as
    # case-sensitive, so "pool_tables" would only work on a Mac.
    __tablename__ = "Pool_Tables"

    table_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Indexed in the database, which implies a Leagues table. No
    # ForeignKey is declared because there's no Leagues model here, and
    # pointing an FK at a missing model breaks SQLAlchemy at startup.
    # Mapping it as a plain column keeps the data readable and writable.
    league_id = db.Column(db.Integer, nullable=True)

    table_name = db.Column(db.String(50), nullable=False)
    current_king_id = db.Column(db.Integer, db.ForeignKey("Players.user_id"), nullable=True)

    # Purpose unknown from the schema alone; mapped so it round-trips
    # untouched rather than being dropped.
    match_code = db.Column(db.Integer, nullable=True)

    current_streak = db.Column(db.Integer, nullable=True, default=0, server_default="0")
    table_record_streak = db.Column(db.Integer, nullable=True, default=0, server_default="0")

    # Which league plays here: BILLIARDS or PING_PONG. Deliberately not the
    # league_id above - that points at the Leagues table, which holds
    # groups of players rather than sports. Every table that existed before
    # ping pong is a pool table, which is what the default says.
    league_type = db.Column(
        db.String(20), nullable=False, default=BILLIARDS, server_default=BILLIARDS
    )

    current_king = db.relationship("Player", foreign_keys=[current_king_id], lazy="joined")

    def to_dict(self):
        return {
            "table_id": self.table_id,
            "table_name": self.table_name,
            "league_type": self.league_type,
            "current_king": self.current_king.username if self.current_king else None,
            "current_streak": self.current_streak or 0,
            "table_record_streak": self.table_record_streak or 0,
        }

    def __repr__(self):
        return f"<PoolTable {self.table_id} {self.table_name!r}>"


class QueueEntry(db.Model):
    """
    One player waiting for one table. Maps to the existing `Queue` table.

    Named QueueEntry rather than Queue because `Queue` collides with
    Python's stdlib queue.Queue. `__tablename__` still points at the real
    table, so the database is unaffected.
    """

    __tablename__ = "Queue"

    queue_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("Players.user_id"), nullable=False)
    table_id = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    queue_position = db.Column(db.Integer, nullable=False)

    # Powers the leave-queue timer. server_default matters: inserts don't
    # set this column, so MySQL fills it in with its own clock.
    joined_at = db.Column(
        db.DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # The ready check (see manage_queue.attempt_matchmaking). called_at is
    # when this player's turn came - NULL while they're only waiting in
    # line. confirmed_at is when they last showed they were here, by
    # tapping "I'm here" or by joining recently enough that nobody needs
    # to ask; with called_at set, it means they're ready to play.
    called_at = db.Column(db.DateTime, nullable=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    player = db.relationship("Player", lazy="joined")

    # Declared as indexes (not a table constraint) so ensure_schema() can
    # add any that are missing to an existing database. The unique one is
    # what stops a double-tapped Join from queueing someone twice.
    __table_args__ = (
        db.Index("uq_queue_user_table", "user_id", "table_id", unique=True),
        db.Index("idx_queue_table", "table_id", "queue_position"),
    )

    @property
    def is_called(self):
        """This player's turn has come: they're up to play next."""
        return self.called_at is not None

    @property
    def is_confirmed(self):
        """Their turn has come and they've said they're here."""
        return self.called_at is not None and self.confirmed_at is not None

    def to_dict(self, place=None):
        """
        One line of /queue/<table_id>. `place` is the player's actual place
        in line; queue_position on its own is only a sort key and drifts
        upwards over an evening. called / confirmed let everyone watching
        see whose turn it is and whether they've said they're here.
        """
        return {
            "queue_position": place if place is not None else self.queue_position,
            "user_id": self.user_id,
            "username": self.player.username,
            "called": self.is_called,
            "confirmed": self.is_confirmed,
        }

    def __repr__(self):
        return f"<QueueEntry user={self.user_id} table={self.table_id} pos={self.queue_position}>"


class Match(db.Model):
    """
    A game at a table. Maps to the existing `Matches` table.

    Each column means exactly one thing, at every stage. The Python
    attribute names are the ones the code has always used; the database
    column each one lives in is in brackets.

      player_one_id   [king_id] Whoever took the table first - either the
                      first player pulled off the queue, or the previous
                      winner staying on as king.
      player_two_id   [challenger_id] The challenger. NULL means nobody
                      has arrived yet: a king holding the table.
      winner_id       NULL while the game is unresolved. Set exactly once,
      loser_id        when the result is reported.
      player_one_balls / player_two_balls
                      [king_balls / challenger_balls] The reported score.
      match_status    'Active' or 'Finished'. (The column also allows
                      'Upcoming', which nothing uses.)
      cancel_requested_by
                      While a game is on: the player who has asked to
                      call it off, waiting for the other to agree. NULL
                      when nobody has. See logic/cancel_match.py.

    Compare with the old design, where winner_id meant "seat one" during
    a match and "the winner" afterwards. Reading a row used to require
    knowing which stage it was in; now it doesn't.
    """

    __tablename__ = "Matches"

    STATUS_ACTIVE = "Active"
    STATUS_FINISHED = "Finished"

    match_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    table_id = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    # Nullable in the database, and left nullable here so the legacy rows
    # ensure_schema() converts can exist. The code always sets it.
    player_one_id = db.Column(
        "king_id", db.Integer, db.ForeignKey("Players.user_id"), nullable=True
    )
    player_two_id = db.Column(
        "challenger_id", db.Integer, db.ForeignKey("Players.user_id"), nullable=True
    )
    winner_id = db.Column(db.Integer, db.ForeignKey("Players.user_id"), nullable=True)
    loser_id = db.Column(db.Integer, db.ForeignKey("Players.user_id"), nullable=True)

    player_one_balls = db.Column("king_balls", db.Integer, nullable=True)
    player_two_balls = db.Column("challenger_balls", db.Integer, nullable=True)

    match_status = db.Column(
        db.String(20), nullable=False, default=STATUS_ACTIVE, server_default=STATUS_ACTIVE
    )
    elo_change = db.Column(db.Integer, nullable=True)
    # What the loser actually lost: elo_change, unless that would have taken
    # them below ELO_FLOOR, where they stopped. NULL for games recorded
    # before the floor, which all lost exactly elo_change.
    loser_elo_change = db.Column(db.Integer, nullable=True)
    # Both players' ratings in this game's league just before it, written by
    # apply_result. Achievements read them: a season reset wipes ratings but
    # keeps games, so "rated 100+ above you" can't be worked out later from
    # ratings as they are now. NULL for games recorded before these existed.
    winner_elo_before = db.Column(db.Integer, nullable=True)
    loser_elo_before = db.Column(db.Integer, nullable=True)
    played_at = db.Column(db.DateTime, nullable=True, server_default=func.current_timestamp())
    # A plain number, not a foreign key: it is only ever one of the two
    # seats above, and it only means anything while the game is on.
    cancel_requested_by = db.Column(db.Integer, nullable=True)

    # Four foreign keys point at Players, so each relationship has to say
    # which one it follows.
    player_one = db.relationship("Player", foreign_keys=[player_one_id], lazy="joined")
    player_two = db.relationship("Player", foreign_keys=[player_two_id], lazy="joined")
    winner = db.relationship("Player", foreign_keys=[winner_id], lazy="joined")
    # Not joined: the loser always sat in one of the seats above, so it is
    # already in the session and loading it costs no query.
    loser = db.relationship("Player", foreign_keys=[loser_id])

    __table_args__ = (
        db.Index("idx_matches_table_status", "table_id", "match_status"),
    )

    # --- State questions, asked in one place ---

    @property
    def is_active(self):
        return self.match_status == self.STATUS_ACTIVE

    @property
    def is_awaiting_challenger(self):
        """A king holding the table with nobody to play yet."""
        return self.is_active and self.player_two_id is None

    @property
    def is_in_progress(self):
        """Two players, mid-game."""
        return self.is_active and self.player_two_id is not None

    def involves(self, user_id):
        return user_id in (self.player_one_id, self.player_two_id)

    def opponent_of(self, user_id):
        """
        The other player, or None if the challenger seat is still empty.

        /match/record relies on the None case to refuse a score report
        when there is nobody to have played against.
        """
        if self.player_two_id is None:
            return None
        return self.player_two_id if self.player_one_id == user_id else self.player_one_id

    def balls_for(self, user_id):
        """The balls this player was reported to have sunk, or None."""
        if user_id == self.player_one_id:
            return self.player_one_balls
        if user_id == self.player_two_id:
            return self.player_two_balls
        return None

    def loser_id_for(self, winner_id):
        """Given who won, who lost. None if the match had no challenger."""
        if self.player_two_id is None:
            return None
        return self.player_two_id if winner_id == self.player_one_id else self.player_one_id

    # --- Serialization: the exact /match/status payloads ---
    # league_type is the league of this match's table. The frontend sends it
    # back when reporting the score, so a ping pong game is never scored
    # with billiards rules because the screen happened to be on billiards.

    def to_playing_dict(self, user_id, league=BILLIARDS):
        """
        The 'playing' response. cancel_requested_by says who, if anyone,
        has asked to call the game off: "you", "opponent" or None.
        """
        opponent = self.player_two if self.player_one_id == user_id else self.player_one
        if self.cancel_requested_by is None:
            cancel_requested_by = None
        else:
            cancel_requested_by = "you" if self.cancel_requested_by == user_id else "opponent"
        return {
            "status": "playing",
            "opponent": opponent.username if opponent else None,
            "opponent_id": self.opponent_of(user_id),
            "match_id": self.match_id,
            "table_id": self.table_id,
            "league_type": league,
            "cancel_requested_by": cancel_requested_by,
        }

    def to_waiting_dict(self, league=BILLIARDS):
        """The 'waiting_for_challenger' response."""
        return {
            "status": "waiting_for_challenger",
            "match_id": self.match_id,
            "table_id": self.table_id,
            "league_type": league,
        }

    @property
    def loser_points_lost(self):
        """What the loser lost - less than elo_change if they hit the floor."""
        return self.elo_change if self.loser_elo_change is None else self.loser_elo_change

    def to_history_dict(self, league, seconds_ago=None, viewer_id=None):
        """
        One finished game for the history feeds.

        seconds_ago is worked out by the database (see match_history.py),
        for the same reason the queue timer is: a timestamp written by
        MySQL's clock and read against Python's is off by the difference
        in their timezones. viewer_id adds "result" from that player's side.
        """
        entry = {
            "match_id": self.match_id,
            "table_id": self.table_id,
            "league_type": league,
            "winner": self.winner.to_card(league) if self.winner else None,
            "loser": self.loser.to_card(league) if self.loser else None,
            # None for games recorded before scores were stored.
            "winner_score": self.balls_for(self.winner_id),
            "loser_score": self.balls_for(self.loser_id),
            "elo_change": self.elo_change,
            "loser_elo_change": self.loser_points_lost,
            "seconds_ago": seconds_ago,
        }
        if viewer_id is not None:
            entry["result"] = "won" if viewer_id == self.winner_id else "lost"
        return entry

    def __repr__(self):
        return (
            f"<Match {self.match_id} table={self.table_id} status={self.match_status} "
            f"p1={self.player_one_id} p2={self.player_two_id} winner={self.winner_id}>"
        )


class PlayerAchievement(db.Model):
    """
    One achievement one player has earned in one league. Only earned
    achievements get a row; what each one *is* - name, tier, rule - lives
    in logic/achievements.py, keyed by achievement_key, so renaming a badge
    needs no migration. Each league's badges are earned separately.
    """

    __tablename__ = "Player_Achievements"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("Players.user_id"), nullable=False)
    league_type = db.Column(db.String(20), nullable=False)
    achievement_key = db.Column(db.String(40), nullable=False)
    # When it was earned: when the game that earned it finished, or when
    # it was noticed for the few that no single game earns.
    earned_at = db.Column(db.DateTime, nullable=False, server_default=func.current_timestamp())
    # The game that earned it, if one did. Not a foreign key: a game can be
    # voided, and the badge outlives it.
    match_id = db.Column(db.Integer, nullable=True)
    # False until the player's screen has announced it.
    seen = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    __table_args__ = (
        # Each achievement is earned once per league, however many results
        # are recorded at the same instant.
        db.Index("uq_achievement", "user_id", "league_type", "achievement_key", unique=True),
    )

    def __repr__(self):
        return f"<PlayerAchievement user={self.user_id} {self.league_type}:{self.achievement_key}>"


class PlayerPicture(db.Model):
    """
    A profile picture a player uploaded, as the server re-encoded it: a
    small square JPEG (see logic/pictures.py). At most one per player.

    Kept in the database rather than on disk because the host's disk is
    wiped on every deploy. Player.profile_picture holds the path it is
    served from; this row holds the picture itself.
    """

    __tablename__ = "Player_Pictures"

    user_id = db.Column(db.Integer, db.ForeignKey("Players.user_id"), primary_key=True)
    # MEDIUMBLOB on MySQL: a plain BLOB stops at 64 KB, which a detailed
    # photo can pass even at this size.
    image = db.Column(db.LargeBinary().with_variant(MEDIUMBLOB(), "mysql"), nullable=False)
    # A hash of the image, which goes in the picture's link: a new picture
    # gets a new link, so nobody keeps seeing a cached old one.
    digest = db.Column(db.String(64), nullable=False)

    def __repr__(self):
        return f"<PlayerPicture user={self.user_id} {len(self.image or b'')} bytes>"



class PasswordReset(db.Model):
    """
    A code emailed to a player who forgot their password - at most one per
    player; asking again replaces it. See logic/password_reset.py.

    The code itself isn't stored, only a hash of it, so even someone
    reading the database can't use one. sent_at is written by the
    database's clock, and the code's age is measured by it too (as the
    queue timer is).
    """

    __tablename__ = "Password_Resets"

    user_id = db.Column(db.Integer, db.ForeignKey("Players.user_id"), primary_key=True)
    code_hash = db.Column(db.String(64), nullable=False)
    sent_at = db.Column(db.DateTime, nullable=False, server_default=func.current_timestamp())
    # Wrong guesses so far; enough of them and the code stops working.
    attempts = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    def __repr__(self):
        return f"<PasswordReset user={self.user_id} attempts={self.attempts}>"
