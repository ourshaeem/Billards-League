/**
 * Login and registration.
 *
 * Validation happens per field and appears next to the field it concerns.
 * The previous version used alert() for every outcome, which meant a
 * typo in one box produced a modal that named none of them.
 */
import React, { useState } from 'react';
import { FieldError } from './Feedback.jsx';

// Mirrors the rules the backend enforces, so people find out before the
// round trip. The server still checks - this is convenience, not trust.
const MIN_USERNAME = 3;
const MIN_PASSWORD = 6;
// The database columns' limits. Past these the server refuses too, but
// saying so here puts the message beside the field that's too long.
const MAX_USERNAME = 50;
const MAX_NAME = 50;
const MAX_PASSWORD = 72;

export function LoginScreen({ onLogin, onSwitch, busy }) {
  const [values, setValues] = useState({ username: '', password: '' });
  const [errors, setErrors] = useState({});

  const update = (field) => (e) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev));
  };

  const submit = (e) => {
    e.preventDefault();
    const next = {};
    if (!values.username.trim()) next.username = 'Enter your username.';
    if (!values.password) next.password = 'Enter your password.';

    setErrors(next);
    if (Object.keys(next).length) return;

    onLogin(values.username.trim(), values.password);
  };

  return (
    <div className="auth-shell">
      <div className="card">
        <h2 className="card-title" style={{ marginBottom: 6 }}>
          Sign in
        </h2>
        <p className="muted small" style={{ marginBottom: 20 }}>
          Sign in to join the queue and report your scores.
        </p>

        <form onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="login-username">Username</label>
            <input
              id="login-username"
              type="text"
              autoComplete="username"
              value={values.username}
              onChange={update('username')}
              aria-invalid={Boolean(errors.username)}
              aria-describedby={errors.username ? 'login-username-error' : undefined}
            />
            <FieldError id="login-username-error" message={errors.username} />
          </div>

          <div className="field">
            <label htmlFor="login-password">Password</label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              value={values.password}
              onChange={update('password')}
              aria-invalid={Boolean(errors.password)}
              aria-describedby={errors.password ? 'login-password-error' : undefined}
            />
            <FieldError id="login-password-error" message={errors.password} />
          </div>

          <button type="submit" className="btn btn-primary" style={{ width: '100%' }} disabled={busy}>
            {busy ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <p className="small" style={{ marginTop: 18, textAlign: 'center' }}>
          <span className="muted">New to the league? </span>
          <button type="button" className="btn-link" onClick={onSwitch}>
            Create an account
          </button>
        </p>
      </div>
    </div>
  );
}

export function RegisterScreen({ onRegister, onSwitch, busy }) {
  const [values, setValues] = useState({
    first_name: '',
    last_name: '',
    username: '',
    password: '',
  });
  const [errors, setErrors] = useState({});

  const update = (field) => (e) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev));
  };

  const submit = (e) => {
    e.preventDefault();
    const next = {};

    if (!values.first_name.trim()) next.first_name = 'Enter your first name.';
    else if (values.first_name.trim().length > MAX_NAME) {
      next.first_name = `Names can be at most ${MAX_NAME} characters.`;
    }
    if (!values.last_name.trim()) next.last_name = 'Enter your last name.';
    else if (values.last_name.trim().length > MAX_NAME) {
      next.last_name = `Names can be at most ${MAX_NAME} characters.`;
    }

    if (!values.username.trim()) {
      next.username = 'Pick a username.';
    } else if (values.username.trim().length < MIN_USERNAME) {
      next.username = `Usernames need at least ${MIN_USERNAME} characters.`;
    } else if (values.username.trim().length > MAX_USERNAME) {
      next.username = `Usernames can be at most ${MAX_USERNAME} characters.`;
    }

    if (!values.password) {
      next.password = 'Pick a password.';
    } else if (values.password.length < MIN_PASSWORD) {
      next.password = `Passwords need at least ${MIN_PASSWORD} characters.`;
    } else if (new TextEncoder().encode(values.password).length > MAX_PASSWORD) {
      next.password = `Passwords can be at most ${MAX_PASSWORD} characters.`;
    }

    setErrors(next);
    if (Object.keys(next).length) return;

    onRegister({
      first_name: values.first_name.trim(),
      last_name: values.last_name.trim(),
      username: values.username.trim(),
      password: values.password,
    });
  };

  return (
    <div className="auth-shell">
      <div className="card">
        <h2 className="card-title" style={{ marginBottom: 6 }}>
          Create an account
        </h2>
        <p className="muted small" style={{ marginBottom: 20 }}>
          Everyone starts at 0 points. Win games to climb the ladder.
        </p>

        <form onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="reg-first">First name</label>
            <input
              id="reg-first"
              type="text"
              autoComplete="given-name"
              value={values.first_name}
              onChange={update('first_name')}
              aria-invalid={Boolean(errors.first_name)}
            />
            <FieldError message={errors.first_name} />
          </div>

          <div className="field">
            <label htmlFor="reg-last">Last name</label>
            <input
              id="reg-last"
              type="text"
              autoComplete="family-name"
              value={values.last_name}
              onChange={update('last_name')}
              aria-invalid={Boolean(errors.last_name)}
            />
            <FieldError message={errors.last_name} />
          </div>

          <div className="field">
            <label htmlFor="reg-username">Username</label>
            <input
              id="reg-username"
              type="text"
              autoComplete="username"
              value={values.username}
              onChange={update('username')}
              aria-invalid={Boolean(errors.username)}
            />
            <FieldError message={errors.username} />
          </div>

          <div className="field">
            <label htmlFor="reg-password">Password</label>
            <input
              id="reg-password"
              type="password"
              autoComplete="new-password"
              value={values.password}
              onChange={update('password')}
              aria-invalid={Boolean(errors.password)}
            />
            <FieldError message={errors.password} />
          </div>

          <button type="submit" className="btn btn-primary" style={{ width: '100%' }} disabled={busy}>
            {busy ? 'Creating account...' : 'Create account'}
          </button>
        </form>

        <p className="small" style={{ marginTop: 18, textAlign: 'center' }}>
          <span className="muted">Already playing? </span>
          <button type="button" className="btn-link" onClick={onSwitch}>
            Sign in
          </button>
        </p>
      </div>
    </div>
  );
}
