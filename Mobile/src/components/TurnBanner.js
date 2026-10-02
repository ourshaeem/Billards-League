/**
 * "It's your turn" over every screen but Play, whose status panel says it
 * already. A player looking at the ladder or someone's profile when their
 * turn comes still has only a minute to answer, so the answer is right
 * here: "I'm here", or a jump to the table.
 *
 * Drawn by RootNavigator above the screens, just over the tab bar (or the
 * bottom of the screen, where there is none).
 */
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Feather from '@expo/vector-icons/Feather';

import { useTheme } from '../state/LeagueContext';
import { useLive } from '../state/LiveContext';
import { fonts, palette, radius, type } from '../theme';

// Where the banner has nothing to add, or would cover something that
// needs answering first.
const HIDDEN_ON = new Set(['Play', 'SwitchLeague', 'ChooseLeague', 'SignIn', 'Register']);

export function TurnBanner({ routeName, overTabs, tabBarHeight, onGoToTable }) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { matchStatus, confirm, busy } = useLive();

  const yourTurn = matchStatus?.status === 'your_turn' && !matchStatus.confirmed;
  if (!yourTurn || !routeName || HIDDEN_ON.has(routeName)) return null;

  const opponent = matchStatus.opponent;
  return (
    <View
      pointerEvents="box-none"
      style={[styles.wrap, { bottom: insets.bottom + (overTabs ? tabBarHeight : 0) + 10 }]}
    >
      <View
        accessibilityLiveRegion="polite"
        style={[styles.banner, { backgroundColor: theme.accent }]}
      >
        <View style={styles.message}>
          <Feather name="bell" size={18} color={theme.onAccent} />
          <Text style={[styles.text, { color: theme.onAccent }]}>
            <Text style={styles.strong}>It's your turn</Text>
            {opponent ? ` against ${opponent}` : ''} - say you're here within the minute.
          </Text>
        </View>
        <View style={styles.actions}>
          <Pressable
            onPress={confirm}
            disabled={busy}
            accessibilityRole="button"
            accessibilityLabel="I'm here"
            style={({ pressed }) => [
              styles.button,
              { backgroundColor: pressed ? theme.accentWash : palette.white },
              busy && styles.disabled,
            ]}
          >
            <Text style={[styles.buttonText, { color: palette.purple800 }]}>I'm here</Text>
          </Pressable>
          <Pressable
            onPress={onGoToTable}
            accessibilityRole="button"
            accessibilityLabel="Go to the table"
            style={({ pressed }) => [
              styles.button,
              styles.quiet,
              pressed && { backgroundColor: 'rgba(255, 255, 255, 0.16)' },
            ]}
          >
            <Text style={[styles.buttonText, { color: theme.onAccent }]}>Go to the table</Text>
          </Pressable>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: 'absolute', left: 12, right: 12, zIndex: 50 },
  banner: {
    borderRadius: radius.md,
    padding: 12,
    gap: 10,
    boxShadow: '0px 10px 28px rgba(0, 0, 0, 0.3)',
  },
  message: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  text: { flex: 1, fontFamily: fonts.regular, fontSize: type.small, lineHeight: 19 },
  strong: { fontFamily: fonts.semibold },
  actions: { flexDirection: 'row', gap: 8 },
  button: {
    flex: 1,
    minHeight: 44,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 10,
  },
  quiet: { borderWidth: 1, borderColor: 'rgba(255, 255, 255, 0.55)' },
  buttonText: { fontFamily: fonts.semibold, fontSize: type.body },
  disabled: { opacity: 0.6 },
});
