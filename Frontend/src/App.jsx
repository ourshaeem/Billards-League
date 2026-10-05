/**
 * Billiards League - app shell.
 *
 * Responsibilities kept here deliberately: who is signed in, what the
 * server last told us, and turning a click into an API call. Anything
 * visual lives in ./components, and anything HTTP lives in ./api.js.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { LogOut } from 'lucide-react';

import * as api from './api.js';
import { ToastStack, ConnectionBanner } from './components/Feedback.jsx';
import { LoginScreen, RegisterScreen } from './components/AuthScreens.jsx';
import { StatusPanel } from './components/StatusPanel.jsx';
import { QueueCard, LeaderboardCard, KingBanner } from './components/Panels.jsx';
import { BadgesCard } from './components/Badges.jsx';

const TABLE_ID = 1;
const POLL_INTERVAL_MS = 2500;

export default function App() {
  // Restore the session on load. Previously a refresh dropped you back to
  // the login screen even though the token was still perfectly valid.
  const [user, setUser] = useState(() => api.getStoredUser());
  const [view, setView] = useState(() => (api.getStoredUser() ? 'dashboard' : 'login'));

  const [queue, setQueue] = useState([]);
  const [leaderboard, setLeaderboard] = useState([]);
  // Who holds the table and their streak. null until the first answer.
  const [table, setTable] = useState(null);
  // The signed-in player's badges: null until loaded.
  const [badges, setBadges] = useState(null);
  // null until the server has answered. Starting at 'idle' flashed a Join
  // button at people who were actually mid-game or holding the table.
  const [matchStatus, setMatchStatus] = useState(null);
  // Set when the status check itself fails, so the panel can say so
  // rather than showing a stale state as if it were current.
  const [statusProblem, setStatusProblem] = useState(null);

  const [loaded, setLoaded] = useState({ queue: false, leaderboard: false });
  const [offline, setOffline] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toasts, setToasts] = useState([]);

  // Badge keys already announced, so a slow "mark seen" can't make the
  // next poll announce them twice.
  const announcedBadgesRef = useRef(new Set());

  // Remembers the last match id we announced, so "match found" fires once
  // rather than on every poll for as long as the match is running.
  const announcedMatchRef = useRef(null);

  const pushToast = useCallback((message, tone = 'info') => {
    if (!message) return;
    setToasts((current) => {
      // Tapping a button that keeps failing shouldn't build a tower of
      // identical messages - the existing one counts up instead.
      const same = current.find((t) => t.message === message && t.tone === tone);
      if (same) {
        return current.map((t) => (t === same ? { ...t, count: t.count + 1 } : t));
      }
      return [...current, { id: Date.now() + Math.random(), message, tone, count: 1 }];
    });
  }, []);

  const dismissToast = useCallback((id) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const signOut = useCallback(() => {
    api.clearSession();
    setUser(null);
    setBadges(null);
    announcedBadgesRef.current = new Set();
    setMatchStatus(null);
    setStatusProblem(null);
    announcedMatchRef.current = null;
    setView('login');
  }, []);

  // One expired token anywhere sends us back to the login screen, instead
  // of leaving buttons that fail silently.
  useEffect(() => {
    api.setAuthFailureHandler(() => {
      setUser((current) => {
        if (current) pushToast('Your session ended. Please sign in again.', 'error');
        return null;
      });
      setView('login');
    });
    return () => api.setAuthFailureHandler(null);
  }, [pushToast]);

  // --- Polling ---------------------------------------------------------

  const username = user?.username;
  const loadBadges = useCallback(async () => {
    if (!username) return;
    const res = await api.getPlayerBadges(username);
    if (res.ok && res.data) setBadges(res.data);
  }, [username]);

  // First load at sign-in; cancelled if they sign out before it lands.
  useEffect(() => {
    if (!username) return undefined;
    const controller = new AbortController();
    api.getPlayerBadges(username, controller.signal).then((res) => {
      if (res.ok && res.data) setBadges(res.data);
    });
    return () => controller.abort();
  }, [username]);

  // Announce newly earned badges once each, then tell the server.
  const announceBadges = useCallback(
    async (signal) => {
      const res = await api.getNewBadges(signal);
      if (!res.ok || signal?.aborted) return;
      const fresh = (res.data?.badges || []).filter(
        (b) => !announcedBadgesRef.current.has(b.key),
      );
      if (fresh.length === 0) return;

      fresh.forEach((b) => announcedBadgesRef.current.add(b.key));
      // A pile of badges at once (credit for past games, say) gets one
      // message instead of a wall of them.
      if (fresh.length > 3) {
        pushToast(`You unlocked ${fresh.length} badges. See them below.`, 'success');
      } else {
        fresh.forEach((b) => pushToast(`Badge unlocked: ${b.name}`, 'success'));
      }
      await api.markBadgesSeen(fresh.map((b) => b.key));
      loadBadges();
    },
    [pushToast, loadBadges],
  );

  const refresh = useCallback(
    async (signal) => {
      const [queueRes, boardRes, tableRes] = await Promise.all([
        api.getQueue(TABLE_ID, signal),
        api.getLeaderboard(signal),
        api.getTable(TABLE_ID, signal),
      ]);

      if (signal?.aborted) return;

      // Only the network case flips the offline banner; a 4xx means the
      // server is up and talking to us, just refusing something.
      const lostConnection =
        (!queueRes.ok && queueRes.kind === api.ErrorKind.NETWORK && !queueRes.aborted) ||
        (!boardRes.ok && boardRes.kind === api.ErrorKind.NETWORK && !boardRes.aborted);
      setOffline(lostConnection);

      if (queueRes.ok) {
        setQueue(Array.isArray(queueRes.data) ? queueRes.data : []);
        setLoaded((l) => (l.queue ? l : { ...l, queue: true }));
      }
      if (boardRes.ok) {
        setLeaderboard(Array.isArray(boardRes.data) ? boardRes.data : []);
        setLoaded((l) => (l.leaderboard ? l : { ...l, leaderboard: true }));
      }
      if (tableRes.ok && tableRes.data) {
        setTable(tableRes.data);
      }

      if (!api.getToken()) return;

      const statusRes = await api.getMatchStatus(TABLE_ID, signal);
      if (signal?.aborted || statusRes.aborted) return;
      if (!statusRes.ok) {
        // A dropped connection already has the offline banner; anything
        // else is the server failing to answer, which the panel shows.
        if (statusRes.kind === api.ErrorKind.SERVER) setStatusProblem(statusRes.message);
        return;
      }

      announceBadges(signal);

      const next = statusRes.data || { status: 'idle' };
      setStatusProblem(null);
      setMatchStatus(next);

      // Tell someone their match started even if they were looking away.
      if (next.status === 'playing' && next.match_id !== announcedMatchRef.current) {
        announcedMatchRef.current = next.match_id;
        pushToast(`Match on: you're playing ${next.opponent}.`, 'success');
      }
      if (next.status !== 'playing') {
        // A game just ended (either player reported it): progress bars
        // have moved even if no badge unlocked.
        if (announcedMatchRef.current !== null) loadBadges();
        announcedMatchRef.current = null;
      }
    },
    [pushToast, announceBadges, loadBadges],
  );

  useEffect(() => {
    const controller = new AbortController();
    let timer;

    const tick = async () => {
      await refresh(controller.signal);
      if (!controller.signal.aborted) {
        timer = setTimeout(tick, POLL_INTERVAL_MS);
      }
    };
    tick();

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
    // Depending on `user` restarts polling at sign-in/out. The original
    // also depended on queue.length, so every queue change tore down and
    // rebuilt the interval - which is why updates could stutter or fire
    // twice. The queue is data this effect reads, not a reason to restart.
  }, [refresh, user]);

  // --- Actions ---------------------------------------------------------

  const handleLogin = async (username, password) => {
    setBusy(true);
    const res = await api.login(username, password);
    setBusy(false);

    if (!res.ok) {
      pushToast(
        res.status === 401 ? 'That username or password is wrong.' : res.message,
        'error',
      );
      return;
    }

    api.setSession({
      token: res.data.access_token,
      userId: res.data.user_id,
      username: res.data.username,
    });
    // Earlier sign-in errors ("wrong password") no longer apply.
    setToasts([]);
    setMatchStatus(null);
    setUser({ user_id: res.data.user_id, username: res.data.username });
    setView('dashboard');
  };

  const handleRegister = async (payload) => {
    setBusy(true);
    const res = await api.register(payload);
    setBusy(false);

    if (!res.ok) {
      // The server explains why (taken username, short password), so pass
      // its wording straight through rather than inventing a vague one.
      pushToast(res.message, 'error');
      return;
    }

    pushToast('Account created. Sign in to get playing.', 'success');
    setView('login');
  };

  const handleJoin = async () => {
    setBusy(true);
    const res = await api.joinQueue(TABLE_ID);
    setBusy(false);

    if (!res.ok) {
      pushToast(res.message, 'error');
      // A refusal usually means the screen was out of date (you're
      // already at the table, say) - catch up with what the server knows.
      refresh();
      return;
    }

    if (res.data?.match_started) {
      pushToast('Match found - get to the table.', 'success');
    } else if (res.data?.status === 'already_queued') {
      pushToast("You're already in the queue.", 'info');
    } else {
      pushToast('You joined the queue.', 'success');
    }

    refresh();
  };

  const handleLeave = async () => {
    setBusy(true);
    const res = await api.leaveQueue(TABLE_ID);
    setBusy(false);

    if (!res.ok) {
      pushToast(res.message, 'error');
      // A 403 means the wait hasn't elapsed; re-sync so the countdown
      // shows the server's number rather than our optimistic one.
      refresh();
      return;
    }

    pushToast('You left the queue.', 'info');
    setMatchStatus({ status: 'idle' });
    refresh();
  };

  const handleStepDown = async () => {
    setBusy(true);
    const res = await api.stepDown(TABLE_ID);
    setBusy(false);

    if (!res.ok) {
      pushToast(res.message, 'error');
      refresh();
      return;
    }

    pushToast(res.data?.message || 'You gave up the table.', 'info');
    setMatchStatus({ status: 'idle' });
    refresh();
  };

  const handleRecord = async (myBalls, oppBalls, matchId) => {
    setBusy(true);
    const res = await api.recordMatch(myBalls, oppBalls, matchId);
    setBusy(false);

    if (!res.ok) {
      pushToast(res.message, 'error');
      // 409: your opponent reported this game first. Move on to whatever
      // the server says is happening now.
      refresh();
      return;
    }

    const won = Number(myBalls) > Number(oppBalls);
    const change = res.data?.elo_change ?? 0;
    pushToast(
      won ? `You won. +${change} points.` : `Logged the loss. -${change} points.`,
      won ? 'success' : 'info',
    );

    announcedMatchRef.current = null;
    refresh();
    loadBadges();
  };

  const handleFeature = async (key) => {
    setBusy(true);
    const res = await api.setFeaturedBadge(key);
    setBusy(false);

    if (!res.ok) {
      pushToast(res.message, 'error');
      return;
    }

    const name = key && badges ? badges.badges.find((b) => b.key === key)?.name : null;
    pushToast(name ? `${name} now shows next to your name.` : 'Your best badge will show automatically.', 'success');
    loadBadges();
    refresh();
  };

  // --- Render ----------------------------------------------------------

  return (
    <div className="page">
      <header className="masthead">
        <h1 className="wordmark">
          <span className="wordmark-dot" aria-hidden="true" />
          Billiards League
        </h1>

        {user && (
          <div className="masthead-side">
            <span>
              Signed in as <strong className="masthead-user">{user.username}</strong>
            </span>
            <button type="button" className="btn btn-quiet btn-small" onClick={signOut}>
              <LogOut size={15} aria-hidden="true" />
              Sign out
            </button>
          </div>
        )}
      </header>

      <ConnectionBanner offline={offline} />

      {view === 'login' && !user && (
        <LoginScreen onLogin={handleLogin} onSwitch={() => setView('register')} busy={busy} />
      )}

      {view === 'register' && !user && (
        <RegisterScreen onRegister={handleRegister} onSwitch={() => setView('login')} busy={busy} />
      )}

      {user && (
        <main>
          <StatusPanel
            status={matchStatus}
            problem={statusProblem}
            queueLength={queue.length}
            kingStreak={table?.current_streak ?? 0}
            onJoin={handleJoin}
            onLeave={handleLeave}
            onRecord={handleRecord}
            onStepDown={handleStepDown}
            busy={busy}
          />

          <KingBanner table={table} currentUsername={user.username} />

          <div className="grid">
            <QueueCard queue={queue} loaded={loaded.queue} currentUsername={user.username} />
            <LeaderboardCard
              players={leaderboard}
              loaded={loaded.leaderboard}
              currentUsername={user.username}
            />
          </div>

          <BadgesCard
            data={badges}
            loaded={badges !== null}
            onFeature={handleFeature}
            busy={busy}
          />
        </main>
      )}

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
