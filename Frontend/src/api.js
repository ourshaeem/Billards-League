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
const API_BASE =
  import.meta.env.VITE_API_BASE || 'http://localhost:5000';

// Give up on a request after this long. Without it a dropped connection
// leaves buttons spinning forever with no explanation.
const REQUEST_TIMEOUT_MS = 10000;

export const TOKEN_KEY = 'token';
// Which league the player chose for this session. Kept beside the token so
// a refresh returns them to the same league, and cleared with it at sign-out.
const LEAGUE_KEY = 'league';

// A message longer than this, or one that looks like the inside of the
// server, is swapped for a plain sentence. The backend no longer sends
// such things - this is the second lock on the door, because the one time
// it did, a SQL statement filled the screen in a box nobody could close.
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
  NETWORK: 'network',   // server unreachable / offline / timed out
  AUTH: 'auth',         // token missing, expired or rejected
  REJECTED: 'rejected', // server understood and said no (4xx)
  SERVER: 'server',     // server broke (5xx)
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

/** Pass null to forget the choice, so the next sign-in asks again. */
export function setStoredLeague(league) {
  try {
    if (league) localStorage.setItem(LEAGUE_KEY, league);
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
async function request(path, { method = 'GET', body, auth = false, signal } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  if (auth) {
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
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
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
  if (auth && (response.status === 401 || response.status === 422)) {
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

/** Each league and the table it plays on: { leagues: [{league_type, name, table_id, table_name}] } */
export const getLeagues = (signal) => request('/leagues', { signal });

export const getLeaderboard = (league, signal) =>
  request(withQuery('/leaderboard', { league_type: league }), { signal });

export const getQueue = (tableId = 1, signal) => request(`/queue/${tableId}`, { signal });

/** Who is at a table right now, as player cards: { table: {state, king, challenger, ...} } */
export const getTable = (tableId, signal) => request(`/table/${tableId}`, { signal });

/** The latest finished games in a league: { league_type, matches: [...] } */
export const getMatchHistory = (league, { limit } = {}, signal) =>
  request(withQuery('/matches/history', { league_type: league, limit }), { signal });

/** One player's finished games in a league, each with result "won" or "lost". */
export const getPlayerMatches = (userId, league, { limit } = {}, signal) =>
  request(withQuery(`/players/${userId}/matches`, { league_type: league, limit }), { signal });

/** Country codes and names for the flag picker: { countries: [{code, name}] } */
export const getCountries = (signal) => request('/countries', { signal });

export const checkHealth = (signal) => request('/health', { signal });

// --- Auth ---

export const login = (username, password) =>
  request('/login', { method: 'POST', body: { username, password } });

export const register = (payload) =>
  request('/register', { method: 'POST', body: payload });

// --- Profile ---

/** The signed-in player's profile, with their standing in both leagues. */
export const getProfile = (signal) => request('/profile', { auth: true, signal });

/**
 * changes: { country_flag?, profile_picture? } - null or '' clears one.
 * A refusal carries data.field, naming the field the message is about.
 */
export const updateProfile = (changes) =>
  request('/profile', { method: 'PATCH', auth: true, body: changes });

// --- Match / queue actions ---
// tableId says which table; league is sent alongside so the server can
// refuse a request whose table and league disagree.

export const getMatchStatus = (tableId = 1, signal) =>
  request(`/match/status?table_id=${tableId}`, { auth: true, signal });

export const joinQueue = (tableId = 1, league) =>
  request('/queue/join', {
    method: 'POST',
    auth: true,
    body: { table_id: tableId, league_type: league },
  });

export const leaveQueue = (tableId = 1, league) =>
  request('/queue/leave', {
    method: 'POST',
    auth: true,
    body: { table_id: tableId, league_type: league },
  });

/**
 * matchId is the game the player saw when they filled in the score. The
 * server refuses the report (409) if that game was already recorded -
 * otherwise a late second report would land on the player's next game.
 *
 * league is the league of that game (the status payload's league_type).
 * Scores are in the game's own units: balls sunk, or points in ping pong.
 */
export const recordMatch = (myScore, oppScore, matchId, league) =>
  request('/match/record', {
    method: 'POST',
    auth: true,
    body: {
      my_balls: Number(myScore),
      opp_balls: Number(oppScore),
      match_id: matchId,
      league_type: league,
    },
  });

/** A king with no challenger gives up the table. */
export const stepDown = (tableId = 1) =>
  request('/table/step-down', { method: 'POST', auth: true, body: { table_id: tableId } });

export { API_BASE };
