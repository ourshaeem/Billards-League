/**
 * The organiser's settings for the league on screen: its 4-digit PIN, and
 * its tables - add one, rename one, stop using one. A port of
 * Frontend/src/components/LeagueSettings.jsx, reached from the Play tab's
 * "Manage" button, which only an admin sees; the server refuses anyone
 * else whatever this screen shows.
 *
 * Changing the PIN means everyone who entered the old one enters the new
 * one - this screen says so before it's done. A table with someone at it
 * can't be removed (take them off first, from the Play tab); its games
 * stay in the history either way.
 */
import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import * as api from '../api';
import { Button, Card, Field, Pill, Screen, Txt } from '../components/ui';
import { useLeague } from '../state/LeagueContext';
import { useLive } from '../state/LiveContext';
import { useToast } from '../state/ToastContext';

export function LeagueSettingsScreen() {
  const { league, reload } = useLeague();
  const { refresh } = useLive();

  if (!league) {
    return (
      <Screen>
        <Txt muted>Loading the league...</Txt>
      </Screen>
    );
  }

  // Everything that shows the league - the list, the Play tab - catches up.
  const changed = () => {
    reload();
    refresh();
  };

  return (
    <Screen>
      <PinCard league={league} onChanged={changed} />
      <TablesCard league={league} onChanged={changed} />
    </Screen>
  );
}

/** A refusal: beside its field when the server names one, else a toast. */
function useRefusal() {
  const toast = useToast();
  return (res, field, setError) => {
    if (res.data?.field === field) setError(res.message);
    else if (res.kind !== api.ErrorKind.AUTH) toast.push(res.message, 'error');
  };
}

function PinCard({ league, onChanged }) {
  const toast = useToast();
  const refuse = useRefusal();
  const [values, setValues] = useState({ pin: '', again: '' });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  const update = (field) => (text) => {
    setValues((v) => ({ ...v, [field]: text.replace(/[^0-9]/g, '').slice(0, 4) }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev));
  };

  const submit = async () => {
    const next = {};
    if (!/^\d{4}$/.test(values.pin)) next.pin = 'The PIN is 4 digits.';
    else if (values.again !== values.pin) next.again = "That doesn't match the PIN above.";
    setErrors(next);
    if (Object.keys(next).length) return;

    setBusy(true);
    const res = await api.adminSetLeaguePin(league.league_id, values.pin);
    setBusy(false);
    if (!res.ok) {
      refuse(res, 'pin', (message) => setErrors({ pin: message }));
      return;
    }
    toast.push(res.data?.message || 'PIN changed.', 'success');
    setValues({ pin: '', again: '' });
    onChanged();
  };

  return (
    <Card title="PIN" icon="key" right={<Pill>{league.has_pin ? 'Set' : 'Not set yet'}</Pill>}>
      <Txt variant="small" muted style={styles.note}>
        {league.has_pin
          ? 'Players enter the PIN once to play here. Changing it means everyone has to enter the new one - tell them before you do.'
          : 'Nobody can play here until there is a PIN - set one, then share it with the players.'}
      </Txt>
      <Field
        label="New 4-digit PIN"
        value={values.pin}
        onChangeText={update('pin')}
        keyboardType="number-pad"
        inputMode="numeric"
        secureTextEntry
        autoComplete="off"
        maxLength={4}
        error={errors.pin}
      />
      <Field
        label="The same PIN again"
        value={values.again}
        onChangeText={update('again')}
        onSubmitEditing={submit}
        keyboardType="number-pad"
        inputMode="numeric"
        secureTextEntry
        autoComplete="off"
        maxLength={4}
        error={errors.again}
      />
      <Button
        title={busy ? 'Saving...' : league.has_pin ? 'Change the PIN' : 'Set the PIN'}
        onPress={submit}
        disabled={busy}
      />
    </Card>
  );
}

