"""
Starting a league over: every player's rating, record and rank in one
league back to where a new player starts, as at the beginning of a
season. Every other league is untouched.

Finished games are kept - they are history, and the Games feeds still
show them - and so is whoever is at the table or in the queue: nobody is
pulled out of a game. A game reported after the reset simply counts
towards the new season.

Run it with the CLI command in app.py:
    flask --app app reset-league ccny-ping-pong
which saves everyone's old numbers to a backup file first.
"""
from database import retry_on_deadlock
from models import STARTING_ELO, League, Player, PoolTable, Rank, Standing, db


def league_standings(league):
    """Every player's current numbers in a league - what a reset replaces."""
    league = League.of(league)
    rows = db.session.execute(
        db.select(Standing, Player.username)
        .join(Player, Player.user_id == Standing.user_id)
        .where(Standing.league_id == league.league_id)
        .order_by(Standing.user_id)
    ).all()
    return [
        {
            "user_id": standing.user_id,
            "username": username,
            "elo": standing.elo,
            "wins": standing.wins,
            "losses": standing.losses,
            "rank_id": standing.rank_id,
        }
        for standing, username in rows
    ]


@retry_on_deadlock
def reset_league_standings(league):
    """
    Put every player in `league` back to a new player's numbers: rating
    STARTING_ELO, no wins or losses, the rank that rating earns. Also
    clears the streaks on that league's tables. Returns how many players
    were reset.
    """
    resolved = League.of(league)
    if resolved is None:
        raise ValueError(f"Unknown league {league!r}.")
    starting_rank = Rank.for_elo(STARTING_ELO)
    try:
        count = db.session.execute(
            db.update(Standing)
            .where(Standing.league_id == resolved.league_id)
            .values(
                elo=STARTING_ELO,
                wins=0,
                losses=0,
                rank_id=starting_rank.rank_id if starting_rank else None,
            )
        ).rowcount
        db.session.execute(
            db.update(PoolTable)
            .where(PoolTable.league_id == resolved.league_id)
            .values(current_streak=0, table_record_streak=0, table_record_holder_id=None)
        )
        db.session.commit()
        # Bulk updates skip the session; don't serve anyone the old numbers.
        db.session.expire_all()
        return count
    except Exception:
        db.session.rollback()
        raise
