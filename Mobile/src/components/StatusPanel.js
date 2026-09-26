/**
 * The status panel: the one question anyone opens this app to answer -
 * can I play right now? The React Native port of
 * Frontend/src/components/StatusPanel.jsx, with the same states and the
 * same wording:
 *
 *   loading                - the server hasn't answered yet
 *   idle                   - not queued, not playing
 *   queued                 - waiting for an opponent
 *   waiting_for_challenger - won the last game, holding the table
 *   playing                - a game is on, report the score
 *
 * `league` is the league on screen. A game or a held table is reported
 * with its own league_type, which can be the other league; the scorecard
 * always follows the game's league, never the screen's.
 */
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import Feather from '@expo/vector-icons/Feather';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';

import { leagueInfo } from '../leagues';
import { useTheme } from '../state/LeagueContext';
import { fonts, radius, type } from '../theme';
import { Button, Field, FieldError } from './ui';

export function StatusPanel({
  status,
  problem,
  league,
  tableName,
  queueLength,
  onJoin,
  onLeave,
  onRecord,
  onStepDown,
  onSwitchLeague,
  busy,
}) {
  const theme = useTheme();
  const state = status ? status.status || 'idle' : 'loading';
  const elsewhere =
    (state === 'playing' || state === 'waiting_for_challenger') &&
    status.league_type &&
    status.league_type !== league
      ? status.league_type
      : null;

  return (
    // No accessibilityState busy here, though the panel is briefly
    // loading: Android kept describing it as "busy" long after, because
    // the description isn't cleared when the state goes away. The loading
    // text and spinner already tell a screen reader what's happening.
    <View
      style={[
        styles.panel,
        {
          backgroundColor: state === 'playing' ? theme.panelBgPlaying : theme.panelBg,
          borderColor: theme.panelBorder,
          boxShadow: theme.panelShadow,
        },
      ]}
    >
      {/* Along the top edge: a faint highlight on the purple billiards
          panel, a purple band on the white ping pong one. */}
      <View style={[styles.edge, { height: theme.panelEdgeSize, backgroundColor: theme.panelEdge }]} />

      {problem ? (
        <Note>{`${problem} What you see below may be out of date - retrying automatically.`}</Note>
      ) : null}
      {elsewhere ? (
        <Note>
          This is your game in the {leagueInfo(elsewhere).name}.{' '}
          <Text
            accessibilityRole="link"
            onPress={() => onSwitchLeague(elsewhere)}
            style={[styles.inlineLink, { color: theme.panelText }]}
          >
            Switch to that league
          </Text>
        </Note>
      ) : null}

      {state === 'loading' && <LoadingState />}
      {state === 'playing' && (
        <PlayingState
          key={status.match_id}
          status={status}
          league={status.league_type || league}
          onRecord={onRecord}
          busy={busy}
        />
      )}
      {state === 'waiting_for_challenger' && (
        <HoldingTableState queueLength={queueLength} onStepDown={onStepDown} busy={busy} />
      )}
      {state === 'queued' && (
        <QueuedState status={status} onLeave={onLeave} busy={busy} queueLength={queueLength} />
      )}
      {state === 'idle' && (
        <IdleState onJoin={onJoin} busy={busy} queueLength={queueLength} tableName={tableName} />
      )}
    </View>
  );
}

// --- Text on the panel, in the panel's colours ---

function Headline({ icon, iconSet = 'community', children }) {
  const theme = useTheme();
  const Icon = iconSet === 'feather' ? Feather : MaterialCommunityIcons;
  return (
    <Text accessibilityRole="header" style={[styles.headline, { color: theme.panelText }]}>
      {icon ? (
        <>
          <Icon name={icon} size={30} color={theme.panelIcon} />{' '}
        </>
      ) : null}
      {children}
    </Text>
  );
}

function Sub({ children, style }) {
  const theme = useTheme();
  return <Text style={[styles.sub, { color: theme.panelDim }, style]}>{children}</Text>;
}

function Meta({ icon, children }) {
  const theme = useTheme();
  return (
    <View style={styles.meta}>
      <Feather name={icon} size={16} color={theme.panelDim} />
      <Text style={[styles.metaText, { color: theme.panelDim }]}>{children}</Text>
    </View>
  );
}

function Note({ children }) {
  const theme = useTheme();
  return (
    <Text
      accessibilityLiveRegion="polite"
      style={[
        styles.note,
        { color: theme.panelText, backgroundColor: theme.panelFill, borderColor: theme.panelLine },
      ]}
    >
      {children}
    </Text>
  );
}

// --- States ---

