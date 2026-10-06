/**
 * Which league is this session for? Shown straight after signing in
 * (route ChooseLeague), and as a modal from the header's Switch league
 * button (route SwitchLeague).
 *
 * Every league, grouped by school (GET /leagues/directory). Each option
 * wears its own league's colours, so the choice and the screens that
 * follow look like the same thing. The player's standing in each league
 * they're in appears once their profile has loaded, and a league whose PIN
 * they haven't entered says so: they can still go in and look.
 */
import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Feather from '@expo/vector-icons/Feather';

import * as api from '../api';
import { ConnectionBanner } from '../components/Feedback';
import { Button, Screen, Txt } from '../components/ui';
import { LeagueBall } from '../components/Wordmark';
import { bySchool, gameInfo } from '../leagues';
import { useAppearance } from '../state/AppearanceContext';
import { useLeague } from '../state/LeagueContext';
import { useSession } from '../state/SessionContext';
import { pointsText } from '../format';
import { fonts, radius, themeFor, type } from '../theme';

export function LeagueSelectScreen({ navigation, route }) {
  const { chooseLeague, user, signOut } = useSession();
  const { leagueId: current, leagues, unreachable } = useLeague();
  const { scheme } = useAppearance();
  const [profile, setProfile] = useState(null);
  const isModal = route.name === 'SwitchLeague';

  useEffect(() => {
    const controller = new AbortController();
    api.getProfile(controller.signal).then((res) => {
      if (!controller.signal.aborted && res.ok) setProfile(res.data?.profile ?? null);
    });
    return () => controller.abort();
  }, []);

  const choose = (leagueId) => {
    chooseLeague(leagueId);
    // After sign-in the navigator moves on by itself; as a modal, close.
    if (isModal) navigation.goBack();
  };

  const content = (
    <Screen contentStyle={styles.content}>
      <View style={styles.head}>
        <Txt variant="display" accessibilityRole="header" color={themeFor(null, scheme).textStrong} style={styles.center}>
          Which league are you playing?
        </Txt>
        <Txt muted style={styles.center}>
          This sets the queue, scores and ladder you see. You can switch any time.
        </Txt>
      </View>

      <ConnectionBanner offline={unreachable && !leagues} />

      {!leagues && !unreachable ? (
        <Txt muted style={styles.center}>
          Loading the leagues...
        </Txt>
      ) : null}

      {bySchool(leagues).map((group) => (
        <View key={group.school} style={styles.school}>
          <Txt variant="label" muted accessibilityRole="header" style={styles.schoolName}>
            {group.school.toUpperCase()}
          </Txt>
          {group.leagues.map((league) => (
            <LeagueOption
              key={league.league_id}
              league={league}
              preview={themeFor(league, scheme)}
              current={current === league.league_id}
              standing={profile?.standings?.find((st) => st.league_id === league.league_id)}
              onChoose={choose}
            />
          ))}
        </View>
      ))}

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

function LeagueOption({ league, preview, current, standing, onChoose }) {
  const info = gameInfo(league.game);
  const tables = league.tables || [];
  // A league with no table can't be played yet.
  const noTable = tables.length === 0;
  const textColor = preview.panelText;
  const dim = preview.panelDim;
  const lock = league.read_only ? (league.has_pin ? 'PIN needed to play' : 'No PIN set yet') : null;

  return (
    <Pressable
      onPress={() => onChoose(league.league_id)}
      disabled={noTable}
      accessibilityRole="button"
      accessibilityLabel={`${league.name}${current ? ', current league' : ''}${lock ? `, ${lock}` : ''}`}
      accessibilityHint={info.blurb}
      accessibilityState={{ disabled: noTable, selected: current }}
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
      <View style={styles.nameRow}>
        <LeagueBall size={30} theme={preview} color={preview.panelCtaBg} />
        <Text style={[styles.name, { color: textColor }]}>{league.name}</Text>
      </View>
      <Text style={[styles.blurb, { color: dim }]}>{info.blurb}</Text>
      {standing ? (
        <View style={styles.standing}>
          <Text style={[styles.standingStrong, { color: textColor }]}>{standing.rank_name}</Text>
          <Text style={[styles.standingText, { color: dim }]}>{pointsText(standing.elo)}</Text>
          <Text style={[styles.standingText, { color: dim }]}>
            {standing.wins}–{standing.losses}
          </Text>
        </View>
      ) : null}
      <View style={styles.foot}>
        <Text style={[styles.footText, { color: dim }]}>
          {noTable
            ? 'No table set up yet'
            : tables.length === 1
              ? `Plays on ${tables[0].table_name}`
              : `${tables.length} tables`}
        </Text>
        {lock ? (
          <View style={styles.lock}>
            <Feather name="lock" size={13} color={textColor} />
            <Text style={[styles.lockText, { color: textColor }]}>{lock}</Text>
          </View>
        ) : null}
        {current ? (
          <Text style={[styles.current, { color: textColor, borderColor: textColor }]}>Current</Text>
        ) : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { maxWidth: 520, width: '100%', alignSelf: 'center', paddingTop: 24 },
  head: { gap: 8, marginBottom: 22 },
  center: { textAlign: 'center' },
  school: { marginBottom: 10 },
  schoolName: { marginBottom: 8, letterSpacing: 0.6 },
  option: {
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: 20,
    paddingTop: 22,
    marginBottom: 12,
    gap: 6,
    overflow: 'hidden',
  },
  edge: { position: 'absolute', top: 0, left: 0, right: 0 },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  name: { fontFamily: fonts.display, fontSize: 28, lineHeight: 32, flexShrink: 1 },
  blurb: { fontFamily: fonts.regular, fontSize: type.body, lineHeight: 22 },
  standing: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 8 },
  standingStrong: { fontFamily: fonts.bold, fontSize: type.small },
  standingText: { fontFamily: fonts.regular, fontSize: type.small, fontVariant: ['tabular-nums'] },
  foot: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12, marginTop: 4 },
  lock: { flexDirection: 'row', alignItems: 'center', gap: 5, marginLeft: 'auto' },
  lockText: { fontFamily: fonts.semibold, fontSize: type.small },
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
