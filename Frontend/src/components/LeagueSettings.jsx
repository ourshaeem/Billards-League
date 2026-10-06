/**
 * The organiser's settings for one league: its 4-digit PIN, and its
 * tables - add one, rename one, stop using one. Shown only to an admin
 * (the masthead's "Manage league"); the server refuses anyone else
 * whatever this screen shows.
 *
 * Changing the PIN means everyone who entered the old one enters the new
 * one - this screen says so before it's done. A table with someone at it
 * can't be removed (take them off first, from the dashboard); its games
 * stay in the history either way.
 */
import React, { useState } from 'react';
import { ArrowLeft, KeyRound, Plus, Swords } from 'lucide-react';

import * as api from '../api.js';
import { FieldError } from './Feedback.jsx';

export function LeagueSettings({ league, onChanged, onBack, pushToast }) {
  return (
    <main className="profile-shell" aria-labelledby="league-settings-title">
      <button type="button" className="btn btn-quiet btn-small profile-back" onClick={onBack}>
        <ArrowLeft size={15} aria-hidden="true" />
        Back to {league.name}
      </button>
      <h2 className="settings-title" id="league-settings-title">
        Manage {league.name}
      </h2>

      <PinCard league={league} onChanged={onChanged} pushToast={pushToast} />
      <TablesSettingsCard league={league} onChanged={onChanged} pushToast={pushToast} />
    </main>
  );
}

function PinCard({ league, onChanged, pushToast }) {
  const [values, setValues] = useState({ pin: '', again: '' });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  const update = (field) => (e) => {
    setValues((v) => ({ ...v, [field]: e.target.value.replace(/\D/g, '').slice(0, 4) }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev));
  };

  const submit = async (e) => {
    e.preventDefault();
    const next = {};
    if (!/^\d{4}$/.test(values.pin)) next.pin = 'The PIN is 4 digits.';
    else if (values.again !== values.pin) next.again = "That doesn't match the PIN above.";
    setErrors(next);
    if (Object.keys(next).length) return;

    setBusy(true);
    const res = await api.adminSetLeaguePin(league.league_id, values.pin);
    setBusy(false);
    if (!res.ok) {
      if (res.data?.field === 'pin') setErrors({ pin: res.message });
      else if (res.kind !== api.ErrorKind.AUTH) pushToast(res.message, 'error');
      return;
    }
    pushToast(res.data?.message || 'PIN changed.', 'success');
    setValues({ pin: '', again: '' });
    onChanged();
  };

  return (
    <section className="card" aria-labelledby="pin-heading">
      <div className="card-head">
        <h2 className="card-title" id="pin-heading">
          <KeyRound size={18} aria-hidden="true" className="card-title-icon" />
          PIN
        </h2>
        <span className="count-pill">{league.has_pin ? 'Set' : 'Not set yet'}</span>
      </div>
      <p className="muted small settings-note">
        {league.has_pin
          ? 'Players enter the PIN once to play here. Changing it means everyone has to enter the new one - tell them before you do.'
          : 'Nobody can play here until there is a PIN - set one, then share it with the players.'}
      </p>
      <form onSubmit={submit} noValidate className="settings-form">
        <div className="field">
          <label htmlFor="league-pin">New 4-digit PIN</label>
          <input
            id="league-pin"
            type="password"
            inputMode="numeric"
            autoComplete="off"
            pattern="[0-9]*"
            maxLength={4}
            value={values.pin}
            onChange={update('pin')}
            aria-invalid={Boolean(errors.pin)}
            aria-describedby={errors.pin ? 'league-pin-error' : undefined}
          />
          <FieldError id="league-pin-error" message={errors.pin} />
        </div>
        <div className="field">
          <label htmlFor="league-pin-again">The same PIN again</label>
          <input
            id="league-pin-again"
            type="password"
            inputMode="numeric"
            autoComplete="off"
            pattern="[0-9]*"
            maxLength={4}
            value={values.again}
            onChange={update('again')}
            aria-invalid={Boolean(errors.again)}
            aria-describedby={errors.again ? 'league-pin-again-error' : undefined}
          />
          <FieldError id="league-pin-again-error" message={errors.again} />
        </div>
        <button type="submit" className="btn btn-small" disabled={busy}>
          {busy ? 'Saving...' : league.has_pin ? 'Change the PIN' : 'Set the PIN'}
        </button>
      </form>
    </section>
  );
}

