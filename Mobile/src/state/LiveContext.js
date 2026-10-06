/**
 * What's happening right now in the chosen league, and the actions that
 * change it: your status, the league's queue, who is at each of its
 * tables; entering the league's PIN, joining, leaving, saying "I'm here",
 * giving up the table, reporting a result, and calling a game off by
 * agreement.
 *
 * readOnly says the player hasn't entered this league's PIN (or it has
 * changed since): they can look, but not join. The latest status poll
 * says so first, so a PIN changed by the organiser shows within seconds.
 *
 * The mobile counterpart of the polling and action handlers in
 * Frontend/src/App.jsx. It polls for the whole app, not one screen, so a
 * player waiting in the queue who wanders over to the ladder still hears
 * that it's their turn - with a buzz - or that their game is on. Polling
 * pauses while the app is in the background: there are no push
 * notifications, so a player whose turn is coming keeps the app open.
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import * as Haptics from 'expo-haptics';

import * as api from '../api';
import { POLL_INTERVAL_MS } from '../config';
import { useAppActive } from '../hooks/useAppActive';
import { usePolling } from '../hooks/usePolling';
import { useLeague } from './LeagueContext';
import { useSession } from './SessionContext';
import { useToast } from './ToastContext';

const EMPTY = {
  // null until the server has answered. Starting at 'idle' would flash a
  // Join button at people who are actually mid-game.
  matchStatus: null,
  // Set when the status check itself fails, so the panel can say so
  // rather than showing a stale state as if it were current.
  statusProblem: null,
  queue: [],
  // Every table the league has in use, and who is at each.
  tables: [],
  loaded: { queue: false, tables: false },
  offline: false,
};

const LiveContext = createContext(null);

export function LiveProvider({ children }) {
  const { status, user } = useSession();
  const { leagueId, league, reload: reloadLeagues, replaceLeague, noticeReadOnly } = useLeague();
  const toast = useToast();
  const active = useAppActive();

  // Everything here belongs to one player in one league. When either
  // changes, the old answers are dropped at once rather than shown under
  // the new league's name until the next poll.
  const scope = `${user?.user_id ?? ''}:${leagueId ?? ''}`;
  const [live, setLive] = useState(() => ({ scope, ...EMPTY }));
  if (live.scope !== scope) {
    setLive({ scope, ...EMPTY });
  }

  const [busy, setBusy] = useState(false);
  // Goes up whenever the game at a table changes - one ended, or one
  // began - so the history and ladder screens know to fetch again.
  const [gamesVersion, setGamesVersion] = useState(0);

  // An answer for a league the player has since switched away from must
  // not land; requests check this when they return.
  const scopeRef = useRef(scope);
  useEffect(() => {
    scopeRef.current = scope;
  }, [scope]);
  // The last match id announced, so "Match on" fires once per game.
  const announcedRef = useRef(null);
  // The status before the latest one, to notice what just happened: a
  // turn arriving, a turn missed, a game called off.
  const lastStatusRef = useRef(null);
  // The games last seen at the tables, per scope.
  const tableMatchRef = useRef(null);

  const inLeague = status === 'signedIn' && leagueId !== null;

  /** Tell the player about a change worth knowing about, wherever they are. */
  const noticeChange = useCallback(
    (previous, next) => {
      if (next.status === 'your_turn' && !next.confirmed && previous?.status !== 'your_turn') {
        toast.push('It\'s your turn - tap "I\'m here" within a minute to keep your place.', 'success');
        // A buzz, so a phone on the table gets noticed. Not every phone can.
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
      }
      if (previous?.status === 'your_turn' && !previous.confirmed && next.status === 'idle') {
        toast.push(
          "You didn't say you were here in time, so you were taken out of the queue. Join again to get back in line.",
          'error',
        );
      }
      if (
        previous?.status === 'playing' &&
        previous.cancel_requested_by === 'you' &&
        next.status !== 'playing'
      ) {
        toast.push(`${previous.opponent} agreed - the game was cancelled. Nothing was recorded.`, 'info');
        setGamesVersion((v) => v + 1);
      }
    },
    [toast],
  );

  const refresh = useCallback(
    async (signal) => {
      if (!inLeague) return;
      const forScope = scope;
      const stale = () => signal?.aborted || scopeRef.current !== forScope;

      const [statusRes, queueRes, tablesRes] = await Promise.all([
        api.getMatchStatus(leagueId, signal),
        api.getLeagueQueue(leagueId, signal),
        api.getLeagueTables(leagueId, signal),
      ]);
      if (stale()) return;

      // Only a dropped connection counts as offline; a 4xx means the
      // server is up and talking to us, just refusing something.
      const offline = [statusRes, queueRes, tablesRes].some(
        (res) => !res.ok && res.kind === api.ErrorKind.NETWORK && !res.aborted,
      );

      const tables =
        tablesRes.ok && Array.isArray(tablesRes.data?.tables) ? tablesRes.data.tables : null;
      let tableMoved = false;
      if (tables) {
        const games = tables.map((t) => `${t.table_id}:${t.match_id}`).join(',');
        const last = tableMatchRef.current;
        tableMoved = last?.scope === forScope && last.games !== games;
        tableMatchRef.current = { scope: forScope, games };
      }

      setLive((current) => {
        if (current.scope !== forScope) return current;
        const next = { ...current, offline };
        if (queueRes.ok) {
          next.queue = Array.isArray(queueRes.data) ? queueRes.data : [];
          next.loaded = { ...next.loaded, queue: true };
        }
        if (tables) {
          next.tables = tables;
          next.loaded = { ...next.loaded, tables: true };
        }
        if (statusRes.ok) {
          next.matchStatus = statusRes.data || { status: 'idle' };
          next.statusProblem = null;
        } else if (statusRes.kind === api.ErrorKind.SERVER) {
          // A dropped connection already shows the offline banner; this
          // is the server failing to answer, which the panel shows.
          next.statusProblem = statusRes.message;
        }
        return next;
      });

      if (tableMoved) setGamesVersion((v) => v + 1);

      // Tell someone their match started, whichever screen they're on.
      if (statusRes.ok) {
        const next = statusRes.data || { status: 'idle' };
        // A changed PIN (or one just entered on the website) shows on the
        // league list too.
        if (typeof next.read_only === 'boolean') noticeReadOnly(leagueId, next.read_only);
        const previous = lastStatusRef.current;
        lastStatusRef.current = next;
        noticeChange(previous, next);
        if (next.status === 'playing' && next.match_id !== announcedRef.current) {
          announcedRef.current = next.match_id;
          toast.push(`Match on: you're playing ${next.opponent}.`, 'success');
        }
        if (next.status !== 'playing') announcedRef.current = null;
      }
    },
    [inLeague, scope, leagueId, toast, noticeChange, noticeReadOnly],
  );

  // A new player or league starts with nothing to compare against.
  useEffect(() => {
    lastStatusRef.current = null;
  }, [scope]);

  usePolling(refresh, POLL_INTERVAL_MS, inLeague && active);

  // --- Actions: each tells the player what happened, then re-syncs ---

  const perform = useCallback(async (call) => {
    setBusy(true);
    try {
      return await call();
    } finally {
      setBusy(false);
    }
  }, []);

  /** A refusal, shown in the server's own words. An expired session already said so. */
  const reportFailure = useCallback(
    (res) => {
      if (res.kind !== api.ErrorKind.AUTH) toast.push(res.message, 'error');
    },
    [toast],
  );

  const setMatchStatus = useCallback((matchStatus) => {
    setLive((current) => ({ ...current, matchStatus }));
  }, []);

  /** A 403 that says the league needs its PIN: show the PIN prompt. */
  const noticeLocked = useCallback(
    (res) => {
      if (res.status === 403 && res.data?.read_only) {
        setLive((current) =>
          current.matchStatus
            ? { ...current, matchStatus: { ...current.matchStatus, read_only: true } }
            : current,
        );
        reloadLeagues();
      }
    },
    [reloadLeagues],
  );

  /** Enter the league's PIN. Returns { ok, field?, message? } for the form. */
  const unlock = useCallback(
    async (pin) => {
      const res = await perform(() => api.unlockLeague(leagueId, pin));
      if (!res.ok) {
        const field = res.data?.field;
        if (!field) reportFailure(res);
        return { ok: false, field, message: res.message };
      }
      toast.push(res.data?.message || "You're in.", 'success');
      replaceLeague(res.data?.league);
      setLive((current) =>
        current.matchStatus
          ? { ...current, matchStatus: { ...current.matchStatus, read_only: false } }
          : current,
      );
      refresh();
      return { ok: true };
    },
    [perform, leagueId, reportFailure, toast, replaceLeague, refresh],
  );

  const join = useCallback(async () => {
    const res = await perform(() => api.joinQueue(leagueId));
    if (!res.ok) {
      reportFailure(res);
      noticeLocked(res);
      // A refusal usually means the screen was out of date (you're
      // already at the table, say) - catch up with what the server knows.
      refresh();
      return;
    }
    if (res.data?.match_started) toast.push('Match found - get to the table.', 'success');
    else if (res.data?.status === 'already_queued') toast.push("You're already in the queue.", 'info');
    else toast.push('You joined the queue.', 'success');
    refresh();
  }, [perform, leagueId, reportFailure, noticeLocked, refresh, toast]);

  const leave = useCallback(async () => {
    const res = await perform(() => api.leaveQueue(leagueId));
    if (!res.ok) {
      reportFailure(res);
      // A 403 means the wait hasn't passed; re-sync so the countdown
      // shows the server's number rather than ours.
      refresh();
      return;
    }
    toast.push('You left the queue.', 'info');
    setMatchStatus({ status: 'idle' });
    // Leaving on your turn isn't missing it.
    lastStatusRef.current = { status: 'idle' };
    refresh();
  }, [perform, leagueId, reportFailure, refresh, toast, setMatchStatus]);

  /** "I'm here": the ready check, when it's the player's turn. */
  const confirm = useCallback(async () => {
    const res = await perform(() => api.confirmHere(leagueId));
    if (!res.ok) {
      reportFailure(res);
      noticeLocked(res);
      // Too late, or not their turn yet: catch up with the server, and
      // don't announce the miss a second time.
      if (res.status === 409 || res.status === 404) lastStatusRef.current = null;
    }
    // On success the panel changes by itself, and "Match on" is announced
    // when the game starts - a toast here too would say it twice.
    refresh();
  }, [perform, leagueId, reportFailure, noticeLocked, refresh]);

  /** Ask to cancel the game - or agree, when the opponent has asked. */
  const cancelGame = useCallback(
    async (matchId) => {
      const res = await perform(() => api.cancelMatch(matchId));
      if (!res.ok) {
        reportFailure(res);
        refresh();
        return;
      }
      if (res.data?.status === 'cancelled') {
        toast.push('Game cancelled - nothing was recorded.', 'info');
        lastStatusRef.current = null;
        announcedRef.current = null;
        setGamesVersion((v) => v + 1);
      }
      refresh();
    },
    [perform, reportFailure, refresh, toast],
  );

  /** Take back a request to cancel, or turn down the opponent's. */
  const keepPlaying = useCallback(
    async (matchId) => {
      const res = await perform(() => api.keepPlaying(matchId));
      if (!res.ok) reportFailure(res);
      refresh();
    },
    [perform, reportFailure, refresh],
  );

  const stepDown = useCallback(async () => {
    const res = await perform(() => api.stepDown());
    if (!res.ok) {
      reportFailure(res);
      refresh();
      return;
    }
    toast.push(res.data?.message || 'You gave up the table.', 'info');
    setMatchStatus({ status: 'idle' });
    lastStatusRef.current = { status: 'idle' };
    setGamesVersion((v) => v + 1);
    refresh();
  }, [perform, reportFailure, refresh, toast, setMatchStatus]);

  // --- The organiser's controls: offered only to an admin; the server
  // refuses anyone else regardless ---

  const finishRemoval = useCallback(
    (res, player) => {
      // Already gone, say, or the game changed: the server says which.
      if (!res.ok) reportFailure(res);
      else toast.push(res.data?.message || `${player.username} was removed.`, 'info');
      // An organiser who removes themselves didn't miss their turn.
      if (player.user_id === user?.user_id) lastStatusRef.current = null;
      refresh();
    },
    [reportFailure, toast, user, refresh],
  );

  /** Take a player out of the league's queue. */
  const removeFromQueue = useCallback(
    async (player) => {
      const res = await perform(() => api.adminRemoveFromQueue(player.user_id, leagueId));
      finishRemoval(res, player);
    },
    [perform, leagueId, finishRemoval],
  );

  /** Take a player off a table; matchId is the game the organiser saw there. */
  const removeFromTable = useCallback(
    async (player, matchId, tableId) => {
      const res = await perform(() => api.adminRemoveFromTable(player.user_id, tableId, matchId));
      finishRemoval(res, player);
    },
    [perform, finishRemoval],
  );

  /** gameLeagueId is the league of the game itself (the status's league_id). */
  const record = useCallback(
    async (myScore, oppScore, matchId, gameLeagueId) => {
      const res = await perform(() => api.recordMatch(myScore, oppScore, matchId, gameLeagueId));
      if (!res.ok) {
        reportFailure(res);
        noticeLocked(res);
        // 409: your opponent reported this game first. Move on to
        // whatever the server says is happening now.
        refresh();
        return;
      }
      const won = Number(myScore) > Number(oppScore);
      const change = res.data?.elo_change ?? 0;
      // A loser at the floor of 0 loses less than the winner gains.
      const lost = res.data?.loser_elo_change ?? change;
      toast.push(
        won ? `You won. +${change} points.` : `Logged the loss. -${lost} points.`,
        won ? 'success' : 'info',
      );
      announcedRef.current = null;
      setGamesVersion((v) => v + 1);
      refresh();
    },
    [perform, reportFailure, noticeLocked, refresh, toast],
  );

  const value = useMemo(() => {
    // scope is internal bookkeeping, not something a screen needs.
    const { scope: _scope, ...state } = live;
    return {
      ...state,
      readOnly: state.matchStatus?.read_only ?? league?.read_only ?? false,
      busy,
      gamesVersion,
      refresh,
      unlock,
      join,
      leave,
      confirm,
      stepDown,
      record,
      cancelGame,
      keepPlaying,
      removeFromQueue,
      removeFromTable,
    };
  }, [
    live,
    league,
    busy,
    gamesVersion,
    refresh,
    unlock,
    join,
    leave,
    confirm,
    stepDown,
    record,
    cancelGame,
    keepPlaying,
    removeFromQueue,
    removeFromTable,
  ]);

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

/**
 * { matchStatus, statusProblem, queue, tables, loaded, offline, readOnly,
 *   busy, gamesVersion, refresh, unlock, join, leave, confirm, stepDown,
 *   record, cancelGame, keepPlaying, removeFromQueue, removeFromTable }
 */
export function useLive() {
  return useContext(LiveContext);
}
