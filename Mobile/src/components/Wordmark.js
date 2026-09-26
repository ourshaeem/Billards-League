/**
 * The league's name with its ball - the 4-ball in billiards, a white
 * ping pong ball in ping pong - and the splash shown while the app reads
 * the saved session at launch.
 */
import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { useTheme } from '../state/LeagueContext';
import { fonts, palette } from '../theme';

/** The current league's ball, drawn from theme tokens. */
export function LeagueBall({ size = 18, theme: override }) {
  const current = useTheme();
  const theme = override ?? current;
  return (
    <View
      accessible={false}
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        backgroundColor: theme.ballFill,
        borderWidth: theme.ballRing === 'transparent' ? 0 : Math.max(1.5, size / 12),
        borderColor: theme.ballRing,
        alignItems: 'center',
        justifyContent: 'center',
        boxShadow: '0px 2px 6px rgba(46, 16, 101, 0.3)',
      }}
    >
      {theme.ballSpot ? (
        <View
          style={{
            width: size * 0.42,
            height: size * 0.42,
            borderRadius: size,
            backgroundColor: theme.ballSpot,
          }}
        />
      ) : null}
    </View>
  );
}

export function Wordmark({ title, size = 26 }) {
  const theme = useTheme();
  return (
    <View style={styles.row} accessibilityRole="header">
      <LeagueBall size={size * 0.62} />
      <Text
        numberOfLines={1}
        style={[styles.title, { fontSize: size, lineHeight: size * 1.2, color: theme.textStrong }]}
      >
        {title}
      </Text>
    </View>
  );
}

export function Splash() {
  return (
    <View style={styles.splash} accessibilityLabel="Loading">
      <ActivityIndicator size="large" color={palette.purple600} />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, flexShrink: 1 },
  title: { fontFamily: fonts.display, flexShrink: 1 },
  splash: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: palette.white },
});
