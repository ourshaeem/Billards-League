/**
 * Another player's profile: who they are, where they stand in both
 * leagues, their games - against everyone, against one opponent, and
 * against you. Port of Frontend/src/components/PlayerProfile.jsx.
 *
 * Opened by tapping a player anywhere (useOpenPlayer in Player.js), on
 * top of the tabs; the back button returns to where they were. Their real
 * name is never here: the server doesn't send it to anyone else.
 */
import React, { useEffect, useLayoutEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import * as api from '../api';
import { GameRow } from '../components/GameRow';
import { Avatar } from '../components/Player';
import { Button, Card, Screen, Segmented, Txt } from '../components/ui';
import { flagEmoji } from '../flags';
import { LEAGUE_ORDER, LEAGUES } from '../leagues';
import { useLeague } from '../state/LeagueContext';
import { useSession } from '../state/SessionContext';
import { pointsText } from '../format';
import { fonts, radius, type } from '../theme';

const GAMES_LIMIT = 30;
const HEAD_TO_HEAD_LIMIT = 10;
const LEAGUE_OPTIONS = LEAGUE_ORDER.map((key) => ({ value: key, label: LEAGUES[key].name }));

export function PlayerScreen({ route, navigation }) {
  const { userId } = route.params;
  const { league: screenLeague } = useLeague();
  const { user } = useSession();
  const [league, setLeague] = useState(screenLeague || LEAGUE_ORDER[0]);
  const [player, setPlayer] = useState(null);
  const [problem, setProblem] = useState(null);
  const currentUserId = user?.user_id ?? null;

  useEffect(() => {
    const controller = new AbortController();
    api.getPlayer(userId, controller.signal).then((res) => {
      if (controller.signal.aborted || res.aborted) return;
      if (res.ok && res.data?.player) setPlayer(res.data.player);
      else setProblem(res.message);
    });
    return () => controller.abort();
  }, [userId]);

  // The header says whose profile this is once it's known.
  useLayoutEffect(() => {
    navigation.setOptions({ title: player?.username ?? '' });
  }, [navigation, player]);

  if (problem || !player) {
    return (
      <Screen>
        <Card>
          <Txt muted>{problem ?? 'Loading their profile...'}</Txt>
        </Card>
      </Screen>
    );
  }

  const flag = flagEmoji(player.country_flag);
  const isYou = player.user_id === currentUserId;

  return (
    <Screen>
      <Card>
        <View style={styles.head}>
          <Avatar player={player} size="xl" label={`Picture of ${player.username}`} />
          <View style={styles.headText}>
            <Txt variant="title" accessibilityRole="header">
              {player.username}
              {flag ? ` ${flag}` : ''}
            </Txt>
            {isYou ? (
              <Txt variant="small" muted>
                This is how other players see you.
              </Txt>
            ) : null}
          </View>
        </View>
        <Standings leagues={player.leagues} highlight={league} />
      </Card>

      <View style={styles.switch}>
        <Segmented
          options={LEAGUE_OPTIONS}
          value={league}
          onChange={setLeague}
          accessibilityLabel="Which league's games to show"
        />
      </View>

      {/* Keyed so a change of league starts each part over, rather than
          showing one league's numbers under the other's name. */}
      <PlayerGames
        key={`${userId}-${league}`}
        player={player}
        league={league}
        currentUserId={currentUserId}
      />
    </Screen>
  );
}

function Standings({ leagues, highlight }) {
  const { theme } = useLeague();
  return (
    <View>
      {LEAGUE_ORDER.map((key, index) => {
        const standing = leagues?.[key];
        return (
          <View
            key={key}
            accessible
            accessibilityLabel={`${LEAGUES[key].name}: ${standing?.rank_name ?? 'Unranked'}, ${pointsText(standing?.elo)}, ${standing?.wins ?? 0} won, ${standing?.losses ?? 0} lost`}
            style={[
              styles.standingRow,
              index < LEAGUE_ORDER.length - 1 && { borderBottomWidth: 1, borderBottomColor: theme.lineSoft },
              key === highlight && { backgroundColor: theme.accentWash },
            ]}
          >
            <View style={styles.standingName}>
              <Txt weight="semibold">{LEAGUES[key].name}</Txt>
              <Txt variant="small" muted>
                {standing?.rank_name ?? 'Unranked'}
              </Txt>
            </View>
            <Text style={[styles.number, { color: theme.text, fontFamily: fonts.bold }]}>
              {standing?.elo ?? 0}
            </Text>
            <Text style={[styles.number, { color: theme.textMuted }]}>
              <Text style={{ color: theme.accentText, fontFamily: fonts.semibold }}>
                {standing?.wins ?? 0}
              </Text>
              –{standing?.losses ?? 0}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

/**
 * One player's games in one league: against you, their record against
 * each opponent, and the games themselves - all of them, or just those
 * against the opponent picked from the record.
 */
function PlayerGames({ player, league, currentUserId }) {
  const { theme } = useLeague();
  const userId = player.user_id;
  const isYou = userId === currentUserId;
  const [opponents, setOpponents] = useState(null);
  const [vsYou, setVsYou] = useState(null);
  const [against, setAgainst] = useState(null);
  const [problem, setProblem] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    Promise.all([
      api.getPlayerOpponents(userId, league, signal),
      !isYou && currentUserId
        ? api.getPlayerMatches(
            userId,
            league,
            { limit: HEAD_TO_HEAD_LIMIT, opponentId: currentUserId },
            signal,
          )
        : null,
    ]).then(([opponentsRes, vsYouRes]) => {
      if (signal.aborted || opponentsRes.aborted) return;
      if (!opponentsRes.ok) {
        setProblem(opponentsRes.message);
        return;
      }
      setOpponents(opponentsRes.data?.opponents ?? []);
      if (vsYouRes?.ok) setVsYou(vsYouRes.data?.matches ?? []);
    });
    return () => controller.abort();
  }, [userId, league, isYou, currentUserId]);

  if (problem) {
    return (
      <Card>
        <Txt muted>{problem}</Txt>
      </Card>
    );
  }

  const yourRecord = opponents?.find((o) => o.opponent?.user_id === currentUserId);
  const leagueName = LEAGUES[league].name;

  return (
    <>
      {!isYou && currentUserId ? (
        <Card title={`You vs ${player.username}`} icon="crosshair">
          {opponents === null || vsYou === null ? (
            <Txt muted style={styles.empty}>
              Loading your games against each other...
            </Txt>
          ) : !yourRecord ? (
            <Txt muted style={styles.empty}>
              You haven't played {player.username} in the {leagueName} yet.
            </Txt>
          ) : (
            <>
              <View
                accessible
                accessibilityLabel={`You ${yourRecord.losses}, ${player.username} ${yourRecord.wins}`}
                style={styles.h2h}
              >
                <Side
                  number={yourRecord.losses}
                  label="You"
                  leading={yourRecord.losses > yourRecord.wins}
                />
                <Text style={[styles.h2hDash, { color: theme.textMuted }]}>–</Text>
                <Side
                  number={yourRecord.wins}
                  label={player.username}
                  leading={yourRecord.wins > yourRecord.losses}
                />
              </View>
              {vsYou.map((match, index) => (
                <GameRow
                  key={match.match_id}
                  match={match}
                  league={league}
                  currentUserId={currentUserId}
                  subject={player.username}
                  last={index === vsYou.length - 1}
                />
              ))}
            </>
          )}
        </Card>
      ) : null}

      <Card
        title={isYou ? 'Your record against everyone' : `${player.username}'s record`}
        icon="users"
        footer={
          opponents?.length
            ? `Wins first, from ${isYou ? 'your' : `${player.username}'s`} side. Tap someone to see just the games between them.`
            : null
        }
      >
        {opponents === null ? (
          <Txt muted style={styles.empty}>
            Loading their record...
          </Txt>
        ) : null}
        {opponents?.length === 0 ? (
          <Txt muted style={styles.empty}>
            No games in the {leagueName} yet.
          </Txt>
        ) : null}
        {opponents?.map(({ opponent, wins, losses }, index) => {
          const selected = against?.user_id === opponent.user_id;
          const name = opponent.user_id === currentUserId ? 'You' : opponent.username;
          return (
            <Pressable
              key={opponent.user_id}
              onPress={() => setAgainst(selected ? null : opponent)}
              accessibilityRole="button"
              accessibilityState={{ selected }}
              accessibilityLabel={`${name}: ${wins} won, ${losses} lost`}
              accessibilityHint={selected ? 'Shows all games again' : 'Shows just the games between them'}
              style={({ pressed }) => [
                styles.opponentRow,
                index < opponents.length - 1 && { borderBottomWidth: 1, borderBottomColor: theme.lineSoft },
                (selected || pressed) && { backgroundColor: theme.accentSoft },
                selected && { borderLeftWidth: 3, borderLeftColor: theme.accent },
              ]}
            >
              <Avatar player={opponent} size="sm" />
              <Txt weight="semibold" numberOfLines={1} style={styles.opponentName}>
                {name}
              </Txt>
              <Text style={[styles.number, { color: theme.textMuted }]}>
                <Text style={{ color: theme.accentText, fontFamily: fonts.semibold }}>{wins}</Text>–
                {losses}
              </Text>
            </Pressable>
          );
        })}
      </Card>

      {/* Keyed by the opponent picked, so a new pick starts from "Loading"
          rather than showing the last pick's games under the new name. */}
      <Games
        key={against?.user_id ?? 'everyone'}
        player={player}
        league={league}
        currentUserId={currentUserId}
        against={against}
        onShowAll={() => setAgainst(null)}
      />
    </>
  );
}

function Side({ number, label, leading }) {
  const { theme } = useLeague();
  return (
    <View style={styles.h2hSide}>
      <Text style={[styles.h2hNumber, { color: leading ? theme.accentText : theme.textMuted }]}>
        {number}
      </Text>
      <Txt variant="small" weight="semibold" muted numberOfLines={1} style={styles.h2hLabel}>
        {label}
      </Txt>
    </View>
  );
}

/** "alice's games", "Your games against bob", "alice's games against you". */
function gamesTitle(subject, opponentName) {
  const whose = subject ? `${subject}'s` : 'Your';
  return opponentName ? `${whose} games against ${opponentName}` : `${whose} games`;
}

function Games({ player, league, currentUserId, against, onShowAll }) {
  const [games, setGames] = useState(null);
  const [problem, setProblem] = useState(null);
  const userId = player.user_id;
  const againstId = against?.user_id ?? null;
  const subject = userId === currentUserId ? null : player.username;

  useEffect(() => {
    const controller = new AbortController();
    api
      .getPlayerMatches(
        userId,
        league,
        { limit: GAMES_LIMIT, opponentId: againstId ?? undefined },
        controller.signal,
      )
      .then((res) => {
        if (controller.signal.aborted || res.aborted) return;
        if (res.ok) setGames(res.data?.matches ?? []);
        else setProblem(res.message);
      });
    return () => controller.abort();
  }, [userId, league, againstId]);

  const opponentName = againstId === currentUserId ? 'you' : against?.username;

  return (
    <Card
      title={gamesTitle(subject, against ? opponentName : null)}
      icon="clock"
      right={
        against ? <Button variant="quiet" size="sm" title="Show all" onPress={onShowAll} /> : null
      }
    >
      {problem ? (
        <Txt muted style={styles.empty}>
          {problem}
        </Txt>
      ) : null}
      {!problem && games === null ? (
        <Txt muted style={styles.empty}>
          Loading games...
        </Txt>
      ) : null}
      {games?.length === 0 ? (
        <Txt muted style={styles.empty}>
          No finished games to show.
        </Txt>
      ) : null}
      {games?.map((match, index) => (
        <GameRow
          key={match.match_id}
          match={match}
          league={league}
          currentUserId={currentUserId}
          subject={subject}
          last={index === games.length - 1}
        />
      ))}
    </Card>
  );
}

const styles = StyleSheet.create({
  head: { flexDirection: 'row', alignItems: 'center', gap: 16, marginBottom: 14 },
  headText: { flex: 1, gap: 2 },
  switch: { marginBottom: 16 },
  empty: { paddingVertical: 12 },
  standingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    minHeight: 56,
    paddingVertical: 8,
    paddingHorizontal: 6,
    borderRadius: radius.sm,
  },
  standingName: { flex: 1 },
  number: {
    fontFamily: fonts.regular,
    fontSize: type.body,
    fontVariant: ['tabular-nums'],
    minWidth: 44,
    textAlign: 'right',
  },
  h2h: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'center',
    gap: 18,
    marginBottom: 6,
  },
  h2hSide: { alignItems: 'center', maxWidth: 140 },
  h2hNumber: { fontFamily: fonts.display, fontSize: 52, lineHeight: 58, fontVariant: ['tabular-nums'] },
  h2hDash: { fontFamily: fonts.display, fontSize: 34, lineHeight: 52 },
  h2hLabel: { textAlign: 'center' },
  opponentRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minHeight: 50,
    paddingVertical: 8,
    paddingHorizontal: 8,
  },
  opponentName: { flex: 1 },
});
