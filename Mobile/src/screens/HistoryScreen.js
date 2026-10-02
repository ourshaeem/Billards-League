/**
 * The Games tab: finished games in this league, newest first -
 * everyone's, or just yours. Port of MatchHistory.jsx.
 *
 * Fetched while the tab is on screen: every 15 seconds, and straight
 * away when LiveContext sees a game end (gamesVersion).
 */
import React, { useCallback, useState } from 'react';
import { StyleSheet } from 'react-native';
import { useIsFocused } from '@react-navigation/native';

import * as api from '../api';
import { HISTORY_LIMIT, SLOW_POLL_INTERVAL_MS } from '../config';
import { GameRow } from '../components/GameRow';
import { Card, Screen, Segmented, Txt } from '../components/ui';
import { useAppActive } from '../hooks/useAppActive';
import { usePolling } from '../hooks/usePolling';
import { useLeague } from '../state/LeagueContext';
import { useLive } from '../state/LiveContext';
import { useSession } from '../state/SessionContext';

const SCOPES = [
  { value: 'all', label: 'Everyone' },
  { value: 'mine', label: 'Your games' },
];

function emptyFor(key) {
  return { key, all: [], mine: [], loaded: false, problem: null };
}

export function HistoryScreen() {
  const { league } = useLeague();
  const { user } = useSession();
  const { gamesVersion } = useLive();
  const focused = useIsFocused();
  const active = useAppActive();
  const [scope, setScope] = useState('all');
  const [refreshing, setRefreshing] = useState(false);

  // Games belong to one player in one league; switching either drops
  // the old list at once rather than showing it under the new name.
  const key = `${user?.user_id}:${league}`;
  const [data, setData] = useState(() => emptyFor(key));
  if (data.key !== key) setData(emptyFor(key));

  const userId = user?.user_id;
  const load = useCallback(
    async (signal) => {
      const [allRes, mineRes] = await Promise.all([
        api.getMatchHistory(league, { limit: HISTORY_LIMIT }, signal),
        userId ? api.getPlayerMatches(userId, league, { limit: HISTORY_LIMIT }, signal) : null,
      ]);
      if (signal?.aborted || allRes.aborted) return;
      setData((current) => {
        if (current.key !== key) return current;
        if (!allRes.ok) {
          // Keep showing what loaded before; only an empty screen needs
          // to explain itself.
          return current.loaded ? current : { ...current, problem: allRes.message };
        }
        return {
          key,
          all: allRes.data?.matches ?? [],
          mine: mineRes?.ok ? (mineRes.data?.matches ?? []) : current.mine,
          loaded: true,
          problem: null,
        };
      });
    },
    // gamesVersion isn't read inside, but a new value means a game just
    // ended: fetch again now rather than at the next tick.
    [key, league, userId, gamesVersion],
  );

  usePolling(load, SLOW_POLL_INTERVAL_MS, focused && active && Boolean(league));

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const matches = scope === 'mine' ? data.mine : data.all;

  return (
    <Screen onRefresh={onRefresh} refreshing={refreshing}>
      <Card
        title="Recent games"
        icon="clock"
        right={
          <Segmented
            options={SCOPES}
            value={scope}
            onChange={setScope}
            accessibilityLabel="Whose games to show"
          />
        }
        footer={data.loaded && matches.length > 0 ? 'Tap a player to see their profile and games.' : null}
      >
        {!data.loaded ? (
          <Txt muted style={styles.empty}>
            {data.problem ? `${data.problem} Retrying automatically.` : 'Loading recent games...'}
          </Txt>
        ) : null}

        {data.loaded && matches.length === 0 ? (
          <Txt muted style={styles.empty}>
            {scope === 'mine'
              ? "You haven't finished a game in this league yet."
              : 'No games finished yet. The first result shows up here.'}
          </Txt>
        ) : null}

        {data.loaded &&
          matches.map((match, index) => (
            <GameRow
              key={match.match_id}
              match={match}
              league={league}
              currentUserId={user?.user_id}
              last={index === matches.length - 1}
            />
          ))}
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  empty: { paddingVertical: 12 },
});
