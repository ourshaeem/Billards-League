/**
 * The two games a league can play, as the screens need to know them: how
 * a score is written, and the quick-pick buttons on the scorecard.
 *
 * The leagues themselves - CCNY Billiards, John Jay Ping Pong and the
 * rest, their names, colours and tables - are NOT here: they come from
 * GET /leagues/directory, because they're the league's data, not the
 * app's. Each league plays one of these games (league.game).
 *
 * Score checks here mirror the server's (score_problem in
 * Backend/logic/record_match.py) so a typo is caught before the round
 * trip. They're a courtesy - the server judges every score against the
 * game's real league regardless of what this file says.
 */

export const BILLIARDS = 'billiards';
export const PING_PONG = 'ping_pong';
export const LEAGUE_ORDER = [BILLIARDS, PING_PONG];

const PING_PONG_GAME_POINT = 11;
const PING_PONG_MAX_POINTS = 99;

export const LEAGUES = {
  [BILLIARDS]: {
    key: BILLIARDS,
    name: 'Billiards',
    sport: 'billiards',
    blurb: 'Eight-ball, king of the table. Win and you stay on.',
    scoreUnit: 'balls',
    maxScore: 8,
    quickScores: [
      { mine: 8, theirs: 0 },
      { mine: 8, theirs: 4 },
      { mine: 0, theirs: 8 },
      { mine: 4, theirs: 8 },
    ],
    scoreProblem(mine, theirs) {
      if (mine === theirs) return "Scores can't be a tie - somebody sank the 8.";
      if (mine < 0 || theirs < 0 || mine > 8 || theirs > 8) return 'Scores run from 0 to 8.';
      return null;
    },
  },
  [PING_PONG]: {
    key: PING_PONG,
    name: 'Ping Pong',
    sport: 'ping pong',
    blurb: 'One game to 11, win by two. Win and you stay on.',
    scoreUnit: 'points',
    maxScore: PING_PONG_MAX_POINTS,
    quickScores: [
      { mine: 11, theirs: 5 },
      { mine: 11, theirs: 9 },
      { mine: 5, theirs: 11 },
      { mine: 9, theirs: 11 },
    ],
    scoreProblem(mine, theirs) {
      const winner = Math.max(mine, theirs);
      const loser = Math.min(mine, theirs);
      if (loser < 0 || winner > PING_PONG_MAX_POINTS) {
        return `Scores run from 0 to ${PING_PONG_MAX_POINTS}.`;
      }
      if (mine === theirs) return "Scores can't be a tie - a game is won by two clear points.";
      if (winner < PING_PONG_GAME_POINT) {
        return 'A game goes to 11 - the winner needs at least 11 points.';
      }
      if (loser < PING_PONG_GAME_POINT - 1 && winner !== PING_PONG_GAME_POINT) {
        return 'Unless it went to 10-10, the game ends as soon as someone reaches 11.';
      }
      if (loser >= PING_PONG_GAME_POINT - 1 && winner !== loser + 2) {
        return 'After 10-10 the game is won by two clear points, like 12-10.';
      }
      return null;
    },
  },
};

/** A game's details - pass league.game - falling back to billiards for anything unknown. */
export function gameInfo(game) {
  return LEAGUES[game] || LEAGUES[BILLIARDS];
}

export function isGame(game) {
  return Object.prototype.hasOwnProperty.call(LEAGUES, game);
}

/** Leagues grouped by school, in the order the server lists them: [{school, leagues}]. */
export function bySchool(leagues) {
  const groups = [];
  (leagues || []).forEach((league) => {
    let group = groups.find((g) => g.school === league.school);
    if (!group) {
      group = { school: league.school, leagues: [] };
      groups.push(group);
    }
    group.leagues.push(league);
  });
  return groups;
}
