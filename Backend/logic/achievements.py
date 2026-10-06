"""
Achievements, and the badges that show them.

Each league has its own set: a Hat Trick at CCNY Ping Pong is a
different badge from a Hat Trick at John Jay Ping Pong, and only that
league's games count towards it. The achievements are the same in every
league except where the game differs - a billiards shutout is 8-0, a ping
pong one 11-0 - which is what each Achievement's `variants` spell out,
keyed by game.

Most achievements are worked out from match history, by replaying a
league's finished games in order (`_replay`). There is one implementation
of the rules, and every use goes through `sync_achievements`:

  - after each result, to award whatever that game earned;
  - on startup (prepare_database), to credit games played before
    achievements existed.

A few depend on where a player stands now - rating, rank, place on the
ladder - and are checked against current standings by the same call.
Two can't be read from either and are awarded when they happen
(`award`): giving up the table, and a long wait in the queue.

History is kept across season resets (seasons.py), so achievements are
for a player's whole career, and once earned are never taken away -
voiding a game doesn't take back a badge it earned.

Ratings at the time of a game come from Matches.winner_elo_before /
loser_elo_before. Games recorded before those existed simply can't earn
the badges that need them (Giant Killer and friends); everything else
about them still counts.
"""
import logging
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from models import (
    BILLIARDS,
    GAMES,
    PING_PONG,
    League,
    Match,
    Player,
    PlayerAchievement,
    PoolTable,
    Rank,
    Standing,
    db,
)

log = logging.getLogger(__name__)

BRONZE, SILVER, GOLD, LEGENDARY = "bronze", "silver", "gold", "legendary"
TIER_ORDER = {BRONZE: 1, SILVER: 2, GOLD: 3, LEGENDARY: 4}

# How long a queue wait earns Patience.
PATIENCE_WAIT_SECONDS = 600

# Ladder badges need this many games this season, so nobody takes #1 by
# winning their only game and never playing again.
LADDER_MIN_GAMES = 10

# The rules that differ by game.
RULES = {
    BILLIARDS: {
        "shutout": (8, 0),  # winner's score, loser's score
        "close_loser_score": 7,  # 8-7: the loser sank everything but the 8
        "dominator_margin": 5,
        "big_payday": 25,  # ratings move up to 32 a game
    },
    PING_PONG: {
        "shutout": (11, 0),
        "close_loser_score": 10,  # 10-10 or later: a deuce game
        "dominator_margin": 7,
        "big_payday": 35,  # ratings move up to 60 a game
    },
}
BIG_DAY_POINTS = 50


@dataclass(frozen=True)
class Achievement:
    key: str
    name: str
    description: str
    tier: str
    group: str
    secret: bool = False
    # (stat, target): shown as a progress bar while locked. The stat is a
    # key of the per-player stats _replay returns.
    progress: tuple = None
    # Earned when something happens, not read from match history.
    event: bool = False
    # Game -> (name, description), where a game says it differently.
    variants: dict = field(default_factory=dict)

    def name_in(self, league):
        return self.variants.get(_game(league), (self.name, self.description))[0]

    def description_in(self, league):
        return self.variants.get(_game(league), (self.name, self.description))[1]


def _game(league):
    """The game of a League (or a game name, or any League.of() reference)."""
    if isinstance(league, str) and league in GAMES:
        return league
    resolved = League.of(league)
    return resolved.game if resolved is not None else BILLIARDS


GROUPS = [
    ("milestones", "Milestones"),
    ("wins", "Wins"),
    ("never_quit", "Never quit"),
    ("streaks", "Streaks"),
    ("king", "King of the hill"),
    ("scorelines", "Scorelines"),
    ("upsets", "Upsets and rating"),
    ("ladder", "The ladder"),
    ("rivals", "Rivals"),
    ("time", "Time and dedication"),
    ("secrets", "Secrets"),
]

