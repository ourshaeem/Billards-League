/**
 * The Ladder tab: the league's top 50. Port of the web leaderboard card.
 * Fetched while the tab is on screen, and straight away when a game ends.
 */
import React, { useCallback, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useIsFocused } from '@react-navigation/native';

import * as api from '../api';
import { SLOW_POLL_INTERVAL_MS } from '../config';
import { YouTag } from '../components/TableCards';
import { Card, Screen, Txt } from '../components/ui';
import { useAppActive } from '../hooks/useAppActive';
import { usePolling } from '../hooks/usePolling';
import { useLeague } from '../state/LeagueContext';
import { useLive } from '../state/LiveContext';
import { useSession } from '../state/SessionContext';
import { fonts, type } from '../theme';

export function LadderScreen() {
  const { league, theme } = useLeague();
  const { user } = useSession();
  const { gamesVersion } = useLive();
  const focused = useIsFocused();
  const active = useAppActive();
  const [refreshing, setRefreshing] = useState(false);

  const [data, setData] = useState(() => ({ league, players: [], loaded: false, problem: null }));
  if (data.league !== league) setData({ league, players: [], loaded: false, problem: null });

  const load = useCallback(
    async (signal) => {
      const res = await api.getLeaderboard(league, signal);
      if (signal?.aborted || res.aborted) return;
      setData((current) => {
        if (current.league !== league) return current;
        if (!res.ok) return current.loaded ? current : { ...current, problem: res.message };
        return { league, players: Array.isArray(res.data) ? res.data : [], loaded: true, problem: null };
      });
    },
    // gamesVersion isn't read inside, but a new value means a game just
    // ended: fetch again now rather than at the next tick.
    [league, gamesVersion],
  );

  usePolling(load, SLOW_POLL_INTERVAL_MS, focused && active && Boolean(league));

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const { players } = data;

  return (
    <Screen onRefresh={onRefresh} refreshing={refreshing}>
      <Card title="League ladder" icon="bar-chart-2">
        {!data.loaded ? (
          <Txt muted style={styles.empty}>
            {data.problem ? `${data.problem} Retrying automatically.` : 'Loading the ladder...'}
          </Txt>
        ) : null}

        {data.loaded && players.length === 0 ? (
          <Txt muted style={styles.empty}>
            No games played yet. The first result starts the ladder.
          </Txt>
        ) : null}

        {data.loaded && players.length > 0 ? (
          <>
            <View style={[styles.row, styles.headRow, { borderBottomColor: theme.line }]}>
              <HeadCell style={styles.place}>#</HeadCell>
              <HeadCell style={styles.player}>Player</HeadCell>
              <HeadCell style={styles.number}>Points</HeadCell>
              <HeadCell style={styles.number}>W–L</HeadCell>
              <HeadCell style={styles.rate}>Win %</HeadCell>
            </View>
            {players.map((player, index) => {
              const played = (player.total_wins || 0) + (player.total_losses || 0);
              const winRate = played > 0 ? Math.round((player.total_wins / played) * 100) : null;
              const isYou = player.username === user?.username;
              return (
                <View
                  key={player.username}
                  accessible
                  accessibilityLabel={`${index + 1}, ${player.username}${isYou ? ', you' : ''}, ${player.rank_name || 'Unranked'}, ${player.elo_rating} points, ${player.total_wins} won, ${player.total_losses} lost`}
                  style={[
                    styles.row,
                    { borderBottomColor: theme.lineSoft },
                    isYou && { backgroundColor: theme.accentWash, borderLeftColor: theme.accent, borderLeftWidth: 3 },
                  ]}
                >
                  <Cell style={styles.place} muted>
                    {index + 1}
                  </Cell>
                  <View style={styles.player}>
                    <View style={styles.nameRow}>
                      <Txt numberOfLines={1} style={styles.name}>
                        {player.username}
                      </Txt>
                      {isYou ? <YouTag /> : null}
                    </View>
                    <Txt variant="small" muted>
                      {player.rank_name || 'Unranked'}
                    </Txt>
                  </View>
                  <Cell style={[styles.number, styles.points]}>{player.elo_rating}</Cell>
                  <Text style={[styles.cell, styles.number]}>
                    <Text style={{ color: theme.accentPressed, fontFamily: fonts.semibold }}>{player.total_wins}</Text>
                    <Text style={{ color: theme.textMuted }}>–{player.total_losses}</Text>
                  </Text>
                  {/* A win rate off zero games would read as 0%, harsher than
                      the truth: they simply haven't played. */}
                  <Cell style={styles.rate} muted={winRate === null}>
                    {winRate === null ? '—' : `${winRate}%`}
                  </Cell>
                </View>
              );
            })}
          </>
        ) : null}
      </Card>
    </Screen>
  );
}

function HeadCell({ style, children }) {
  const { theme } = useLeague();
  return <Text style={[styles.cell, styles.head, { color: theme.textMuted }, style]}>{children}</Text>;
}

function Cell({ style, muted, children }) {
  const { theme } = useLeague();
  return (
    <Text style={[styles.cell, { color: muted ? theme.textMuted : theme.text }, style]}>{children}</Text>
  );
}

const styles = StyleSheet.create({
  empty: { paddingVertical: 12 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    minHeight: 56,
    paddingVertical: 8,
    paddingHorizontal: 4,
    borderBottomWidth: 1,
  },
  headRow: { minHeight: 32, paddingVertical: 4 },
  cell: { fontFamily: fonts.regular, fontSize: type.body, fontVariant: ['tabular-nums'] },
  head: { fontFamily: fonts.semibold, fontSize: type.small },
  place: { width: 26 },
  player: { flex: 1, minWidth: 0 },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  name: { flexShrink: 1 },
  number: { width: 52, textAlign: 'right' },
  points: { fontFamily: fonts.bold },
  rate: { width: 46, textAlign: 'right' },
});
