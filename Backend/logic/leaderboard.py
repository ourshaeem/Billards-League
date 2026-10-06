"""The top 50 players by rating, in one league."""
from logic.achievements import featured_badges
from models import BILLIARDS, League, Player, Standing, db


def top50_leaderboard(league=BILLIARDS):
    """
    The league's ladder, best first:
        [{user_id, username, country_flag, profile_picture, elo_rating,
          total_wins, total_losses, rank_name, badge}, ...]
    Everyone with a place in the league - their Standing, which they get
    on entering its PIN or playing their first game there. badge is the
    badge they show by their name in this league ({key, name, tier}), or
    None before they've earned one.

    Errors are left to the app's error handler. This used to swallow them
    and return [], which the UI can only show as "no games played yet" -
    a database outage dressed up as an empty league.
    """
    league = League.of(league)
    if league is None:
        return []
    players = db.session.scalars(
        db.select(Player)
        .join(Standing, Standing.user_id == Player.user_id)
        .where(
            Standing.league_id == league.league_id,
            # A deleted account keeps its row for other people's history,
            # but has no place on the ladder.
            Player.deleted_at.is_(None),
        )
        # Wins then name break ties, so two players on the same rating
        # don't swap places from one poll to the next.
        .order_by(Standing.elo.desc(), Standing.wins.desc(), Player.username)
        .limit(50)
    ).all()
    badges = featured_badges(players, league)
    return [
        {**player.to_leaderboard_dict(league), "badge": badges[player.user_id]}
        for player in players
    ]
