/**
 * Billiards & Ping Pong League - app shell.
 *
 * Responsibilities kept here deliberately: who is signed in, which league
 * this session is for, what the server last told us, and turning a click
 * into an API call. Anything visual lives in ./components, and anything
 * HTTP lives in ./api.js.
 *
 * Screens: login / register -> league (pick billiards or ping pong) ->
 * dashboard, with profile reachable from the masthead. The league choice
 * sets the theme, the table everything is polled for, and whose ratings
 * the ladder and hover cards show.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeftRight, LogOut } from 'lucide-react';

import * as api from './api.js';
import { flagEmoji } from './flags.js';
import { isLeague, leagueInfo } from './leagues.js';
import { ToastStack, ConnectionBanner } from './components/Feedback.jsx';
import { LoginScreen, RegisterScreen } from './components/AuthScreens.jsx';
import { StatusPanel } from './components/StatusPanel.jsx';
import { QueueCard, LeaderboardCard } from './components/Panels.jsx';
import { ActiveTableCard } from './components/ActiveTable.jsx';
import { MatchHistoryCard } from './components/MatchHistory.jsx';
import { LeagueSelect } from './components/LeagueSelect.jsx';
import { ProfileSettings } from './components/ProfileSettings.jsx';
import { Avatar } from './components/Player.jsx';

const POLL_INTERVAL_MS = 2500;
// History only changes when a game ends. It's fetched on every Nth poll,
// and straight away whenever the table shows a different game - rather
// than two more requests every 2.5 seconds.
const HISTORY_EVERY_N_POLLS = 6;
const HISTORY_LIMIT = 15;
const LEAGUES_RETRY_MS = 5000;

const APP_NAME = 'Billiards & Ping Pong';
const EMPTY_HISTORY = { all: [], mine: [] };
const NOTHING_LOADED = { queue: false, leaderboard: false, table: false, history: false };

function storedLeague() {
  const league = api.getStoredLeague();
  return isLeague(league) ? league : null;
}

/** The signed-in player's profile, or null if it couldn't be loaded. */
async function fetchProfile(signal) {
  const res = await api.getProfile(signal);
  if (signal?.aborted || res.aborted || !res.ok) return null;
  return res.data?.profile ?? null;
}

function firstView() {
  if (!api.getStoredUser()) return 'login';
  return storedLeague() ? 'dashboard' : 'league';
}

