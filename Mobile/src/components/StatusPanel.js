/**
 * The status panel: the one question anyone opens this app to answer -
 * can I play right now? The React Native port of
 * Frontend/src/components/StatusPanel.jsx, with the same states and the
 * same wording:
 *
 *   loading                - the server hasn't answered yet
 *   idle                   - not queued, not playing
 *   queued                 - waiting for an opponent
 *   your_turn              - up to play: say "I'm here" within the minute
 *   waiting_for_challenger - won the last game, holding the table
 *   playing                - a game is on, report the score (or agree
 *                            with the opponent to call it off)
 *
 * `league` is the league on screen (from GET /leagues/directory). A game
 * or a held table is reported with its own league_id, which can be
 * another league; the scorecard always follows the game's league (its
 * game's rules), never the screen's.
 *
 * readOnly: the player hasn't entered this league's PIN. Instead of Join
 * the panel asks for it; anything they're already in (a game from before
 * the PIN changed, say) still shows, with the prompt above it.
 */
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import Feather from '@expo/vector-icons/Feather';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';

import { gameInfo } from '../leagues';
import { useTheme } from '../state/LeagueContext';
import { fonts, radius, type } from '../theme';
import { Button, Field, FieldError } from './ui';

/** "0:42" from a number of seconds. */
function clockText(seconds) {
  const whole = Math.max(0, Math.round(seconds ?? 0));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

/**
 * A countdown that ticks every second between polls, re-synced to the
 * server's number each time it changes. Display only: the server keeps
 * its own clock for every rule. null in, null out - no countdown running.
 */
function useCountdown(serverSeconds) {
  const target = typeof serverSeconds === 'number' ? serverSeconds : null;
  const [synced, setSynced] = useState(target);
  const [left, setLeft] = useState(target);

  // Adjusting state during render when a prop changes, which React
  // recommends over mirroring props into state inside an effect.
  if (target !== synced) {
    setSynced(target);
    setLeft(target);
  }

  const running = left !== null && left > 0;
  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(() => {
      setLeft((remaining) => (remaining === null ? null : Math.max(0, remaining - 1)));
    }, 1000);
    return () => clearInterval(timer);
  }, [running]);

  return left;
}

export function StatusPanel({
  status,
  problem,
  league,
  leagues,
  readOnly,
  onUnlock,
  queue = [],
  queueLength = queue.length,
  onJoin,
  onLeave,
  onConfirm,
  onRecord,
  onCancelGame,
  onKeepPlaying,
  onStepDown,
  onVote,
  onKingHere,
  onSwitchLeague,
  busy,
}) {
  const theme = useTheme();
  // Before the league list arrives there's nothing to say yet.
  const state = status && league ? status.status || 'idle' : 'loading';
  // The league of the game or held table, which can be another one.
  const gameLeague =
    (state === 'playing' || state === 'waiting_for_challenger') && status.league_id
      ? (leagues?.find((l) => l.league_id === status.league_id) ?? league)
      : league;
  const elsewhere = gameLeague && gameLeague.league_id !== league?.league_id ? gameLeague : null;
  // Without the PIN, idle becomes "enter the PIN"; anything else keeps its
  // own panel, with the prompt above it.
  const locked = readOnly && state !== 'loading';
  const askOnly = locked && state === 'idle';

  return (
    // No accessibilityState busy here, though the panel is briefly
    // loading: Android kept describing it as "busy" long after, because
    // the description isn't cleared when the state goes away. The loading
    // text and spinner already tell a screen reader what's happening.
    <View
      style={[
        styles.panel,
        {
          backgroundColor:
            state === 'playing' || state === 'your_turn' ? theme.panelBgPlaying : theme.panelBg,
          borderColor: theme.panelBorder,
          boxShadow: theme.panelShadow,
        },
      ]}
    >
      {/* Along the top edge: a band in the league's second colour. */}
      <View style={[styles.edge, { height: theme.panelEdgeSize, backgroundColor: theme.panelEdge }]} />

      {problem ? (
        <Note>{`${problem} What you see below may be out of date - retrying automatically.`}</Note>
      ) : null}
      {elsewhere ? (
        <Note>
          This is your game in {elsewhere.name}.{' '}
          <Text
            accessibilityRole="link"
            onPress={() => onSwitchLeague(elsewhere.league_id)}
            style={[styles.inlineLink, { color: theme.panelText }]}
          >
            Switch to that league
          </Text>
        </Note>
      ) : null}

      {locked && !askOnly ? (
        <PinPrompt
          league={league}
          onUnlock={onUnlock}
          busy={busy}
          compact
          // In this league already (a game, a place in line): the PIN must
          // have changed since. A game elsewhere: they just haven't entered
          // this league's yet.
          changed={!elsewhere}
        />
      ) : null}
      {state === 'loading' && <LoadingState />}
      {state === 'playing' && (
        <PlayingState
          key={status.match_id}
          status={status}
          league={gameLeague}
          onRecord={onRecord}
          onCancelGame={onCancelGame}
          onKeepPlaying={onKeepPlaying}
          onVote={onVote}
          onKingHere={onKingHere}
          busy={busy}
        />
      )}
      {state === 'your_turn' && (
        <YourTurnState status={status} onConfirm={onConfirm} onLeave={onLeave} busy={busy} />
      )}
      {state === 'waiting_for_challenger' && (
        <HoldingTableState
          status={status}
          queueLength={queueLength}
          onStepDown={onStepDown}
          onKingHere={onKingHere}
          busy={busy}
        />
      )}
      {state === 'queued' && (
        <QueuedState
          status={status}
          league={league}
          queue={queue}
          onJoin={onJoin}
          onLeave={onLeave}
          busy={busy}
          queueLength={queueLength}
        />
      )}
      {askOnly ? <PinPrompt league={league} onUnlock={onUnlock} busy={busy} /> : null}
      {state === 'idle' && !askOnly && (
        <IdleState onJoin={onJoin} busy={busy} queueLength={queueLength} queue={queue} league={league} />
      )}
    </View>
  );
}

