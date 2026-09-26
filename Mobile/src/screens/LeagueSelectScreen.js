/**
 * Which league is this session for? Shown straight after signing in
 * (route ChooseLeague), and as a modal from the header's Switch league
 * button (route SwitchLeague).
 *
 * Each option wears its own league's colours, so the choice and the
 * screens that follow look like the same thing. The player's standing
 * in each league appears once their profile has loaded.
 */
import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import * as api from '../api';
import { ConnectionBanner } from '../components/Feedback';
import { Button, Screen, Txt } from '../components/ui';
import { LeagueBall } from '../components/Wordmark';
import { LEAGUE_ORDER, LEAGUES } from '../leagues';
import { useLeague } from '../state/LeagueContext';
import { useSession } from '../state/SessionContext';
import { fonts, radius, themeFor, type } from '../theme';

export function LeagueSelectScreen({ navigation, route }) {
  const { league: current, chooseLeague, user, signOut } = useSession();
  const { tables, unreachable } = useLeague();
  const [profile, setProfile] = useState(null);
  const isModal = route.name === 'SwitchLeague';

  useEffect(() => {
    const controller = new AbortController();
    api.getProfile(controller.signal).then((res) => {
      if (!controller.signal.aborted && res.ok) setProfile(res.data?.profile ?? null);
    });
    return () => controller.abort();
  }, []);

  const choose = (key) => {
    chooseLeague(key);
    // After sign-in the navigator moves on by itself; as a modal, close.
    if (isModal) navigation.goBack();
  };

  const content = (
    <Screen contentStyle={styles.content}>
      <View style={styles.head}>
        <Txt variant="display" accessibilityRole="header" color={themeFor(null).textStrong} style={styles.center}>
          Which league are you playing?
        </Txt>
        <Txt muted style={styles.center}>
          This sets the queue, scores and ladder you see. You can switch any time.
        </Txt>
      </View>

      <ConnectionBanner offline={unreachable && !tables} />

      {LEAGUE_ORDER.map((key) => {
        const info = LEAGUES[key];
        const preview = themeFor(key);
        const standing = profile?.leagues?.[key];
        const table = tables?.[key];
        // A league the venue hasn't given a table can't be played yet.
        const noTable = Boolean(tables) && !table?.table_id;
        const isCurrent = current === key;
        const textColor = preview.panelText;
        const dim = preview.panelDim;

        return (
          <Pressable
            key={key}
            onPress={() => choose(key)}
            disabled={noTable}
            accessibilityRole="button"
            accessibilityLabel={`${info.name}${isCurrent ? ', current league' : ''}`}
            accessibilityHint={info.blurb}
            accessibilityState={{ disabled: noTable, selected: isCurrent }}
            style={({ pressed }) => [
              styles.option,
              {
                backgroundColor: preview.panelBg,
                borderColor: preview.panelBorder,
                boxShadow: preview.panelShadow,
                opacity: noTable ? 0.6 : 1,
                transform: [{ scale: pressed ? 0.985 : 1 }],
              },
            ]}
          >
            <View style={[styles.edge, { height: preview.panelEdgeSize, backgroundColor: preview.panelEdge }]} />
            <LeagueBall size={44} theme={preview} />
            <Text style={[styles.name, { color: textColor }]}>{info.name}</Text>
            <Text style={[styles.blurb, { color: dim }]}>{info.blurb}</Text>
            {standing ? (
              <View style={styles.standing}>
                <Text style={[styles.standingStrong, { color: textColor }]}>{standing.rank_name}</Text>
                <Text style={[styles.standingText, { color: dim }]}>{standing.elo} points</Text>
                <Text style={[styles.standingText, { color: dim }]}>
                  {standing.wins}–{standing.losses}
                </Text>
              </View>
            ) : null}
            <View style={styles.foot}>
              <Text style={[styles.footText, { color: dim }]}>
                {noTable ? 'No table set up yet' : table?.table_name ? `Plays on ${table.table_name}` : ' '}
              </Text>
              {isCurrent ? (
                <Text style={[styles.current, { color: textColor, borderColor: textColor }]}>Current</Text>
              ) : null}
            </View>
          </Pressable>
        );
      })}

      {!isModal ? (
        <View style={styles.signedIn}>
          <Txt variant="small" muted>
            Signed in as {user?.username}.
          </Txt>
          <Button variant="link" size="sm" title="Sign out" onPress={signOut} />
        </View>
      ) : null}
    </Screen>
  );

  // As a modal the navigator draws the header; straight after sign-in
  // there is none, so keep clear of the status bar.
  if (isModal) return content;
  return (
    <SafeAreaView edges={['top']} style={styles.flex}>
      {content}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { maxWidth: 520, width: '100%', alignSelf: 'center', paddingTop: 24 },
  head: { gap: 8, marginBottom: 22 },
  center: { textAlign: 'center' },
  option: {
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: 24,
    marginBottom: 16,
    gap: 8,
    overflow: 'hidden',
  },
  edge: { position: 'absolute', top: 0, left: 0, right: 0 },
  name: { fontFamily: fonts.display, fontSize: 34, lineHeight: 38, marginTop: 6 },
  blurb: { fontFamily: fonts.regular, fontSize: type.body, lineHeight: 22 },
  standing: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 8 },
  standingStrong: { fontFamily: fonts.bold, fontSize: type.small },
  standingText: { fontFamily: fonts.regular, fontSize: type.small, fontVariant: ['tabular-nums'] },
  foot: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginTop: 4 },
  footText: { fontFamily: fonts.regular, fontSize: type.small, flexShrink: 1 },
  current: {
    fontFamily: fonts.bold,
    fontSize: type.small,
    paddingHorizontal: 10,
    paddingVertical: 2,
    borderWidth: 1,
    borderRadius: radius.pill,
    overflow: 'hidden',
  },
  signedIn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 4, marginTop: 8 },
});
