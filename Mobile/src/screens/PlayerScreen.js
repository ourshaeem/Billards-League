/**
 * Another player's profile: who they are, where they stand in each league
 * they're in, their games there - against everyone, against one opponent,
 * and against you. Port of Frontend/src/components/PlayerProfile.jsx.
 * Tapping one of their leagues shows their games in it.
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
import { Button, Card, Screen, Txt } from '../components/ui';
import { flagEmoji } from '../flags';
import { useLeague } from '../state/LeagueContext';
import { useSession } from '../state/SessionContext';
import { pointsText } from '../format';
import { fonts, radius, type } from '../theme';

const GAMES_LIMIT = 30;
const HEAD_TO_HEAD_LIMIT = 10;

export function PlayerScreen({ route, navigation }) {
  const { userId } = route.params;
  const { league: screenLeague, leagues } = useLeague();
  const { user } = useSession();
  const [leagueId, setLeagueId] = useState(screenLeague?.league_id ?? null);
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
  // The leagues to show: every one they have numbers in, and the one on
  // screen even if they've never played there.
  const standings = player.standings || [];
  const choices = (leagues || []).filter(
    (l) => standings.some((st) => st.league_id === l.league_id) || l.league_id === screenLeague?.league_id,
  );
  const league = choices.find((l) => l.league_id === leagueId) ?? choices[0] ?? screenLeague;

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
        <Standings
          choices={choices}
          standings={standings}
          selected={league?.league_id}
          onSelect={setLeagueId}
        />
      </Card>

      {/* Keyed so a change of league starts each part over, rather than
          showing one league's numbers under the other's name. */}
      {league ? (
        <PlayerGames
          key={`${userId}-${league.league_id}`}
          player={player}
          league={league}
          currentUserId={currentUserId}
        />
      ) : null}
    </Screen>
  );
}

/**
 * Their standing in each league to show, one row each. With more than one,
 * a row is also how to pick the league whose games show below.
 */
function Standings({ choices, standings, selected, onSelect }) {
  const { theme } = useLeague();
  const many = choices.length > 1;
  if (!choices.length) {
    return (
      <Txt muted style={styles.empty}>
        Not on any ladder yet.
      </Txt>
    );
  }
  return (
    <View>
      {choices.map((league, index) => {
        const standing = standings.find((st) => st.league_id === league.league_id);
        const isSelected = league.league_id === selected;
        return (
          <Pressable
            key={league.league_id}
            onPress={() => onSelect(league.league_id)}
            disabled={!many}
            accessibilityRole={many ? 'button' : undefined}
            accessibilityState={many ? { selected: isSelected } : undefined}
            accessibilityHint={many ? 'Shows their games in this league' : undefined}
            accessibilityLabel={`${league.name}: ${standing?.rank_name ?? 'Unranked'}, ${pointsText(standing?.elo)}, ${standing?.wins ?? 0} won, ${standing?.losses ?? 0} lost`}
            style={({ pressed }) => [
              styles.standingRow,
              index < choices.length - 1 && { borderBottomWidth: 1, borderBottomColor: theme.lineSoft },
              (isSelected || pressed) && many && { backgroundColor: theme.accentWash },
              isSelected && many && { borderLeftWidth: 3, borderLeftColor: theme.accent },
            ]}
          >
            <View style={styles.standingName}>
              <Txt weight="semibold">{league.name}</Txt>
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
          </Pressable>
        );
      })}
      {many ? (
        <Txt variant="small" muted style={styles.standingHint}>
          Tap a league to see their games there.
        </Txt>
      ) : null}
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
  const leagueId = league.league_id;
  const isYou = userId === currentUserId;
  const [opponents, setOpponents] = useState(null);
  const [vsYou, setVsYou] = useState(null);
  const [against, setAgainst] = useState(null);
  const [problem, setProblem] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    Promise.all([
      api.getPlayerOpponents(userId, leagueId, signal),
      !isYou && currentUserId
        ? api.getPlayerMatches(
            userId,
            leagueId,
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
  }, [userId, leagueId, isYou, currentUserId]);

  if (problem) {
    return (
      <Card>
        <Txt muted>{problem}</Txt>
      </Card>
    );
  }

  const yourRecord = opponents?.find((o) => o.opponent?.user_id === currentUserId);
  const leagueName = league.name;

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
              You haven't played {player.username} in {leagueName} yet.
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
                  league={leagueId}
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
            No games in {leagueName} yet.
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
  const leagueId = league.league_id;
  const againstId = against?.user_id ?? null;
  const subject = userId === currentUserId ? null : player.username;

  useEffect(() => {
    const controller = new AbortController();
    api
      .getPlayerMatches(
        userId,
        leagueId,
        { limit: GAMES_LIMIT, opponentId: againstId ?? undefined },
        controller.signal,
      )
      .then((res) => {
        if (controller.signal.aborted || res.aborted) return;
        if (res.ok) setGames(res.data?.matches ?? []);
        else setProblem(res.message);
      });
    return () => controller.abort();
  }, [userId, leagueId, againstId]);

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
          league={leagueId}
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
  standingHint: { marginTop: 8 },
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
