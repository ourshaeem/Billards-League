"""
Starting a league over: every player's rating, record and rank in one
league back to where a new player starts, as at the beginning of a
season. The other league is untouched.

Finished games are kept - they are history, and the Games feeds still
show them - and so is whoever is at the table or in the queue: nobody is
pulled out of a game. A game reported after the reset simply counts
towards the new season.

Run it with the CLI command in app.py:
    flask --app app reset-league ping_pong
which saves everyone's old numbers to a backup file first.
"""
from database import retry_on_deadlock
from models import LEAGUE_TYPES, STARTING_ELO, Player, PoolTable, Rank, db


def league_standings(league):
    """Every player's current numbers in a league - what a reset replaces."""
    fields = Player.LEAGUE_FIELDS[league]
    return [
        {
            "user_id": player.user_id,
            "username": player.username,
            "elo": getattr(player, fields["elo"]),
            "wins": getattr(player, fields["wins"]),
            "losses": getattr(player, fields["losses"]),
            "rank_id": getattr(player, fields["rank_id"]),
        }
        for player in db.session.scalars(db.select(Player).order_by(Player.user_id))
    ]


@retry_on_deadlock
def reset_league_standings(league):
    """
    Put every player in `league` back to a new player's numbers: rating
    STARTING_ELO, no wins or losses, the rank that rating earns. Also
    clears the streaks on that league's tables. Returns how many players
    were reset.
    """
    if league not in LEAGUE_TYPES:
        raise ValueError(f"Unknown league {league!r} - use one of {', '.join(LEAGUE_TYPES)}.")

    fields = Player.LEAGUE_FIELDS[league]
    starting_rank = Rank.for_elo(STARTING_ELO)
    try:
        count = db.session.execute(
            db.update(Player).values(
                {
                    fields["elo"]: STARTING_ELO,
                    fields["wins"]: 0,
                    fields["losses"]: 0,
                    fields["rank_id"]: starting_rank.rank_id if starting_rank else None,
                }
            )
        ).rowcount
        db.session.execute(
            db.update(PoolTable)
            .where(PoolTable.league_type == league)
            .values(current_streak=0, table_record_streak=0)
        )
        db.session.commit()
        return count
    except Exception:
        db.session.rollback()
        raise