function TablesSettingsCard({ league, onChanged, pushToast }) {
  const [newName, setNewName] = useState('');
  const [addError, setAddError] = useState(null);
  const [busy, setBusy] = useState(false);
  const tables = league.tables || [];

  const add = async (e) => {
    e.preventDefault();
    if (!newName.trim()) {
      setAddError('Give the table a name, like "Table 2".');
      return;
    }
    setBusy(true);
    const res = await api.adminAddTable(league.league_id, newName.trim());
    setBusy(false);
    if (!res.ok) {
      if (res.data?.field === 'name') setAddError(res.message);
      else if (res.kind !== api.ErrorKind.AUTH) pushToast(res.message, 'error');
      return;
    }
    pushToast(res.data?.message || 'Table added.', 'success');
    setNewName('');
    onChanged();
  };

  return (
    <section className="card" aria-labelledby="tables-settings-heading">
      <div className="card-head">
        <h2 className="card-title" id="tables-settings-heading">
          <Swords size={18} aria-hidden="true" className="card-title-icon" />
          Tables
        </h2>
        <span className="count-pill">
          {tables.length} in use
        </span>
      </div>
      <p className="muted small settings-note">
        One queue feeds every table: whoever is next in line goes to the first table that needs
        a player.
      </p>

      <ul className="settings-tables">
        {tables.map((table) => (
          <TableRow
            key={table.table_id}
            table={table}
            onChanged={onChanged}
            pushToast={pushToast}
          />
        ))}
      </ul>

      <form onSubmit={add} noValidate className="settings-add">
        <div className="field">
          <label htmlFor="new-table-name">Add a table</label>
          <input
            id="new-table-name"
            type="text"
            maxLength={50}
            placeholder={`Table ${tables.length + 1}`}
            value={newName}
            onChange={(e) => {
              setNewName(e.target.value);
              setAddError(null);
            }}
            aria-invalid={Boolean(addError)}
            aria-describedby={addError ? 'new-table-name-error' : undefined}
          />
          <FieldError id="new-table-name-error" message={addError} />
        </div>
        <button type="submit" className="btn btn-small" disabled={busy}>
          <Plus size={15} aria-hidden="true" />
          {busy ? 'Adding...' : 'Add table'}
        </button>
      </form>
    </section>
  );
}

function TableRow({ table, onChanged, pushToast }) {
  const [name, setName] = useState(table.table_name);
  const [error, setError] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const fieldId = `table-name-${table.table_id}`;
  const renamed = name.trim() && name.trim() !== table.table_name;

  const rename = async (e) => {
    e.preventDefault();
    if (!renamed) return;
    setBusy(true);
    const res = await api.adminRenameTable(table.table_id, name.trim());
    setBusy(false);
    if (!res.ok) {
      if (res.data?.field === 'name') setError(res.message);
      else if (res.kind !== api.ErrorKind.AUTH) pushToast(res.message, 'error');
      return;
    }
    pushToast(res.data?.message || 'Renamed.', 'success');
    onChanged();
  };

  const remove = async () => {
    setBusy(true);
    const res = await api.adminRemoveTable(table.table_id);
    setBusy(false);
    setConfirming(false);
    if (!res.ok) {
      if (res.kind !== api.ErrorKind.AUTH) pushToast(res.message, 'error');
      return;
    }
    pushToast(res.data?.message || 'Table removed.', 'info');
    onChanged();
  };

  return (
    <li className="settings-table">
      <form onSubmit={rename} noValidate className="settings-table-form">
        <label htmlFor={fieldId} className="sr-only">
          Name of {table.table_name}
        </label>
        <input
          id={fieldId}
          type="text"
          maxLength={50}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setError(null);
          }}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${fieldId}-error` : undefined}
        />
        <button type="submit" className="btn btn-quiet btn-small" disabled={busy || !renamed}>
          Rename
        </button>
        <button
          type="button"
          className="btn btn-danger-quiet btn-small"
          onClick={() => setConfirming((c) => !c)}
          aria-expanded={confirming}
          disabled={busy}
        >
          Remove
        </button>
      </form>
      <FieldError id={`${fieldId}-error`} message={error} />
      {confirming && (
        <div className="admin-confirm" role="group" aria-label={`Remove ${table.table_name}?`}>
          <p className="admin-confirm-question">Stop using {table.table_name}?</p>
          <p className="small admin-confirm-text">
            Nobody will be sent to play on it. Its games stay in the history. If someone is at it,
            take them off first.
          </p>
          <div className="admin-confirm-actions">
            <button type="button" className="btn btn-danger btn-small" onClick={remove} disabled={busy}>
              Remove {table.table_name}
            </button>
            <button type="button" className="btn btn-quiet btn-small" onClick={() => setConfirming(false)}>
              Keep it
            </button>
          </div>
        </div>
      )}
    </li>
  );
}