function LoadingState() {
  const theme = useTheme();
  return (
    <>
      <Headline>Checking the table…</Headline>
      <View style={styles.loadingRow}>
        <ActivityIndicator color={theme.panelDim} />
        <Sub style={styles.flush}>Finding out whether you're queued, playing or free.</Sub>
      </View>
    </>
  );
}

function IdleState({ onJoin, busy, queueLength, tableName }) {
  return (
    <>
      <Headline>{tableName || 'The table'} is open to you</Headline>
      <Sub>
        {queueLength === 0
          ? 'Nobody is waiting. Join and you play as soon as someone else does.'
          : `${queueLength} ${queueLength === 1 ? 'player is' : 'players are'} waiting. Join the line to get a game.`}
      </Sub>
      <Button
        title={busy ? 'Joining...' : 'Join the queue'}
        variant="panelPrimary"
        size="lg"
        onPress={onJoin}
        disabled={busy}
      />
    </>
  );
}

function QueuedState({ status, onLeave, busy, queueLength }) {
  const unlockIn = status.leave_unlocks_in ?? 0;

  // The countdown ticks locally so the number moves every second rather
  // than lurching with each poll. It's display only - the server
  // enforces the wait, so drift here can't let anyone leave early.
  const [prevUnlockIn, setPrevUnlockIn] = useState(unlockIn);
  const [secondsLeft, setSecondsLeft] = useState(unlockIn);

  // Adjusting state during render when a prop changes, which React
  // recommends over mirroring props into state inside an effect. Each
  // poll re-syncs this to the server's number.
  if (unlockIn !== prevUnlockIn) {
    setPrevUnlockIn(unlockIn);
    setSecondsLeft(unlockIn);
  }

  useEffect(() => {
    if (secondsLeft <= 0) return undefined;
    const timer = setInterval(() => {
      setSecondsLeft((remaining) => Math.max(0, remaining - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [secondsLeft]);

  const canLeave = secondsLeft <= 0;
  const position = status.queue_position;
  const ahead = Math.max(0, (position ?? 1) - 1);

  return (
    <>
      <Headline>{ahead === 0 ? "You're up next" : `You're number ${position} in line`}</Headline>
      <Sub>
        {ahead === 0
          ? 'Stay close to the table. You go on as soon as an opponent is free.'
          : `${ahead} ${ahead === 1 ? 'player' : 'players'} ahead of you. This screen updates on its own.`}
      </Sub>

      <View style={styles.actions}>
        <Meta icon="users">{`${queueLength} in the queue`}</Meta>
        <Button
          variant="panelQuiet"
          onPress={onLeave}
          disabled={!canLeave || busy}
          waiting={!canLeave}
          icon={canLeave ? undefined : 'clock'}
          title={canLeave ? 'Leave the queue' : `Leave in ${secondsLeft}s`}
          // The countdown explains a disabled button rather than leaving
          // someone tapping a dead control with no idea why.
          accessibilityLabel={
            canLeave
              ? 'Leave the queue'
              : `You can leave in ${secondsLeft} seconds if you still haven't been matched`
          }
        />
      </View>

      {!canLeave ? (
        <Sub style={styles.smallNote}>
          Joined by accident? Leaving unlocks shortly, so nobody drops out of a match that was
          about to start.
        </Sub>
      ) : null}
    </>
  );
}

function HoldingTableState({ queueLength, onStepDown, busy }) {
  return (
    <>
      <Headline icon="crown-outline">You hold the table</Headline>
      <Sub>
        {queueLength === 0
          ? 'You won, so you stay on. The next person to join the queue plays you.'
          : 'You won, so you stay on. Your next challenger is being matched now.'}
      </Sub>
      <View style={styles.actions}>
        <Meta icon="users">{`${queueLength} waiting to challenge you`}</Meta>
        {/* Without this, whoever won the last game of the night held the
            table forever. */}
        <Button
          variant="panelQuiet"
          title={busy ? 'Leaving...' : 'Give up the table'}
          onPress={onStepDown}
          disabled={busy}
        />
      </View>
    </>
  );
}

function PlayingState({ status, league, onRecord, busy }) {
  const theme = useTheme();
  const [scores, setScores] = useState({ mine: '', theirs: '' });
  const [error, setError] = useState(null);
  const info = leagueInfo(league);
  const unit = info.scoreUnit;

  // A new match gets a clean scorecard because the parent gives this
  // component key={status.match_id}, so React remounts it.

  const setBoth = (mine, theirs) => {
    setScores({ mine: String(mine), theirs: String(theirs) });
    setError(null);
  };

  const submit = () => {
    if (scores.mine.trim() === '' || scores.theirs.trim() === '') {
      setError('Enter both scores.');
      return;
    }

    const mine = Number(scores.mine);
    const theirs = Number(scores.theirs);

    if (!Number.isInteger(mine) || !Number.isInteger(theirs)) {
      setError('Scores need to be whole numbers.');
      return;
    }
    const problem = info.scoreProblem(mine, theirs);
    if (problem) {
      setError(problem);
      return;
    }

    // The match id says which game this score is for; the league lets the
    // server refuse a score sent under the wrong league's rules.
    onRecord(mine, theirs, status.match_id, league);
  };

  const onlyDigits = (value) => value.replace(/[^0-9]/g, '');

  return (
    <>
      <Headline icon="sword-cross">You're playing {status.opponent}</Headline>
      <Sub>
        {info.name}, table {status.table_id}. When the game is done,{' '}
        {unit === 'points'
          ? 'put the points each of you scored below'
          : 'put the balls each of you sank below'}{' '}
        and the ladder updates for both of you.
      </Sub>

      <View style={styles.scoreGrid}>
        <Field
          onPanel
          label={`Your ${unit}`}
          value={scores.mine}
          onChangeText={(text) => {
            setScores((s) => ({ ...s, mine: onlyDigits(text) }));
            setError(null);
          }}
          keyboardType="number-pad"
          inputMode="numeric"
          maxLength={2}
          style={styles.scoreField}
          inputStyle={styles.scoreInput}
        />
        <Field
          onPanel
          label={`${status.opponent}'s ${unit}`}
          value={scores.theirs}
          onChangeText={(text) => {
            setScores((s) => ({ ...s, theirs: onlyDigits(text) }));
            setError(null);
          }}
          keyboardType="number-pad"
          inputMode="numeric"
          maxLength={2}
          style={styles.scoreField}
          inputStyle={styles.scoreInput}
        />
      </View>

      <View style={styles.quickScores}>
        {info.quickScores.map(({ mine, theirs }) => {
          const won = mine > theirs;
          return (
            <Button
              key={`${mine}-${theirs}`}
              variant={won ? 'panelWin' : 'panelLoss'}
              size="sm"
              title={`${won ? 'Won' : 'Lost'} ${mine}–${theirs}`}
              onPress={() => setBoth(mine, theirs)}
              style={styles.quickScore}
            />
          );
        })}
      </View>

      {error ? (
        <View style={[styles.error, { backgroundColor: theme.panelFill, borderColor: theme.panelLine, borderLeftColor: theme.panelErrorEdge }]}>
          <FieldError message={error} onPanel />
        </View>
      ) : null}

      <Button
        title={busy ? 'Saving...' : 'Report the result'}
        variant="panelPrimary"
        size="lg"
        onPress={submit}
        disabled={busy}
      />
    </>
  );
}

const styles = StyleSheet.create({
  panel: {
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: 22,
    paddingTop: 26,
    marginBottom: 18,
    overflow: 'hidden',
  },
  edge: { position: 'absolute', top: 0, left: 0, right: 0 },
  headline: {
    fontFamily: fonts.display,
    fontSize: 34,
    lineHeight: 38,
    marginBottom: 10,
  },
  sub: { fontFamily: fonts.regular, fontSize: type.body, lineHeight: 23, marginBottom: 20 },
  flush: { marginBottom: 0, flex: 1 },
  smallNote: { fontSize: type.small, lineHeight: 19, marginTop: 14, marginBottom: 0 },
  loadingRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  actions: { gap: 12 },
  meta: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  metaText: { fontFamily: fonts.regular, fontSize: type.small },
  note: {
    fontFamily: fonts.regular,
    fontSize: type.small,
    lineHeight: 19,
    padding: 10,
    borderRadius: radius.sm,
    borderWidth: 1,
    marginBottom: 16,
    overflow: 'hidden',
  },
  inlineLink: { fontFamily: fonts.semibold, textDecorationLine: 'underline' },
  scoreGrid: { flexDirection: 'row', gap: 12 },
  scoreField: { flex: 1 },
  scoreInput: { textAlign: 'center', fontSize: 26, fontVariant: ['tabular-nums'], minHeight: 58 },
  quickScores: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 14 },
  quickScore: { flexGrow: 1, flexBasis: '45%' },
  error: {
    borderWidth: 1,
    borderLeftWidth: 4,
    borderRadius: radius.sm,
    paddingHorizontal: 12,
    paddingBottom: 8,
    marginBottom: 14,
  },
});
