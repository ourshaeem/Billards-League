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
import { API_BASE, REQUEST_TIMEOUT_MS } from './config';

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
async function request(path, { method = 'GET', body, auth = false, signal } = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  if (auth) {
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
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
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
  if (auth && (response.status === 401 || response.status === 422)) {
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

/** Each league and the table it plays on: { leagues: [{league_type, name, table_id, table_name}] } */
export const getLeagues = (signal) => request('/leagues', { signal });

export const getLeaderboard = (league, signal) =>
  request(withQuery('/leaderboard', { league_type: league }), { signal });

export const getQueue = (tableId, signal) => request(`/queue/${tableId}`, { signal });

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

// --- Auth ---

export const login = (username, password) =>
  request('/login', { method: 'POST', body: { username, password } });

export const register = (payload) => request('/register', { method: 'POST', body: payload });

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

export const getMatchStatus = (tableId, signal) =>
  request(withQuery('/match/status', { table_id: tableId }), { auth: true, signal });

export const joinQueue = (tableId, league) =>
  request('/queue/join', {
    method: 'POST',
    auth: true,
    body: { table_id: tableId, league_type: league },
  });

export const leaveQueue = (tableId, league) =>
  request('/queue/leave', {
    method: 'POST',
    auth: true,
    body: { table_id: tableId, league_type: league },
  });

/**
 * matchId is the game the player saw when they filled in the score; the
 * server refuses (409) a report for a game already recorded. league is
 * that game's league (the status payload's league_type). Scores are in
 * the game's own units: balls sunk, or points in ping pong.
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
export const stepDown = (tableId) =>
  request('/table/step-down', { method: 'POST', auth: true, body: { table_id: tableId } });

export { API_BASE };
