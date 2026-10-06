/**
 * The league's name with its ball - the 4-ball in billiards, a white
 * ping pong ball in ping pong - and the splash shown while the app reads
 * the saved session at launch.
 */
import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View, useColorScheme } from 'react-native';

import { useTheme } from '../state/LeagueContext';
import { fonts, themeFor } from '../theme';

/**
 * The current league's ball, drawn from theme tokens. color repaints it -
 * the 4-ball's fill, the ping pong ball's ring - for a ball drawn on the
 * status panel's colour rather than the page's.
 */
export function LeagueBall({ size = 18, theme: override, color }) {
  const current = useTheme();
  const theme = override ?? current;
  const ring = color && theme.ballRing !== 'transparent' ? color : theme.ballRing;
  const fill = color && theme.ballRing === 'transparent' ? color : theme.ballFill;
  return (
    <View
      accessible={false}
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        backgroundColor: fill,
        borderWidth: ring === 'transparent' ? 0 : Math.max(1.5, size / 12),
        borderColor: ring,
        alignItems: 'center',
        justifyContent: 'center',
        boxShadow: '0px 2px 6px rgba(0, 0, 0, 0.25)',
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

/**
 * Shown for a moment at launch, before the saved settings are read - so
 * it follows the phone's own light or dark setting.
 */
export function Splash() {
  const colors = themeFor(null, useColorScheme() === 'dark' ? 'dark' : 'light');
  return (
    <View style={[styles.splash, { backgroundColor: colors.page }]} accessibilityLabel="Loading">
      <ActivityIndicator size="large" color={colors.accent} />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, flexShrink: 1 },
  title: { fontFamily: fonts.display, flexShrink: 1 },
  splash: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
