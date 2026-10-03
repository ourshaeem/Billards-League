/**
 * Forgot your password: an email, then the 6-digit code that arrives and
 * a new password. Success signs the player straight in - the session
 * moves the navigator on, so this screen doesn't navigate anywhere.
 * Port of ForgotPasswordScreen in Frontend/src/components/AuthScreens.jsx.
 *
 * A code rather than a link: typing six digits needs nothing to open in
 * the right app.
 */
import React, { useRef, useState } from 'react';
import { StyleSheet } from 'react-native';

import { emailProblem, passwordProblem } from '../accountRules';
import * as api from '../api';
import { Button, Field, Txt } from '../components/ui';
import { useSession } from '../state/SessionContext';
import { useToast } from '../state/ToastContext';
import { AuthShell } from './AuthShell';

export function ForgotPasswordScreen({ navigation }) {
  const { resetPassword } = useSession();
  const toast = useToast();
  const [step, setStep] = useState('email');
  const [values, setValues] = useState({ email: '', code: '', password: '' });
  const [errors, setErrors] = useState({});
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef(null);

  const update = (field) => (text) => {
    setValues((v) => ({ ...v, [field]: text }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: null } : prev));
  };

  const requestCode = async () => {
    const problem = emailProblem(values.email);
    if (problem) {
      setErrors({ email: problem });
      return;
    }
    setErrors({});
    setBusy(true);
    const res = await api.forgotPassword(values.email.trim());
    setBusy(false);
    if (!res.ok) {
      if (res.data?.field) setErrors({ [res.data.field]: res.message });
      else toast.push(res.message, 'error');
      return;
    }
    setNote(res.data?.message);
    setStep('code');
  };

  const reset = async () => {
    const next = {};
    if (!values.code.replace(/\D/g, '')) next.code = 'Enter the code from the email.';
    const passwordIssue = passwordProblem(values.password);
    if (passwordIssue) next.password = passwordIssue;
    setErrors(next);
    if (Object.keys(next).length) return;

    setBusy(true);
    const res = await resetPassword(values.email.trim(), values.code, values.password);
    if (res.ok) {
      toast.push(res.data?.message || 'Password changed.', 'success');
      return; // this screen is about to be replaced
    }
    setBusy(false);
    if (res.data?.field) setErrors({ [res.data.field]: res.message });
    else toast.push(res.message, 'error');
  };

  return (
    <AuthShell
      title="Reset your password"
      intro={
        step === 'email'
          ? "Enter the email on your account and we'll send you a code."
          : note || 'Check your email for the code.'
      }
    >
      {step === 'email' ? (
        <>
          <Field
            label="Email"
            value={values.email}
            onChangeText={update('email')}
            error={errors.email}
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="email"
            textContentType="emailAddress"
            keyboardType="email-address"
            inputMode="email"
            returnKeyType="send"
            onSubmitEditing={requestCode}
          />
          <Button
            title={busy ? 'Sending...' : 'Send me a code'}
            size="lg"
            onPress={requestCode}
            busy={busy}
          />
        </>
      ) : (
        <>
          <Field
            label="Code from the email"
            value={values.code}
            onChangeText={update('code')}
            error={errors.code}
            keyboardType="number-pad"
            inputMode="numeric"
            autoComplete="one-time-code"
            textContentType="oneTimeCode"
            maxLength={7}
            returnKeyType="next"
            onSubmitEditing={() => passwordRef.current?.focus()}
            submitBehavior="submit"
          />
          <Field
            ref={passwordRef}
            label="New password"
            value={values.password}
            onChangeText={update('password')}
            error={errors.password}
            secureTextEntry
            autoCapitalize="none"
            autoComplete="new-password"
            textContentType="newPassword"
            returnKeyType="go"
            onSubmitEditing={reset}
          />
          <Button
            title={busy ? 'Saving...' : 'Change password and sign in'}
            size="lg"
            onPress={reset}
            busy={busy}
          />
          <Button
            variant="link"
            size="sm"
            title="No email? Send another code"
            onPress={requestCode}
            disabled={busy}
            style={styles.link}
          />
        </>
      )}
      <Txt variant="small" muted style={styles.back}>
        Remembered it?
      </Txt>
      <Button
        variant="link"
        size="sm"
        title="Back to sign in"
        onPress={() => navigation.navigate('SignIn')}
        style={styles.link}
      />
    </AuthShell>
  );
}

const styles = StyleSheet.create({
  link: { alignSelf: 'center', marginTop: 8 },
  back: { textAlign: 'center', marginTop: 18 },
});
