/**
 * Sign in. On success the session saves the token to SecureStore, and
 * the navigator moves on to choosing a league by itself - this screen
 * doesn't navigate anywhere.
 */
import React, { useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Button, Field, Txt } from '../components/ui';
import { useSession } from '../state/SessionContext';
import { useToast } from '../state/ToastContext';
import { AuthShell } from './AuthShell';

export function LoginScreen({ navigation }) {
  const { signIn } = useSession();
  const toast = useToast();
  const [values, setValues] = useState({ username: '', password: '' });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef(null);

  const update = (field) => (text) => {
    setValues((v) => ({ ...v, [field]: text }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev));
  };

  const submit = async () => {
    const next = {};
    if (!values.username.trim()) next.username = 'Enter your username.';
    if (!values.password) next.password = 'Enter your password.';
    setErrors(next);
    if (Object.keys(next).length) return;

    setBusy(true);
    const res = await signIn(values.username.trim(), values.password);
    if (res.ok) return; // this screen is about to be replaced
    setBusy(false);
    // A 401 from /login means the password was wrong - not a lost session.
    toast.push(res.status === 401 ? 'That username or password is wrong.' : res.message, 'error');
  };

  return (
    <AuthShell title="Sign in" intro="Sign in to join the queue and report your scores.">
      <Field
        label="Username"
        value={values.username}
        onChangeText={update('username')}
        error={errors.username}
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="username"
        textContentType="username"
        returnKeyType="next"
        onSubmitEditing={() => passwordRef.current?.focus()}
        submitBehavior="submit"
      />
      <Field
        ref={passwordRef}
        label="Password"
        value={values.password}
        onChangeText={update('password')}
        error={errors.password}
        secureTextEntry
        autoCapitalize="none"
        autoComplete="current-password"
        textContentType="password"
        returnKeyType="go"
        onSubmitEditing={submit}
      />
      <Button
        title={busy ? 'Signing in...' : 'Sign in'}
        size="lg"
        onPress={submit}
        busy={busy}
        style={styles.submit}
      />
      <View style={styles.switchRow}>
        <Txt variant="small" muted>
          New to the league?
        </Txt>
        <Button variant="link" size="sm" title="Create an account" onPress={() => navigation.navigate('Register')} />
      </View>
    </AuthShell>
  );
}

const styles = StyleSheet.create({
  submit: { marginTop: 4 },
  switchRow: {
    marginTop: 18,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    flexWrap: 'wrap',
    gap: 4,
  },
});
