/**
 * The organiser's controls: a small "Remove" beside each player at the
 * table or in the queue, shown only to an admin. It asks before doing
 * anything - a slip of the thumb mustn't throw someone off the table -
 * and says what will happen to the game and the line. Port of
 * Frontend/src/components/AdminControls.jsx.
 *
 * Hiding these from everyone else is only a courtesy: the server refuses
 * anyone who isn't an admin.
 */
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Feather from '@expo/vector-icons/Feather';

import { useTheme } from '../state/LeagueContext';
import { fonts, radius } from '../theme';
import { Button, Txt } from './ui';

/** The quiet trigger beside a player's name. */
export function RemoveButton({ name, place, expanded, onPress }) {
  const theme = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`Remove ${name} from ${place}`}
      accessibilityState={{ expanded }}
      hitSlop={6}
      style={({ pressed }) => {
        const pointed = expanded || pressed;
        return [
          styles.remove,
          {
            borderColor: pointed ? theme.dangerLine : theme.quietBorder,
            backgroundColor: pointed ? theme.dangerSoft : 'transparent',
          },
        ];
      }}
    >
      <Feather name="user-x" size={13} color={expanded ? theme.danger : theme.textMuted} />
      <Text style={[styles.removeText, { color: expanded ? theme.danger : theme.textMuted }]}>
        Remove
      </Text>
    </Pressable>
  );
}

/** "Remove them?" with what it means, and the safe answer beside it. */
export function RemoveConfirm({ question, consequence, onConfirm, onCancel, busy }) {
  const theme = useTheme();
  return (
    <View
      accessibilityLiveRegion="polite"
      style={[styles.confirm, { backgroundColor: theme.dangerSoft, borderColor: theme.dangerLine }]}
    >
      <Txt weight="bold" color={theme.danger}>
        {question}
      </Txt>
      <Txt variant="small" style={styles.confirmText}>
        {consequence}
      </Txt>
      <View style={styles.actions}>
        <Button variant="danger" size="sm" icon="user-x" title="Remove" onPress={onConfirm} busy={busy} />
        <Button variant="quiet" size="sm" title="Keep them" onPress={onCancel} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  remove: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    minHeight: 32,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderRadius: radius.pill,
  },
  removeText: { fontFamily: fonts.semibold, fontSize: 12.5 },
  confirm: { marginTop: 10, marginBottom: 4, padding: 14, borderWidth: 1, borderRadius: radius.md },
  confirmText: { marginTop: 4, marginBottom: 12 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
