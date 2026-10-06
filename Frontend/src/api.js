/**
 * All backend communication lives here.
 *
 * Two reasons it's a separate module rather than fetch() calls sprinkled
 * through the components:
 *
 * 1. Errors get handled once, consistently. Every call returns the same
 *    shape, so a component never has to guess whether a failure was a
 *    network drop, an expired login, or a real rejection from the server.
 *
 * 2. This is the only file that knows about HTTP. When the React Native
 *    version happens, this module and the API_BASE below are what change;
 *    the screens can be rebuilt without re-deriving how the API behaves.
 */

// Vite exposes env vars prefixed with VITE_. Set VITE_API_BASE in a
// Frontend/.env file to point at a different backend (a phone on the same
// wifi can't reach "localhost" - it needs the computer's LAN IP).
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5000';

// Give up on a request after this long. Without it a dropped connection
// leaves buttons spinning forever with no explanation.
const REQUEST_TIMEOUT_MS = 10000;
// A photo is a much bigger request than anything else, and a slow
// upstream connection needs longer to send it.
const UPLOAD_TIMEOUT_MS = 45000;

export const TOKEN_KEY = 'token';
// Which league the player chose for this session. Kept beside the token so
// a refresh returns them to the same league, and cleared with it at sign-out.
const LEAGUE_KEY = 'league';

// A message longer than this, or one that looks like the inside of the
// server, is swapped for a plain sentence. The backend no longer sends
// such things - this is the second lock on the door, because the one time
// it did, a SQL statement filled the screen in a box nobody could close.
const MAX_MESSAGE_LENGTH = 240;
const TECHNICAL_MESSAGE =
  /traceback|sqlalche|\bsql\b|select\s.+\sfrom\s|mysql|exception|errno|stack/i;

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

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    // Private browsing modes can throw on storage access.
    return null;
  }
}

export function setSession({ token, userId, username }) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem('user_id', userId);
    localStorage.setItem('username', username);
  } catch {
    // Not fatal - the session just won't survive a refresh.
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem('user_id');
    localStorage.removeItem('username');
    localStorage.removeItem(LEAGUE_KEY);
  } catch {
    /* nothing useful to do */
  }
}

export function getStoredLeague() {
  try {
    return localStorage.getItem(LEAGUE_KEY);
  } catch {
    return null;
  }
}

/**
 * The league this device last played in: its league_id (as a string), or
 * - saved by the app before there were schools - "billiards" or
 * "ping_pong", which mean CCNY's (league.legacy_key). Pass null to forget
 * the choice, so the next sign-in asks again.
 */
export function setStoredLeague(league) {
  try {
    if (league) localStorage.setItem(LEAGUE_KEY, String(league));
    else localStorage.removeItem(LEAGUE_KEY);
  } catch {
    // Not fatal - the choice just won't survive a refresh.
  }
}

export function getStoredUser() {
  try {
    const username = localStorage.getItem('username');
    const userId = localStorage.getItem('user_id');
    if (!getToken() || !username) return null;
    return { username, user_id: Number(userId) };
  } catch {
    return null;
  }
}

/**
 * Called whenever the server rejects our token. Set by App so that an
 * expired login anywhere drops the user back to the login screen instead
 * of leaving them clicking buttons that silently do nothing.
 */
let onAuthFailure = () => {};
export function setAuthFailureHandler(fn) {
  onAuthFailure = typeof fn === 'function' ? fn : () => {};
}

/**
 * Every response is normalised to:
 *   { ok: true,  data }
 *   { ok: false, kind, message, status, data }
 *
 * `message` is always safe to show a person directly - the backend's own
 * wording when it sent one, otherwise something plain written here. No
 * caller ever has to render "[object Object]" or a raw stack trace.
 */
async function request(
  path,
  { method = 'GET', body, auth = false, signal, timeoutMs = REQUEST_TIMEOUT_MS } = {},
) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  if (auth === 'optional') {
    // Signed in or not: the answer says more for someone signed in (which
    // leagues they can play in), and a stale login is no reason to fail.
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  } else if (auth) {
    const token = getToken();
    if (!token) {
      onAuthFailure();
      return {
        ok: false,
        kind: ErrorKind.AUTH,
        status: 0,
        message: 'Your session ended. Please log in again.',
      };
    }
    headers.Authorization = `Bearer ${token}`;
  }

  // Combine our timeout with any caller-supplied cancellation, so an
  // unmounting component and a slow server are both handled.
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  if (signal) signal.addEventListener('abort', () => controller.abort());

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timeoutId);
    // A caller-triggered abort isn't a failure worth reporting.
    if (signal?.aborted) {
      return { ok: false, kind: ErrorKind.NETWORK, status: 0, message: '', aborted: true };
    }
    return {
      ok: false,
      kind: ErrorKind.NETWORK,
      status: 0,
      message:
        err.name === 'AbortError'
          ? "The server didn't respond. It may be starting up - try again in a moment."
          : "Can't reach the server. Check it's running, then try again.",
    };
  }
  clearTimeout(timeoutId);

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
    clearSession();
    onAuthFailure();
    return {
      ok: false,
      kind: ErrorKind.AUTH,
      status: response.status,
      message: 'Your session ended. Please log in again.',
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

/** A path with a query string, leaving out anything undefined or null. */
function withQuery(path, params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) query.set(key, String(value));
  });
  const text = query.toString();
  return text ? `${path}?${text}` : path;
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
 * won a game in it yet.
 */
export const getTopPlayers = (leagueId, signal) =>
  request(withQuery('/top-players', { league_id: leagueId }), { signal });

// --- Badges ---

/** One player's badges in a league, earned or not: { badges, featured, chosen, ... } */
export const getPlayerBadges = (userId, leagueId, signal) =>
  request(withQuery(`/players/${userId}/badges`, { league_id: leagueId }), { signal });

/** Badges earned in any league since the screen last announced any. */
export const getNewBadges = (signal) => request('/me/badges/new', { auth: true, signal });

export const markBadgesSeen = (ids) =>
  request('/me/badges/seen', { method: 'POST', auth: true, body: { ids } });

/** Choose the badge a league shows by your name; null picks automatically. */
export const setFeaturedBadge = (leagueId, key) =>
  request('/me/featured-badge', { method: 'POST', auth: true, body: { league_id: leagueId, key } });

/** Country codes and names for the flag picker: { countries: [{code, name}] } */
export const getCountries = (signal) => request('/countries', { signal });

export const checkHealth = (signal) => request('/health', { signal });

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

/** The signed-in player's profile, with their standing in both leagues. */
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

export const joinQueue = (leagueId) =>
  request('/queue/join', { method: 'POST', auth: true, body: { league_id: leagueId } });

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
 * matchId is the game the player saw when they filled in the score. The
 * server refuses the report (409) if that game was already recorded -
 * otherwise a late second report would land on the player's next game.
 *
 * leagueId is the league of that game (the status payload's league_id).
 * Scores are in the game's own units: balls sunk, or points in ping pong.
 * 403 with data.read_only when the league's PIN has changed since.
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

// --- The organiser's controls ---
// Only for an account whose profile says is_admin; the server refuses
// anyone else (403) whatever the app shows.

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