A = Achievement
ACHIEVEMENTS = [
    # --- Milestones ---
    A("first_break", "First Break", "Play your first game.", BRONZE, "milestones", progress=("games", 1),
      variants={PING_PONG: ("First Serve", "Play your first game.")}),
    A("regular", "Regular", "Play 10 games.", BRONZE, "milestones", progress=("games", 10)),
    A("veteran", "Veteran", "Play 50 games.", SILVER, "milestones", progress=("games", 50)),
    A("centurion", "Centurion", "Play 100 games.", GOLD, "milestones", progress=("games", 100)),
    A("lifer", "Lifer", "Play 250 games.", GOLD, "milestones", progress=("games", 250)),
    A("hall_of_famer", "Hall of Famer", "Play 500 games.", LEGENDARY, "milestones", progress=("games", 500)),
    # --- Wins ---
    A("first_blood", "First Blood", "Win your first game.", BRONZE, "wins", progress=("wins", 1)),
    A("double_digits", "Double Digits", "Win 10 games.", BRONZE, "wins", progress=("wins", 10)),
    A("fifty_club", "Fifty Club", "Win 50 games.", SILVER, "wins", progress=("wins", 50)),
    A("hundred_club", "Hundred Club", "Win 100 games.", GOLD, "wins", progress=("wins", 100)),
    # --- Never quit ---
    A("learning_curve", "Learning Curve", "Lose your first game.", BRONZE, "never_quit", progress=("losses", 1)),
    A("thick_skin", "Thick Skin", "Lose 25 games and keep showing up.", BRONZE, "never_quit", progress=("losses", 25)),
    A("phoenix", "Phoenix", "Win right after losing 5 in a row.", SILVER, "never_quit"),
    # --- Streaks ---
    A("bounce_back", "Bounce Back", "Win the game right after a loss.", BRONZE, "streaks"),
    A("hat_trick", "Hat Trick", "Win 3 in a row.", BRONZE, "streaks", progress=("best_streak", 3)),
    A("on_fire", "On Fire", "Win 5 in a row.", SILVER, "streaks", progress=("best_streak", 5)),
    A("unstoppable", "Unstoppable", "Win 10 in a row.", GOLD, "streaks", progress=("best_streak", 10)),
    A("untouchable", "Untouchable", "Win 15 in a row.", LEGENDARY, "streaks", progress=("best_streak", 15)),
    # --- King of the hill ---
    A("crowned", "Crowned", "Take the table by beating a sitting king.", BRONZE, "king"),
    A("kingslayer", "Kingslayer", "End a king's streak of 3 or more.", SILVER, "king"),
    A("tyrant_toppler", "Tyrant Toppler", "End a king's streak of 5 or more.", GOLD, "king"),
    A("usurper", "Usurper", "Dethrone the same king 3 times.", SILVER, "king"),
    A("record_breaker", "Record Breaker", "Set a new table record streak of 3 or more.", GOLD, "king"),
    # --- Scorelines ---
    A("shutout", "Shutout", "Win 8-0.", SILVER, "scorelines",
      variants={PING_PONG: ("Bagel", "Win 11-0.")}),
    A("shutout_artist", "Shutout Artist", "Win 5 games 8-0.", GOLD, "scorelines", progress=("shutouts", 5),
      variants={PING_PONG: ("Bakery", "Win 5 games 11-0.")}),
    A("nail_biter", "Nail-Biter", "Win 8-7.", BRONZE, "scorelines",
      variants={PING_PONG: ("Deuce Survivor", "Win a game that went to 10-10.")}),
    A("so_close", "So Close", "Lose 7-8.", BRONZE, "scorelines",
      variants={PING_PONG: ("So Close", "Lose a game that went to 10-10.")}),
    A("dominator", "Dominator", "Win 5 in a row, each by 5 or more balls.", GOLD, "scorelines",
      variants={PING_PONG: ("Dominator", "Win 5 in a row, each by 7 or more points.")}),
    # --- Upsets and rating ---
    A("giant_killer", "Giant Killer", "Beat someone rated 100+ above you.", SILVER, "upsets"),
    A("david_vs_goliath", "David vs Goliath", "Beat someone rated 250+ above you.", GOLD, "upsets"),
    A("underdog", "Underdog", "Beat 5 opponents rated higher than you.", SILVER, "upsets", progress=("upsets", 5)),
    A("big_payday", "Big Payday", "Gain 25+ points from one win.", SILVER, "upsets",
      variants={PING_PONG: ("Big Payday", "Gain 35+ points from one win.")}),
    A("big_day", "Big Day", f"Gain {BIG_DAY_POINTS}+ points in one day.", BRONZE, "upsets"),
    A("century", "Century", "Reach a rating of 100.", SILVER, "upsets", progress=("rating", 100)),
    A("double_century", "Double Century", "Reach a rating of 250.", GOLD, "upsets", progress=("rating", 250)),
    # --- The ladder ---
    A("rank_silver", "Silver Rank", "Reach the Silver rank.", SILVER, "ladder"),
    A("rank_gold", "Gold Rank", "Reach the Gold rank.", GOLD, "ladder"),
    A("rank_platinum", "Platinum Rank", "Reach the Platinum rank.", LEGENDARY, "ladder"),
    A("podium", "Podium", f"Be top 3 on the ladder, with {LADDER_MIN_GAMES}+ games this season.", SILVER, "ladder"),
    A("number_one", "Number One", f"Be #1 on the ladder, with {LADDER_MIN_GAMES}+ games this season.", LEGENDARY, "ladder"),
    # --- Rivals ---
    A("social_butterfly", "Social Butterfly", "Play 10 different opponents.", BRONZE, "rivals", progress=("opponents", 10)),
    A("networker", "Networker", "Play 25 different opponents.", SILVER, "rivals", progress=("opponents", 25)),
    A("rivalry", "Rivalry", "Play the same person 10 times.", SILVER, "rivals", progress=("most_played", 10)),
    A("nemesis", "Nemesis", "Lose to the same person 5 times.", BRONZE, "rivals", progress=("most_lost_to", 5)),
    A("revenge", "Revenge", "Beat the person who beat you last time you met.", BRONZE, "rivals"),
    A("welcome_committee", "Welcome Committee", "Play someone in their first-ever game.", BRONZE, "rivals"),
    # --- Time and dedication ---
    A("early_bird", "Early Bird", "Finish a game before 9am.", BRONZE, "time"),
    A("night_owl", "Night Owl", "Finish a game between midnight and 4am.", SILVER, "time"),
    A("marathon", "Marathon", "Play 10 games in one day.", SILVER, "time", progress=("best_day", 10)),
    A("iron_man", "Iron Man", "Play 20 games in one day.", GOLD, "time", progress=("best_day", 20)),
    A("flawless_night", "Flawless Night", "Win 5+ games in a day without losing any.", GOLD, "time"),
    A("weekend_warrior", "Weekend Warrior", "Play 20 games on weekends.", SILVER, "time", progress=("weekend_games", 20)),
    A("loyal", "Loyal", "Play in 4 weeks in a row.", SILVER, "time"),
    A("welcome_back", "Welcome Back", "Return after 30+ days away.", BRONZE, "time"),
    # --- Secrets ---
    A("deja_vu", "Deja Vu", "Play the same opponent 3 games in a row.", BRONZE, "secrets", secret=True),
    A("perfectly_balanced", "Perfectly Balanced", "Have exactly as many wins as losses after 20+ games.", SILVER, "secrets", secret=True),
    A("lucky_sevens", "Lucky Sevens", "Hit a rating of exactly 77.", SILVER, "secrets", secret=True),
    A("mirror_match", "Mirror Match", "Play someone with exactly your rating (not 0).", BRONZE, "secrets", secret=True),
    A("spooky", "Spooky", "Play on Halloween.", BRONZE, "secrets", secret=True),
    A("ho_ho_ho", "Ho Ho Ho", "Play on Christmas.", BRONZE, "secrets", secret=True),
    A("fresh_start", "Fresh Start", "Play on New Year's Day.", BRONZE, "secrets", secret=True),
    A("friday_13th", "Friday the 13th", "Win on a Friday the 13th.", SILVER, "secrets", secret=True),
    A("abdication", "Abdication", "Give up the table.", BRONZE, "secrets", secret=True, event=True),
    A("patience", "Patience", "Wait 10+ minutes in the queue for a game.", BRONZE, "secrets", secret=True, event=True),
]
del A

