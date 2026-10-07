/**
 * The league's name with its ball - the 8-ball in billiards, a white
 * ping pong ball in ping pong - and the splash shown while the app reads
 * the saved session at launch.
 */
import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View, useColorScheme } from 'react-native';

import { useTheme } from '../state/LeagueContext';
import { fonts, themeFor } from '../theme';

// The 8-ball's own colours, the same in every league and every theme.
const EIGHT_BALL = '#0b0b0e';
const EIGHT_BALL_CIRCLE = '#ffffff';

/**
 * The current league's ball, drawn from theme tokens: the 8-ball in
 * billiards (theme.ballSpot set), the ping pong ball otherwise. color
 * repaints the ring round it - for a ball drawn on the status panel's
 * colour rather than the page's.
 */
export function LeagueBall({ size = 18, theme: override, color }) {
  const current = useTheme();
  const theme = override ?? current;
  if (theme.ballSpot) return <EightBall size={size} ring={color ?? theme.ballFill} />;
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

/**
 * Glossy black, with its white circle and 8, ringed in the league's colour
 * - which also keeps it visible on a dark screen. No gradients in React
 * Native, so the light is drawn in layers: a soft sheen over the upper
 * half, and a shine at the top left, over everything.
 */
function EightBall({ size, ring }) {
  const circle = size * 0.46;
  return (
    <View
      accessible={false}
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        backgroundColor: EIGHT_BALL,
        borderWidth: Math.max(1.5, size / 15),
        borderColor: ring,
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        boxShadow: '0px 2px 6px rgba(0, 0, 0, 0.35)',
      }}
    >
      <View
        style={{
          position: 'absolute',
          top: -size * 0.22,
          left: -size * 0.18,
          width: size * 0.95,
          height: size * 0.95,
          borderRadius: size,
          backgroundColor: 'rgba(255, 255, 255, 0.09)',
        }}
      />
      <View
        style={{
          width: circle,
          height: circle,
          borderRadius: circle / 2,
          marginTop: -size * 0.1,
          backgroundColor: EIGHT_BALL_CIRCLE,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text
          allowFontScaling={false}
          style={{
            fontFamily: fonts.bold,
            fontSize: circle * 0.74,
            lineHeight: circle * 0.9,
            color: EIGHT_BALL,
            textAlign: 'center',
            includeFontPadding: false,
          }}
        >
          8
        </Text>
      </View>
      <View
        style={{
          position: 'absolute',
          top: size * 0.08,
          left: size * 0.14,
          width: size * 0.32,
          height: size * 0.16,
          borderRadius: size,
          backgroundColor: 'rgba(255, 255, 255, 0.5)',
          transform: [{ rotate: '-35deg' }],
        }}
      />
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
