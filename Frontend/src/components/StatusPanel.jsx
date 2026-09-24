/**
 * The status panel: the one question anyone opens this app to answer -
 * can I play right now?
 *
 * It handles four states the backend reports:
 *   idle                   - not queued, not playing
 *   queued                 - waiting for an opponent
 *   waiting_for_challenger - won the last game, holding the table
 *   playing                - a game is on, report the score
 *
 * The old version only knew "playing" and "idle", so someone holding the
 * table looked idle and was offered a Join button that then failed.
 *
 * Until the first answer arrives, status is null and the panel says it's
 * checking - rather than guessing "idle" and offering that same button.
 */
import React, { useEffect, useState } from 'react';
import { Swords, Users, Clock, Crown, LoaderCircle } from 'lucide-react';

export function StatusPanel({
  status,
  problem,
  queueLength,
  onJoin,
  onLeave,
  onRecord,
  onStepDown,
  busy,
}) {
  const state = status ? status.status || 'idle' : 'loading';

  return (
    <section
      className="status-panel"
      data-tone={state === 'playing' ? 'playing' : 'default'}
      data-animate={state === 'playing' ? 'true' : 'false'}
      aria-labelledby="status-headline"
      aria-busy={state === 'loading'}
    >
      {problem && (
        <p className="status-problem" role="status">
          {problem} The panel below may be out of date - retrying automatically.
        </p>
      )}
      {state === 'loading' && <LoadingState />}
      {state === 'playing' && (
        <PlayingState
          key={status.match_id}
          status={status}
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
        <IdleState onJoin={onJoin} busy={busy} queueLength={queueLength} />
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

function IdleState({ onJoin, busy, queueLength }) {
  return (
    <>
      <h2 className="status-headline" id="status-headline">
        Table&nbsp;1 is open to you
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
  const unlockIn = status.leave_unlocks_in ?? 0;

  // The countdown ticks locally so the number moves every second rather
  // than lurching each time the server is polled. It's display only - the
  // server independently enforces the wait, so a second of drift here
  // can't let anyone leave early.
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
      <h2 className="status-headline" id="status-headline">
        {ahead === 0 ? "You're up next" : `You're number ${position} in line`}
      </h2>
      <p className="status-sub">
        {ahead === 0
          ? 'Stay close to the table. You go on as soon as an opponent is free.'
          : `${ahead} ${ahead === 1 ? 'player' : 'players'} ahead of you. This page updates on its own.`}
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
          Joined by accident? Leaving unlocks shortly, so nobody drops out of a
          match that was about to start.
        </p>
      )}
    </>
  );
}

function HoldingTableState({ queueLength, onStepDown, busy }) {
  return (
    <>
      <h2 className="status-headline" id="status-headline">
        <Crown size={30} aria-hidden="true" className="headline-icon headline-icon-crown" />
        You hold the table
      </h2>
      <p className="status-sub">
        {queueLength === 0
          ? 'You won, so you stay on. The next person to join the queue plays you.'
          : 'You won, so you stay on. Your next challenger is being matched now.'}
      </p>
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

function PlayingState({ status, onRecord, busy }) {
  const [scores, setScores] = useState({ mine: '', theirs: '' });
  const [error, setError] = useState(null);

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
    if (mine === theirs) {
      setError("Scores can't be a tie - somebody sank the 8.");
      return;
    }
    if (mine < 0 || theirs < 0 || mine > 8 || theirs > 8) {
      setError('Scores run from 0 to 8.');
      return;
    }

    // The match id says which game this score is for. If the opponent has
    // already reported it, the server refuses rather than filing this
    // score against the next game.
    onRecord(mine, theirs, status.match_id);
  };

  return (
    <>
      <h2 className="status-headline" id="status-headline">
        <Swords size={28} aria-hidden="true" className="headline-icon" />
        You're playing {status.opponent}
      </h2>
      <p className="status-sub">
        Table {status.table_id}. When the game is done, put the balls each of you
        sank below and the ladder updates for both of you.
      </p>

      <form onSubmit={submit} noValidate>
        <div className="score-grid">
          <div className="field field-flush">
            <label htmlFor="score-mine">Your balls</label>
            <input
              id="score-mine"
              className="score-input"
              type="number"
              min="0"
              max="8"
              inputMode="numeric"
              value={scores.mine}
              onChange={(e) => {
                setScores((s) => ({ ...s, mine: e.target.value }));
                setError(null);
              }}
            />
          </div>
          <div className="field field-flush">
            <label htmlFor="score-theirs">{status.opponent}&rsquo;s balls</label>
            <input
              id="score-theirs"
              className="score-input"
              type="number"
              min="0"
              max="8"
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
          <button type="button" className="btn btn-score btn-win" onClick={() => setBoth(8, 0)}>
            Won 8&ndash;0
          </button>
          <button type="button" className="btn btn-score btn-win" onClick={() => setBoth(8, 4)}>
            Won 8&ndash;4
          </button>
          <button type="button" className="btn btn-score btn-loss" onClick={() => setBoth(0, 8)}>
            Lost 0&ndash;8
          </button>
          <button type="button" className="btn btn-score btn-loss" onClick={() => setBoth(4, 8)}>
            Lost 4&ndash;8
          </button>
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
    </>
  );
}