BY_KEY = {a.key: a for a in ACHIEVEMENTS}

# Rank badges by the rank's name in the Ranks table, which both leagues
# share. A league without a rank of that name can't earn its badge.
RANK_BADGES = {"rank_silver": "silver", "rank_gold": "gold", "rank_platinum": "platinum"}

# Badges that are a plain count of one total.
COUNTED = [
    ("first_break", "games", 1),
    ("regular", "games", 10),
    ("veteran", "games", 50),
    ("centurion", "games", 100),
    ("lifer", "games", 250),
    ("hall_of_famer", "games", 500),
    ("first_blood", "wins", 1),
    ("double_digits", "wins", 10),
    ("fifty_club", "wins", 50),
    ("hundred_club", "wins", 100),
    ("learning_curve", "losses", 1),
    ("thick_skin", "losses", 25),
    ("hat_trick", "best_streak", 3),
    ("on_fire", "best_streak", 5),
    ("unstoppable", "best_streak", 10),
    ("untouchable", "best_streak", 15),
    ("shutout_artist", "shutouts", 5),
    ("dominator", "big_wins", 5),
    ("underdog", "upsets", 5),
    ("perfectly_balanced", "balanced", 1),
]

SECRET_DESCRIPTION = "A secret achievement. Keep playing to find it."


