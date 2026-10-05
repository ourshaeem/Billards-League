/**
 * The two cards under the status panel on the Play tab: who is at the
 * table right now, and who is waiting - ports of ActiveTable.jsx and the
 * queue card in Panels.jsx.
 *
 * Both tell "still loading" apart from "genuinely empty": a list that
 * failed to load must not read as "nobody is waiting".
 *
 * For the organiser (onRemove given), each player has a Remove button,
 * which asks first (AdminControls.js).
 */
import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';

import { useTheme } from '../state/LeagueContext';
import { fonts, radius, type } from '../theme';
import { RemoveButton, RemoveConfirm } from './AdminControls';
import { PlayerChip, useOpenPlayer } from './Player';
import { Card, Pill, Txt } from './ui';

const STATE_LABEL = {
  free: 'Free',
  waiting_for_challenger: 'Waiting',
  playing: 'Game on',
};

/** What taking `player` off the table does, in a sentence. */
function removalConsequence(table, player) {
  if (table.state !== 'playing') return 'The table goes to the next in the queue.';
  const other = player.user_id === table.king?.user_id ? table.challenger : table.king;
  const name = other?.username ?? 'the other player';
  return `Their game with ${name} is called off - nothing is recorded and no points move - and ${name} keeps the table.`;
}

