/**
 * Create an account. The checks here mirror the server's so people find
 * out before the round trip; the server still checks everything, and
 * its wording is shown when it refuses - beside the field it names.
 *
 * An email is required: one account per email is what stops a player
 * who forgot their password making a second account.
 */
import React, { useRef, useState } from 'react';
import { Linking, StyleSheet, View } from 'react-native';

import {
  MAX_NAME,
  MAX_USERNAME,
  MIN_USERNAME,
  emailProblem,
  passwordProblem,
} from '../accountRules';
import * as api from '../api';
import { Button, Field, Txt } from '../components/ui';
import { useToast } from '../state/ToastContext';
import { AuthShell } from './AuthShell';

export function RegisterScreen({ navigation }) {
  const toast = useToast();
  const [values, setValues] = useState({
    first_name: '',
    last_name: '',
    username: '',
    email: '',
    password: '',
  });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const refs = {
    last_name: useRef(null),
    username: useRef(null),
    email: useRef(null),
    password: useRef(null),
  };

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
    else if (username.includes('@')) next.username = "Usernames can't contain @.";

    const emailIssue = emailProblem(values.email);
    if (emailIssue) next.email = emailIssue;
    const passwordIssue = passwordProblem(values.password);
    if (passwordIssue) next.password = passwordIssue;

    setErrors(next);
    if (Object.keys(next).length) return;

    setBusy(true);
    const res = await api.register({
      first_name: first,
      last_name: last,
      username,
      email: values.email.trim(),
      password: values.password,
    });
    setBusy(false);

    if (!res.ok) {
      // The server explains why (taken username or email, short
      // password), so its wording goes straight through - beside the
      // field it names, when it names one.
      if (res.data?.field) setErrors({ [res.data.field]: res.message });
      else toast.push(res.message, 'error');
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
        onSubmitEditing={nextField('email')}
        submitBehavior="submit"
      />
      <Field
        ref={refs.email}
        label="Email"
        value={values.email}
        onChangeText={update('email')}
        error={errors.email}
        hint="For a code if you ever forget your password. Never shown to other players."
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="email"
        textContentType="emailAddress"
        keyboardType="email-address"
        inputMode="email"
        returnKeyType="next"
        onSubmitEditing={nextField('password')}
        submitBehavior="submit"
      />
      {errors.email?.includes('reset your password') ? (
        <Button
          variant="link"
          size="sm"
          title="Reset your password"
          onPress={() => navigation.navigate('ForgotPassword')}
          style={styles.resetLink}
        />
      ) : null}
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
  resetLink: { alignSelf: 'flex-start', marginTop: -8, marginBottom: 10 },
  switchRow: {
    marginTop: 18,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    flexWrap: 'wrap',
    gap: 4,
  },
});