class _Record:
    """One player's running totals in one league during a replay."""

    def __init__(self):
        self.games = self.wins = self.losses = 0
        self.win_streak = self.loss_streak = self.best_streak = 0
        self.shutouts = 0
        self.big_wins = 0  # wins in a row by the league's dominator margin
        self.upsets = 0  # wins over higher-rated opponents
        self.played = Counter()  # opponent -> games
        self.lost_to = Counter()  # opponent -> losses
        self.recent = deque(maxlen=3)  # last three opponents
        self.day_games = Counter()
        self.day_wins = Counter()
        self.day_losses = Counter()
        self.day_points = Counter()  # rating gained (or lost) each day
        self.weekend_games = 0
        self.weeks = set()  # (iso year, iso week)
        self.last_played = None

    @property
    def balanced(self):
        return 1 if self.games >= 20 and self.wins == self.losses else 0

    def stats(self):
        return {
            "games": self.games,
            "wins": self.wins,
            "losses": self.losses,
            "best_streak": self.best_streak,
            "shutouts": self.shutouts,
            "upsets": self.upsets,
            "opponents": len(self.played),
            "most_played": max(self.played.values(), default=0),
            "most_lost_to": max(self.lost_to.values(), default=0),
            "best_day": max(self.day_games.values(), default=0),
            "weekend_games": self.weekend_games,
        }


def _iso_week(day):
    iso = day.isocalendar()
    return iso[0], iso[1]


def _league_matches(league):
    """A league's finished games, in the order they were recorded."""
    tables = dict(db.session.execute(db.select(PoolTable.table_id, PoolTable.league_id)).all())
    matches = db.session.scalars(
        db.select(Match)
        .where(
            Match.match_status == Match.STATUS_FINISHED,
            Match.winner_id.isnot(None),
            Match.loser_id.isnot(None),
        )
        .order_by(Match.match_id)
    )
    # A table the venue never registered counts as CCNY's billiards, as it
    # does everywhere else (tables.league_for_table).
    unregistered = league.league_id if league.legacy_key == BILLIARDS else None
    return [
        m
        for m in matches
        if tables.get(m.table_id, unregistered) == league.league_id
    ]


