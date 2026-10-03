/**
 * Signing in, signing up, resetting a forgotten password, and the one
 * step an account from before sign-up asked for an email still needs:
 * adding one.
 *
 * Validation happens per field and appears next to the field it concerns
 * - including the server's refusals, which name their field. The previous
 * version used alert() for every outcome, which meant a typo in one box
 * produced a modal that named none of them.
 */
import React, { useState } from 'react';

import {
  MAX_NAME,
  MAX_USERNAME,
  MIN_USERNAME,
  emailProblem,
  passwordProblem,
} from '../accountRules.js';
import { FieldError } from './Feedback.jsx';

export function LoginScreen({ onLogin, onSwitch, onForgot, busy }) {
  const [values, setValues] = useState({ username: '', password: '' });
  const [errors, setErrors] = useState({});

  const update = (field) => (e) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev));
  };

  const submit = (e) => {
    e.preventDefault();
    const next = {};
    if (!values.username.trim()) next.username = 'Enter your username or email.';
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
            <label htmlFor="login-username">Username or email</label>
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

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%' }}
            disabled={busy}
          >
            {busy ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <p className="small" style={{ marginTop: 14, textAlign: 'center' }}>
          <button type="button" className="btn-link" onClick={onForgot}>
            Forgot your password?
          </button>
        </p>

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

export function RegisterScreen({ onRegister, onSwitch, onForgot, busy }) {
  const [values, setValues] = useState({
    first_name: '',
    last_name: '',
    username: '',
    email: '',
    password: '',
  });
  const [errors, setErrors] = useState({});

  const update = (field) => (e) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev));
  };

  const submit = async (e) => {
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
    } else if (values.username.includes('@')) {
      next.username = "Usernames can't contain @.";
    }

    const emailIssue = emailProblem(values.email);
    if (emailIssue) next.email = emailIssue;
    const passwordIssue = passwordProblem(values.password);
    if (passwordIssue) next.password = passwordIssue;

    setErrors(next);
    if (Object.keys(next).length) return;

    const result = await onRegister({
      first_name: values.first_name.trim(),
      last_name: values.last_name.trim(),
      username: values.username.trim(),
      email: values.email.trim(),
      password: values.password,
    });
    if (!result.ok && result.field) setErrors({ [result.field]: result.message });
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
            <label htmlFor="reg-email">Email</label>
            <input
              id="reg-email"
              type="email"
              inputMode="email"
              autoComplete="email"
              value={values.email}
              onChange={update('email')}
              aria-invalid={Boolean(errors.email)}
              aria-describedby={errors.email ? 'reg-email-error' : 'reg-email-hint'}
            />
            {!errors.email && (
              <span className="field-hint" id="reg-email-hint">
                For a code if you ever forget your password. Never shown to other players.
              </span>
            )}
            <FieldError id="reg-email-error" message={errors.email} />
            {errors.email && errors.email.includes('reset your password') && (
              <button type="button" className="btn-link btn-link-small" onClick={onForgot}>
                Reset your password
              </button>
            )}
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

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%' }}
            disabled={busy}
          >
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

/**
 * Forgot your password: an email, then the 6-digit code that arrives and
 * a new password. Success signs the player straight in (App handles it).
 * A code rather than a link, so it works the same in every app.
 */
