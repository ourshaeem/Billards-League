/**
 * The two cards under the status panel on the Play tab: who is at the
 * table right now, and who is waiting - ports of ActiveTable.jsx and the
 * queue card in Panels.jsx.
 *
 * Both tell "still loading" apart from "genuinely empty": a list that
 * failed to load must not read as "nobody is waiting".
 */
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';

import { useTheme } from '../state/LeagueContext';
import { fonts, radius, type } from '../theme';
import { PlayerChip } from './Player';
import { Card, Pill, Txt } from './ui';

const STATE_LABEL = {
  free: 'Free',
  waiting_for_challenger: 'Waiting',
  playing: 'Game on',
};

export function ActiveTableCard({ table, loaded, league, tableName, currentUserId }) {
  const state = table?.state;
  const occupied = state === 'playing' || state === 'waiting_for_challenger';

  return (
    <Card
      title="At the table"
      icon="target"
      right={loaded && state ? <Pill>{STATE_LABEL[state] ?? state}</Pill> : null}
      footer={loaded && occupied ? 'Tap a player to see their rank and rating.' : null}
    >
      {!loaded ? <Txt muted style={styles.empty}>Checking the table...</Txt> : null}

      {loaded && state === 'free' ? (
        <Txt muted style={styles.empty}>
          Nobody is on {tableName || 'the table'}. The first two in the queue play.
        </Txt>
      ) : null}

      {loaded && occupied ? (
        <View style={styles.matchup}>
          <Seat label="Holding the table" crown player={table.king} league={league} currentUserId={currentUserId} />
          <Txt muted style={styles.vs}>
            vs
          </Txt>
          {table.challenger ? (
            <Seat label="Challenger" player={table.challenger} league={league} currentUserId={currentUserId} />
          ) : (
            <View style={styles.seat}>
              <SeatLabel>Challenger</SeatLabel>
              <Txt variant="small" muted style={styles.italic}>
                Next in the queue
              </Txt>
            </View>
          )}
        </View>
      ) : null}

      {loaded && table?.king_streak >= 2 ? (
        <Txt variant="small" muted style={styles.streak}>
          {table.king.username} has won {table.king_streak} in a row.
        </Txt>
      ) : null}
    </Card>
  );
}

function SeatLabel({ crown, children }) {
  const theme = useTheme();
  return (
    <View style={styles.seatLabelRow}>
      {crown ? <MaterialCommunityIcons name="crown-outline" size={14} color={theme.accent} /> : null}
      <Text style={[styles.seatLabel, { color: theme.textMuted }]}>{children.toUpperCase()}</Text>
    </View>
  );
}

function Seat({ label, crown = false, player, league, currentUserId }) {
  return (
    <View style={styles.seat}>
      <SeatLabel crown={crown}>{label}</SeatLabel>
      <PlayerChip player={player} league={league} size="lg" isYou={player?.user_id === currentUserId} />
    </View>
  );
}

export function QueueCard({ queue, loaded, currentUsername }) {
  const theme = useTheme();
  return (
    <Card
      title="Waiting to play"
      icon="users"
      right={<Pill>{`${queue.length} ${queue.length === 1 ? 'player' : 'players'}`}</Pill>}
      footer="The winner keeps the table and plays whoever is next in line."
    >
      {!loaded ? <Txt muted style={styles.empty}>Checking the queue...</Txt> : null}

      {loaded && queue.length === 0 ? (
        <Txt muted style={styles.empty}>
          Nobody is waiting. Join and you're first up.
        </Txt>
      ) : null}

      {loaded && queue.length > 0
        ? queue.map((player, index) => {
            const isYou = currentUsername && player.username === currentUsername;
            const next = index === 0;
            return (
              <View
                key={`${player.username}-${player.queue_position}`}
                accessibilityLabel={`Number ${index + 1}, ${player.username}${isYou ? ', you' : ''}${next ? ', up next' : ''}`}
                accessible
                style={[
                  styles.queueRow,
                  index < queue.length - 1 && { borderBottomWidth: 1, borderBottomColor: theme.lineSoft },
                ]}
              >
                <View
                  style={[styles.queuePos, { backgroundColor: next ? theme.accent : theme.lineSoft }]}
                >
                  <Text style={[styles.queuePosText, { color: next ? theme.onAccent : theme.textMuted }]}>
                    {index + 1}
                  </Text>
                </View>
                <Txt numberOfLines={1} style={styles.queueName}>
                  {player.username}
                </Txt>
                {isYou ? <YouTag /> : null}
                {next ? (
                  <Txt variant="label" color={theme.accent}>
                    up next
                  </Txt>
                ) : null}
              </View>
            );
          })
        : null}
    </Card>
  );
}

export function YouTag() {
  const theme = useTheme();
  return (
    <View style={[styles.you, { backgroundColor: theme.accent }]}>
      <Text style={[styles.youText, { color: theme.onAccent }]}>you</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  empty: { paddingVertical: 12 },
  italic: { fontStyle: 'italic' },
  matchup: { gap: 10, paddingVertical: 4 },
  seat: { gap: 6, alignItems: 'flex-start' },
  seatLabelRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  seatLabel: { fontFamily: fonts.semibold, fontSize: 11.5, letterSpacing: 0.5 },
  vs: { fontFamily: fonts.display, fontStyle: 'italic', fontSize: type.large },
  streak: { marginTop: 12 },
  queueRow: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 50, paddingVertical: 8 },
  queuePos: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center' },
  queuePosText: { fontFamily: fonts.bold, fontSize: type.small, fontVariant: ['tabular-nums'] },
  queueName: { flex: 1 },
  you: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.pill },
  youText: { fontFamily: fonts.semibold, fontSize: 11.5 },
});