def _replay(league):
    """
    Walk a league's finished games in order.

    Returns (earned, stats):
      earned  {(user_id, key): (match_id, played_at)} - the first game
              that earned each achievement
      stats   {user_id: {...}} - totals for progress bars
    """
    league = League.of(league)
    rules = RULES[league.game]
    shutout_score = rules["shutout"]
    close = rules["close_loser_score"]
    rank_floor = {
        name.lower(): min_elo
        for name, min_elo in db.session.execute(db.select(Rank.rank_name, Rank.min_elo))
    }

    records = defaultdict(_Record)
    earned = {}
    kings, streaks, table_records = {}, {}, {}
    usurped = Counter()  # (challenger, king) -> times dethroned
    last_winner = {}  # frozenset of two players -> who won when they last met

    for m in _league_matches(league):
        w, l = m.winner_id, m.loser_id
        if w == l:
            continue
        when = m.played_at

        def give(user_id, key, m=m, when=when):
            earned.setdefault((user_id, key), (m.match_id, when))

        pair = frozenset((w, l))
        gained = m.elo_change or 0
        lost = m.loser_points_lost or 0

        # --- King of the hill ---
        table = m.table_id
        king = kings.get(table)
        reigning = king is not None and m.player_one_id == king
        if reigning and w != king:
            give(w, "crowned")
            if streaks[table] >= 3:
                give(w, "kingslayer")
            if streaks[table] >= 5:
                give(w, "tyrant_toppler")
            usurped[(w, king)] += 1
            if usurped[(w, king)] >= 3:
                give(w, "usurper")
        if reigning and w == king:
            streaks[table] += 1
        else:
            kings[table], streaks[table] = w, 1
        if streaks[table] > table_records.get(table, 0):
            if streaks[table] >= 3:
                give(w, "record_breaker")
            table_records[table] = streaks[table]

        # --- Who they played ---
        if records[l].games == 0:
            give(w, "welcome_committee")
        if records[w].games == 0:
            give(l, "welcome_committee")

        # --- Ratings at the time, where the game recorded them ---
        rw, rl = m.winner_elo_before, m.loser_elo_before
        if rw is not None and rl is not None:
            if rw == rl != 0:
                give(w, "mirror_match")
                give(l, "mirror_match")
            if rl - rw >= 100:
                give(w, "giant_killer")
            if rl - rw >= 250:
                give(w, "david_vs_goliath")
            if rl > rw:
                records[w].upsets += 1
            for uid, after in ((w, rw + gained), (l, rl - lost)):
                _rating_badges(give, uid, after, rank_floor)
        if gained >= rules["big_payday"]:
            give(w, "big_payday")

        # --- Each player's own record ---
        for uid, opp, won in ((w, l, True), (l, w, False)):
            r = records[uid]
            mine, theirs = m.balls_for(uid), m.balls_for(opp)
            scored = mine is not None and theirs is not None

            if won:
                if r.loss_streak >= 1:
                    give(uid, "bounce_back")
                if r.loss_streak >= 5:
                    give(uid, "phoenix")
                if last_winner.get(pair) == opp:
                    give(uid, "revenge")
                r.wins += 1
                r.win_streak += 1
                r.loss_streak = 0
                r.best_streak = max(r.best_streak, r.win_streak)
                if scored and (mine, theirs) == shutout_score:
                    r.shutouts += 1
                    give(uid, "shutout")
                if scored and theirs >= close and _is_close(league, mine, theirs):
                    give(uid, "nail_biter")
                won_big = scored and mine - theirs >= rules["dominator_margin"]
                r.big_wins = r.big_wins + 1 if won_big else 0
            else:
                r.losses += 1
                r.loss_streak += 1
                r.win_streak = 0
                r.big_wins = 0
                r.lost_to[opp] += 1
                if scored and mine >= close and _is_close(league, theirs, mine):
                    give(uid, "so_close")

            r.games += 1
            r.played[opp] += 1
            r.recent.append(opp)

            for key, stat, target in COUNTED:
                if getattr(r, stat) >= target:
                    give(uid, key)
            if len(r.played) >= 10:
                give(uid, "social_butterfly")
            if len(r.played) >= 25:
                give(uid, "networker")
            if r.played[opp] >= 10:
                give(uid, "rivalry")
            if r.lost_to[opp] >= 5:
                give(uid, "nemesis")
            if len(r.recent) == 3 and len(set(r.recent)) == 1:
                give(uid, "deja_vu")

            # --- When they played ---
            if when is None:
                continue
            day = when.date()
            if 4 <= when.hour < 9:
                give(uid, "early_bird")
            if when.hour < 4:
                give(uid, "night_owl")
            r.day_games[day] += 1
            if r.day_games[day] >= 10:
                give(uid, "marathon")
            if r.day_games[day] >= 20:
                give(uid, "iron_man")
            if won:
                r.day_wins[day] += 1
                r.day_points[day] += gained
                if r.day_points[day] >= BIG_DAY_POINTS:
                    give(uid, "big_day")
                if r.day_wins[day] >= 5 and r.day_losses[day] == 0:
                    give(uid, "flawless_night")
            else:
                r.day_losses[day] += 1
                r.day_points[day] -= lost
            if day.weekday() >= 5:
                r.weekend_games += 1
                if r.weekend_games >= 20:
                    give(uid, "weekend_warrior")
            r.weeks.add(_iso_week(day))
            if all(_iso_week(day - timedelta(weeks=k)) in r.weeks for k in (1, 2, 3)):
                give(uid, "loyal")
            if r.last_played is not None and when - r.last_played >= timedelta(days=30):
                give(uid, "welcome_back")
            r.last_played = when
            if (day.month, day.day) == (10, 31):
                give(uid, "spooky")
            if (day.month, day.day) == (12, 25):
                give(uid, "ho_ho_ho")
            if (day.month, day.day) == (1, 1):
                give(uid, "fresh_start")
            if won and day.weekday() == 4 and day.day == 13:
                give(uid, "friday_13th")

        last_winner[pair] = w

    stats = {uid: r.stats() for uid, r in records.items()}
    return earned, stats


