/**
 * What the app remembers between launches: the login token, whose it is,
 * and which league they chose for the session.
 *
 * On a phone this lives in Expo SecureStore - the iOS Keychain, or
 * storage encrypted with the Android Keystore - so no other app can read
 * the token. This replaces the web app's localStorage, which any script
 * on the page can read.
 *
 * The web build (a quick preview in a browser, not what ships to phones)
 * has no SecureStore, so there, and only there, it uses localStorage.
 */
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

// SecureStore keys may only use letters, digits, ".", "-" and "_".
const KEYS = {
  token: 'league.token',
  user: 'league.user',
  league: 'league.league',
};

const onWeb = Platform.OS === 'web';

async function read(key) {
  try {
    if (onWeb) return globalThis.localStorage?.getItem(key) ?? null;
    return await SecureStore.getItemAsync(key);
  } catch {
    // A keychain that can't be read - restored onto a new phone, say -
    // means signing in again, not a crash.
    return null;
  }
}

async function write(key, value) {
  try {
    if (onWeb) {
      if (value == null) globalThis.localStorage?.removeItem(key);
      else globalThis.localStorage?.setItem(key, value);
      return;
    }
    if (value == null) await SecureStore.deleteItemAsync(key);
    else await SecureStore.setItemAsync(key, value);
  } catch {
    // Not fatal: the session just won't survive the app being closed.
  }
}

/** The saved session - { token, user: {user_id, username}, league } - or null. */
export async function loadSession() {
  const [token, userJson, league] = await Promise.all([
    read(KEYS.token),
    read(KEYS.user),
    read(KEYS.league),
  ]);
  if (!token || !userJson) return null;
  try {
    const user = JSON.parse(userJson);
    return user?.username ? { token, user, league } : null;
  } catch {
    return null;
  }
}

/** A fresh sign-in. The league is forgotten: every sign-in chooses again. */
export async function saveSession({ token, user }) {
  await Promise.all([
    write(KEYS.token, token),
    write(KEYS.user, JSON.stringify(user)),
    write(KEYS.league, null),
  ]);
}

export function saveLeague(league) {
  return write(KEYS.league, league);
}

export async function clearSession() {
  await Promise.all(Object.values(KEYS).map((key) => write(key, null)));
}
