/**
 * Where the app finds its backend, and how often it asks.
 *
 * The live Render server by default. To point a development build at a
 * different backend, set EXPO_PUBLIC_API_BASE in Mobile/.env - for
 * example a backend running on your computer:
 *   - from a phone on the same wifi:  http://192.168.1.50:5000
 *     (your computer's LAN address; "localhost" on a phone is the phone)
 *   - from the Android emulator:      http://10.0.2.2:5000
 * Expo builds the value into the app and caches the result, so after
 * changing it start with a cleared cache - `npx expo start --clear` -
 * or the app keeps the old address.
 */
export const API_BASE = (
  process.env.EXPO_PUBLIC_API_BASE || 'https://billards-league.onrender.com'
).replace(/\/+$/, '');

// Give up on a request after this long. Longer than the web app's 10s:
// phone networks are slower, and the free Render plan takes up to a
// minute to wake after a quiet spell.
export const REQUEST_TIMEOUT_MS = 20000;
// A photo is a much bigger request than anything else, and a phone's
// upload speed is often a fraction of its download speed.
export const UPLOAD_TIMEOUT_MS = 60000;

// Your status, the queue and the table: often, so a match starting is
// noticed within a couple of seconds.
export const POLL_INTERVAL_MS = 2500;
// Recent games and the ladder only change when a game ends, and are
// also refreshed straight away when one does.
export const SLOW_POLL_INTERVAL_MS = 15000;
export const LEAGUES_RETRY_MS = 5000;
export const HISTORY_LIMIT = 20;