export default function App() {
  // Restore the session on load. Previously a refresh dropped you back to
  // the login screen even though the token was still perfectly valid.
  const [user, setUser] = useState(() => api.getStoredUser());
  const [view, setView] = useState(firstView);
  const [league, setLeague] = useState(() => (api.getStoredUser() ? storedLeague() : null));

  // From GET /leagues: { billiards: {table_id, table_name, ...}, ping_pong: {...} }
  const [leagueTables, setLeagueTables] = useState(null);
  const [profile, setProfile] = useState(null);
  const [countries, setCountries] = useState(null);

  const [queue, setQueue] = useState([]);
  const [leaderboard, setLeaderboard] = useState([]);
  const [activeTable, setActiveTable] = useState(null);
  const [history, setHistory] = useState(EMPTY_HISTORY);
  // null until the server has answered. Starting at 'idle' flashed a Join
  // button at people who were actually mid-game or holding the table.
  const [matchStatus, setMatchStatus] = useState(null);
  // Set when the status check itself fails, so the panel can say so
  // rather than showing a stale state as if it were current.
  const [statusProblem, setStatusProblem] = useState(null);

  const [loaded, setLoaded] = useState(NOTHING_LOADED);
  const [offline, setOffline] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toasts, setToasts] = useState([]);

  // Remembers the last match id we announced, so "match found" fires once
  // rather than on every poll for as long as the match is running.
  const announcedMatchRef = useRef(null);
  // The game last seen at the table. When it changes, a game has ended
  // (or begun), so the history is due a refresh.
  const tableMatchRef = useRef(undefined);
  // The league on screen, read by requests as they return: an answer for
  // the league the player just switched away from must not land.
  const leagueRef = useRef(league);

  const userId = user?.user_id ?? null;
  const tableId = league ? (leagueTables?.[league]?.table_id ?? null) : null;
  const tableName = league ? leagueTables?.[league]?.table_name : null;

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

  /** Forget everything shown for the current league. */
  const clearLeagueData = useCallback(() => {
    setQueue([]);
    setLeaderboard([]);
    setActiveTable(null);
    setHistory(EMPTY_HISTORY);
    setMatchStatus(null);
    setStatusProblem(null);
    setLoaded(NOTHING_LOADED);
    tableMatchRef.current = undefined;
  }, []);

  const switchLeague = useCallback(
    (next) => {
      leagueRef.current = next;
      setLeague(next);
      clearLeagueData();
    },
    [clearLeagueData],
  );

  const signOut = useCallback(() => {
    api.clearSession();
    setUser(null);
    setProfile(null);
    switchLeague(null);
    announcedMatchRef.current = null;
    setView('login');
  }, [switchLeague]);

  // One expired token anywhere sends us back to the login screen, instead
  // of leaving buttons that fail silently.
  useEffect(() => {
    api.setAuthFailureHandler(() => {
      setUser((current) => {
        if (current) pushToast('Your session ended. Please sign in again.', 'error');
        return null;
      });
      setProfile(null);
      switchLeague(null);
      setView('login');
    });
    return () => api.setAuthFailureHandler(null);
  }, [pushToast, switchLeague]);

  // The theme follows the league. Set on <html> so the page background,
  // outside the React tree, changes with it.
  useEffect(() => {
    const root = document.documentElement;
    if (league) root.dataset.league = league;
    else delete root.dataset.league;
    document.title = league ? leagueInfo(league).name : APP_NAME;
  }, [league]);

  // --- Reference data --------------------------------------------------

  // Which table each league plays on. Retried until it arrives: without
  // it there is no table to show or queue for.
  useEffect(() => {
    if (leagueTables) return undefined;
    const controller = new AbortController();
    let timer;

    const load = async () => {
      const res = await api.getLeagues(controller.signal);
      if (controller.signal.aborted || res.aborted) return;
      if (res.ok && Array.isArray(res.data?.leagues)) {
        const byLeague = {};
        res.data.leagues.forEach((entry) => {
          if (isLeague(entry.league_type)) byLeague[entry.league_type] = entry;
        });
        setOffline(false);
        setLeagueTables(byLeague);
        return;
      }
      if (res.kind === api.ErrorKind.NETWORK) setOffline(true);
      timer = setTimeout(load, LEAGUES_RETRY_MS);
    };
    load();

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [leagueTables]);

  // Reloaded on every change of screen, so the standings on the league
  // picker and profile page reflect the games just played.
  useEffect(() => {
    if (!userId) return undefined;
    const controller = new AbortController();
    fetchProfile(controller.signal).then((next) => {
      if (next && !controller.signal.aborted) setProfile(next);
    });
    return () => controller.abort();
  }, [userId, view]);

  // The flag picker's list, fetched the first time it's needed.
  useEffect(() => {
    if (view !== 'profile' || countries) return undefined;
    const controller = new AbortController();
    api.getCountries(controller.signal).then((res) => {
      if (controller.signal.aborted || res.aborted) return;
      if (res.ok && Array.isArray(res.data?.countries)) {
        setCountries(res.data.countries);
      } else {
        pushToast("Couldn't load the list of countries. Try opening your profile again.", 'error');
      }
    });
    return () => controller.abort();
  }, [view, countries, pushToast]);

  // --- Polling ---------------------------------------------------------

  const refresh = useCallback(
    async (signal, { withHistory = false } = {}) => {
      if (!league || !tableId) return;
      const forLeague = league;
      const stale = () => signal?.aborted || leagueRef.current !== forLeague;

      const [queueRes, boardRes, tableRes] = await Promise.all([
        api.getQueue(tableId, signal),
        api.getLeaderboard(forLeague, signal),
        api.getTable(tableId, signal),
      ]);
      if (stale()) return;

      // Only the network case flips the offline banner; a 4xx means the
      // server is up and talking to us, just refusing something.
      setOffline(
        [queueRes, boardRes, tableRes].some(
          (res) => !res.ok && res.kind === api.ErrorKind.NETWORK && !res.aborted,
        ),
      );

      if (queueRes.ok) {
        setQueue(Array.isArray(queueRes.data) ? queueRes.data : []);
        setLoaded((l) => (l.queue ? l : { ...l, queue: true }));
      }
      if (boardRes.ok) {
        setLeaderboard(Array.isArray(boardRes.data) ? boardRes.data : []);
        setLoaded((l) => (l.leaderboard ? l : { ...l, leaderboard: true }));
      }

      let tableMoved = false;
      if (tableRes.ok && tableRes.data?.table) {
        const table = tableRes.data.table;
        tableMoved =
          tableMatchRef.current !== undefined && tableMatchRef.current !== table.match_id;
        tableMatchRef.current = table.match_id;
        setActiveTable(table);
        setLoaded((l) => (l.table ? l : { ...l, table: true }));
      }

      if (withHistory || tableMoved) {
        const [allRes, mineRes] = await Promise.all([
          api.getMatchHistory(forLeague, { limit: HISTORY_LIMIT }, signal),
          userId
            ? api.getPlayerMatches(userId, forLeague, { limit: HISTORY_LIMIT }, signal)
            : null,
        ]);
        if (stale()) return;
        if (allRes.ok) {
          setHistory((h) => ({
            all: Array.isArray(allRes.data?.matches) ? allRes.data.matches : [],
            mine: mineRes?.ok && Array.isArray(mineRes.data?.matches) ? mineRes.data.matches : h.mine,
          }));
          setLoaded((l) => (l.history ? l : { ...l, history: true }));
        }
      }

      if (!api.getToken()) return;

      const statusRes = await api.getMatchStatus(tableId, signal);
      if (stale() || statusRes.aborted) return;
      if (!statusRes.ok) {
        // A dropped connection already has the offline banner; anything
        // else is the server failing to answer, which the panel shows.
        if (statusRes.kind === api.ErrorKind.SERVER) setStatusProblem(statusRes.message);
        return;
      }

      const next = statusRes.data || { status: 'idle' };
      setStatusProblem(null);
      setMatchStatus(next);

      // Tell someone their match started even if they were looking away.
      if (next.status === 'playing' && next.match_id !== announcedMatchRef.current) {
        announcedMatchRef.current = next.match_id;
        pushToast(`Match on: you're playing ${next.opponent}.`, 'success');
      }
      if (next.status !== 'playing') {
        announcedMatchRef.current = null;
      }
    },
    [league, tableId, userId, pushToast],
  );

  const polling = Boolean(userId) && view === 'dashboard' && Boolean(tableId);

  useEffect(() => {
    if (!polling) return undefined;
    const controller = new AbortController();
    let timer;
    let ticks = 0;

    const tick = async () => {
      await refresh(controller.signal, { withHistory: ticks % HISTORY_EVERY_N_POLLS === 0 });
      ticks += 1;
      if (!controller.signal.aborted) {
        timer = setTimeout(tick, POLL_INTERVAL_MS);
      }
    };
    tick();

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
    // Restarts when the league (and so the table) changes, or when the
    // dashboard is left and returned to. The queue is data this effect
    // reads, not a reason to restart - depending on it once made every
    // queue change tear down and rebuild the timer.
  }, [refresh, polling]);

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
    // Every sign-in starts by choosing a league for the session.
    api.setStoredLeague(null);
    switchLeague(null);
    // Earlier sign-in errors ("wrong password") no longer apply.
    setToasts([]);
    setUser({ user_id: res.data.user_id, username: res.data.username });
    setView('league');
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

  const chooseLeague = (next) => {
    api.setStoredLeague(next);
    if (next !== league) switchLeague(next);
    setView('dashboard');
  };

  const handleJoin = async () => {
    setBusy(true);
    const res = await api.joinQueue(tableId, league);
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
    const res = await api.leaveQueue(tableId, league);
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
    const res = await api.stepDown(tableId);
    setBusy(false);

    if (!res.ok) {
      pushToast(res.message, 'error');
      refresh();
      return;
    }

    pushToast(res.data?.message || 'You gave up the table.', 'info');
    setMatchStatus({ status: 'idle' });
    refresh(undefined, { withHistory: true });
  };

  const handleRecord = async (myScore, oppScore, matchId, gameLeague) => {
    setBusy(true);
    const res = await api.recordMatch(myScore, oppScore, matchId, gameLeague);
    setBusy(false);

    if (!res.ok) {
      pushToast(res.message, 'error');
      // 409: your opponent reported this game first. Move on to whatever
      // the server says is happening now.
      refresh();
      return;
    }

    const won = Number(myScore) > Number(oppScore);
    const change = res.data?.elo_change ?? 0;
    pushToast(
      won ? `You won. +${change} points.` : `Logged the loss. -${change} points.`,
      won ? 'success' : 'info',
    );

    announcedMatchRef.current = null;
    refresh(undefined, { withHistory: true });
    // So the league picker and profile page show the new rating.
    fetchProfile().then((next) => next && setProfile(next));
  };

  /** Returns { ok, field?, message? } so the form can put a problem beside its field. */
  const handleSaveProfile = async (changes) => {
    setBusy(true);
    const res = await api.updateProfile(changes);
    setBusy(false);

    if (!res.ok) {
      const field = res.data?.field;
      // A problem with one field is shown beside it by the form.
      if (!field) pushToast(res.message, 'error');
      return { ok: false, field, message: res.message };
    }

    setProfile(res.data.profile);
    pushToast('Profile saved.', 'success');
    return { ok: true };
  };

  // --- Render ----------------------------------------------------------

  // A dashboard with no league chosen can't show anything; ask instead.
  const screen = user ? (view === 'dashboard' && !league ? 'league' : view) : view;
  const me = profile ?? (user ? { username: user.username } : null);
  const myFlag = flagEmoji(profile?.country_flag);

  return (
    <div className="page">
      <header className="masthead">
        <h1 className="wordmark">
          <span className="wordmark-dot" aria-hidden="true" />
          {league ? leagueInfo(league).name : APP_NAME}
        </h1>

        {user && (
          <div className="masthead-side">
            <button
              type="button"
              className="masthead-profile"
              onClick={() => setView('profile')}
              aria-current={screen === 'profile' ? 'page' : undefined}
            >
              <Avatar player={me} size="sm" />
              <strong className="masthead-user">{user.username}</strong>
              {myFlag && <span aria-hidden="true">{myFlag}</span>}
              <span className="sr-only"> - your profile</span>
            </button>
            {league && screen !== 'league' && (
              <button
                type="button"
                className="btn btn-quiet btn-small"
                onClick={() => setView('league')}
              >
                <ArrowLeftRight size={15} aria-hidden="true" />
                Switch league
              </button>
            )}
            <button type="button" className="btn btn-quiet btn-small" onClick={signOut}>
              <LogOut size={15} aria-hidden="true" />
              Sign out
            </button>
          </div>
        )}
      </header>

      <ConnectionBanner offline={offline} />

      {screen === 'login' && !user && (
        <LoginScreen onLogin={handleLogin} onSwitch={() => setView('register')} busy={busy} />
      )}

      {screen === 'register' && !user && (
        <RegisterScreen onRegister={handleRegister} onSwitch={() => setView('login')} busy={busy} />
      )}

      {user && screen === 'league' && (
        <LeagueSelect
          current={league}
          profile={profile}
          leagueTables={leagueTables}
          onChoose={chooseLeague}
        />
      )}

      {user && screen === 'profile' &&
        (profile ? (
          <ProfileSettings
            key={profile.user_id}
            profile={profile}
            countries={countries}
            onSave={handleSaveProfile}
            onBack={() => setView(league ? 'dashboard' : 'league')}
            busy={busy}
          />
        ) : (
          <main className="profile-shell">
            <p className="empty">Loading your profile...</p>
          </main>
        ))}

      {user && screen === 'dashboard' && league && leagueTables && !tableId && (
        <main className="auth-shell">
          <div className="card">
            <p>The {leagueInfo(league).name} doesn&rsquo;t have a table set up yet.</p>
            <button
              type="button"
              className="btn btn-quiet btn-small"
              style={{ marginTop: 14 }}
              onClick={() => setView('league')}
            >
              Choose another league
            </button>
          </div>
        </main>
      )}

      {user && screen === 'dashboard' && league && (!leagueTables || tableId) && (
        <main>
          <StatusPanel
            status={matchStatus}
            problem={statusProblem}
            league={league}
            tableName={tableName}
            queueLength={queue.length}
            onJoin={handleJoin}
            onLeave={handleLeave}
            onRecord={handleRecord}
            onStepDown={handleStepDown}
            onSwitchLeague={chooseLeague}
            busy={busy}
          />

          <div className="grid">
            <ActiveTableCard
              table={activeTable}
              loaded={loaded.table}
              league={league}
              tableName={tableName}
              currentUserId={userId}
            />
            <QueueCard queue={queue} loaded={loaded.queue} currentUsername={user.username} />
            <MatchHistoryCard
              history={history}
              loaded={loaded.history}
              league={league}
              currentUserId={userId}
            />
            <LeaderboardCard
              players={leaderboard}
              loaded={loaded.leaderboard}
              currentUsername={user.username}
            />
          </div>
        </main>
      )}

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
