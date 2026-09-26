/**
 * What's happening right now in the chosen league, and the actions that
 * change it: your status, the queue, who is at the table; joining,
 * leaving, giving up the table and reporting a result.
 *
 * The mobile counterpart of the polling and action handlers in
 * Frontend/src/App.jsx. It polls for the whole app, not one screen, so a
 * player waiting in the queue who wanders over to the ladder still hears
 * "Match on" when their game starts. Polling pauses while the app is in
 * the background.
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

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
  table: null,
  loaded: { queue: false, table: false },
  offline: false,
};

const LiveContext = createContext(null);

export function LiveProvider({ children }) {
  const { status, user, league } = useSession();
  const { tableId } = useLeague();
  const toast = useToast();
  const active = useAppActive();

  // Everything here belongs to one player in one league. When either
  // changes, the old answers are dropped at once rather than shown under
  // the new league's name until the next poll.
  const scope = `${user?.user_id ?? ''}:${league ?? ''}:${tableId ?? ''}`;
  const [live, setLive] = useState(() => ({ scope, ...EMPTY }));
  if (live.scope !== scope) {
    setLive({ scope, ...EMPTY });
  }

  const [busy, setBusy] = useState(false);
  // Goes up whenever the game at the table changes - one ended, or one
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
  // The game last seen at the table, per scope.
  const tableMatchRef = useRef(null);

  const signedInWithTable = status === 'signedIn' && Boolean(league) && Boolean(tableId);

  const refresh = useCallback(
    async (signal) => {
      if (!signedInWithTable) return;
      const forScope = scope;
      const stale = () => signal?.aborted || scopeRef.current !== forScope;

      const [statusRes, queueRes, tableRes] = await Promise.all([
        api.getMatchStatus(tableId, signal),
        api.getQueue(tableId, signal),
        api.getTable(tableId, signal),
      ]);
      if (stale()) return;

      // Only a dropped connection counts as offline; a 4xx means the
      // server is up and talking to us, just refusing something.
      const offline = [statusRes, queueRes, tableRes].some(
        (res) => !res.ok && res.kind === api.ErrorKind.NETWORK && !res.aborted,
      );

      const table = tableRes.ok ? (tableRes.data?.table ?? null) : null;
      let tableMoved = false;
      if (table) {
        const last = tableMatchRef.current;
        tableMoved = last?.scope === forScope && last.matchId !== table.match_id;
        tableMatchRef.current = { scope: forScope, matchId: table.match_id };
      }

      setLive((current) => {
        if (current.scope !== forScope) return current;
        const next = { ...current, offline };
        if (queueRes.ok) {
          next.queue = Array.isArray(queueRes.data) ? queueRes.data : [];
          next.loaded = { ...next.loaded, queue: true };
        }
        if (table) {
          next.table = table;
          next.loaded = { ...next.loaded, table: true };
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
        if (next.status === 'playing' && next.match_id !== announcedRef.current) {
          announcedRef.current = next.match_id;
          toast.push(`Match on: you're playing ${next.opponent}.`, 'success');
        }
        if (next.status !== 'playing') announcedRef.current = null;
      }
    },
    [signedInWithTable, scope, tableId, toast],
  );

  usePolling(refresh, POLL_INTERVAL_MS, signedInWithTable && active);

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

  const join = useCallback(async () => {
    const res = await perform(() => api.joinQueue(tableId, league));
    if (!res.ok) {
      reportFailure(res);
      // A refusal usually means the screen was out of date (you're
      // already at the table, say) - catch up with what the server knows.
      refresh();
      return;
    }
    if (res.data?.match_started) toast.push('Match found - get to the table.', 'success');
    else if (res.data?.status === 'already_queued') toast.push("You're already in the queue.", 'info');
    else toast.push('You joined the queue.', 'success');
    refresh();
  }, [perform, tableId, league, reportFailure, refresh, toast]);

  const leave = useCallback(async () => {
    const res = await perform(() => api.leaveQueue(tableId, league));
    if (!res.ok) {
      reportFailure(res);
      // A 403 means the wait hasn't passed; re-sync so the countdown
      // shows the server's number rather than ours.
      refresh();
      return;
    }
    toast.push('You left the queue.', 'info');
    setMatchStatus({ status: 'idle' });
    refresh();
  }, [perform, tableId, league, reportFailure, refresh, toast, setMatchStatus]);

  const stepDown = useCallback(async () => {
    const res = await perform(() => api.stepDown(tableId));
    if (!res.ok) {
      reportFailure(res);
      refresh();
      return;
    }
    toast.push(res.data?.message || 'You gave up the table.', 'info');
    setMatchStatus({ status: 'idle' });
    setGamesVersion((v) => v + 1);
    refresh();
  }, [perform, tableId, reportFailure, refresh, toast, setMatchStatus]);

  /** gameLeague is the league of the game itself, from the status payload. */
  const record = useCallback(
    async (myScore, oppScore, matchId, gameLeague) => {
      const res = await perform(() => api.recordMatch(myScore, oppScore, matchId, gameLeague));
      if (!res.ok) {
        reportFailure(res);
        // 409: your opponent reported this game first. Move on to
        // whatever the server says is happening now.
        refresh();
        return;
      }
      const won = Number(myScore) > Number(oppScore);
      const change = res.data?.elo_change ?? 0;
      toast.push(
        won ? `You won. +${change} points.` : `Logged the loss. -${change} points.`,
        won ? 'success' : 'info',
      );
      announcedRef.current = null;
      setGamesVersion((v) => v + 1);
      refresh();
    },
    [perform, reportFailure, refresh, toast],
  );

  const value = useMemo(() => {
    // scope is internal bookkeeping, not something a screen needs.
    const { scope: _scope, ...state } = live;
    return { ...state, busy, gamesVersion, refresh, join, leave, stepDown, record };
  }, [live, busy, gamesVersion, refresh, join, leave, stepDown, record]);

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

/**
 * { matchStatus, statusProblem, queue, table, loaded, offline, busy,
 *   gamesVersion, refresh, join, leave, stepDown, record }
 */
export function useLive() {
  return useContext(LiveContext);
}
