/**
 * Which league is this session for? Shown straight after signing in
 * (route ChooseLeague), and as a modal from the header's Switch league
 * button (route SwitchLeague).
 *
 * At the top, the champions across every school. Then the schools, each
 * a tile in its own colours; choosing one shows its two leagues -
 * billiards and ping pong - and dresses the screen in that school's
 * colours (ThemeOverride), so the choice and the league look like one
 * thing before it's even made. The player's standing in each league
 * they're in appears once their profile has loaded, and a league whose PIN
 * they haven't entered says so: they can still go in and look.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Feather from '@expo/vector-icons/Feather';
import { useIsFocused } from '@react-navigation/native';

import * as api from '../api';
import { ConnectionBanner } from '../components/Feedback';
import { GlobalLeaderboard } from '../components/GlobalLeaderboard';
import { Button, Screen, Txt } from '../components/ui';
import { LeagueBall } from '../components/Wordmark';
import { bySchool, gameInfo } from '../leagues';
import { useAppearance } from '../state/AppearanceContext';
import { ThemeOverride, useLeague } from '../state/LeagueContext';
import { usePolling } from '../hooks/usePolling';
import { useSession } from '../state/SessionContext';
import { pointsText } from '../format';
import { fonts, radius, themeFor, type } from '../theme';

// The champions change only when a game ends.
const CHAMPIONS_REFRESH_MS = 60000;

export function LeagueSelectScreen({ navigation, route }) {
  const { chooseLeague, user, signOut } = useSession();
  const { leagueId: current, leagues, unreachable } = useLeague();
  const { scheme } = useAppearance();
  const [profile, setProfile] = useState(null);
  const isModal = route.name === 'SwitchLeague';
  const focused = useIsFocused();

  // The school whose leagues are showing: the current league's at first.
  const groups = bySchool(leagues);
  const currentSchool = leagues?.find((l) => l.league_id === current)?.school ?? null;
  const [picked, setPicked] = useState(null);
  const school = picked ?? currentSchool;
  const group = groups.find((g) => g.school === school) ?? null;
  const pageTheme = themeFor(group ? group.leagues[0] : null, scheme);

  const [champions, setChampions] = useState(null);
  const loadChampions = useCallback(async (signal) => {
    const res = await api.getGlobalLeaderboard(signal);
    if (signal?.aborted || res.aborted) return;
    if (res.ok && res.data?.sports) setChampions(res.data);
  }, []);
  usePolling(loadChampions, CHAMPIONS_REFRESH_MS, focused);

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
    <ThemeOverride theme={pageTheme}>
      <Screen contentStyle={styles.content}>
        <GlobalLeaderboard champions={champions} currentUserId={user?.user_id} />

        <View style={styles.head}>
          <Txt variant="display" accessibilityRole="header" color={pageTheme.textStrong} style={styles.center}>
            Which league are you playing?
          </Txt>
          <Txt muted style={styles.center}>
            Pick your school, then billiards or ping pong. You can switch any time.
          </Txt>
        </View>

        <ConnectionBanner offline={unreachable && !leagues} />

        {!leagues && !unreachable ? (
          <Txt muted style={styles.center}>
            Loading the leagues...
          </Txt>
        ) : null}

        <View style={styles.schoolGrid} accessibilityRole="radiogroup" accessibilityLabel="Schools">
          {groups.map((g) => (
            <SchoolTile
              key={g.school}
              group={g}
              preview={themeFor(g.leagues[0], scheme)}
              ring={pageTheme.accent}
              selected={g.school === school}
              current={g.school === currentSchool}
              onPress={() => setPicked(g.school)}
            />
          ))}
        </View>

        {group ? (
          <View style={styles.school}>
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
        ) : leagues ? (
          <Txt muted style={[styles.center, styles.hint]}>
            Choose a school to see its leagues.
          </Txt>
        ) : null}

        {!isModal ? (
          <View style={styles.signedIn}>
            <Txt variant="small" muted>
              Signed in as {user?.username}.
            </Txt>
            <Button variant="link" size="sm" title="Sign out" onPress={signOut} />
          </View>
        ) : null}
      </Screen>
    </ThemeOverride>
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

/** A school, in its own colours: tap to see its two leagues. */
function SchoolTile({ group, preview, ring, selected, current, onPress }) {
  const games = group.leagues.map((l) => gameInfo(l.game).name).join(' · ');
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="radio"
      accessibilityState={{ checked: selected, selected }}
      accessibilityLabel={`${group.school}${current ? ', your league now' : ''}`}
      accessibilityHint={`Shows ${group.school}'s ${games} leagues`}
      style={({ pressed }) => [
        styles.tile,
        {
          backgroundColor: preview.panelBg,
          borderColor: selected ? ring : preview.panelBorder,
          borderWidth: selected ? 3 : 1,
          boxShadow: preview.panelShadow,
          transform: [{ scale: pressed ? 0.98 : 1 }],
        },
      ]}
    >
      <View style={[styles.edge, { height: preview.panelEdgeSize, backgroundColor: preview.panelEdge }]} />
      <Text style={[styles.tileName, { color: preview.panelText }]} numberOfLines={2}>
        {group.school}
      </Text>
      <Text style={[styles.tileGames, { color: preview.panelDim }]}>{games}</Text>
      {current ? (
        <Text style={[styles.current, styles.tileCurrent, { color: preview.panelText, borderColor: preview.panelText }]}>
          Yours now
        </Text>
      ) : null}
    </Pressable>
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
  hint: { marginBottom: 16 },
  schoolGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginBottom: 22 },
  tile: {
    flexGrow: 1,
    flexBasis: '45%',
    minHeight: 92,
    borderRadius: radius.lg,
    padding: 14,
    paddingTop: 16,
    gap: 3,
    overflow: 'hidden',
  },
  tileName: { fontFamily: fonts.display, fontSize: 22, lineHeight: 25 },
  tileGames: { fontFamily: fonts.regular, fontSize: 12 },
  tileCurrent: { alignSelf: 'flex-start', marginTop: 6, fontSize: 11 },
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
