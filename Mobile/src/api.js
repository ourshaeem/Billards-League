/**
 * All backend communication lives here - the mobile twin of
 * Frontend/src/api.js, with the same functions, the same result shape
 * and the same error kinds, so screens never touch fetch themselves.
 *
 * What changed from the web version:
 *   - The server address comes from config.js (the live Render URL).
 *   - The login token is held in memory here, set by the session code
 *     after it reads SecureStore at launch (storage.js). localStorage is
 *     gone: it doesn't exist in React Native, and a token in it can be
 *     read by any script on a web page.
 *   - Query strings are built by hand. React Native's URLSearchParams is
 *     only partly implemented and throws on some methods.
 *
 * No CORS handling is needed: CORS is a browser rule, and a native app's
 * requests aren't made by a browser.
 */
import { API_BASE, REQUEST_TIMEOUT_MS, UPLOAD_TIMEOUT_MS } from './config';

// A message longer than this, or one that looks like the inside of the
// server, is swapped for a plain sentence. The backend doesn't send such
// things - this is the second lock on the door.
const MAX_MESSAGE_LENGTH = 240;
const TECHNICAL_MESSAGE = /traceback|sqlalche|\bsql\b|select\s.+\sfrom\s|mysql|exception|errno|stack/i;

function readableMessage(message, fallback) {
  if (typeof message !== 'string') return fallback;
  const trimmed = message.trim();
  if (!trimmed || trimmed.length > MAX_MESSAGE_LENGTH || TECHNICAL_MESSAGE.test(trimmed)) {
    return fallback;
  }
  return trimmed;
}

/** Error categories, so callers can react without string-matching messages. */
export const ErrorKind = {
  NETWORK: 'network', // server unreachable / offline / timed out
  AUTH: 'auth', // token missing, expired or rejected
  REJECTED: 'rejected', // server understood and said no (4xx)
  SERVER: 'server', // server broke (5xx)
};

// --- The login token -------------------------------------------------

let authToken = null;

/** Set by the session code after sign-in or at launch; null signs out. */
export function setAuthToken(token) {
  authToken = token || null;
}

export function hasAuthToken() {
  return authToken !== null;
}

/**
 * Called whenever the server rejects our token. Set by the session code
 * so an expired login anywhere returns the player to the sign-in screen
 * instead of leaving buttons that silently do nothing.
 */
let onAuthFailure = () => {};
export function setAuthFailureHandler(fn) {
  onAuthFailure = typeof fn === 'function' ? fn : () => {};
}

// --- Requests --------------------------------------------------------

/** "/path?key=value&...", leaving out anything undefined or null. */
function withQuery(path, params) {
  const parts = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null)
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  return parts.length ? `${path}?${parts.join('&')}` : path;
}

/**
 * Every response is normalised to:
 *   { ok: true,  data }
 *   { ok: false, kind, message, status, data }
 *
 * `message` is always safe to show a person directly - the backend's own
 * wording when it sent one, otherwise something plain written here.
 */
async function request(
  path,
  { method = 'GET', body, auth = false, signal, timeoutMs = REQUEST_TIMEOUT_MS } = {},
) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  if (auth === 'optional') {
    // Signed in or not: the answer says more for someone signed in (which
    // leagues they can play in), and a stale login is no reason to fail.
    if (authToken) headers.Authorization = `Bearer ${authToken}`;
  } else if (auth) {
    if (!authToken) {
      onAuthFailure();
      return {
        ok: false,
        kind: ErrorKind.AUTH,
        status: 0,
        message: 'Your session ended. Please sign in again.',
      };
    }
    headers.Authorization = `Bearer ${authToken}`;
  }

  // Combine our timeout with any caller-supplied cancellation, so a
  // screen that closes and a slow server are both handled.
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  const forwardAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', forwardAbort);
  }

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch {
    // A caller-triggered abort isn't a failure worth reporting.
    if (signal?.aborted) {
      return { ok: false, kind: ErrorKind.NETWORK, status: 0, message: '', aborted: true };
    }
    return {
      ok: false,
      kind: ErrorKind.NETWORK,
      status: 0,
      message: controller.signal.aborted
        ? "The server didn't respond. It may be waking up - try again in a moment."
        : "Can't reach the server. Check your internet connection and try again.",
    };
  } finally {
    clearTimeout(timeoutId);
    signal?.removeEventListener?.('abort', forwardAbort);
  }

  // Not every response has a JSON body (204s, proxy error pages).
  let data = null;
  try {
    const text = await response.text();
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }

  if (response.ok) {
    return { ok: true, status: response.status, data };
  }

  // Only a signed-in call can have an expired session. A 401 from /login
  // just means the password was wrong, and must not read as "session ended".
  if (auth === true && (response.status === 401 || response.status === 422)) {
    // 422 is what flask-jwt-extended returns for a malformed token.
    onAuthFailure();
    return {
      ok: false,
      kind: ErrorKind.AUTH,
      status: response.status,
      message: 'Your session ended. Please sign in again.',
      data,
    };
  }

  const fallback =
    response.status >= 500
      ? 'The server hit an error. Try again in a moment.'
      : 'That request was rejected.';

  return {
    ok: false,
    kind: response.status >= 500 ? ErrorKind.SERVER : ErrorKind.REJECTED,
    status: response.status,
    message: readableMessage(data?.message, fallback),
    data,
  };
}

