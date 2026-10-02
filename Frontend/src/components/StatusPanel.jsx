/**
 * The status panel: the one question anyone opens this app to answer -
 * can I play right now?
 *
 * It handles five states the backend reports:
 *   idle                   - not queued, not playing
 *   queued                 - waiting for an opponent
 *   your_turn              - up to play: say "I'm here" within the minute
 *   waiting_for_challenger - won the last game, holding the table
 *   playing                - a game is on, report the score (or agree
 *                            with the opponent to call it off)
 *
 * The old version only knew "playing" and "idle", so someone holding the
 * table looked idle and was offered a Join button that then failed.
 *
 * Until the first answer arrives, status is null and the panel says it's
 * checking - rather than guessing "idle" and offering that same button.
 *
 * `league` is the league on screen. A game or a held table is reported
 * with its own league_type, which can be the other league - one person
 * plays one game at a time, whichever screen they're looking at. The
 * scorecard always follows the game's league, never the screen's.
 */
import React, { useEffect, useState } from 'react';
import { BellRing, Swords, Users, Clock, Crown, LoaderCircle } from 'lucide-react';

import { leagueInfo } from '../leagues.js';

/** "0:42" from a number of seconds. */
function clockText(seconds) {
  const whole = Math.max(0, Math.round(seconds ?? 0));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

/**
 * A countdown that ticks every second between polls, re-synced to the
 * server's number each time it changes. Display only: the server keeps
 * its own clock for every rule, so a second of drift here changes
 * nothing. null in, null out - for "no countdown running".
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
  tableName,
  queueLength,
  onJoin,
  onLeave,
  onConfirm,
  onRecord,
  onCancelGame,
  onKeepPlaying,
  onStepDown,
  onSwitchLeague,
  busy,
}) {
  const state = status ? status.status || 'idle' : 'loading';
  const elsewhere =
    (state === 'playing' || state === 'waiting_for_challenger') &&
    status.league_type &&
    status.league_type !== league
      ? status.league_type
      : null;

  return (
    <section
      className="status-panel"
      data-tone={state === 'playing' || state === 'your_turn' ? 'playing' : 'default'}
      data-animate={state === 'playing' || state === 'your_turn' ? 'true' : 'false'}
      aria-labelledby="status-headline"
      aria-busy={state === 'loading'}
    >
      {problem && (
        <p className="status-problem" role="status">
          {problem} The panel below may be out of date - retrying automatically.
        </p>
      )}
      {elsewhere && (
        <p className="status-problem status-elsewhere">
          This is your game in the {leagueInfo(elsewhere).name}.{' '}
          <button type="button" className="btn-link" onClick={() => onSwitchLeague(elsewhere)}>
            Switch to that league
          </button>
        </p>
      )}
      {state === 'loading' && <LoadingState />}
      {state === 'playing' && (
        <PlayingState
          key={status.match_id}
          status={status}
          league={status.league_type || league}
          onRecord={onRecord}
          onCancelGame={onCancelGame}
          onKeepPlaying={onKeepPlaying}
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
          busy={busy}
        />
      )}
      {state === 'queued' && (
        <QueuedState status={status} onLeave={onLeave} busy={busy} queueLength={queueLength} />
      )}
      {state === 'idle' && (
        <IdleState onJoin={onJoin} busy={busy} queueLength={queueLength} tableName={tableName} />
      )}
    </section>
  );
}

function LoadingState() {
  return (
    <>
      <h2 className="status-headline" id="status-headline">
        Checking the table&hellip;
      </h2>
      <p className="status-sub status-loading">
        <LoaderCircle size={18} aria-hidden="true" className="spin" />
        Finding out whether you're queued, playing or free.
      </p>
    </>
  );
}

function IdleState({ onJoin, busy, queueLength, tableName }) {
  return (
    <>
      <h2 className="status-headline" id="status-headline">
        {tableName || 'The table'} is open to you
      </h2>
      <p className="status-sub">
        {queueLength === 0
          ? 'Nobody is waiting. Join and you play as soon as someone else does.'
          : `${queueLength} ${queueLength === 1 ? 'player is' : 'players are'} waiting. Join the line to get a game.`}
      </p>
      <div className="status-actions">
        <button type="button" className="btn btn-primary" onClick={onJoin} disabled={busy}>
          {busy ? 'Joining...' : 'Join the queue'}
        </button>
      </div>
    </>
  );
}

function QueuedState({ status, onLeave, busy, queueLength }) {
  // Ticks locally so the number moves every second rather than lurching
  // each time the server is polled. The server enforces the wait itself,
  // so a second of drift here can't let anyone leave early.
  const secondsLeft = useCountdown(status.leave_unlocks_in ?? 0) ?? 0;

  const canLeave = secondsLeft <= 0;
  const position = status.queue_position;
  const ahead = Math.max(0, (position ?? 1) - 1);

  return (
    <>
      <h2 className="status-headline" id="status-headline">
        {ahead === 0 ? "You're up next" : `You're number ${position} in line`}
      </h2>
      <p className="status-sub">
        {ahead === 0
          ? "Stay close to the table. When it's your turn you'll have a minute to say you're here."
          : `${ahead} ${ahead === 1 ? 'player' : 'players'} ahead of you. When it's your turn you'll have a minute to say you're here - keep this page open.`}
      </p>

      <div className="status-actions">
        <span className="status-meta">
          <Users size={16} aria-hidden="true" />
          {queueLength} in the queue
        </span>

        <button
          type="button"
          className="btn btn-quiet"
          onClick={onLeave}
          disabled={!canLeave || busy}
          // The countdown explains a disabled button rather than leaving
          // someone tapping a dead control with no idea why.
          title={
            canLeave
              ? 'Leave the queue'
              : `You can leave in ${secondsLeft}s if you still haven't been matched`
          }
        >
          {canLeave ? (
            'Leave the queue'
          ) : (
            <>
              <Clock size={15} aria-hidden="true" />
              <span>
                Leave in <span className="countdown">{secondsLeft}s</span>
              </span>
            </>
          )}
        </button>
      </div>

      {!canLeave && (
        <p className="status-note">
          Joined by accident? Leaving unlocks shortly, so nobody drops out of a match that was about
          to start.
        </p>
      )}
    </>
  );
}

function HoldingTableState({ status, queueLength, onStepDown, busy }) {
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
      <h2 className="status-headline" id="status-headline">
        <Crown size={30} aria-hidden="true" className="headline-icon headline-icon-crown" />
        You hold the table
      </h2>
      <p className="status-sub">{sub}</p>
      <div className="status-actions">
        <span className="status-meta">
          <Users size={16} aria-hidden="true" />
          {queueLength} waiting to challenge you
        </span>
        {/* Without this, whoever won the last game of the night held the
            table forever, and the next person to join tomorrow was matched
            against someone who'd gone home. */}
        <button type="button" className="btn btn-quiet" onClick={onStepDown} disabled={busy}>
          {busy ? 'Leaving...' : 'Give up the table'}
        </button>
      </div>
    </>
  );
}

