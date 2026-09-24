/**
 * A flag emoji from an ISO country code ("CA"): each letter maps to a
 * "regional indicator" character, and a pair of those is drawn as the
 * flag. Windows shows the two letters instead of a flag, which is still
 * readable. The backend stores and checks the code; drawing it is ours.
 */
export function flagEmoji(code) {
  if (typeof code !== 'string' || !/^[A-Z]{2}$/.test(code)) return '';
  return String.fromCodePoint(...[...code].map((letter) => 0x1f1e6 + letter.charCodeAt(0) - 65));
}
