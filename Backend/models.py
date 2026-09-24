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
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.orm import synonym

db = SQLAlchemy()

# Where every new player's rating starts. Matches the database's own
# column default and the Ranks table, whose lowest tier begins at 0.
STARTING_ELO = 0

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
    profile_picture = db.Column(db.String(512), nullable=True)

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
        Exactly the shape /leaderboard already returns, for either league.

        "Unranked" mirrors the LEFT JOIN in the old SQL: a player whose
        rank hasn't been calculated yet still has to appear on the ladder.
        """
        standing = self.standing(league)
        return {
            "username": self.username,
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
            "username": self.username,
            "country_flag": self.country_flag,
            "profile_picture": self.profile_picture,
            "league_type": league,
            **self.standing(league),
        }

    def to_profile_dict(self):
        """The signed-in player's own profile, with both leagues."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "country_flag": self.country_flag,
            "profile_picture": self.profile_picture,
            "leagues": {league: self.standing(league) for league in LEAGUE_TYPES},
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

    player = db.relationship("Player", lazy="joined")

    # Declared as indexes (not a table constraint) so ensure_schema() can
    # add any that are missing to an existing database. The unique one is
    # what stops a double-tapped Join from queueing someone twice.
    __table_args__ = (
        db.Index("uq_queue_user_table", "user_id", "table_id", unique=True),
        db.Index("idx_queue_table", "table_id", "queue_position"),
    )

    def to_dict(self, place=None):
        """
        Exactly the shape /queue/<table_id> already returns. `place` is the
        player's actual place in line; queue_position on its own is only a
        sort key and drifts upwards over an evening.
        """
        return {
            "queue_position": place if place is not None else self.queue_position,
            "username": self.player.username,
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
    played_at = db.Column(db.DateTime, nullable=True, server_default=func.current_timestamp())

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
        """The 'playing' response, byte-for-byte as the frontend expects."""
        opponent = self.player_two if self.player_one_id == user_id else self.player_one
        return {
            "status": "playing",
            "opponent": opponent.username if opponent else None,
            "opponent_id": self.opponent_of(user_id),
            "match_id": self.match_id,
            "table_id": self.table_id,
            "league_type": league,
        }

    def to_waiting_dict(self, league=BILLIARDS):
        """The 'waiting_for_challenger' response."""
        return {
            "status": "waiting_for_challenger",
            "match_id": self.match_id,
            "table_id": self.table_id,
            "league_type": league,
        }

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
