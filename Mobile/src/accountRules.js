/**
 * The account rules the server enforces, checked here too so people see
 * a problem beside the field before the round trip - the mobile twin of
 * Frontend/src/accountRules.js. The server still checks everything.
 */
export const MIN_USERNAME = 3;
export const MIN_PASSWORD = 6;
// The database columns' limits.
export const MAX_USERNAME = 50;
export const MAX_NAME = 50;
export const MAX_EMAIL = 254;
// bcrypt reads at most 72 bytes of a password, and the server refuses more.
export const MAX_PASSWORD_BYTES = 72;
// As loose as the server's: something@something.something, no spaces.
const EMAIL_SHAPE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** A string's length in UTF-8 bytes - what the server's limit counts. */
export function utf8Length(text) {
  let bytes = 0;
  for (const char of text) {
    const code = char.codePointAt(0);
    bytes += code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
  }
  return bytes;
}

/** Why an email can't be used, or null. */
export function emailProblem(email) {
  const value = (email || '').trim();
  if (!value) return 'Enter your email address.';
  if (value.length > MAX_EMAIL) return `Email addresses can be at most ${MAX_EMAIL} characters.`;
  if (!EMAIL_SHAPE.test(value)) return "That doesn't look like an email address.";
  return null;
}

/** Why a new password can't be used, or null. */
export function passwordProblem(password) {
  if (!password) return 'Pick a password.';
  if (password.length < MIN_PASSWORD) return `Passwords need at least ${MIN_PASSWORD} characters.`;
  if (utf8Length(password) > MAX_PASSWORD_BYTES) {
    return `Passwords can be at most ${MAX_PASSWORD_BYTES} characters.`;
  }
  return null;
}