// --- Public data ---

/**
 * Every league - CCNY Billiards, John Jay Ping Pong and the rest - with its
 * colours, its tables and read_only (true unless the signed-in player can
 * play there): { leagues: [{league_id, name, school, game, primary_color,
 * secondary_color, has_pin, legacy_key, tables: [{table_id, table_name}],
 * read_only}] }.
 */
export const getLeagueDirectory = (signal) =>
  request('/leagues/directory', { auth: 'optional', signal });

/** One league, as in the directory: { league: {...} }. */
export const getLeague = (leagueId, signal) =>
  request(`/leagues/${leagueId}`, { auth: 'optional', signal });

/** Every table a league has in use, and who is at each: { tables: [table, ...] } */
export const getLeagueTables = (leagueId, signal) =>
  request(`/leagues/${leagueId}/tables`, { signal });

/**
 * A league's one queue, for all its tables: [{queue_position, user_id,
 * username, called, confirmed, table_id, table_name}] - table_* say which
 * table a player whose turn has come is called to.
 */
export const getLeagueQueue = (leagueId, signal) => request(`/leagues/${leagueId}/queue`, { signal });

/**
 * Enter a league's 4-digit PIN - once; it's remembered. { message, league }
 * on success. A refusal names data.field "pin": 403 wrong (data.tries_left),
 * 429 too many tries (data.retry_in seconds), 400 not 4 digits; 409 the
 * league has no PIN yet.
 */
export const unlockLeague = (leagueId, pin) =>
  request('/league/unlock', { method: 'POST', auth: true, body: { league_id: leagueId, pin } });

/**
 * The champions across every school - the top 3 in each game this week,
 * this month and of all time, in any league: { timezone, sports: {
 * billiards: { week, month, all_time }, ping_pong: {...} } }, each a list
 * of { place, player: card, league_id, league_name, school, wins, losses,
 * points (week, month) | elo (all time) }.
 */
export const getGlobalLeaderboard = (signal) => request('/leaderboard/global', { signal });

export const getLeaderboard = (leagueId, signal) =>
  request(withQuery('/leaderboard', { league_id: leagueId }), { signal });

/** Who is at a table right now, as player cards: { table: {state, king, challenger, ...} } */
export const getTable = (tableId, signal) => request(`/table/${tableId}`, { signal });

/** The latest finished games in a league: { league_id, matches: [...] } */
export const getMatchHistory = (leagueId, { limit } = {}, signal) =>
  request(withQuery('/matches/history', { league_id: leagueId, limit }), { signal });

/**
 * One player's finished games in a league, each with result "won" or
 * "lost" from their side. opponentId narrows it to the games between the
 * two of them - head to head.
 */
export const getPlayerMatches = (userId, leagueId, { limit, opponentId } = {}, signal) =>
  request(
    withQuery(`/players/${userId}/matches`, {
      league_id: leagueId,
      limit,
      opponent_id: opponentId,
    }),
    { signal },
  );

/**
 * Another player's profile as anyone may see it - picture, flag and their
 * standing in every league they're in, never their name: { player: {...} }.
 * 404 for an unknown or deleted account.
 */
export const getPlayer = (userId, signal) => request(`/players/${userId}`, { signal });

/**
 * A player's record against everyone they've played in a league, most
 * games first: { opponents: [{ opponent: card, wins, losses }] }.
 */
