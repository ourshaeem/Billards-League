"""The top 50 players by rating."""
from models import Player, db


def top50_leaderboard():
    """
    Returns the same list of dicts as before:
        [{username, elo_rating, total_wins, total_losses, rank_name}, ...]

    Player.rank is lazy="joined", so the rank name comes back in the same
    query rather than one extra query per player. The relationship is
    optional on the Player side, which reproduces the old LEFT JOIN: a
    player with no rank yet still appears, as "Unranked".

    Errors are left to the app's error handler. This used to swallow them
    and return [], which the UI can only show as "no games played yet" -
    a database outage dressed up as an empty league.
    """
    players = db.session.scalars(
        # Wins then name break ties, so two players on the same rating
        # don't swap places from one poll to the next.
        db.select(Player)
        .order_by(Player.elo_rating.desc(), Player.total_wins.desc(), Player.username)
        .limit(50)
    ).all()
    return [player.to_leaderboard_dict() for player in players]
