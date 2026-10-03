/**
 * The player's own profile: pick a flag, upload or link a picture, choose
 * light or dark, see where they stand in both leagues.
 *
 * Problems appear beside the field they concern - both the ones caught
 * here and the ones the server sends back (it names the field).
 */
import React, { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ImageUp, Trash2 } from 'lucide-react';

import { emailProblem } from '../accountRules.js';
import { PRIVACY_POLICY_URL } from '../api.js';
import { flagEmoji } from '../flags.js';
import { LEAGUE_ORDER, LEAGUES } from '../leagues.js';
import { PhotoProblem, squarePhoto } from '../photo.js';
import { THEME_CHOICES } from '../theme.js';
import { useOpenPlayer } from '../openPlayer.js';
import { Avatar } from './Player.jsx';
import { FieldError } from './Feedback.jsx';

// The database column's limit. The server enforces it too; checking here
// puts the message beside the field without a round trip.
const MAX_PICTURE_LINK = 512;
const WEB_LINK = /^https?:\/\/[^\s/]+\S*$/i;
// How long typing must pause before the preview tries the link.
const PREVIEW_DELAY_MS = 600;

function pictureProblem(link) {
  if (!link) return null;
  if (link.length > MAX_PICTURE_LINK) {
    return `Picture links can be at most ${MAX_PICTURE_LINK} characters.`;
  }
  if (!WEB_LINK.test(link)) return 'Use a link that starts with https:// (or http://).';
  return null;
}

