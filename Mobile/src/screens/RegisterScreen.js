/**
 * Create an account. The checks here mirror the server's so people find
 * out before the round trip; the server still checks everything, and
 * its wording is shown when it refuses.
 */
import React, { useRef, useState } from 'react';
import { Linking, StyleSheet, View } from 'react-native';

import * as api from '../api';
import { Button, Field, Txt } from '../components/ui';
import { useToast } from '../state/ToastContext';
import { AuthShell } from './AuthShell';

const MIN_USERNAME = 3;
const MIN_PASSWORD = 6;
// The database columns' limits.
const MAX_USERNAME = 50;
const MAX_NAME = 50;
// bcrypt reads at most 72 bytes of a password, and the server refuses more.
const MAX_PASSWORD_BYTES = 72;

/** A string's length in UTF-8 bytes - what the server's limit counts. */
function utf8Length(text) {
  let bytes = 0;
  for (const char of text) {
    const code = char.codePointAt(0);
    bytes += code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
  }
  return bytes;
}

export function RegisterScreen({ navigation }) {
  const toast = useToast();
  const [values, setValues] = useState({ first_name: '', last_name: '', username: '', password: '' });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const refs = { last_name: useRef(null), username: useRef(null), password: useRef(null) };

  const update = (field) => (text) => {
    setValues((v) => ({ ...v, [field]: text }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev));
  };

  const submit = async () => {
    const next = {};
    const first = values.first_name.trim();
    const last = values.last_name.trim();
    const username = values.username.trim();

    if (!first) next.first_name = 'Enter your first name.';
    else if (first.length > MAX_NAME) next.first_name = `Names can be at most ${MAX_NAME} characters.`;
    if (!last) next.last_name = 'Enter your last name.';
    else if (last.length > MAX_NAME) next.last_name = `Names can be at most ${MAX_NAME} characters.`;

    if (!username) next.username = 'Pick a username.';
    else if (username.length < MIN_USERNAME) next.username = `Usernames need at least ${MIN_USERNAME} characters.`;
    else if (username.length > MAX_USERNAME) next.username = `Usernames can be at most ${MAX_USERNAME} characters.`;

    if (!values.password) next.password = 'Pick a password.';
    else if (values.password.length < MIN_PASSWORD) next.password = `Passwords need at least ${MIN_PASSWORD} characters.`;
    else if (utf8Length(values.password) > MAX_PASSWORD_BYTES) next.password = `Passwords can be at most ${MAX_PASSWORD_BYTES} characters.`;

    setErrors(next);
    if (Object.keys(next).length) return;

    setBusy(true);
    const res = await api.register({ first_name: first, last_name: last, username, password: values.password });
    setBusy(false);

    if (!res.ok) {
      // The server explains why (taken username, short password), so its
      // wording goes straight through.
      toast.push(res.message, 'error');
      return;
    }
    toast.push('Account created. Sign in to get playing.', 'success');
    navigation.navigate('SignIn');
  };

  const nextField = (name) => () => refs[name].current?.focus();

  return (
    <AuthShell title="Create an account" intro="Everyone starts at 0 points. Win games to climb the ladder.">
      <Field
        label="First name"
        value={values.first_name}
        onChangeText={update('first_name')}
        error={errors.first_name}
        autoComplete="given-name"
        textContentType="givenName"
        returnKeyType="next"
        onSubmitEditing={nextField('last_name')}
        submitBehavior="submit"
      />
      <Field
        ref={refs.last_name}
        label="Last name"
        value={values.last_name}
        onChangeText={update('last_name')}
        error={errors.last_name}
        autoComplete="family-name"
        textContentType="familyName"
        returnKeyType="next"
        onSubmitEditing={nextField('username')}
        submitBehavior="submit"
      />
      <Field
        ref={refs.username}
        label="Username"
        value={values.username}
        onChangeText={update('username')}
        error={errors.username}
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="username-new"
        textContentType="username"
        returnKeyType="next"
        onSubmitEditing={nextField('password')}
        submitBehavior="submit"
      />
      <Field
        ref={refs.password}
        label="Password"
        value={values.password}
        onChangeText={update('password')}
        error={errors.password}
        secureTextEntry
        autoCapitalize="none"
        autoComplete="new-password"
        textContentType="newPassword"
        returnKeyType="go"
        onSubmitEditing={submit}
      />
      <Button
        title={busy ? 'Creating account...' : 'Create account'}
        size="lg"
        onPress={submit}
        busy={busy}
        style={styles.submit}
      />
      <View style={styles.switchRow}>
        <Txt variant="small" muted>
          How we handle your details:
        </Txt>
        <Button
          variant="link"
          size="sm"
          title="Privacy policy"
          accessibilityHint="Opens in your browser"
          onPress={() => Linking.openURL(api.PRIVACY_POLICY_URL)}
        />
      </View>
      <View style={styles.switchRow}>
        <Txt variant="small" muted>
          Already playing?
        </Txt>
        <Button variant="link" size="sm" title="Sign in" onPress={() => navigation.navigate('SignIn')} />
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
