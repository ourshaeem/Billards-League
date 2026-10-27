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
 *
 * Copied from Frontend/src/leagues.js - a rule changed in one must be
 * changed in the other.
 */

export const BILLIARDS = 'billiards';
export const PING_PONG = 'ping_pong';
export const LEAGUE_ORDER = [BILLIARDS, PING_PONG];

const PING_PONG_GAME_POINT = 11;
const PING_PONG_MAX_POINTS = 99;

// The games a billiards score can be reported as. Each has its own rating
// and ladder in every billiards league: points won at 8-ball never move a
// 9-ball or 10-ball rating, or the other way round. STANDARD is the game a
// league has always played - 8-ball, and ping pong's only one.
export const STANDARD = 'standard';
export const NINE_BALL = 'nine_ball';
export const TEN_BALL = 'ten_ball';

/** A billiards game scored in balls sunk, 0 to `balls`, with no tie. */
function ballGame(key, name, balls, near) {
  return {
    key,
    name,
    scoreUnit: 'balls',
    maxScore: balls,
    quickScores: [
      { mine: balls, theirs: 0 },
      { mine: balls, theirs: near },
      { mine: 0, theirs: balls },
      { mine: near, theirs: balls },
    ],
    scoreProblem(mine, theirs) {
      if (mine === theirs) return `Scores can't be a tie - somebody sank the ${balls}.`;
      if (mine < 0 || theirs < 0 || mine > balls || theirs > balls) {
        return `In ${name}, scores run from 0 to ${balls}.`;
      }
      return null;
    },
  };
}

const EIGHT_BALL_GAME = ballGame(STANDARD, '8-ball', 8, 4);

export const LEAGUES = {
  [BILLIARDS]: {
    key: BILLIARDS,
    name: 'Billiards',
    sport: 'billiards',
    blurb: '8-ball, 9-ball or 10-ball, king of the table. Win and you stay on.',
    // 8-ball's, the standard game's - what the app always used.
    scoreUnit: EIGHT_BALL_GAME.scoreUnit,
    maxScore: EIGHT_BALL_GAME.maxScore,
    quickScores: EIGHT_BALL_GAME.quickScores,
    scoreProblem: EIGHT_BALL_GAME.scoreProblem,
    modes: [EIGHT_BALL_GAME, ballGame(NINE_BALL, '9-ball', 9, 4), ballGame(TEN_BALL, '10-ball', 10, 5)],
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
// Ping pong has one game: its own.
LEAGUES[PING_PONG].modes = [{ ...LEAGUES[PING_PONG], key: STANDARD, name: 'Ping pong' }];

/** A game's details - pass league.game - falling back to billiards for anything unknown. */
export function gameInfo(game) {
  return LEAGUES[game] || LEAGUES[BILLIARDS];
}

/**
 * One of a game's modes - 8-ball, 9-ball or 10-ball in billiards (with its
 * name, score unit, quick scores and score rules) - falling back to the
 * standard one.
 */
export function modeInfo(game, mode) {
  const { modes } = gameInfo(game);
  return modes.find((m) => m.key === mode) || modes[0];
}

/** Whether a game has more than one mode - billiards does. */
export function hasModes(game) {
  return gameInfo(game).modes.length > 1;
}

export function isGame(game) {
  return Object.prototype.hasOwnProperty.call(LEAGUES, game);
}

/**
 * A player's standings for a profile, with their 9-ball and 10-ball ones
 * (the profile's mode_standings) right after each league's standard one:
 * [{...standing, key, modeName}]. modeName names the game - "8-ball",
 * "9-ball" - wherever a league has more than one row, and is null for a
 * league with only its standard game's.
 */
export function standingRows(standings, modeStandings) {
  const extra = modeStandings || [];
  const rows = [];
  const placed = new Set();
  (standings || []).forEach((st) => {
    const others = extra.filter((m) => m.league_id === st.league_id);
    rows.push({
      ...st,
      key: `${st.league_id}:${STANDARD}`,
      modeName: others.length ? modeInfo(st.league_type, STANDARD).name : null,
    });
    others.forEach((m) => {
      rows.push({ ...m, key: `${m.league_id}:${m.mode}`, modeName: m.mode_name });
      placed.add(m);
    });
  });
  extra
    .filter((m) => !placed.has(m))
    .forEach((m) => rows.push({ ...m, key: `${m.league_id}:${m.mode}`, modeName: m.mode_name }));
  return rows;
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