export function ForgotPasswordScreen({ onRequestCode, onReset, onBack, busy }) {
  const [step, setStep] = useState('email');
  const [values, setValues] = useState({ email: '', code: '', password: '' });
  const [errors, setErrors] = useState({});
  const [note, setNote] = useState(null);

  const update = (field) => (e) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev));
  };

  const requestCode = async (e) => {
    e?.preventDefault();
    const problem = emailProblem(values.email);
    if (problem) {
      setErrors({ email: problem });
      return;
    }
    setErrors({});
    const result = await onRequestCode(values.email.trim());
    if (result.ok) {
      setNote(result.message);
      setStep('code');
    } else if (result.field) {
      setErrors({ [result.field]: result.message });
    }
  };

  const reset = async (e) => {
    e.preventDefault();
    const next = {};
    if (!values.code.replace(/\D/g, '')) next.code = 'Enter the code from the email.';
    const passwordIssue = passwordProblem(values.password);
    if (passwordIssue) next.password = passwordIssue;
    setErrors(next);
    if (Object.keys(next).length) return;

    const result = await onReset(values.email.trim(), values.code, values.password);
    if (!result.ok && result.field) setErrors({ [result.field]: result.message });
  };

  return (
    <div className="auth-shell">
      <div className="card">
        <h2 className="card-title" style={{ marginBottom: 6 }}>
          Reset your password
        </h2>

        {step === 'email' ? (
          <form onSubmit={requestCode} noValidate>
            <p className="muted small" style={{ marginBottom: 20 }}>
              Enter the email on your account and we&rsquo;ll send you a code.
            </p>
            <div className="field">
              <label htmlFor="forgot-email">Email</label>
              <input
                id="forgot-email"
                type="email"
                inputMode="email"
                autoComplete="email"
                value={values.email}
                onChange={update('email')}
                aria-invalid={Boolean(errors.email)}
                aria-describedby={errors.email ? 'forgot-email-error' : undefined}
              />
              <FieldError id="forgot-email-error" message={errors.email} />
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              style={{ width: '100%' }}
              disabled={busy}
            >
              {busy ? 'Sending...' : 'Send me a code'}
            </button>
          </form>
        ) : (
          <form onSubmit={reset} noValidate>
            <p className="muted small" style={{ marginBottom: 20 }} role="status">
              {note}
            </p>
            <div className="field">
              <label htmlFor="forgot-code">Code from the email</label>
              <input
                id="forgot-code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={7}
                value={values.code}
                onChange={update('code')}
                aria-invalid={Boolean(errors.code)}
                aria-describedby={errors.code ? 'forgot-code-error' : undefined}
              />
              <FieldError id="forgot-code-error" message={errors.code} />
            </div>
            <div className="field">
              <label htmlFor="forgot-password">New password</label>
              <input
                id="forgot-password"
                type="password"
                autoComplete="new-password"
                value={values.password}
                onChange={update('password')}
                aria-invalid={Boolean(errors.password)}
                aria-describedby={errors.password ? 'forgot-password-error' : undefined}
              />
              <FieldError id="forgot-password-error" message={errors.password} />
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              style={{ width: '100%' }}
              disabled={busy}
            >
              {busy ? 'Saving...' : 'Change password and sign in'}
            </button>
            <p className="small" style={{ marginTop: 14, textAlign: 'center' }}>
              <span className="muted">No email? </span>
              <button type="button" className="btn-link" onClick={requestCode} disabled={busy}>
                Send another code
              </button>
            </p>
          </form>
        )}

        <p className="small" style={{ marginTop: 18, textAlign: 'center' }}>
          <button type="button" className="btn-link" onClick={onBack}>
            Back to sign in
          </button>
        </p>
      </div>
    </div>
  );
}

/**
 * Accounts made before sign-up asked for an email add one once, after
 * signing in: without it, a forgotten password would mean a second
 * account - the thing emails are here to stop.
 */
export function AddEmailScreen({ username, onSave, onSignOut, busy }) {
  const [email, setEmail] = useState('');
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    const problem = emailProblem(email);
    if (problem) {
      setError(problem);
      return;
    }
    const result = await onSave(email.trim());
    if (!result.ok && result.field) setError(result.message);
  };

  return (
    <div className="auth-shell">
      <div className="card">
        <h2 className="card-title" style={{ marginBottom: 6 }}>
          Add your email, {username}
        </h2>
        <p className="muted small" style={{ marginBottom: 20 }}>
          If you ever forget your password, we&rsquo;ll send a code here to get you back in - so
          nobody has to start a new account. It&rsquo;s never shown to other players.
        </p>
        <form onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="add-email">Email</label>
            <input
              id="add-email"
              type="email"
              inputMode="email"
              autoComplete="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setError(null);
              }}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? 'add-email-error' : undefined}
            />
            <FieldError id="add-email-error" message={error} />
          </div>
          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%' }}
            disabled={busy}
          >
            {busy ? 'Saving...' : 'Save email'}
          </button>
        </form>
        <p className="small" style={{ marginTop: 18, textAlign: 'center' }}>
          <button type="button" className="btn-link" onClick={onSignOut}>
            Sign out
          </button>
        </p>
      </div>
    </div>
  );
}
