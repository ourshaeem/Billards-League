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
  } catch {
    /* nothing useful to do */
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

// --- Public data ---

export const getLeaderboard = (signal) => request('/leaderboard', { signal });

export const getQueue = (tableId = 1, signal) => request(`/queue/${tableId}`, { signal });

export const checkHealth = (signal) => request('/health', { signal });

// --- Auth ---

export const login = (username, password) =>
  request('/login', { method: 'POST', body: { username, password } });

export const register = (payload) =>
  request('/register', { method: 'POST', body: payload });

// --- Match / queue actions ---

export const getMatchStatus = (tableId = 1, signal) =>
  request(`/match/status?table_id=${tableId}`, { auth: true, signal });

export const joinQueue = (tableId = 1) =>
  request('/queue/join', { method: 'POST', auth: true, body: { table_id: tableId } });

export const leaveQueue = (tableId = 1) =>
  request('/queue/leave', { method: 'POST', auth: true, body: { table_id: tableId } });

/**
 * matchId is the game the player saw when they filled in the score. The
 * server refuses the report (409) if that game was already recorded -
 * otherwise a late second report would land on the player's next game.
 */
export const recordMatch = (myBalls, oppBalls, matchId) =>
  request('/match/record', {
    method: 'POST',
    auth: true,
    body: { my_balls: Number(myBalls), opp_balls: Number(oppBalls), match_id: matchId },
  });

/** A king with no challenger gives up the table. */
export const stepDown = (tableId = 1) =>
  request('/table/step-down', { method: 'POST', auth: true, body: { table_id: tableId } });

export { API_BASE };