export const getPlayerOpponents = (userId, leagueId, signal) =>
  request(withQuery(`/players/${userId}/opponents`, { league_id: leagueId }), { signal });

/**
 * The players of the day, week and month in a league - who gained the
 * most points in each: { league_id, timezone, day, week, month }, each
 * period { player: card, points, wins, losses } or null when nobody has
 * won a game in it yet. (The web app's status panel shows them.)
 */
export const getTopPlayers = (leagueId, signal) =>
  request(withQuery('/top-players', { league_id: leagueId }), { signal });

/** Country codes and names for the flag picker: { countries: [{code, name}] } */
export const getCountries = (signal) => request('/countries', { signal });

// --- Auth ---

/**
 * username may also be the account's email. The answer's email is null
 * for an account made before sign-up asked for one - ask them to add it.
 */
export const login = (username, password) =>
  request('/login', { method: 'POST', body: { username, password } });

/** payload: { username, first_name, last_name, email, password }. A refusal names data.field. */
export const register = (payload) => request('/register', { method: 'POST', body: payload });

/**
 * Forgot your password, step 1: email a 6-digit code to the account with
 * this email. Answers the same whether or not one exists. 503 when email
 * isn't set up on the server (the message says to ask the organiser).
 */
export const forgotPassword = (email) =>
  request('/password/forgot', { method: 'POST', body: { email } });

/**
 * Step 2: the code and a new password. Success answers like login (a
 * token) - the player is signed in. A refusal names data.field: "code"
 * or "password".
 */
export const resetPassword = (email, code, password) =>
  request('/password/reset', { method: 'POST', body: { email, code, password } });

// --- Profile ---

/** The signed-in player's profile, with their standing in every league they're in. */
export const getProfile = (signal) => request('/profile', { auth: true, signal });

/**
 * changes: { country_flag?, profile_picture? } - null or '' clears one.
 * A refusal carries data.field, naming the field the message is about.
 */
export const updateProfile = (changes) =>
  request('/profile', { method: 'PATCH', auth: true, body: changes });

/**
 * Add or change the account's email: { message, profile }. Changing one
 * that's already set needs the password (a wrong one is 403 with field
 * "password", never 401); adding the first doesn't.
 */
export const setEmail = (email, password) =>
  request('/profile/email', { method: 'POST', auth: true, body: { email, password } });

/**
 * Upload a photo as the profile picture: image is base64, or a data: URL.
 * The server crops it square, shrinks it and strips its metadata, and
 * returns { message, profile }. A refusal carries data.field
 * "profile_picture". Removing it is updateProfile({ profile_picture: null }).
 */
export const uploadProfilePicture = (image) =>
  request('/profile/picture', {
    method: 'POST',
    auth: true,
    body: { image },
    timeoutMs: UPLOAD_TIMEOUT_MS,
  });

// --- Match / queue actions ---
// A league's queue is one line for all its tables: these take the league.
// Without the league's PIN, joining and saying "I'm here" are refused with
// 403 and data.read_only.

/** Your status in a league (or your game wherever it is), plus read_only. */
export const getMatchStatus = (leagueId, signal) =>
  request(withQuery('/match/status', { league_id: leagueId }), { auth: true, signal });

/**
 * Join a league's queue, waiting for tableId - or, null, for whichever of
 * its tables frees up first. Already waiting, it changes where they'll
 * play and they keep their place: { status: "switched" }. 409 when their
 * turn has already come at another table; 400 (field "table_id") for a
 * table no longer in use.
 */
export const joinQueue = (leagueId, tableId = null) =>
  request('/queue/join', {
    method: 'POST',
    auth: true,
    body: tableId ? { league_id: leagueId, table_id: tableId } : { league_id: leagueId },
  });

export const leaveQueue = (leagueId) =>
  request('/queue/leave', { method: 'POST', auth: true, body: { league_id: leagueId } });

/**
 * "I'm here" - the ready check. When the status is "your_turn", the player
 * has a minute to send this or they're taken out of the queue. Returns
 * { message, status: "confirmed" | "already_confirmed", match_started }.
 * 409 before their turn or once the minute is up; 404 not in the queue.
 */
export const confirmHere = (leagueId) =>
  request('/queue/confirm', { method: 'POST', auth: true, body: { league_id: leagueId } });

/**
 * Ask to call off the game in progress - or, when the opponent has asked
 * already, agree, which cancels it with nothing recorded. Returns
 * { message, status: "requested" | "already_requested" | "cancelled" }.
 * matchId is the game the player saw: 409 if it has finished meanwhile.
 */
