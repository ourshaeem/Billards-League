/**
 * The account rules the server enforces, checked here too so people see
 * a problem beside the field before the round trip. The server still
 * checks everything - this is convenience, not trust.
 */
export const MIN_USERNAME = 3;
export const MIN_PASSWORD = 6;
// The database columns' limits.
export const MAX_USERNAME = 50;
export const MAX_NAME = 50;
export const MAX_PASSWORD = 72;
export const MAX_EMAIL = 254;
// As loose as the server's: something@something.something, no spaces.
const EMAIL_SHAPE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

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
  if (new TextEncoder().encode(password).length > MAX_PASSWORD) {
    return `Passwords can be at most ${MAX_PASSWORD} characters.`;
  }
  return null;
}