/**
 * "Enter the PIN to play": the league is open to look at, but playing
 * here needs its 4-digit PIN - once; it's remembered. compact is the
 * smaller version shown above a game or a place in line; changed says the
 * PIN changed since the player got there (rather than that they're
 * looking at this league while their game is in another).
 */
function PinPrompt({ league, onUnlock, busy, compact = false, changed = false }) {
  const theme = useTheme();
  const [pin, setPin] = useState('');
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!/^\d{4}$/.test(pin)) {
      setError('The PIN is 4 digits.');
      return;
    }
    setError(null);
    const result = await onUnlock(pin);
    if (!result.ok) {
      if (result.field === 'pin') setError(result.message);
      setPin('');
    }
  };

  const title = !league.has_pin
    ? compact
      ? `No playing at ${league.name} yet`
      : 'Enter the 4-digit PIN to play'
    : compact && changed
      ? `${league.name}'s PIN has changed`
      : compact
        ? `To play at ${league.name}, enter its PIN`
        : 'Enter the 4-digit PIN to play';

  return (
    <View style={compact ? [styles.pinCompact, { backgroundColor: theme.panelFill, borderColor: theme.panelLine }] : null}>
      {compact ? (
        <View style={styles.pinCompactHead}>
          <Feather name="lock" size={16} color={theme.panelIcon} />
          <Text style={[styles.pinCompactTitle, { color: theme.panelText }]}>{title}</Text>
        </View>
      ) : (
        <Headline icon="lock" iconSet="feather">
          {title}
        </Headline>
      )}
      {!league.has_pin ? (
        <Sub style={compact ? styles.pinCompactSub : null}>
          {league.name} doesn't have a PIN yet. Ask the organiser - until they set one, you can look
          around but not play.
        </Sub>
      ) : (
        <>
          <Sub style={compact ? styles.pinCompactSub : null}>
            {compact && changed
              ? 'Enter the new one to keep playing here - you only need to once.'
              : compact
                ? 'You only need to once.'
                : `Look around all you like. To join the line at ${league.name}, enter its PIN - you only need to once. Ask the organiser if you don't have it.`}
          </Sub>
          <View style={styles.pinRow}>
            <Field
              onPanel
              // The heading names the league; a longer label wraps and
              // pushes the field out of line with its button.
              label="4-digit PIN"
              accessibilityLabel={`${league.name}'s 4-digit PIN`}
              value={pin}
              onChangeText={(text) => {
                setPin(text.replace(/[^0-9]/g, '').slice(0, 4));
                setError(null);
              }}
              onSubmitEditing={submit}
              keyboardType="number-pad"
              inputMode="numeric"
              secureTextEntry
              autoComplete="off"
              textContentType="oneTimeCode"
              maxLength={4}
              placeholder="••••"
              error={error}
              style={styles.pinField}
              inputStyle={styles.pinInput}
            />
            <Button
              variant="panelPrimary"
              title={busy ? 'Checking...' : 'Unlock'}
              onPress={submit}
              disabled={busy || pin.length !== 4}
              style={styles.pinButton}
            />
          </View>
        </>
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

/** Which of the league's tables a game or a turn is at. */
function Where({ children }) {
  const theme = useTheme();
  return (
    <View style={styles.where}>
      <Feather name="map-pin" size={15} color={theme.panelIcon} />
      <Text style={[styles.whereText, { color: theme.panelText }]}>{children}</Text>
    </View>
  );
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

/**
 * Where to play, at a league with more than one table: whichever table
 * frees up first, or one in particular. Chips, each saying how many are
 * already waiting in that line.
 */
function TableChoice({ label, tables, queue, value, onChange, disabled, style }) {
  const theme = useTheme();
  const waiting = (key) => queue.filter((entry) => (entry.target_table_id ?? null) === key).length;
  const options = [
    { key: null, label: 'First available' },
    ...tables.map((t) => ({ key: t.table_id, label: t.table_name })),
  ];
  return (
    <View style={[styles.choice, style]} accessibilityRole="radiogroup" accessibilityLabel={label}>
      <Text style={[styles.choiceLabel, { color: theme.panelDim }]}>{label}</Text>
      <View style={styles.choiceOptions}>
        {options.map((option) => {
          const count = waiting(option.key);
          const checked = value === option.key;
          const countText = count === 0 ? 'nobody waiting' : `${count} waiting`;
          return (
            <Pressable
              key={option.key ?? 'any'}
              onPress={() => onChange(option.key)}
              disabled={disabled}
              accessibilityRole="radio"
              accessibilityState={{ checked, selected: checked, disabled }}
              accessibilityLabel={`${option.label}, ${countText}`}
              style={({ pressed }) => [
                styles.chip,
                {
                  borderColor: checked ? theme.panelCtaBg : theme.panelLine,
                  backgroundColor: checked ? theme.panelCtaBg : pressed ? theme.panelFillStrong : theme.panelFill,
                  opacity: disabled ? 0.7 : 1,
                },
              ]}
            >
              <Text style={[styles.chipName, { color: checked ? theme.panelCtaText : theme.panelText }]}>
                {option.label}
              </Text>
              <Text style={[styles.chipCount, { color: checked ? theme.panelCtaText : theme.panelDim }]}>
                {countText}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

function IdleState({ onJoin, busy, queueLength, queue, league }) {
  const tables = league.tables || [];
  const many = tables.length > 1;
  // null: the first table that frees up.
  const [choice, setChoice] = useState(null);
  const chosen = many ? tables.find((t) => t.table_id === choice) : null;
  return (
    <>
      <Headline>{tables.length === 1 ? tables[0].table_name : league.name} is open to you</Headline>
      <Sub>
        {queueLength === 0
          ? 'Nobody is waiting. Join and you play as soon as someone else does.'
          : `${queueLength} ${queueLength === 1 ? 'player is' : 'players are'} waiting. Join the line to get a game.`}
      </Sub>
      {many ? (
        <TableChoice
          label="Where do you want to play?"
          tables={tables}
          queue={queue}
          value={chosen ? chosen.table_id : null}
          onChange={setChoice}
          disabled={busy}
        />
      ) : null}
      <Button
        title={busy ? 'Joining...' : chosen ? `Join the line for ${chosen.table_name}` : 'Join the queue'}
        variant="panelPrimary"
        size="lg"
        onPress={() => onJoin(chosen ? chosen.table_id : null)}
        disabled={busy}
      />
    </>
  );
}

function QueuedState({ status, league, queue, onJoin, onLeave, busy, queueLength }) {
  // Ticks locally so the number moves every second rather than lurching
  // with each poll. The server enforces the wait itself, so drift here
  // can't let anyone leave early.
  const secondsLeft = useCountdown(status.leave_unlocks_in ?? 0) ?? 0;

  const canLeave = secondsLeft <= 0;
  const position = status.queue_position;
  const ahead = Math.max(0, (position ?? 1) - 1);
  const tables = league.tables || [];
  const many = tables.length > 1;
  const target = status.target_table_id ?? null;

  return (
    <>
      <Headline>{ahead === 0 ? "You're up next" : `You're number ${position} in line`}</Headline>
      {many ? (
        <Where>
          {status.target_table_name ? `Waiting for ${status.target_table_name}` : 'Waiting for the first free table'}
        </Where>
      ) : null}
      <Sub>
        {ahead === 0
          ? "Stay close to the table. When it's your turn you'll have a minute to say you're here - keep the app open."
          : `${ahead} ${ahead === 1 ? 'player' : 'players'} ahead of you. When it's your turn you'll have a minute to say you're here - keep the app open.`}
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

      {many ? (
        <TableChoice
          label="Change where you'll play - you keep your place"
          tables={tables}
          queue={queue}
          value={target}
          onChange={(key) => key !== target && onJoin(key)}
          disabled={busy}
          style={styles.choiceQueued}
        />
      ) : null}
    </>
  );
}

/**
 * A vote that the king isn't at the table (logic/king_votes.py), as the
 * two players there see it. The king (who can't vote) is told, with an
 * "I'm here" that clears it; the challenger, seated against a king who
 * hasn't turned up, can vote. Nothing for anyone else - they vote from
 * the table card.
 */
function KingVoteNotice({ status, onVote, onKingHere, busy }) {
  const theme = useTheme();
  const vote = status.removal_vote;
  const counting = vote?.seconds_left != null;
  const left = useCountdown(counting ? vote.seconds_left : null);
  if (!vote) return null;

  if (!vote.you_can_vote) {
    if (vote.votes === 0) return null;
    return (
      <Notice>
        <Text style={[styles.noticeText, { color: theme.panelText }]}>
          <Text style={styles.noticeStrong}>
            {vote.votes} of {vote.needed} waiting {vote.votes === 1 ? 'says' : 'say'} you're not at the table.
          </Text>{' '}
          {counting
            ? `Say you're here within ${clockText(left)}, or you'll be taken off it.`
            : "If everyone does, you'll have a minute to say you are."}
        </Text>
        <View style={styles.noticeActions}>
          <Button variant="panelPrimary" size="sm" title="I'm here" onPress={onKingHere} disabled={busy} />
        </View>
      </Notice>
    );
  }

  // Nobody has voted: only a quiet way in, at the foot of the game (every
  // game has a king, and most kings are standing right there).
  if (vote.votes === 0 && !counting) return null;

  return (
    <Notice>
      <Text style={[styles.noticeText, { color: theme.panelText }]}>
        {counting ? (
          <>
            <Text style={styles.noticeStrong}>Everyone waiting has voted.</Text> {status.opponent} has{' '}
            {clockText(left)} to say they're here, or they come off the table and it's yours.
          </>
        ) : (
          <>
            <Text style={styles.noticeStrong}>{status.opponent} not at the table?</Text> Vote them off:
            once everyone waiting has ({vote.votes} of {vote.needed} so far), they get a minute to turn
            up. If they don't, the game is called off and the table is yours.
          </>
        )}
      </Text>
      <View style={styles.noticeActions}>
        <Button
          variant="panelQuiet"
          size="sm"
          title={vote.you_voted ? 'Take back my vote' : `Vote: ${status.opponent} isn't here`}
          onPress={() => onVote(status, !vote.you_voted)}
          disabled={busy}
        />
      </View>
    </Notice>
  );
}

function HoldingTableState({ status, queueLength, onStepDown, onKingHere, busy }) {
  const upNextLeft = useCountdown(status.up_next_seconds_left ?? null);

  let sub;
  if (status.up_next) {
    sub =
      upNextLeft === null
        ? `${status.up_next} is up next - get ready.`
        : `${status.up_next} is up next and has ${clockText(upNextLeft)} to say they're here. If they don't, the next in line is asked.`;
  } else if (queueLength === 0) {
    sub = 'You stay on. The next person to join the queue plays you.';
  } else {
    sub = 'You stay on. Your next challenger is being matched now.';
  }

  return (
    <>
      <Headline icon="crown-outline">You hold {status.table_name || 'the table'}</Headline>
      <KingVoteNotice status={status} onKingHere={onKingHere} busy={busy} />
      <Sub>{sub}</Sub>
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

function PlayingState({ status, league, onRecord, onCancelGame, onKeepPlaying, onVote, onKingHere, busy }) {
  const theme = useTheme();
  const [scores, setScores] = useState({ mine: '', theirs: '' });
  const [error, setError] = useState(null);
  const info = gameInfo(league.game);
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
    onRecord(mine, theirs, status.match_id, status.league_id ?? league.league_id);
  };

  const onlyDigits = (value) => value.replace(/[^0-9]/g, '');
  const cancelAsked = status.cancel_requested_by;

  return (
    <>
      <Headline icon="sword-cross">You're playing {status.opponent}</Headline>
      {status.table_name ? <Where>At {status.table_name}</Where> : null}

      <KingVoteNotice status={status} onVote={onVote} onKingHere={onKingHere} busy={busy} />

      {cancelAsked === 'opponent' ? (
        <Notice>
          <Text style={[styles.noticeText, { color: theme.panelText }]}>
            <Text style={styles.noticeStrong}>{status.opponent} wants to cancel this game.</Text> If
            you agree, it's called off: nothing is recorded and nobody's points change.
          </Text>
          <View style={styles.noticeActions}>
            <Button
              variant="panelPrimary"
              size="sm"
              title="Agree to cancel"
              onPress={() => onCancelGame(status.match_id)}
              disabled={busy}
            />
            <Button
              variant="panelQuiet"
              size="sm"
              title="Keep playing"
              onPress={() => onKeepPlaying(status.match_id)}
              disabled={busy}
            />
          </View>
        </Notice>
      ) : null}
      {cancelAsked === 'you' ? (
        <Notice>
          <Text style={[styles.noticeText, { color: theme.panelText }]}>
            You asked to cancel this game. It's called off once {status.opponent} agrees.
          </Text>
          <View style={styles.noticeActions}>
            <Button
              variant="panelQuiet"
              size="sm"
              title="Take it back - keep playing"
              onPress={() => onKeepPlaying(status.match_id)}
              disabled={busy}
            />
          </View>
        </Notice>
      ) : null}
      <Sub>
        {league.name}. When the game is done,{' '}
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

      {!cancelAsked ? (
        <View style={styles.cancelRow}>
          <Sub style={styles.cancelText}>
            Can't finish the game? It's only called off if you both agree, and then nothing is
            recorded.
          </Sub>
          <Button
            variant="panelQuiet"
            size="sm"
            title={`Ask ${status.opponent} to cancel`}
            onPress={() => onCancelGame(status.match_id)}
            disabled={busy}
          />
        </View>
      ) : null}
      {status.removal_vote?.you_can_vote &&
      status.removal_vote.votes === 0 &&
      status.removal_vote.seconds_left == null ? (
        <View style={styles.cancelRow}>
          <Sub style={styles.cancelText}>
            {status.opponent} not at the table at all? Everyone waiting has to agree; then they get a
            minute to turn up.
          </Sub>
          <Button
            variant="panelQuiet"
            size="sm"
            title="Vote them off"
            onPress={() => onVote(status, true)}
            disabled={busy}
          />
        </View>
      ) : null}
    </>
  );
}

/** A question on the panel that needs an answer. */
function Notice({ children }) {
  const theme = useTheme();
  return (
    <View
      accessibilityLiveRegion="polite"
      style={[styles.notice, { backgroundColor: theme.panelFill, borderColor: theme.panelLine }]}
    >
      {children}
    </View>
  );
}

/**
 * Up to play. The player has a minute to say they're here, or they're
 * taken out of the queue and the next in line is asked. Once they have,
 * they wait for their opponent to do the same - unless that's the king,
 * who is at the table already.
 */
function YourTurnState({ status, onConfirm, onLeave, busy }) {
  const theme = useTheme();
  const mine = useCountdown(status.confirmed ? null : status.seconds_left);
  const theirs = useCountdown(status.opponent_confirmed ? null : status.opponent_seconds_left);
  const opponent = status.opponent;

  if (status.confirmed) {
    return (
      <>
        <Headline>You're in - get ready</Headline>
        {status.table_name ? <Where>At {status.table_name}</Where> : null}
        <Sub>
          {opponent ? `Waiting for ${opponent} to say they're here` : 'Waiting for your opponent'}
          {theirs !== null ? ` - they have ${clockText(theirs)} left.` : '.'} The game starts the
          moment they do. If they don't, the next player in line is asked instead.
        </Sub>
        <Button variant="panelQuiet" title="Leave the queue" onPress={onLeave} disabled={busy} />
      </>
    );
  }

  const left = Math.max(0, mine ?? 0);
  return (
    <>
      <Headline icon="bell-ring-outline">It's your turn</Headline>
      {status.table_name ? <Where>At {status.table_name}</Where> : null}
      <Sub>
        {opponent ? `You're up against ${opponent}. Tap "I'm here" to play.` : 'Tap "I\'m here" to play.'}{' '}
        If you don't in time, you're taken out of the queue and the next player is asked.
      </Sub>

      <View style={styles.meter}>
        <View
          accessible
          accessibilityRole="progressbar"
          accessibilityLabel="Time left to confirm"
          accessibilityValue={{ min: 0, max: 60, now: left, text: `${left} seconds left` }}
          style={[styles.meterTrack, { backgroundColor: theme.panelFillStrong }]}
        >
          <View
            style={[
              styles.meterFill,
              { width: `${(left / 60) * 100}%`, backgroundColor: theme.panelCtaBg },
            ]}
          />
        </View>
        <Text
          importantForAccessibility="no"
          accessibilityElementsHidden
          style={[styles.meterClock, { color: theme.panelText }]}
        >
          {clockText(left)}
        </Text>
      </View>

      <View style={styles.actions}>
        <Button
          variant="panelPrimary"
          size="lg"
          title={busy ? 'Confirming...' : "I'm here"}
          onPress={onConfirm}
          disabled={busy}
        />
        <Button
          variant="panelQuiet"
          title="Can't play now - leave the queue"
          onPress={onLeave}
          disabled={busy}
        />
      </View>
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
  notice: { borderWidth: 1, borderRadius: radius.sm, padding: 12, marginBottom: 16, gap: 10 },
  noticeText: { fontFamily: fonts.regular, fontSize: type.small, lineHeight: 19 },
  noticeStrong: { fontFamily: fonts.semibold },
  noticeActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  cancelRow: { marginTop: 18, gap: 8, alignItems: 'flex-start' },
  cancelText: { fontSize: type.small, lineHeight: 19, marginBottom: 0 },
  meter: { flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 20 },
  meterTrack: { flex: 1, height: 10, borderRadius: radius.pill, overflow: 'hidden' },
  meterFill: { height: '100%', borderRadius: radius.pill },
  meterClock: { fontFamily: fonts.bold, fontSize: 24, fontVariant: ['tabular-nums'], minWidth: 56 },
  where: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: -2, marginBottom: 10 },
  whereText: { fontFamily: fonts.semibold, fontSize: type.body },
  pinCompact: { borderWidth: 1, borderRadius: radius.sm, padding: 12, marginBottom: 18 },
  pinCompactHead: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 4 },
  pinCompactTitle: { fontFamily: fonts.semibold, fontSize: type.body, flexShrink: 1 },
  pinCompactSub: { fontSize: type.small, lineHeight: 19, marginBottom: 10 },
  pinRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  pinField: { flex: 1, marginBottom: 0 },
  pinInput: { fontSize: 22, letterSpacing: 8, textAlign: 'center', fontVariant: ['tabular-nums'] },
  pinButton: { marginTop: 25 },
  choice: { marginBottom: 18 },
  choiceQueued: { marginTop: 18, marginBottom: 0 },
  choiceLabel: { fontFamily: fonts.semibold, fontSize: type.small, marginBottom: 8 },
  choiceOptions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { minWidth: 104, paddingVertical: 8, paddingHorizontal: 12, borderRadius: radius.md, borderWidth: 1 },
  chipName: { fontFamily: fonts.bold, fontSize: type.small },
  chipCount: { fontFamily: fonts.regular, fontSize: 12 },
});