export const cancelMatch = (matchId) =>
  request('/match/cancel', { method: 'POST', auth: true, body: { match_id: matchId } });

/** Take back a request to cancel, or turn down the opponent's: the game goes on. */
export const keepPlaying = (matchId) =>
  request('/match/keep', { method: 'POST', auth: true, body: { match_id: matchId } });

/**
 * matchId is the game the player saw when they filled in the score; the
 * server refuses (409) a report for a game already recorded. leagueId is
 * that game's league (the status payload's league_id). Scores are in the
 * game's own units: balls sunk, or points in ping pong. 403 with
 * data.read_only when the league's PIN has changed since.
 */
export const recordMatch = (myScore, oppScore, matchId, leagueId) =>
  request('/match/record', {
    method: 'POST',
    auth: true,
    body: {
      my_balls: Number(myScore),
      opp_balls: Number(oppScore),
      match_id: matchId,
      league_id: leagueId,
    },
  });

/**
 * Delete the signed-in player's account, confirming with their password.
 * A wrong password is a 403 with data.field "password" - not a 401,
 * which would read as "session ended".
 */
export const deleteAccount = (password) =>
  request('/profile/delete', { method: 'POST', auth: true, body: { password } });

/** The privacy policy web page, which the app stores ask to be linked. */
export const PRIVACY_POLICY_URL = `${API_BASE}/privacy`;

/** A king with no challenger gives up the table. */
export const stepDown = () => request('/table/step-down', { method: 'POST', auth: true, body: {} });

/**
 * Vote that the king at a table isn't here - or, remove false, take the
 * vote back. matchId is the king's game as the player saw it (409 if the
 * table has changed hands). Everyone waiting who could play there has to
 * vote; then the king has a minute to say they're here. Returns
 * { message, status, removal_vote }; 403 when the player isn't waiting
 * for that table, 409 on themselves.
 */
export const voteOnKing = (tableId, matchId, remove = true) =>
  request('/table/vote', {
    method: 'POST',
    auth: true,
    body: { table_id: tableId, match_id: matchId, remove },
  });

/** The king says they're here: every vote that they aren't is cleared. */
export const kingIsHere = () => request('/table/here', { method: 'POST', auth: true, body: {} });

// --- The organiser's controls ---
// Only for an account whose profile (or sign-in) says is_admin; the
// server refuses anyone else (403) whatever the app shows.

/**
 * Take a player out of a table's queue: { message, status: "removed" }.
 * 404 when they aren't in it any more.
 */
export const adminRemoveFromQueue = (userId, leagueId) =>
  request('/admin/queue/remove', {
    method: 'POST',
    auth: true,
    body: { user_id: userId, league_id: leagueId },
  });

/**
 * Take a player off a table: { message, status: "table_freed" |
 * "game_called_off" }. A game in progress is called off with nothing
 * recorded, and the other player keeps the table. matchId is the game the
 * organiser saw there: 409 if it has changed since, 404 if the player
 * isn't at the table any more.
 */
export const adminRemoveFromTable = (userId, tableId, matchId) =>
  request('/admin/table/remove', {
    method: 'POST',
    auth: true,
    body: { user_id: userId, table_id: tableId, match_id: matchId },
  });

/**
 * Give a league a new 4-digit PIN: { message, revoked, league }. Everyone
 * who entered the old one has to enter the new one. 400 (field "pin") for
 * anything but 4 digits.
 */
export const adminSetLeaguePin = (leagueId, pin) =>
  request(`/admin/leagues/${leagueId}/pin`, { method: 'POST', auth: true, body: { pin } });

/** Add a table to a league: 201 { message, table }. 400 (field "name") for a bad or taken name. */
export const adminAddTable = (leagueId, name) =>
  request(`/admin/leagues/${leagueId}/tables`, { method: 'POST', auth: true, body: { name } });

/** Rename a table: { message, table }. 400 (field "name") for a bad or taken name. */
export const adminRenameTable = (tableId, name) =>
  request(`/admin/tables/${tableId}`, { method: 'PATCH', auth: true, body: { name } });

/** Stop using a table; its games stay in the history. 409 while anyone is at it. */
export const adminRemoveTable = (tableId) =>
  request(`/admin/tables/${tableId}`, { method: 'DELETE', auth: true });

export { API_BASE };