def _is_close(league, winner_score, loser_score):
    """8-7 in billiards; in ping pong, any game that reached 10-10."""
    if _game(league) == PING_PONG:
        return loser_score >= RULES[PING_PONG]["close_loser_score"]
    return (winner_score, loser_score) == (8, RULES[BILLIARDS]["close_loser_score"])


def _rating_badges(give, user_id, rating, rank_floor):
    """The badges a rating earns the moment a player reaches it."""
    if rating >= 100:
        give(user_id, "century")
    if rating >= 250:
        give(user_id, "double_century")
    if rating == 77:
        give(user_id, "lucky_sevens")
    for key, rank_name in RANK_BADGES.items():
        floor = rank_floor.get(rank_name)
        if floor is not None and rating >= floor:
            give(user_id, key)


def _standings(league):
    """
    Badges for where players stand right now: rating, rank, and place on
    the ladder. Covers games from before ratings were recorded per game,
    and the ladder, which no single game decides. Returns {(user_id, key)}.
    """
    league = League.of(league)
    players = db.session.execute(
        db.select(Standing.user_id, Standing.elo, Standing.wins, Standing.losses)
        .join(Player, Player.user_id == Standing.user_id)
        .where(Standing.league_id == league.league_id, Player.deleted_at.is_(None))
    ).all()
    rank_floor = {
        name.lower(): min_elo
        for name, min_elo in db.session.execute(db.select(Rank.rank_name, Rank.min_elo))
    }

    earned = set()

    def give(user_id, key):
        earned.add((user_id, key))

    ratings = [rating or 0 for _, rating, _, _ in players]
    for user_id, rating, won, lost in players:
        rating = rating or 0
        if (won or 0) + (lost or 0) == 0:
            continue  # nothing to show for a player who hasn't played
        _rating_badges(give, user_id, rating, rank_floor)
        if (won or 0) + (lost or 0) >= LADDER_MIN_GAMES:
            above = sum(1 for other in ratings if other > rating)
            if above < 3:
                give(user_id, "podium")
            if above == 0:
                give(user_id, "number_one")
    return earned


