/**
 * The frame around sign in and registration: the app's name at the top,
 * then a card. Shared so the two screens can't drift apart.
 */
import React from 'react';
import { StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ConnectionBanner } from '../components/Feedback';
import { Card, Screen, Txt } from '../components/ui';
import { Wordmark } from '../components/Wordmark';
import { useLeague } from '../state/LeagueContext';

export function AuthShell({ title, intro, children }) {
  const { theme, unreachable } = useLeague();
  return (
    <SafeAreaView edges={['top']} style={[styles.flex, { backgroundColor: theme.page }]}>
      <Screen contentStyle={styles.content}>
        <View style={styles.brand}>
          <Wordmark title="Billiards & Ping Pong" size={30} />
        </View>
        <ConnectionBanner offline={unreachable} />
        <Card>
          <Txt variant="title" accessibilityRole="header" style={styles.title}>
            {title}
          </Txt>
          <Txt variant="small" muted style={styles.intro}>
            {intro}
          </Txt>
          {children}
        </Card>
      </Screen>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { paddingTop: 28, maxWidth: 460, width: '100%', alignSelf: 'center' },
  brand: { marginBottom: 24, alignItems: 'center' },
  title: { marginBottom: 6 },
  intro: { marginBottom: 20 },
});