export function ActiveTableCard({ table, loaded, league, tableName, currentUserId, onRemove = null, busy = false }) {
  const state = table?.state;
  const occupied = state === 'playing' || state === 'waiting_for_challenger';
  // { userId, matchId } of the player the organiser is asking to remove.
  // Tied to the game it was asked about: once that game is over, the
  // question no longer applies.
  const [asking, setAsking] = useState(null);
  const asked =
    asking && table?.match_id === asking.matchId
      ? [table.king, table.challenger].find((p) => p?.user_id === asking.userId)
      : null;

  const removal = (player) =>
    onRemove && player
      ? {
          expanded: asked?.user_id === player.user_id,
          onAsk: () =>
            setAsking(
              asked?.user_id === player.user_id ? null : { userId: player.user_id, matchId: table.match_id },
            ),
        }
      : null;

  return (
    <Card
      title="At the table"
      icon="target"
      right={loaded && state ? <Pill>{STATE_LABEL[state] ?? state}</Pill> : null}
      footer={loaded && occupied ? 'Tap a player to see their profile.' : null}
    >
      {!loaded ? <Txt muted style={styles.empty}>Checking the table...</Txt> : null}

      {loaded && state === 'free' ? (
        <Txt muted style={styles.empty}>
          Nobody is on {tableName || 'the table'}. The first two in the queue play.
        </Txt>
      ) : null}

      {loaded && occupied ? (
        <View style={styles.matchup}>
          <Seat
            label="Holding the table"
            crown
            player={table.king}
            league={league}
            currentUserId={currentUserId}
            removal={removal(table.king)}
          />
          <Txt muted style={styles.vs}>
            vs
          </Txt>
          {table.challenger ? (
            <Seat
              label="Challenger"
              player={table.challenger}
              league={league}
              currentUserId={currentUserId}
              removal={removal(table.challenger)}
            />
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

      {asked ? (
        <RemoveConfirm
          question={`Take ${asked.username} off the table?`}
          consequence={removalConsequence(table, asked)}
          busy={busy}
          onCancel={() => setAsking(null)}
          onConfirm={async () => {
            await onRemove(asked, table.match_id);
            setAsking(null);
          }}
        />
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

function Seat({ label, crown = false, player, league, currentUserId, removal }) {
  return (
    <View style={styles.seat}>
      <SeatLabel crown={crown}>{label}</SeatLabel>
      <View style={styles.seatRow}>
        <View style={styles.seatChip}>
          <PlayerChip player={player} league={league} size="lg" isYou={player?.user_id === currentUserId} />
        </View>
        {removal ? (
          <RemoveButton
            name={player.username}
            place="the table"
            expanded={removal.expanded}
            onPress={removal.onAsk}
          />
        ) : null}
      </View>
    </View>
  );
}

/** Where someone whose turn has come stands: asked, or confirmed. */
function turnLabel(entry) {
  if (!entry.called) return null;
  return entry.confirmed ? 'here' : 'up - confirming';
}

export function QueueCard({ queue, loaded, currentUsername, onRemove = null, busy = false }) {
  const theme = useTheme();
  const openPlayer = useOpenPlayer();
  // user_id of the player the organiser is asking to remove.
  const [asking, setAsking] = useState(null);
  return (
    <Card
      title="Waiting to play"
      icon="users"
      right={<Pill>{`${queue.length} ${queue.length === 1 ? 'player' : 'players'}`}</Pill>}
      footer="The winner keeps the table and plays whoever is next in line. When it's your turn, you have a minute to say you're here."
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
            const next = index === 0 || player.called;
            const turn = turnLabel(player);
            const said = turn ?? (index === 0 ? 'up next' : null);
            const removable = Boolean(onRemove && player.user_id);
            const askingHere = removable && asking === player.user_id;
            const divided = index < queue.length - 1 && { borderBottomWidth: 1, borderBottomColor: theme.lineSoft };
            return (
              <View key={`${player.username}-${player.queue_position}`} style={divided}>
                {/* The Remove button sits beside the row, not inside it: a
                    button inside a button can't be reached by a screen
                    reader, which reads the outer one as a single control. */}
                <View style={styles.queueLine}>
                  <Pressable
                    onPress={() => openPlayer(player.user_id)}
                    disabled={!player.user_id}
                    accessibilityRole="button"
                    accessibilityLabel={`Number ${index + 1}, ${player.username}${isYou ? ', you' : ''}${said ? `, ${said}` : ''}`}
                    accessibilityHint="Opens their profile"
                    style={({ pressed }) => [styles.queueRow, pressed && { backgroundColor: theme.accentWash }]}
                  >
                    <View
                      style={[styles.queuePos, { backgroundColor: next ? theme.accent : theme.fillSoft }]}
                    >
                      <Text style={[styles.queuePosText, { color: next ? theme.onAccent : theme.textMuted }]}>
                        {index + 1}
                      </Text>
                    </View>
                    <Txt numberOfLines={1} weight="semibold" style={styles.queueName}>
                      {player.username}
                    </Txt>
                    {isYou ? <YouTag /> : null}
                    {turn ? (
                      <View
                        style={[
                          styles.turnTag,
                          { backgroundColor: player.confirmed ? theme.accent : theme.accentSoft },
                        ]}
                      >
                        <Text
                          style={[
                            styles.turnTagText,
                            { color: player.confirmed ? theme.onAccent : theme.accentText },
                          ]}
                        >
                          {turn.toUpperCase()}
                        </Text>
                      </View>
                    ) : index === 0 ? (
                      <Txt variant="label" color={theme.accentText}>
                        up next
                      </Txt>
                    ) : null}
                  </Pressable>
                  {removable ? (
                    <RemoveButton
                      name={player.username}
                      place="the queue"
                      expanded={askingHere}
                      onPress={() => setAsking(askingHere ? null : player.user_id)}
                    />
                  ) : null}
                </View>
                {askingHere ? (
                  <RemoveConfirm
                    question={`Take ${player.username} out of the queue?`}
                    consequence={
                      player.called
                        ? "It's their turn, so the next in line is up instead."
                        : 'They lose their place in line.'
                    }
                    busy={busy}
                    onCancel={() => setAsking(null)}
                    onConfirm={async () => {
                      await onRemove(player);
                      setAsking(null);
                    }}
                  />
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
  seatRow: { flexDirection: 'row', alignItems: 'center', gap: 10, alignSelf: 'stretch' },
  seatChip: { flexShrink: 1, flexGrow: 1, alignItems: 'flex-start' },
  seatLabelRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  seatLabel: { fontFamily: fonts.semibold, fontSize: 11.5, letterSpacing: 0.5 },
  vs: { fontFamily: fonts.display, fontStyle: 'italic', fontSize: type.large },
  streak: { marginTop: 12 },
  queueLine: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  queueRow: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 50, paddingVertical: 8 },
  queuePos: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center' },
  queuePosText: { fontFamily: fonts.bold, fontSize: type.small, fontVariant: ['tabular-nums'] },
  queueName: { flex: 1 },
  turnTag: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.pill },
  turnTagText: { fontFamily: fonts.bold, fontSize: 10.5, letterSpacing: 0.4 },
  you: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.pill },
  youText: { fontFamily: fonts.semibold, fontSize: 11.5 },
});
