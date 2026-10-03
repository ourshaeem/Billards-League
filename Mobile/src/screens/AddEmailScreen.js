/**
 * Accounts made before sign-up asked for an email add one once, after
 * signing in: without it, a forgotten password would mean a second
 * account - the thing emails are here to stop. Port of AddEmailScreen in
 * Frontend/src/components/AuthScreens.jsx.
 *
 * The navigator shows this until the session hears the email is saved.
 */
import React, { useState } from 'react';
import { StyleSheet } from 'react-native';

import { emailProblem } from '../accountRules';
import * as api from '../api';
import { Button, Field } from '../components/ui';
import { useSession } from '../state/SessionContext';
import { useToast } from '../state/ToastContext';
import { AuthShell } from './AuthShell';

export function AddEmailScreen() {
  const { user, emailSaved, signOut } = useSession();
  const toast = useToast();
  const [email, setEmail] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    const problem = emailProblem(email);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    const res = await api.setEmail(email.trim());
    setBusy(false);
    if (!res.ok) {
      if (res.data?.field) setError(res.message);
      else if (res.kind !== api.ErrorKind.AUTH) toast.push(res.message, 'error');
      return;
    }
    toast.push('Email saved.', 'success');
    emailSaved();
  };

  return (
    <AuthShell
      title={`Add your email, ${user?.username ?? ''}`}
      intro="If you ever forget your password, we'll send a code here to get you back in - so nobody has to start a new account. It's never shown to other players."
    >
      <Field
        label="Email"
        value={email}
        onChangeText={(text) => {
          setEmail(text);
          setError(null);
        }}
        error={error}
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="email"
        textContentType="emailAddress"
        keyboardType="email-address"
        inputMode="email"
        returnKeyType="done"
        onSubmitEditing={save}
      />
      <Button title={busy ? 'Saving...' : 'Save email'} size="lg" onPress={save} busy={busy} />
      <Button variant="link" size="sm" title="Sign out" onPress={signOut} style={styles.signOut} />
    </AuthShell>
  );
}

const styles = StyleSheet.create({
  signOut: { alignSelf: 'center', marginTop: 14 },
});
