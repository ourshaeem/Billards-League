"""The top 50 players by rating, in either league."""
from sqlalchemy.orm import selectinload

from models import BILLIARDS, PING_PONG, Player, db


def top50_leaderboard(league=BILLIARDS):
    """
    Returns the same list of dicts as before, for the given league:
        [{username, elo_rating, total_wins, total_losses, rank_name}, ...]

    Billiards' Player.rank is lazy="joined", so the rank name comes back
    in the same query rather than one extra query per player; ping pong's
    rank is loaded for the whole page in one more. Both relationships are
    optional on the Player side, which reproduces the old LEFT JOIN: a
    player with no rank yet still appears, as "Unranked".

    Errors are left to the app's error handler. This used to swallow them
    and return [], which the UI can only show as "no games played yet" -
    a database outage dressed up as an empty league.
    """
    fields = Player.LEAGUE_FIELDS[league]
    elo = getattr(Player, fields["elo"])
    wins = getattr(Player, fields["wins"])

    stmt = (
        # Wins then name break ties, so two players on the same rating
        # don't swap places from one poll to the next.
        db.select(Player)
        .order_by(elo.desc(), wins.desc(), Player.username)
        .limit(50)
    )
    if league == PING_PONG:
        stmt = stmt.options(selectinload(Player.ping_pong_rank))

    players = db.session.scalars(stmt).all()
    return [player.to_leaderboard_dict(league) for player in players]
