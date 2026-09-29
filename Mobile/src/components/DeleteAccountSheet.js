/**
 * Deleting your account: says plainly what will happen, asks for the
 * password again, and only then deletes. Both app stores require that
 * an account made in the app can be deleted in the app.
 *
 * onDeleted runs after the server confirms; the Profile screen then
 * signs out.
 */
import React, { useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import * as api from '../api';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { useTheme } from '../state/LeagueContext';
import { fonts, radius, type } from '../theme';
import { Button, Field, Txt } from './ui';

export function DeleteAccountSheet({ visible, onClose, onDeleted }) {
  const theme = useTheme();
  const reducedMotion = useReducedMotion();
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  // Anything that isn't about the password - in a game, server trouble.
  // Shown here, not as a toast: toasts are drawn under this sheet.
  const [problem, setProblem] = useState(null);
  const [busy, setBusy] = useState(false);

  const close = () => {
    if (busy) return;
    setPassword('');
    setError(null);
    setProblem(null);
    onClose();
  };

  const confirm = async () => {
    if (!password) {
      setError('Enter your password to delete your account.');
      return;
    }
    setProblem(null);
    setBusy(true);
    const res = await api.deleteAccount(password);
    setBusy(false);

    if (res.ok) {
      setPassword('');
      onDeleted();
      return;
    }
    // A problem with the password goes beside the field; anything else
    // (in a game, server trouble) above the buttons, in the server's words.
    if (res.data?.field === 'password') setError(res.message);
    else if (res.kind !== api.ErrorKind.AUTH) setProblem(res.message);
  };

  return (
    <Modal
      visible={visible}
      animationType={reducedMotion ? 'none' : 'slide'}
      presentationStyle="pageSheet"
      onRequestClose={close}
    >
      <SafeAreaView style={[styles.sheet, { backgroundColor: theme.page }]} edges={['top', 'bottom']}>
        <KeyboardAvoidingView style={styles.sheet} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
            <Txt variant="display" accessibilityRole="header" color={theme.danger} style={styles.title}>
              Delete your account?
            </Txt>
            <Txt style={styles.paragraph}>
              This removes your username, name, flag, picture and password straight away,
              takes you out of every queue and off the ladders, and signs you out.
            </Txt>
            <Txt style={styles.paragraph}>
              Games you've played stay in other players' history, shown as "Deleted player"
              with nothing that identifies you.
            </Txt>
            <Txt weight="semibold" style={styles.paragraph}>
              This can't be undone.
            </Txt>

            <Field
              label="Your password"
              value={password}
              onChangeText={(text) => {
                setPassword(text);
                setError(null);
              }}
              error={error}
              secureTextEntry
              autoCapitalize="none"
              autoComplete="current-password"
              textContentType="password"
              returnKeyType="done"
              onSubmitEditing={confirm}
            />

            {problem ? (
              <Text
                accessibilityRole="alert"
                accessibilityLiveRegion="polite"
                style={[
                  styles.problem,
                  { color: theme.danger, backgroundColor: theme.dangerSoft, borderColor: theme.dangerLine },
                ]}
              >
                {problem}
              </Text>
            ) : null}

            <View style={styles.actions}>
              <Button
                variant="danger"
                size="lg"
                title={busy ? 'Deleting...' : 'Delete my account'}
                busy={busy}
                onPress={confirm}
              />
              <Button variant="quiet" title="Keep my account" onPress={close} disabled={busy} />
            </View>
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  sheet: { flex: 1 },
  content: { padding: 20, paddingTop: 28, maxWidth: 520, width: '100%', alignSelf: 'center' },
  title: { marginBottom: 14 },
  paragraph: { marginBottom: 12 },
  actions: { gap: 10, marginTop: 8 },
  problem: {
    fontFamily: fonts.regular,
    fontSize: type.small,
    lineHeight: 19,
    padding: 12,
    borderWidth: 1,
    borderRadius: radius.sm,
    overflow: 'hidden',
    marginBottom: 6,
  },
});
