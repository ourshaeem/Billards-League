/**
 * The two cards under the status panel on the Play tab: who is at the
 * league's tables right now, and who is waiting - ports of ActiveTable.jsx
 * and the queue card in Panels.jsx. A league has one queue for all its
 * tables; with more than one table, each table is named, and so is the
 * table a player whose turn has come is called to.
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

export function TablesCard({ tables, loaded, league, currentUserId, onRemove = null, busy = false }) {
  const many = tables.length > 1;
  const playing = tables.filter((t) => t.state !== 'free').length;
  const single = !many ? tables[0] : null;

  return (
    <Card
      title={many ? 'At the tables' : 'At the table'}
      icon="target"
      right={
        loaded && single ? (
          <Pill>{STATE_LABEL[single.state] ?? single.state}</Pill>
        ) : loaded && many ? (
          <Pill>{`${playing} of ${tables.length} in use`}</Pill>
        ) : null
      }
      footer={loaded && playing > 0 ? 'Tap a player to see their profile.' : null}
    >
      {!loaded ? <Txt muted style={styles.empty}>Checking the tables...</Txt> : null}

      {loaded
        ? tables.map((table, index) => (
            <TableBlock
              key={table.table_id}
              table={table}
              showName={many}
              divided={many && index > 0}
              league={league}
              currentUserId={currentUserId}
              onRemove={onRemove}
              busy={busy}
            />
          ))
        : null}
    </Card>
  );
}

function TableBlock({ table, showName, divided, league, currentUserId, onRemove, busy }) {
  const theme = useTheme();
  const state = table.state;
  const occupied = state === 'playing' || state === 'waiting_for_challenger';
  // { userId, matchId } of the player the organiser is asking to remove.
  // Tied to the game it was asked about: once that game is over, the
  // question no longer applies.
  const [asking, setAsking] = useState(null);
  const asked =
    asking && table.match_id === asking.matchId
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
    <View style={[divided && { borderTopWidth: 1, borderTopColor: theme.lineSoft, marginTop: 10, paddingTop: 12 }]}>
      {showName ? (
        <View style={styles.tableHead}>
          <Txt weight="semibold" style={styles.tableName} numberOfLines={1}>
            {table.table_name}
          </Txt>
          <Txt variant="label" color={occupied ? theme.accentText : theme.textMuted}>
            {STATE_LABEL[state] ?? state}
          </Txt>
        </View>
      ) : null}

      {state === 'free' ? (
        <Txt muted style={styles.empty}>
          Nobody is on {table.table_name}. The next two in the queue play here.
        </Txt>
      ) : null}

      {occupied ? (
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
          question={`Take ${asked.username} off ${table.table_name}?`}
          consequence={removalConsequence(table, asked)}
          busy={busy}
          onCancel={() => setAsking(null)}
          onConfirm={async () => {
            await onRemove(asked, table.match_id, table.table_id);
            setAsking(null);
          }}
        />
      ) : null}

      {table.king_streak >= 2 ? (
        <Txt variant="small" muted style={styles.streak}>
          {table.king.username} has won {table.king_streak} in a row
          {table.king_streak >= (table.table_record_streak ?? 0) ? ' - the table record.' : '.'}
        </Txt>
      ) : null}
      <TableRecord table={table} league={league} currentUserId={currentUserId} />
    </View>
  );
}

/** The table's longest winning run, and whose it is - their picture and name. */
function TableRecord({ table, league, currentUserId }) {
  const theme = useTheme();
  const record = table.table_record_streak ?? 0;
  const holder = table.table_record_holder;
  if (record < 2) return null;
  return (
    <View style={[styles.record, { backgroundColor: theme.accentWash }]}>
      <View style={styles.recordHead}>
        <MaterialCommunityIcons name="trophy-outline" size={16} color={theme.accent} />
        <Txt variant="small" muted>
          Table record:{' '}
          <Text style={{ fontFamily: fonts.semibold, color: theme.text }}>{record} wins in a row</Text>
          {holder ? ', by' : '.'}
        </Txt>
      </View>
      {holder ? (
        <PlayerChip player={holder} league={league} size="sm" isYou={holder.user_id === currentUserId} />
      ) : null}
    </View>
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

/**
 * Where someone whose turn has come stands: asked, or confirmed - and,
 * when the league has more than one, at which table.
 */
function turnLabel(entry, showTable) {
  if (!entry.called) return null;
  const where = showTable && entry.table_name ? ` - ${entry.table_name}` : '';
  return entry.confirmed ? `here${where}` : `up${where || ' - confirming'}`;
}

/**
 * A league's queue, split into its lines when it has more than one table:
 * the line for whichever table frees up first, then one for each table
 * someone chose. queue_position is each player's place in their own line.
 */
function linesOf(queue, tables) {
  const lines = [{ key: 'any', title: 'First available table', entries: [] }];
  (tables || []).forEach((t) => lines.push({ key: t.table_id, title: t.table_name, entries: [] }));
  queue.forEach((entry) => {
    const key = entry.target_table_id ?? 'any';
    let line = lines.find((l) => l.key === key);
    if (!line) {
      line = { key, title: entry.target_table_name || 'Another table', entries: [] };
      lines.push(line);
    }
    line.entries.push(entry);
  });
  return lines.filter((l) => l.entries.length > 0);
}

export function QueueCard({
  queue,
  loaded,
  currentUsername,
  onRemove = null,
  busy = false,
  manyTables = false,
  tables = null,
}) {
  const theme = useTheme();
  const openPlayer = useOpenPlayer();
  // user_id of the player the organiser is asking to remove.
  const [asking, setAsking] = useState(null);
  const lines = manyTables ? linesOf(queue, tables) : [{ key: 'any', title: null, entries: queue }];

  const row = (player, index, entries) => {
    const isYou = currentUsername && player.username === currentUsername;
    const place = player.queue_position ?? index + 1;
    const next = place === 1 || player.called;
    const turn = turnLabel(player, manyTables);
    const said = turn ?? (place === 1 ? 'up next' : null);
    const removable = Boolean(onRemove && player.user_id);
    const askingHere = removable && asking === player.user_id;
    const divided = index < entries.length - 1 && { borderBottomWidth: 1, borderBottomColor: theme.lineSoft };
    return (
      <View key={`${player.username}-${player.user_id}`} style={divided}>
        {/* The Remove button sits beside the row, not inside it: a
            button inside a button can't be reached by a screen
            reader, which reads the outer one as a single control. */}
        <View style={styles.queueLine}>
          <Pressable
            onPress={() => openPlayer(player.user_id)}
            disabled={!player.user_id}
            accessibilityRole="button"
            accessibilityLabel={`Number ${place}, ${player.username}${isYou ? ', you' : ''}${said ? `, ${said}` : ''}`}
            accessibilityHint="Opens their profile"
            style={({ pressed }) => [styles.queueRow, pressed && { backgroundColor: theme.accentWash }]}
          >
            <View style={[styles.queuePos, { backgroundColor: next ? theme.accent : theme.fillSoft }]}>
              <Text style={[styles.queuePosText, { color: next ? theme.onAccent : theme.textMuted }]}>
                {place}
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
                  style={[styles.turnTagText, { color: player.confirmed ? theme.onAccent : theme.accentText }]}
                >
                  {turn.toUpperCase()}
                </Text>
              </View>
            ) : place === 1 ? (
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
  };

  return (
    <Card
      title="Waiting to play"
      icon="users"
      right={<Pill>{`${queue.length} ${queue.length === 1 ? 'player' : 'players'}`}</Pill>}
      footer={
        manyTables
          ? "Each table takes the next player who chose it, and only then the next who'll play anywhere. The winner keeps the table. When it's your turn, you have a minute to say you're here."
          : "The winner keeps the table and plays whoever is next in line. When it's your turn, you have a minute to say you're here."
      }
    >
      {!loaded ? <Txt muted style={styles.empty}>Checking the queue...</Txt> : null}

      {loaded && queue.length === 0 ? (
        <Txt muted style={styles.empty}>
          Nobody is waiting. Join and you're first up.
        </Txt>
      ) : null}

      {loaded && queue.length > 0
        ? lines.map((line, lineIndex) => (
            <View key={line.key} style={lineIndex > 0 && styles.lineGap}>
              {line.title ? (
                <View style={[styles.lineHead, { borderBottomColor: theme.line }]}>
                  <Txt variant="label" muted accessibilityRole="header">
                    {line.title.toUpperCase()}
                  </Txt>
                  <Txt variant="small" muted>
                    {`${line.entries.length} waiting`}
                  </Txt>
                </View>
              ) : null}
              {line.entries.map((player, index) => row(player, index, line.entries))}
            </View>
          ))
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
  lineGap: { marginTop: 16 },
  lineHead: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    gap: 10,
    paddingBottom: 6,
    borderBottomWidth: 1,
  },
  record: { marginTop: 12, paddingVertical: 6, paddingHorizontal: 10, borderRadius: radius.md, gap: 4 },
  recordHead: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  tableHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 6 },
  tableName: { flexShrink: 1 },
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