function TablesCard({ league, onChanged }) {
  const toast = useToast();
  const refuse = useRefusal();
  const [newName, setNewName] = useState('');
  const [addError, setAddError] = useState(null);
  const [busy, setBusy] = useState(false);
  const tables = league.tables || [];

  const add = async () => {
    if (!newName.trim()) {
      setAddError('Give the table a name, like "Table 2".');
      return;
    }
    setBusy(true);
    const res = await api.adminAddTable(league.league_id, newName.trim());
    setBusy(false);
    if (!res.ok) {
      refuse(res, 'name', setAddError);
      return;
    }
    toast.push(res.data?.message || 'Table added.', 'success');
    setNewName('');
    onChanged();
  };

  return (
    <Card
      title="Tables"
      icon="target"
      right={<Pill>{`${tables.length} in use`}</Pill>}
      footer="One queue feeds every table: whoever is next in line goes to the first table that needs a player."
    >
      {tables.map((table) => (
        // Keyed on the name too, so a rename (here or on the website)
        // resets the row's field to the new name.
        <TableRow key={`${table.table_id}:${table.table_name}`} table={table} onChanged={onChanged} />
      ))}

      <View style={styles.addRow}>
        <Field
          label="Add a table"
          value={newName}
          onChangeText={(text) => {
            setNewName(text);
            setAddError(null);
          }}
          onSubmitEditing={add}
          placeholder={`Table ${tables.length + 1}`}
          maxLength={50}
          error={addError}
          style={styles.grow}
        />
        <Button
          icon="plus"
          title={busy ? 'Adding...' : 'Add'}
          onPress={add}
          disabled={busy}
          style={styles.besideField}
        />
      </View>
    </Card>
  );
}

function TableRow({ table, onChanged }) {
  const toast = useToast();
  const refuse = useRefusal();
  const [name, setName] = useState(table.table_name);
  const [error, setError] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const renamed = Boolean(name.trim()) && name.trim() !== table.table_name;

  const rename = async () => {
    if (!renamed) return;
    setBusy(true);
    const res = await api.adminRenameTable(table.table_id, name.trim());
    setBusy(false);
    if (!res.ok) {
      refuse(res, 'name', setError);
      return;
    }
    toast.push(res.data?.message || 'Renamed.', 'success');
    onChanged();
  };

  const remove = async () => {
    setBusy(true);
    const res = await api.adminRemoveTable(table.table_id);
    setBusy(false);
    setConfirming(false);
    if (!res.ok) {
      refuse(res, null, () => {});
      return;
    }
    toast.push(res.data?.message || 'Table removed.', 'info');
    onChanged();
  };

  return (
    <View style={styles.tableRow}>
      <Field
        label={`Name of ${table.table_name}`}
        value={name}
        onChangeText={(text) => {
          setName(text);
          setError(null);
        }}
        onSubmitEditing={rename}
        maxLength={50}
        error={error}
      />
      <View style={styles.rowActions}>
        <Button variant="quiet" size="sm" title="Rename" onPress={rename} disabled={busy || !renamed} />
        <Button
          variant="dangerQuiet"
          size="sm"
          title="Remove"
          onPress={() => setConfirming((c) => !c)}
          disabled={busy}
        />
      </View>
      {confirming ? (
        <View style={styles.confirm}>
          <Txt weight="bold">Stop using {table.table_name}?</Txt>
          <Txt variant="small" muted style={styles.confirmText}>
            Nobody will be sent to play on it. Its games stay in the history. If someone is at it,
            take them off first.
          </Txt>
          <View style={styles.rowActions}>
            <Button
              variant="danger"
              size="sm"
              title={`Remove ${table.table_name}`}
              onPress={remove}
              busy={busy}
            />
            <Button variant="quiet" size="sm" title="Keep it" onPress={() => setConfirming(false)} />
          </View>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  note: { marginBottom: 14 },
  tableRow: { marginBottom: 18 },
  rowActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  confirm: { marginTop: 12 },
  confirmText: { marginTop: 4, marginBottom: 10 },
  addRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  grow: { flex: 1 },
  besideField: { marginTop: 25 },
});