function PlayingState({ status, league, onRecord, onCancelGame, onKeepPlaying, busy }) {
  const [scores, setScores] = useState({ mine: '', theirs: '' });
  const [error, setError] = useState(null);
  const info = leagueInfo(league);
  const unit = info.scoreUnit;

  // Note: a new match gets a clean scorecard because the parent gives
  // this component key={status.match_id}, so React remounts it with fresh
  // state. That's cheaper and harder to get wrong than clearing the
  // fields from an effect.

  const setBoth = (mine, theirs) => {
    setScores({ mine: String(mine), theirs: String(theirs) });
    setError(null);
  };

  const submit = (e) => {
    e.preventDefault();

    if (scores.mine === '' || scores.theirs === '') {
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

    // The match id says which game this score is for. If the opponent has
    // already reported it, the server refuses rather than filing this
    // score against the next game. The league lets the server refuse a
    // score sent under the wrong league's rules.
    onRecord(mine, theirs, status.match_id, league);
  };

  const cancelAsked = status.cancel_requested_by;

  return (
    <>
      <h2 className="status-headline" id="status-headline">
        <Swords size={28} aria-hidden="true" className="headline-icon" />
        You're playing {status.opponent}
      </h2>

      {cancelAsked === 'opponent' && (
        <div className="panel-notice" role="status">
          <p>
            <strong>{status.opponent} wants to cancel this game.</strong> If you agree, it's called
            off: nothing is recorded and nobody's points change.
          </p>
          <div className="panel-notice-actions">
            <button
              type="button"
              className="btn btn-primary btn-small"
              onClick={() => onCancelGame(status.match_id)}
              disabled={busy}
            >
              Agree to cancel
            </button>
            <button
              type="button"
              className="btn btn-quiet btn-small"
              onClick={() => onKeepPlaying(status.match_id)}
              disabled={busy}
            >
              Keep playing
            </button>
          </div>
        </div>
      )}
      {cancelAsked === 'you' && (
        <div className="panel-notice" role="status">
          <p>You asked to cancel this game. It&rsquo;s called off once {status.opponent} agrees.</p>
          <div className="panel-notice-actions">
            <button
              type="button"
              className="btn btn-quiet btn-small"
              onClick={() => onKeepPlaying(status.match_id)}
              disabled={busy}
            >
              Take it back - keep playing
            </button>
          </div>
        </div>
      )}
      <p className="status-sub">
        {info.name}, table {status.table_id}. When the game is done,{' '}
        {unit === 'points'
          ? 'put the points each of you scored below'
          : 'put the balls each of you sank below'}{' '}
        and the ladder updates for both of you.
      </p>

      <form onSubmit={submit} noValidate>
        <div className="score-grid">
          <div className="field field-flush">
            <label htmlFor="score-mine">Your {unit}</label>
            <input
              id="score-mine"
              className="score-input"
              type="number"
              min="0"
              max={info.maxScore}
              inputMode="numeric"
              value={scores.mine}
              onChange={(e) => {
                setScores((s) => ({ ...s, mine: e.target.value }));
                setError(null);
              }}
            />
          </div>
          <div className="field field-flush">
            <label htmlFor="score-theirs">
              {status.opponent}&rsquo;s {unit}
            </label>
            <input
              id="score-theirs"
              className="score-input"
              type="number"
              min="0"
              max={info.maxScore}
              inputMode="numeric"
              value={scores.theirs}
              onChange={(e) => {
                setScores((s) => ({ ...s, theirs: e.target.value }));
                setError(null);
              }}
            />
          </div>
        </div>

        <div className="quick-scores">
          {info.quickScores.map(({ mine, theirs }) => {
            const won = mine > theirs;
            return (
              <button
                key={`${mine}-${theirs}`}
                type="button"
                className={`btn btn-score ${won ? 'btn-win' : 'btn-loss'}`}
                onClick={() => setBoth(mine, theirs)}
              >
                {won ? 'Won' : 'Lost'} {mine}&ndash;{theirs}
              </button>
            );
          })}
        </div>

        {error && (
          <div className="banner banner-error banner-on-panel" role="alert">
            {error}
          </div>
        )}

        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Saving...' : 'Report the result'}
        </button>
      </form>

      {!cancelAsked && (
        <p className="status-note">
          Can&rsquo;t finish the game?{' '}
          <button
            type="button"
            className="btn-link"
            onClick={() => onCancelGame(status.match_id)}
            disabled={busy}
          >
            Ask {status.opponent} to cancel it
          </button>
          . It&rsquo;s only called off if you both agree, and then nothing is recorded.
        </p>
      )}
    </>
  );
}

/**
 * Up to play. The player has READY_CHECK_SECONDS (a minute) to say
 * they're here, or they're taken out of the queue and the next in line
 * is asked. Once they have, they wait for their opponent to do the same -
 * unless that's the king, who is at the table already.
 */
function YourTurnState({ status, onConfirm, onLeave, busy }) {
  const mine = useCountdown(status.confirmed ? null : status.seconds_left);
  const theirs = useCountdown(status.opponent_confirmed ? null : status.opponent_seconds_left);
  const opponent = status.opponent;

  if (status.confirmed) {
    return (
      <>
        <h2 className="status-headline" id="status-headline">
          You&rsquo;re in - get ready
        </h2>
        <p className="status-sub">
          {opponent ? `Waiting for ${opponent} to say they're here` : 'Waiting for your opponent'}
          {theirs !== null ? ` - they have ${clockText(theirs)} left.` : '.'} The game starts the
          moment they do. If they don&rsquo;t, the next player in line is asked instead.
        </p>
        <div className="status-actions">
          <button type="button" className="btn btn-quiet" onClick={onLeave} disabled={busy}>
            Leave the queue
          </button>
        </div>
      </>
    );
  }

  return (
    <>
      {/* Announced once, as the state appears. The ticking clock below
          isn't live - a reading every second would drown everything. */}
      <p className="sr-only" role="alert">
        It&rsquo;s your turn. Confirm you&rsquo;re here within a minute to keep your place.
      </p>
      <h2 className="status-headline" id="status-headline">
        <BellRing size={28} aria-hidden="true" className="headline-icon" />
        It&rsquo;s your turn
      </h2>
      <p className="status-sub">
        {opponent
          ? `You're up against ${opponent}. Tap "I'm here" to play.`
          : 'Tap "I\'m here" to play.'}{' '}
        If you don&rsquo;t in time, you&rsquo;re taken out of the queue and the next player is
        asked.
      </p>

      <TurnMeter seconds={mine} />

      <div className="status-actions">
        <button type="button" className="btn btn-primary" onClick={onConfirm} disabled={busy}>
          {busy ? 'Confirming...' : "I'm here"}
        </button>
        <button type="button" className="btn btn-quiet" onClick={onLeave} disabled={busy}>
          Can&rsquo;t play now - leave the queue
        </button>
      </div>
    </>
  );
}

/** The time left to say you're here, as a draining bar and a clock. */
function TurnMeter({ seconds, total = 60 }) {
  const left = Math.max(0, seconds ?? 0);
  return (
    <div className="turn-meter">
      <div
        className="turn-meter-track"
        role="progressbar"
        aria-label="Time left to confirm"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={left}
        aria-valuetext={`${left} seconds left`}
      >
        <span className="turn-meter-fill" style={{ width: `${(left / total) * 100}%` }} />
      </div>
      <span className="turn-meter-clock countdown" aria-hidden="true">
        {clockText(left)}
      </span>
    </div>
  );
}