def _insert(league, rows):
    """
    Store earned achievements that aren't stored yet; returns how many were
    new. Badges never go to deleted accounts. Retries once if a concurrent
    call stored some first - the unique index settles who wins.
    """
    league = League.of(league)
    deleted = set(db.session.scalars(db.select(Player.user_id).where(Player.deleted_at.isnot(None))))
    rows = [row for row in rows if row["user_id"] not in deleted]
    for _ in range(2):
        existing = set(
            db.session.execute(
                db.select(PlayerAchievement.user_id, PlayerAchievement.achievement_key).where(
                    PlayerAchievement.league_id == league.league_id
                )
            ).all()
        )
        new = [row for row in rows if (row["user_id"], row["achievement_key"]) not in existing]
        if not new:
            db.session.commit()
            return 0
        try:
            # earned_at only when known, so the database fills in now
            # rather than storing NULL.
            db.session.add_all(
                PlayerAchievement(
                    league_id=league.league_id,
                    league_type=league.game,
                    **{k: v for k, v in row.items() if v is not None},
                )
                for row in new
            )
            db.session.commit()
            return len(new)
        except IntegrityError:
            db.session.rollback()
    return 0


def sync_achievements(league=None):
    """
    Award everything a league's history and standings say has been
    earned - every league when none is named. Safe to call any time;
    returns how many achievements were newly awarded.
    """
    total = 0
    leagues = [League.of(league)] if league else list(db.session.scalars(db.select(League)))
    for lg in leagues:
        try:
            earned, _ = _replay(lg)
            rows = [
                {"user_id": uid, "achievement_key": key, "match_id": match_id, "earned_at": when}
                for (uid, key), (match_id, when) in earned.items()
            ]
            rows += [
                {"user_id": uid, "achievement_key": key}
                for uid, key in _standings(lg)
                if (uid, key) not in earned
            ]
            total += _insert(lg, rows)
        except Exception:
            db.session.rollback()
            raise
    return total


def award(user_id, league, key):
    """Award one event achievement. True if it was new."""
    try:
        return _insert(league, [{"user_id": user_id, "achievement_key": key}]) > 0
    except Exception:
        # Leave the session usable for whatever the caller does next.
        db.session.rollback()
        raise


# --- Reading badges ---


def badge_summary(key, league):
    """The few fields a name tag needs: {key, name, tier}."""
    a = BY_KEY[key]
    return {"key": a.key, "name": a.name_in(league), "tier": a.tier}


def _best(rows):
    """Highest tier, then most recently earned."""
    known = [row for row in rows if row.achievement_key in BY_KEY]
    if not known:
        return None
    best = max(
        known,
        key=lambda row: (TIER_ORDER[BY_KEY[row.achievement_key].tier], row.earned_at, row.id),
    )
    return best.achievement_key


def _chosen(player, league):
    standing = player.standing_in(league)
    return standing.featured_badge if standing is not None else None


def _featured_key(player, league, rows):
    """The player's chosen badge if they hold it, else their best."""
    held = {row.achievement_key for row in rows}
    chosen = _chosen(player, league)
    if chosen in held and chosen in BY_KEY:
        return chosen
    return _best(rows)


def _rows_for(user_ids, league):
    league = League.of(league)
    rows = defaultdict(list)
    if user_ids and league is not None:
        for row in db.session.scalars(
            db.select(PlayerAchievement).where(
                PlayerAchievement.user_id.in_(user_ids),
                PlayerAchievement.league_id == league.league_id,
            )
        ):
            rows[row.user_id].append(row)
    return rows


def featured_badges(players, league):
    """{user_id: {key, name, tier} or None} for players in a league, in one query."""
    players = [p for p in players if p is not None]
    rows = _rows_for([p.user_id for p in players], league)
    result = {}
    for p in players:
        key = _featured_key(p, league, rows[p.user_id])
        result[p.user_id] = badge_summary(key, league) if key else None
    return result