export function ProfileSettings({
  profile,
  countries,
  onSave,
  onSetEmail,
  onUploadPicture,
  onDeleteAccount,
  onBack,
  themeChoice,
  onThemeChoice,
  busy,
}) {
  // An uploaded photo's address isn't a link anyone typed, so the link
  // field starts empty rather than offering it back to edit.
  const startingLink = profile.picture_uploaded ? '' : profile.profile_picture || '';
  const [values, setValues] = useState({
    country_flag: profile.country_flag || '',
    profile_picture: startingLink,
  });
  const [errors, setErrors] = useState({});
  const openPlayer = useOpenPlayer();

  const update = (field) => (e) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev));
  };

  const link = values.profile_picture.trim();

  // The preview follows the link once typing pauses. Following every
  // keystroke fired a request at each half-typed address on the way -
  // http://l, http://lo, http://loc...
  const [previewLink, setPreviewLink] = useState(link);
  useEffect(() => {
    const timer = setTimeout(() => setPreviewLink(link), PREVIEW_DELAY_MS);
    return () => clearTimeout(timer);
  }, [link]);
  // The link being typed, once it looks like one; otherwise whatever the
  // saved picture is - including an uploaded photo.
  const linkEdited = link !== startingLink;
  const preview = {
    username: profile.username,
    profile_picture: linkEdited
      ? previewLink && !pictureProblem(previewLink)
        ? previewLink
        : null
      : profile.profile_picture,
  };

  const submit = async (e) => {
    e.preventDefault();
    const problem = pictureProblem(link);
    if (problem) {
      setErrors({ profile_picture: problem });
      return;
    }
    setErrors({});

    // The picture is only sent when the link was changed: an empty link
    // field also means "keep my uploaded photo", and sending it would
    // delete the photo.
    const changes = { country_flag: values.country_flag || null };
    if (linkEdited) changes.profile_picture = link || null;
    const result = await onSave(changes);
    if (!result.ok && result.field) {
      setErrors({ [result.field]: result.message });
    }
  };

  // Until the list arrives (or if it can't), the player's current choice
  // still has to be a valid option.
  const options =
    countries ??
    (profile.country_flag ? [{ code: profile.country_flag, name: profile.country_flag }] : []);

  return (
    <main className="profile-shell" aria-labelledby="profile-title">
      <button type="button" className="btn btn-quiet btn-small profile-back" onClick={onBack}>
        <ArrowLeft size={15} aria-hidden="true" />
        Back
      </button>

      <section className="card">
        <div className="profile-head">
          <Avatar player={preview} size="xl" label={`Picture for ${profile.username}`} />
          <div>
            <h2 className="card-title" id="profile-title">
              {profile.username}
              {flagEmoji(profile.country_flag) && (
                <span className="profile-flag"> {flagEmoji(profile.country_flag)}</span>
              )}
            </h2>
            <p className="muted small">
              {profile.first_name} {profile.last_name}
            </p>
            {openPlayer && (
              <button
                type="button"
                className="btn-link btn-link-small"
                onClick={() => openPlayer(profile.user_id)}
              >
                See your profile as others do
              </button>
            )}
          </div>
        </div>

        <PhotoPicker
          profile={profile}
          onUpload={onUploadPicture}
          onRemove={() => onSave({ profile_picture: null })}
          busy={busy}
        />

        <form onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="profile-flag">Country flag</label>
            <select
              id="profile-flag"
              value={values.country_flag}
              onChange={update('country_flag')}
              aria-invalid={Boolean(errors.country_flag)}
              aria-describedby={errors.country_flag ? 'profile-flag-error' : undefined}
            >
              <option value="">No flag</option>
              {options.map((country) => (
                <option key={country.code} value={country.code}>
                  {flagEmoji(country.code)} {country.name}
                </option>
              ))}
            </select>
            {!countries && <span className="field-hint">Loading the list of countries...</span>}
            <FieldError id="profile-flag-error" message={errors.country_flag} />
          </div>

          <div className="field">
            <label htmlFor="profile-picture">Or use a link to a picture</label>
            <input
              id="profile-picture"
              type="url"
              inputMode="url"
              autoComplete="photo"
              placeholder="https://..."
              value={values.profile_picture}
              onChange={update('profile_picture')}
              aria-invalid={Boolean(errors.profile_picture)}
              aria-describedby={
                errors.profile_picture ? 'profile-picture-error' : 'profile-picture-hint'
              }
            />
            <span className="field-hint" id="profile-picture-hint">
              {profile.picture_uploaded
                ? "You're using an uploaded photo. Paste a link here to use that instead."
                : 'Paste a link to an image. Leave it empty to show your initial instead.'}
            </span>
            <FieldError id="profile-picture-error" message={errors.profile_picture} />
          </div>

          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? 'Saving...' : 'Save profile'}
          </button>
        </form>
      </section>

      <section className="card" aria-labelledby="standing-heading">
        <div className="card-head">
          <h2 className="card-title" id="standing-heading">
            Where you stand
          </h2>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">League</th>
                <th scope="col">Rank</th>
                <th scope="col">Points</th>
                <th scope="col">W&ndash;L</th>
              </tr>
            </thead>
            <tbody>
              {LEAGUE_ORDER.map((key) => {
                const standing = profile.leagues?.[key];
                return (
                  <tr key={key}>
                    <th scope="row" className="standing-league">
                      {LEAGUES[key].name}
                    </th>
                    <td>{standing?.rank_name ?? 'Unranked'}</td>
                    <td className="elo">{standing?.elo ?? 0}</td>
                    <td className="record">
                      <span className="record-win">{standing?.wins ?? 0}</span>
                      <span className="muted"> &ndash; </span>
                      <span className="record-loss">{standing?.losses ?? 0}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <EmailSetting email={profile.email} onSetEmail={onSetEmail} busy={busy} />

      <section className="card" aria-labelledby="appearance-heading">
        <div className="card-head">
          <h2 className="card-title" id="appearance-heading">
            Appearance
          </h2>
          <div className="segmented" role="group" aria-labelledby="appearance-heading">
            {THEME_CHOICES.map((option) => (
              <button
                key={option.key}
                type="button"
                className="segmented-option"
                aria-pressed={themeChoice === option.key}
                onClick={() => onThemeChoice(option.key)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <p className="muted small">
          Automatic follows your device&rsquo;s light or dark setting. Your choice is remembered on
          this device.
        </p>
      </section>

      <DeleteAccount onDelete={onDeleteAccount} />

      <p className="small profile-privacy">
        <a href={PRIVACY_POLICY_URL} target="_blank" rel="noopener noreferrer">
          Privacy policy
        </a>
      </p>
    </main>
  );
}

/**
 * The account's email - where a reset code goes if the password is
 * forgotten. Changing it asks for the password, so a computer left signed
 * in can't be used to redirect those codes.
 */
function EmailSetting({ email, onSetEmail, busy }) {
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState({ email: '', password: '' });
  const [errors, setErrors] = useState({});

  const update = (field) => (e) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev));
  };

  const close = () => {
    setEditing(false);
    setValues({ email: '', password: '' });
    setErrors({});
  };

  const submit = async (e) => {
    e.preventDefault();
    const next = {};
    const problem = emailProblem(values.email);
    if (problem) next.email = problem;
    if (email && !values.password) next.password = 'Enter your password to change your email.';
    setErrors(next);
    if (Object.keys(next).length) return;

    const result = await onSetEmail(values.email.trim(), email ? values.password : undefined);
    if (result.ok) close();
    else if (result.field) setErrors({ [result.field]: result.message });
  };

  return (
    <section className="card" aria-labelledby="email-heading">
      <div className="card-head">
        <h2 className="card-title" id="email-heading">
          Email
        </h2>
      </div>
      {!editing ? (
        <>
          <p className="email-current">{email || <span className="muted">No email yet</span>}</p>
          <p className="muted small" style={{ marginBottom: 14 }}>
            Where a code goes if you forget your password. Never shown to other players.
          </p>
          <button
            type="button"
            className="btn btn-quiet btn-small"
            onClick={() => setEditing(true)}
          >
            {email ? 'Change email' : 'Add email'}
          </button>
        </>
      ) : (
        <form onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="profile-email">{email ? 'New email' : 'Email'}</label>
            <input
              id="profile-email"
              type="email"
              inputMode="email"
              autoComplete="email"
              value={values.email}
              onChange={update('email')}
              aria-invalid={Boolean(errors.email)}
              aria-describedby={errors.email ? 'profile-email-error' : undefined}
            />
            <FieldError id="profile-email-error" message={errors.email} />
          </div>
          {email && (
            <div className="field">
              <label htmlFor="profile-email-password">Your password</label>
              <input
                id="profile-email-password"
                type="password"
                autoComplete="current-password"
                value={values.password}
                onChange={update('password')}
                aria-invalid={Boolean(errors.password)}
                aria-describedby={errors.password ? 'profile-email-password-error' : undefined}
              />
              <FieldError id="profile-email-password-error" message={errors.password} />
            </div>
          )}
          <div className="danger-zone-actions">
            <button type="submit" className="btn btn-primary btn-small" disabled={busy}>
              {busy ? 'Saving...' : 'Save email'}
            </button>
            <button
              type="button"
              className="btn btn-quiet btn-small"
              onClick={close}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

/**
 * Uploading a photo as the picture, or removing the picture. The photo is
 * cropped and shrunk here (see photo.js), and again on the server, which
 * also strips its metadata - where it was taken, the camera - before
 * anyone sees it.
 */
function PhotoPicker({ profile, onUpload, onRemove, busy }) {
  const inputRef = useRef(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(null);

  const choose = async (e) => {
    const file = e.target.files?.[0];
    // Cleared, so choosing the same file again still counts as a change.
    e.target.value = '';
    if (!file) return;
    setError(null);
    setWorking(true);
    try {
      const image = await squarePhoto(file);
      const result = await onUpload(image);
      if (!result.ok && result.field) setError(result.message);
    } catch (problem) {
      setError(
        problem instanceof PhotoProblem
          ? problem.message
          : "That picture couldn't be prepared. Try a different one.",
      );
    } finally {
      setWorking(false);
    }
  };

  return (
    <div className="photo-picker">
      <div className="photo-picker-actions">
        {/* The button below stands in for the browser's own file control,
            which can't be styled; this one stays out of reach. */}
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          className="sr-only"
          onChange={choose}
          tabIndex={-1}
          aria-hidden="true"
        />
        <button
          type="button"
          className="btn btn-quiet btn-small"
          onClick={() => inputRef.current?.click()}
          disabled={working || busy}
          aria-describedby={error ? 'profile-photo-error' : 'profile-photo-hint'}
        >
          <ImageUp size={16} aria-hidden="true" />
          {working
            ? 'Uploading...'
            : profile.profile_picture
              ? 'Upload a new photo'
              : 'Upload a photo'}
        </button>
        {profile.profile_picture && (
          <button
            type="button"
            className="btn btn-quiet btn-small"
            onClick={onRemove}
            disabled={working || busy}
          >
            Remove picture
          </button>
        )}
      </div>
      <span className="field-hint" id="profile-photo-hint">
        Any photo works - it&rsquo;s cropped to a square, and the location and other details photos
        carry are removed.
      </span>
      <FieldError id="profile-photo-error" message={error} />
    </div>
  );
}

/**
 * Deleting the account: says what will happen, asks for the password
 * again, and only then deletes. The confirmation opens in place rather
 * than in a browser dialog, which would block the tab and can't be styled.
 */
function DeleteAccount({ onDelete }) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const passwordRef = useRef(null);

  useEffect(() => {
    if (open) passwordRef.current?.focus();
  }, [open]);

  const cancel = () => {
    setOpen(false);
    setPassword('');
    setError(null);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!password) {
      setError('Enter your password to delete your account.');
      return;
    }
    setDeleting(true);
    const result = await onDelete(password);
    // On success the app signs out and this screen goes away.
    if (result.ok) return;
    setDeleting(false);
    if (result.field === 'password') setError(result.message);
  };

  return (
    <section className="card danger-zone" aria-labelledby="account-heading">
      <div className="card-head">
        <h2 className="card-title" id="account-heading">
          Your account
        </h2>
      </div>

      {!open ? (
        <>
          <p className="muted small danger-zone-text">
            Deleting your account removes your name, flag, picture and password, and takes you off
            the ladders. Your games stay in other players' history as "Deleted player".
          </p>
          <button type="button" className="btn btn-danger-quiet" onClick={() => setOpen(true)}>
            <Trash2 size={16} aria-hidden="true" />
            Delete account
          </button>
        </>
      ) : (
        <form onSubmit={submit} noValidate>
          <p className="danger-zone-title">Delete your account?</p>
          <p className="small danger-zone-text">
            This removes your username, name, flag, picture and password straight away, takes you
            out of every queue and off the ladders, and signs you out. Games you've played stay in
            other players' history, shown as "Deleted player" with nothing that identifies you.{' '}
            <strong>This can't be undone.</strong>
          </p>
          <div className="field">
            <label htmlFor="delete-password">Your password</label>
            <input
              ref={passwordRef}
              id="delete-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setError(null);
              }}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? 'delete-password-error' : undefined}
            />
            <FieldError id="delete-password-error" message={error} />
          </div>
          <div className="danger-zone-actions">
            <button type="submit" className="btn btn-danger" disabled={deleting}>
              {deleting ? 'Deleting...' : 'Delete my account'}
            </button>
            <button type="button" className="btn btn-quiet" onClick={cancel} disabled={deleting}>
              Keep my account
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
