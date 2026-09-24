/**
 * The player's own profile: pick a flag, set a picture, see where they
 * stand in both leagues.
 *
 * Problems appear beside the field they concern - both the ones caught
 * here and the ones the server sends back (it names the field).
 */
import React, { useEffect, useState } from 'react';
import { ArrowLeft } from 'lucide-react';

import { flagEmoji } from '../flags.js';
import { LEAGUE_ORDER, LEAGUES } from '../leagues.js';
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

export function ProfileSettings({ profile, countries, onSave, onBack, busy }) {
  const [values, setValues] = useState({
    country_flag: profile.country_flag || '',
    profile_picture: profile.profile_picture || '',
  });
  const [errors, setErrors] = useState({});

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
  const preview = {
    username: profile.username,
    profile_picture: previewLink && !pictureProblem(previewLink) ? previewLink : null,
  };

  const submit = async (e) => {
    e.preventDefault();
    const problem = pictureProblem(link);
    if (problem) {
      setErrors({ profile_picture: problem });
      return;
    }
    setErrors({});

    const result = await onSave({
      country_flag: values.country_flag || null,
      profile_picture: link || null,
    });
    if (!result.ok && result.field) {
      setErrors({ [result.field]: result.message });
    }
  };

  // Until the list arrives (or if it can't), the player's current choice
  // still has to be a valid option.
  const options = countries ?? (profile.country_flag ? [{ code: profile.country_flag, name: profile.country_flag }] : []);

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
          </div>
        </div>

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
            <label htmlFor="profile-picture">Profile picture link</label>
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
              Paste a link to an image. Leave it empty to show your initial instead.
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
    </main>
  );
}