def player_badges(user_id, league):
    """
    Every badge in a league for one player, earned or not; None if there's
    no such player, or they deleted their account. Secret badges stay
    "???" until earned.
    """
    player = db.session.get(Player, user_id)
    if player is None or player.is_deleted:
        return None

    league = League.of(league)
    rows = _rows_for([user_id], league)[user_id]
    held = {row.achievement_key: row for row in rows}
    _, stats = _replay(league)
    mine = dict(stats.get(user_id, {}))
    mine["rating"] = player.standing(league)["elo"] or 0

    badges = []
    for a in ACHIEVEMENTS:
        row = held.get(a.key)
        hidden = a.secret and row is None
        progress = None
        if row is None and a.progress and not hidden:
            stat, target = a.progress
            progress = {"current": max(0, min(mine.get(stat, 0), target)), "target": target}
        badges.append(
            {
                "key": a.key,
                "name": "???" if hidden else a.name_in(league),
                "description": SECRET_DESCRIPTION if hidden else a.description_in(league),
                "tier": a.tier,
                "group": a.group,
                "secret": a.secret,
                "earned": row is not None,
                "earned_at": row.earned_at.isoformat() if row is not None and row.earned_at else None,
                "progress": progress,
            }
        )

    chosen = _chosen(player, league)
    return {
        "user_id": player.user_id,
        "username": player.username,
        "league_type": league.game,
        "league_id": league.league_id,
        "featured": _featured_key(player, league, rows),
        "chosen": chosen if chosen in held else None,
        "earned_count": len([k for k in held if k in BY_KEY]),
        "total": len(ACHIEVEMENTS),
        "groups": [{"key": key, "name": name} for key, name in GROUPS],
        "badges": badges,
    }


def set_featured_badge(user_id, league, key):
    """
    Choose the badge a league's ladder shows by a name; None goes back to
    automatic. Returns None on success, or a message saying why not.
    """
    league = League.of(league)
    if key is not None:
        if key not in BY_KEY:
            return "That badge doesn't exist."
        held = db.session.scalar(
            db.select(PlayerAchievement.id).where(
                PlayerAchievement.user_id == user_id,
                PlayerAchievement.league_id == league.league_id,
                PlayerAchievement.achievement_key == key,
            )
        )
        if held is None:
            return "You haven't earned that badge in this league yet."
    player = db.session.get(Player, user_id)
    if player is None:
        return "That player doesn't exist."
    standing = player.standing_in(league)
    if standing is None:
        if key is None:
            return None  # automatic already: nothing chosen anywhere
        return "You haven't earned that badge in this league yet."
    standing.featured_badge = key
    db.session.commit()
    return None


def new_badges(user_id):
    """
    Badges earned in any league but not yet announced on the player's
    screen: [{id, league_type, league_id, league_name, key, name, tier}].
    """
    leagues = {league.league_id: league for league in db.session.scalars(db.select(League))}
    rows = db.session.scalars(
        db.select(PlayerAchievement)
        .where(PlayerAchievement.user_id == user_id, PlayerAchievement.seen.is_(False))
        .order_by(PlayerAchievement.earned_at, PlayerAchievement.id)
    )
    return [
        {
            "id": row.id,
            "league_type": leagues[row.league_id].game,
            "league_id": row.league_id,
            "league_name": leagues[row.league_id].name,
            **badge_summary(row.achievement_key, leagues[row.league_id]),
        }
        for row in rows
        if row.achievement_key in BY_KEY and row.league_id in leagues
    ]


def mark_badges_seen(user_id, ids):
    """Stop announcing these badges (by id). Returns how many were marked."""
    ids = [i for i in ids if isinstance(i, int) and not isinstance(i, bool)]
    if not ids:
        return 0
    count = db.session.execute(
        db.update(PlayerAchievement)
        .where(PlayerAchievement.user_id == user_id, PlayerAchievement.id.in_(ids))
        .values(seen=True)
    ).rowcount
    db.session.commit()
    return count
