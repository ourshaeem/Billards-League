/**
 * The champions across every school, at the top of the league picker: the
 * top 3 in billiards or ping pong this week, this month or of all time,
 * whichever league they play in (GET /leaderboard/global). Port of
 * Frontend/src/components/GlobalLeaderboard.jsx; on a phone the three
 * timeframes take turns rather than sitting side by side.
 *
 * This week and this month rank by rating points gained; all time by the
 * best rating anyone holds. Tapping a name opens that player's profile.
 */
import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { LEAGUE_ORDER, gameInfo } from '../leagues';
import { useTheme } from '../state/LeagueContext';
import { fonts, type } from '../theme';
import { PlayerChip } from './Player';
import { Card, Segmented, Txt } from './ui';

const TIMEFRAMES = [
  { value: 'week', label: 'This week' },
  { value: 'month', label: 'This month' },
  { value: 'all_time', label: 'All time' },
];
const GAME_OPTIONS = LEAGUE_ORDER.map((key) => ({ value: key, label: gameInfo(key).name }));

function signed(points) {
  return points > 0 ? `+${points}` : String(points);
}

export function GlobalLeaderboard({ champions, currentUserId }) {
  const theme = useTheme();
  const [game, setGame] = useState(LEAGUE_ORDER[0]);
  const [timeframe, setTimeframe] = useState('week');
  const places = champions?.sports?.[game]?.[timeframe] ?? [];

  return (
    <Card
      title="Champions"
      icon="award"
      footer="This week and this month: most points gained, in every school's league. All time: the best rating anyone holds."
      style={[styles.card, { borderTopColor: theme.accent }]}
    >
      <View style={styles.switches}>
        <Segmented options={GAME_OPTIONS} value={game} onChange={setGame} accessibilityLabel="Which game" />
        <Segmented
          options={TIMEFRAMES}
          value={timeframe}
          onChange={setTimeframe}
          accessibilityLabel="Which timeframe"
        />
      </View>

      {!champions ? (
        <Txt muted style={styles.empty}>
          Loading the champions...
        </Txt>
      ) : null}

      {champions && places.length === 0 ? (
        <Txt muted style={styles.empty}>
          {timeframe === 'all_time' ? 'No games played yet.' : 'Nobody has won a game yet.'}
        </Txt>
      ) : null}

      {places.map((place, index) => {
        const first = place.place === 1;
        const value = timeframe === 'all_time' ? String(place.elo) : signed(place.points);
        return (
          <View
            key={place.player.user_id}
            style={[
              styles.row,
              index < places.length - 1 && { borderBottomWidth: 1, borderBottomColor: theme.lineSoft },
            ]}
          >
            <View style={[styles.place, { backgroundColor: first ? theme.accent : theme.fillSoft }]}>
              <Text style={[styles.placeText, { color: first ? theme.onAccent : theme.textMuted }]}>
                {place.place}
              </Text>
            </View>
            <View style={styles.who}>
              <PlayerChip
                player={place.player}
                league={{ league_id: place.league_id, name: place.league_name, game }}
                size="sm"
                isYou={place.player.user_id === currentUserId}
              />
              <Txt variant="small" muted style={styles.school}>
                {place.school}
              </Txt>
            </View>
            <View style={styles.value} accessible accessibilityLabel={`${value} points, ${place.wins} won, ${place.losses} lost`}>
              <Text style={[styles.points, { color: theme.text }]}>
                {value} <Text style={[styles.pts, { color: theme.textMuted }]}>pts</Text>
              </Text>
              <Txt variant="small" muted>
                {place.wins}–{place.losses}
              </Txt>
            </View>
          </View>
        );
      })}
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { borderTopWidth: 4 },
  switches: { gap: 8, marginBottom: 8 },
  empty: { paddingVertical: 12 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8 },
  place: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  placeText: { fontFamily: fonts.bold, fontSize: type.small, fontVariant: ['tabular-nums'] },
  who: { flex: 1, minWidth: 0, alignItems: 'flex-start' },
  school: { paddingLeft: 4, marginTop: -2 },
  value: { alignItems: 'flex-end' },
  points: { fontFamily: fonts.bold, fontSize: type.body, fontVariant: ['tabular-nums'] },
  pts: { fontFamily: fonts.regular, fontSize: type.small },
});
