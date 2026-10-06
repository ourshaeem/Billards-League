/**
 * Billiards & Ping Pong League - app shell.
 *
 * Responsibilities kept here deliberately: who is signed in, which league
 * this session is for, what the server last told us, and turning a click
 * into an API call. Anything visual lives in ./components, and anything
 * HTTP lives in ./api.js.
 *
 * Screens: login / register -> league (any school's billiards or ping
 * pong) -> dashboard, with profile reachable from the masthead, and - for
 * the organiser - the league's settings. The league choice sets the
 * colours (from the league's own two), the queue and tables everything is
 * polled for, and whose ratings the ladder and hover cards show. Anyone
 * can look at any league; playing there takes its PIN, entered once.
 * Clicking any player opens their profile over whichever screen is
 * showing; the browser's Back button closes it again.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeftRight, BellRing, LogOut, Moon, Settings, Sun } from 'lucide-react';

import * as api from './api.js';
import { flagEmoji } from './flags.js';
import {
  applyLeagueColors,
  applyTheme,
  getThemeChoice,
  resolveTheme,
  setThemeChoice,
  watchSystemTheme,
} from './theme.js';
import { ToastStack, ConnectionBanner } from './components/Feedback.jsx';
import {
  AddEmailScreen,
  ForgotPasswordScreen,
  LoginScreen,
  RegisterScreen,
} from './components/AuthScreens.jsx';
import { StatusPanel } from './components/StatusPanel.jsx';
import { QueueCard, LeaderboardCard } from './components/Panels.jsx';
import { TablesCard } from './components/ActiveTable.jsx';
import { BadgesCard } from './components/Badges.jsx';
import { MatchHistoryCard } from './components/MatchHistory.jsx';
import { LeagueSelect } from './components/LeagueSelect.jsx';
import { LeagueSettings } from './components/LeagueSettings.jsx';
import { ProfileSettings } from './components/ProfileSettings.jsx';
import { PlayerProfile } from './components/PlayerProfile.jsx';
import { Avatar } from './components/Player.jsx';
import { OpenPlayerContext } from './openPlayer.js';

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

/**
 * The league this device last played in, as stored: a league_id, or the
 * "billiards" / "ping_pong" an app from before schools saved - resolved
 * against the directory once it arrives (league.legacy_key).
 */
function storedLeagueId() {
  const stored = api.getStoredLeague();
  return stored && /^\d+$/.test(stored) ? Number(stored) : null;
}

/** The signed-in player's profile, or null if it couldn't be loaded. */
async function fetchProfile(signal) {
  const res = await api.getProfile(signal);
  if (signal?.aborted || res.aborted || !res.ok) return null;
  return res.data?.profile ?? null;
}

function firstView() {
  if (!api.getStoredUser()) return 'login';
  return api.getStoredLeague() ? 'dashboard' : 'league';
}

export default function App() {
  // Restore the session on load. Previously a refresh dropped you back to
  // the login screen even though the token was still perfectly valid.
  const [user, setUser] = useState(() => api.getStoredUser());
  const [view, setView] = useState(firstView);
  const [leagueId, setLeagueId] = useState(() => (api.getStoredUser() ? storedLeagueId() : null));

  // Every league, from GET /leagues/directory: names, colours, tables and
  // read_only - which belongs to whoever was signed in when it loaded, so
  // it's kept with them, and a list from before a sign-in is never shown
  // after it. null until it arrives.
  const [directory, setDirectory] = useState({ forUser: undefined, leagues: null });
  const leagues = directory.forUser === (user?.user_id ?? null) ? directory.leagues : null;
  const setLeagues = useCallback(
    (update) =>
      setDirectory((d) => ({
        ...d,
        leagues: typeof update === 'function' ? update(d.leagues) : update,
      })),
    [],
  );
  const league = leagues?.find((l) => l.league_id === leagueId) ?? null;
  const [profile, setProfile] = useState(null);
  // Whether the signed-in account still needs an email (made before
  // sign-up asked for one): null until known. True shows the add-email
  // step before anything else.
  const [emailMissing, setEmailMissing] = useState(null);
  const [countries, setCountries] = useState(null);

  const [queue, setQueue] = useState([]);
  const [leaderboard, setLeaderboard] = useState([]);
  // Every table the league has in use, and who is at each.
  const [tables, setTables] = useState([]);
  const [history, setHistory] = useState(EMPTY_HISTORY);
  // Players of the day, week and month; null until first loaded.
  const [topPlayers, setTopPlayers] = useState(null);
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

  // Light or dark: the stored choice, and what it means right now.
  const [themeChoice, setThemeChoiceState] = useState(getThemeChoice);
  const [theme, setTheme] = useState(() => resolveTheme(getThemeChoice()));
  // The player whose profile is open, over the current screen, or null.
  const [viewingPlayer, setViewingPlayer] = useState(null);
  // Bumped whenever the signed-in player's badges may have changed, so
  // their badge card loads again.
  const [badgeVersion, setBadgeVersion] = useState(0);

  // Remembers the last match id we announced, so "match found" fires once
  // rather than on every poll for as long as the match is running.
  const announcedMatchRef = useRef(null);
  // Badges already announced, so a slow "mark seen" can't make the next
  // poll announce them twice.
  const announcedBadgesRef = useRef(new Set());
  // The status before the latest one, to notice what just happened: a
  // turn arriving, a turn missed, a game called off.
  const lastStatusRef = useRef(null);
  // The games last seen at the tables. When they change, a game has ended
  // (or begun), so the history is due a refresh.
  const tableMatchRef = useRef(undefined);
  // The league on screen, read by requests as they return: an answer for
  // the league the player just switched away from must not land.
  const leagueRef = useRef(leagueId);

  const userId = user?.user_id ?? null;
  // What the panel offers: read_only from the latest status poll (which
  // notices a changed PIN at once), else the directory's.
  const readOnly = matchStatus?.read_only ?? league?.read_only ?? false;

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
    setTables([]);
    setHistory(EMPTY_HISTORY);
    setTopPlayers(null);
    setMatchStatus(null);
    setStatusProblem(null);
    setLoaded(NOTHING_LOADED);
    tableMatchRef.current = undefined;
  }, []);

  const switchLeague = useCallback(
    (next) => {
      leagueRef.current = next;
      setLeagueId(next);
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
    announcedBadgesRef.current = new Set();
    lastStatusRef.current = null;
    setViewingPlayer(null);
    setEmailMissing(null);
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
      setViewingPlayer(null);
      setView('login');
    });
    return () => api.setAuthFailureHandler(null);
  }, [pushToast, switchLeague]);

  // The league's colours follow the league, and light or dark. Set on
  // <html> so the page background, outside the React tree, changes too.
  const leagueColors = league ? `${league.league_id}:${league.primary_color}:${league.secondary_color}` : '';
  useEffect(() => {
    applyLeagueColors(league, theme);
    // Keyed on the colours, not the league object, which every directory
    // reload replaces.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leagueColors, theme]);

  // The tab's title says when it's your turn, so a player in another tab
  // can see it from the tab strip.
  const yourTurnNow = matchStatus?.status === 'your_turn' && !matchStatus.confirmed;
  const leagueName = league?.name ?? null;
  useEffect(() => {
    const base = leagueName ?? APP_NAME;
    document.title = yourTurnNow ? `Your turn! - ${base}` : base;
  }, [leagueName, yourTurnNow]);

  // Light or dark. "Automatic" keeps following the device as it changes.
  useEffect(() => {
    const apply = () => {
      const next = resolveTheme(themeChoice);
      applyTheme(next);
      setTheme(next);
    };
    apply();
    return themeChoice === 'system' ? watchSystemTheme(apply) : undefined;
  }, [themeChoice]);

  const chooseTheme = useCallback((choice) => {
    setThemeChoice(choice);
    setThemeChoiceState(choice);
  }, []);

  // --- Looking at another player -------------------------------------
  // Each profile opened is a step in the browser's history, so Back (or
  // a phone's back gesture) closes it instead of leaving the site.

  const openPlayer = useCallback((playerId) => {
    setViewingPlayer(playerId);
    try {
      window.history.pushState({ playerId }, '');
    } catch {
      // History can be unavailable in odd embeddings; the Back button still works.
    }
    window.scrollTo({ top: 0 });
  }, []);

  const closePlayer = useCallback(() => {
    if (window.history.state?.playerId) window.history.back();
    else setViewingPlayer(null);
  }, []);

  useEffect(() => {
    const onPop = (e) => setViewingPlayer(e.state?.playerId ?? null);
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  // --- Reference data --------------------------------------------------

  // Every league: names, colours, tables, and where this player can play.
  // Reloaded when someone signs in or out (read_only is theirs), and on
  // reloadLeagues(); retried until it arrives - without it there is
  // nothing to show.
  const [directoryVersion, setDirectoryVersion] = useState(0);
  const reloadLeagues = useCallback(() => setDirectoryVersion((v) => v + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    const forUser = userId;
    let timer;

    const load = async () => {
      const res = await api.getLeagueDirectory(controller.signal);
      if (controller.signal.aborted || res.aborted) return;
      if (res.ok && Array.isArray(res.data?.leagues)) {
        setOffline(false);
        setDirectory({ forUser, leagues: res.data.leagues });
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
  }, [userId, directoryVersion]);

  // A league saved as "billiards" / "ping_pong" by the app before there
  // were schools: CCNY's league of that game, now it can be looked up.
  useEffect(() => {
    if (!leagues || leagueId !== null || !user) return;
    const stored = api.getStoredLeague();
    const match = stored && leagues.find((l) => l.legacy_key === stored);
    if (match) {
      api.setStoredLeague(match.league_id);
      switchLeague(match.league_id);
    } else if (stored && view === 'dashboard') {
      setView('league');
    }
  }, [leagues, leagueId, user, view, switchLeague]);

  // Reloaded on every change of screen, so the standings on the league
  // picker and profile page reflect the games just played.
  useEffect(() => {
    if (!userId) return undefined;
    const controller = new AbortController();
    fetchProfile(controller.signal).then((next) => {
      if (next && !controller.signal.aborted) {
        setProfile(next);
        setEmailMissing(!next.email);
      }
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

  /** Tell the player about a change worth knowing about, wherever they are. */
  const noticeStatusChange = useCallback(
    (previous, next) => {
      if (next.status === 'your_turn' && !next.confirmed && previous?.status !== 'your_turn') {
        pushToast(
          'It\'s your turn - tap "I\'m here" within a minute to keep your place.',
          'success',
        );
        // A buzz, on phones that allow it.
        navigator.vibrate?.([200, 100, 200]);
      }
      if (previous?.status === 'your_turn' && !previous.confirmed && next.status === 'idle') {
        pushToast(
          "You didn't say you were here in time, so you were taken out of the queue. Join again to get back in line.",
          'error',
        );
      }
      if (
        previous?.status === 'playing' &&
        previous.cancel_requested_by === 'you' &&
        next.status !== 'playing'
      ) {
        pushToast(
          `${previous.opponent} agreed - the game was cancelled. Nothing was recorded.`,
          'info',
        );
      }
    },
    [pushToast],
  );

  /** Announce badges earned since the last look - in either league - once each. */
  const announceBadges = useCallback(
    async (signal) => {
      const res = await api.getNewBadges(signal);
      if (!res.ok || signal?.aborted) return;
      const fresh = (res.data?.badges || []).filter((b) => !announcedBadgesRef.current.has(b.id));
      if (fresh.length === 0) return;

      fresh.forEach((b) => announcedBadgesRef.current.add(b.id));
      // A pile at once (credit for past games, say) is one message, not a wall.
      if (fresh.length > 3) {
        pushToast(`You unlocked ${fresh.length} badges. See them on your dashboard.`, 'success');
      } else {
        fresh.forEach((b) => {
          const where =
            b.league_id !== leagueRef.current && b.league_name ? ` (${b.league_name})` : '';
          pushToast(`Badge unlocked: ${b.name}${where}`, 'success');
        });
      }
      await api.markBadgesSeen(fresh.map((b) => b.id));
      setBadgeVersion((v) => v + 1);
    },
    [pushToast],
  );

  const refresh = useCallback(
    async (signal, { withHistory = false, statusOnly = false } = {}) => {
      if (!leagueId) return;
      const forLeague = leagueId;
      const stale = () => signal?.aborted || leagueRef.current !== forLeague;

      // Off the dashboard (a profile page) only your own status matters:
      // enough to tell you when it's your turn.
      if (!statusOnly) {
        const [queueRes, boardRes, tableRes] = await Promise.all([
          api.getLeagueQueue(forLeague, signal),
          api.getLeaderboard(forLeague, signal),
          api.getLeagueTables(forLeague, signal),
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
        if (tableRes.ok && Array.isArray(tableRes.data?.tables)) {
          const games = tableRes.data.tables.map((t) => `${t.table_id}:${t.match_id}`).join(',');
          tableMoved = tableMatchRef.current !== undefined && tableMatchRef.current !== games;
          tableMatchRef.current = games;
          setTables(tableRes.data.tables);
          setLoaded((l) => (l.table ? l : { ...l, table: true }));
        }

        if (withHistory || tableMoved) {
          // The players of the day, week and month change only when a game
          // finishes (or a day begins), so they come with the history.
          const [allRes, mineRes, topRes] = await Promise.all([
            api.getMatchHistory(forLeague, { limit: HISTORY_LIMIT }, signal),
            userId
              ? api.getPlayerMatches(userId, forLeague, { limit: HISTORY_LIMIT }, signal)
              : null,
            api.getTopPlayers(forLeague, signal),
          ]);
          if (stale()) return;
          if (topRes.ok && topRes.data) setTopPlayers(topRes.data);
          if (allRes.ok) {
            setHistory((h) => ({
              all: Array.isArray(allRes.data?.matches) ? allRes.data.matches : [],
              mine:
                mineRes?.ok && Array.isArray(mineRes.data?.matches) ? mineRes.data.matches : h.mine,
            }));
            setLoaded((l) => (l.history ? l : { ...l, history: true }));
          }
        }
      }

      if (!api.getToken()) return;

      const statusRes = await api.getMatchStatus(forLeague, signal);
      if (stale() || statusRes.aborted) return;
      if (!statusRes.ok) {
        // A dropped connection already has the offline banner; anything
        // else is the server failing to answer, which the panel shows.
        if (statusRes.kind === api.ErrorKind.SERVER) setStatusProblem(statusRes.message);
        if (statusRes.kind === api.ErrorKind.NETWORK) setOffline(true);
        return;
      }

      const next = statusRes.data || { status: 'idle' };
      setStatusProblem(null);
      if (statusOnly) setOffline(false);
      setMatchStatus(next);
      // A changed PIN (or a PIN just entered elsewhere) shows on the
      // league list too.
      if (typeof next.read_only === 'boolean') {
        setLeagues((current) =>
          current?.some((l) => l.league_id === forLeague && l.read_only !== next.read_only)
            ? current.map((l) => (l.league_id === forLeague ? { ...l, read_only: next.read_only } : l))
            : current,
        );
      }
      noticeStatusChange(lastStatusRef.current, next);
      lastStatusRef.current = next;
      announceBadges(signal);

      // Tell someone their match started even if they were looking away.
      if (next.status === 'playing' && next.match_id !== announcedMatchRef.current) {
        announcedMatchRef.current = next.match_id;
        pushToast(`Match on: you're playing ${next.opponent}.`, 'success');
      }
      if (next.status !== 'playing') {
        // A game just ended - either player may have reported it - so
        // progress bars have moved even if no badge unlocked.
        if (announcedMatchRef.current !== null) setBadgeVersion((v) => v + 1);
        announcedMatchRef.current = null;
      }
    },
    [leagueId, userId, pushToast, noticeStatusChange, announceBadges, setLeagues],
  );

  // Polled on the dashboard, and - status only - everywhere else a league
  // is chosen (the profile pages, the league picker), so a player who
  // wandered off the dashboard still hears when it's their turn.
  const onDashboard = view === 'dashboard' && viewingPlayer === null;
  const polling = Boolean(userId) && Boolean(leagueId);

  useEffect(() => {
    if (!polling) return undefined;
    const controller = new AbortController();
    let timer;
    let ticks = 0;

    const tick = async () => {
      await refresh(controller.signal, {
        withHistory: ticks % HISTORY_EVERY_N_POLLS === 0,
        statusOnly: !onDashboard,
      });
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
    // Restarts when the league (and so the tables) changes, or when the
    // dashboard is left and returned to. The queue is data this effect
    // reads, not a reason to restart - depending on it once made every
    // queue change tear down and rebuild the timer.
  }, [refresh, polling, onDashboard]);

  // --- Actions ---------------------------------------------------------

  /** Signed in - by password, or by a password reset, which answers the same way. */
  const startSession = (data) => {
    api.setSession({ token: data.access_token, userId: data.user_id, username: data.username });
    // Every sign-in starts by choosing a league for the session.
    api.setStoredLeague(null);
    switchLeague(null);
    // Earlier sign-in errors ("wrong password") no longer apply.
    setToasts([]);
    setUser({ user_id: data.user_id, username: data.username });
    setEmailMissing(!data.email);
    setView('league');
  };

  const handleLogin = async (username, password) => {
    setBusy(true);
    const res = await api.login(username, password);
    setBusy(false);

    if (!res.ok) {
      pushToast(
        res.status === 401 ? 'That username, email or password is wrong.' : res.message,
        'error',
      );
      return;
    }
    startSession(res.data);
  };

  /** Returns { ok, field?, message? } so the form can put a problem beside its field. */
  const handleRegister = async (payload) => {
    setBusy(true);
    const res = await api.register(payload);
    setBusy(false);

    if (!res.ok) {
      // The server explains why (taken username, short password), so pass
      // its wording straight through rather than inventing a vague one -
      // beside its field when it names one.
      if (!res.data?.field) pushToast(res.message, 'error');
      return { ok: false, field: res.data?.field, message: res.message };
    }

    pushToast('Account created. Sign in to get playing.', 'success');
    setView('login');
    return { ok: true };
  };

  /** Forgot your password, step 1. Returns { ok, message } or a refusal. */
  const handleRequestCode = async (email) => {
    setBusy(true);
    const res = await api.forgotPassword(email);
    setBusy(false);
    if (!res.ok) {
      if (!res.data?.field) pushToast(res.message, 'error');
      return { ok: false, field: res.data?.field, message: res.message };
    }
    return { ok: true, message: res.data?.message };
  };

  /** Step 2: the code and a new password. Success signs the player in. */
  const handleResetPassword = async (email, code, password) => {
    setBusy(true);
    const res = await api.resetPassword(email, code, password);
    setBusy(false);
    if (!res.ok) {
      if (!res.data?.field) pushToast(res.message, 'error');
      return { ok: false, field: res.data?.field, message: res.message };
    }
    startSession(res.data);
    pushToast(res.data?.message || 'Password changed.', 'success');
    return { ok: true };
  };

  /** Add or change the email. Returns { ok, field?, message? }. */
  const handleSetEmail = async (email, password) => {
    setBusy(true);
    const res = await api.setEmail(email, password);
    setBusy(false);
    if (!res.ok) {
      if (!res.data?.field && res.kind !== api.ErrorKind.AUTH) pushToast(res.message, 'error');
      return { ok: false, field: res.data?.field, message: res.message };
    }
    setProfile(res.data.profile);
    setEmailMissing(false);
    pushToast('Email saved.', 'success');
    return { ok: true };
  };

  /** next is a league_id. */
  const chooseLeague = (next) => {
    api.setStoredLeague(next);
    if (next !== leagueId) switchLeague(next);
    setView('dashboard');
  };

  /** A 403 that says the league needs its PIN: show the PIN prompt. */
  const noticeReadOnly = (res) => {
    if (res.status === 403 && res.data?.read_only) {
      setMatchStatus((current) => (current ? { ...current, read_only: true } : current));
      reloadLeagues();
    }
  };

  /** Enter the league's PIN. Returns { ok, field?, message? } for the form. */
  const handleUnlock = async (pin) => {
    setBusy(true);
    const res = await api.unlockLeague(leagueId, pin);
    setBusy(false);
    if (!res.ok) {
      const field = res.data?.field;
      if (!field && res.kind !== api.ErrorKind.AUTH) pushToast(res.message, 'error');
      return { ok: false, field, message: res.message };
    }
    pushToast(res.data?.message || "You're in.", 'success');
    if (res.data?.league) {
      setLeagues((current) =>
        current?.map((l) => (l.league_id === res.data.league.league_id ? res.data.league : l)),
      );
    }
    setMatchStatus((current) => (current ? { ...current, read_only: false } : current));
    refresh(undefined, { withHistory: true });
    return { ok: true };
  };

  const handleJoin = async () => {
    setBusy(true);
    const res = await api.joinQueue(leagueId);
    setBusy(false);

    if (!res.ok) {
      pushToast(res.message, 'error');
      noticeReadOnly(res);
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
    const res = await api.leaveQueue(leagueId);
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
    // Leaving on your turn isn't missing it.
    lastStatusRef.current = { status: 'idle' };
    refresh();
  };

  const handleConfirm = async () => {
    setBusy(true);
    const res = await api.confirmHere(leagueId);
    setBusy(false);

    if (!res.ok) {
      pushToast(res.message, 'error');
      noticeReadOnly(res);
      // Too late or not your turn yet: catch up with what the server knows.
      if (res.status === 409 || res.status === 404) lastStatusRef.current = null;
      refresh();
      return;
    }
    // The panel changes on its own, and "Match on" is announced when the
    // game starts - a toast here as well would say it twice.
    refresh();
  };

  /** Ask to cancel the game - or agree, when the opponent has asked. */
  const handleCancelGame = async (matchId) => {
    setBusy(true);
    const res = await api.cancelMatch(matchId);
    setBusy(false);

    if (!res.ok) {
      pushToast(res.message, 'error');
      refresh();
      return;
    }
    if (res.data?.status === 'cancelled') {
      pushToast('Game cancelled - nothing was recorded.', 'info');
      lastStatusRef.current = null;
      announcedMatchRef.current = null;
    }
    refresh();
  };

  /** Take back a request to cancel, or turn down the opponent's. */
  const handleKeepPlaying = async (matchId) => {
    setBusy(true);
    const res = await api.keepPlaying(matchId);
    setBusy(false);
    if (!res.ok) pushToast(res.message, 'error');
    refresh();
  };

  const handleStepDown = async () => {
    setBusy(true);
    const res = await api.stepDown();
    setBusy(false);

    if (!res.ok) {
      pushToast(res.message, 'error');
      refresh();
      return;
    }

    pushToast(res.data?.message || 'You gave up the table.', 'info');
    setMatchStatus({ status: 'idle' });
    lastStatusRef.current = { status: 'idle' };
    refresh(undefined, { withHistory: true });
  };

  // --- The organiser's controls -----------------------------------------
  // Offered only to an admin; the server refuses anyone else regardless.

  const finishRemoval = (res, player) => {
    if (!res.ok) {
      // Already gone, say, or the game changed: the server says which.
      if (res.kind !== api.ErrorKind.AUTH) pushToast(res.message, 'error');
    } else {
      pushToast(res.data?.message || `${player.username} was removed.`, 'info');
    }
    // An organiser who removes themselves didn't miss their turn.
    if (player.user_id === userId) lastStatusRef.current = null;
    refresh();
  };

  /** Take a player out of this table's queue. */
  const handleRemoveFromQueue = async (player) => {
    setBusy(true);
    const res = await api.adminRemoveFromQueue(player.user_id, leagueId);
    setBusy(false);
    finishRemoval(res, player);
  };

  /** Take a player off a table; matchId is the game the organiser saw there. */
  const handleRemoveFromTable = async (player, matchId, tableId) => {
    setBusy(true);
    const res = await api.adminRemoveFromTable(player.user_id, tableId, matchId);
    setBusy(false);
    finishRemoval(res, player);
  };

  /** gameLeagueId is the league of the game itself (the status's league_id). */
  const handleRecord = async (myScore, oppScore, matchId, gameLeagueId) => {
    setBusy(true);
    const res = await api.recordMatch(myScore, oppScore, matchId, gameLeagueId);
    setBusy(false);

    if (!res.ok) {
      pushToast(res.message, 'error');
      noticeReadOnly(res);
      // 409: your opponent reported this game first. Move on to whatever
      // the server says is happening now.
      refresh();
      return;
    }

    const won = Number(myScore) > Number(oppScore);
    const change = res.data?.elo_change ?? 0;
    // A loser at the floor of 0 loses less than the winner gains.
    const lost = res.data?.loser_elo_change ?? change;
    pushToast(
      won ? `You won. +${change} points.` : `Logged the loss. -${lost} points.`,
      won ? 'success' : 'info',
    );

    announcedMatchRef.current = null;
    setBadgeVersion((v) => v + 1);
    refresh(undefined, { withHistory: true });
    // So the league picker and profile page show the new rating.
    fetchProfile().then((next) => next && setProfile(next));
  };

  /** Choose the badge this league shows by your name; null picks automatically. */
  const handleFeature = async (key) => {
    setBusy(true);
    const res = await api.setFeaturedBadge(leagueId, key);
    setBusy(false);

    if (!res.ok) {
      pushToast(res.message, 'error');
      return;
    }
    pushToast(
      key ? 'Done - that badge now shows next to your name.' : 'Your best badge will show automatically.',
      'success',
    );
    setBadgeVersion((v) => v + 1);
    refresh();
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

  /** image is the prepared photo as a data: URL. Returns { ok, field?, message? }. */
  const handleUploadPicture = async (image) => {
    setBusy(true);
    const res = await api.uploadProfilePicture(image);
    setBusy(false);

    if (!res.ok) {
      const field = res.data?.field;
      if (!field) pushToast(res.message, 'error');
      return { ok: false, field, message: res.message };
    }
    setProfile(res.data.profile);
    pushToast('Picture saved.', 'success');
    return { ok: true };
  };

  /** Returns { ok, field?, message? }; on success the player is signed out. */
  const handleDeleteAccount = async (password) => {
    const res = await api.deleteAccount(password);
    if (!res.ok) {
      const field = res.data?.field;
      // A wrong password is shown beside the field; anything else here.
      if (!field && res.kind !== api.ErrorKind.AUTH) pushToast(res.message, 'error');
      return { ok: false, field, message: res.message };
    }
    signOut();
    pushToast('Your account was deleted.', 'info');
    return { ok: true };
  };

  // --- Render ----------------------------------------------------------

  // A dashboard with no league chosen can't show anything; ask instead.
  // An account without an email adds one before anything else.
  const gated = Boolean(user) && emailMissing === true;
  const isAdmin = Boolean(profile?.is_admin);
  const screen = gated
    ? 'add-email'
    : user
      ? (view === 'dashboard' || view === 'league-settings') && leagueId === null
        ? 'league'
        : view === 'league-settings' && !isAdmin
          ? 'dashboard'
          : view
      : view;
  const me = profile ?? (user ? { username: user.username } : null);
  const myFlag = flagEmoji(profile?.country_flag);
  const showingPlayer = Boolean(user) && viewingPlayer !== null && !gated;
  // Away from the status panel, a turn coming up still needs answering.
  const turnBanner =
    yourTurnNow && Boolean(user) && !gated && (showingPlayer || screen !== 'dashboard');

  /** Change screen from the masthead, closing any profile that's open. */
  const goTo = (next) => {
    setViewingPlayer(null);
    setView(next);
  };

  return (
    <OpenPlayerContext.Provider value={user ? openPlayer : null}>
      <div className="page">
        <header className="masthead">
          <h1 className="wordmark">
            <span className="wordmark-dot" aria-hidden="true" />
            {league ? league.name : APP_NAME}
          </h1>

          <div className="masthead-side">
            {user && (
              <>
                <button
                  type="button"
                  className="masthead-profile"
                  onClick={() => goTo('profile')}
                  aria-current={screen === 'profile' && !showingPlayer ? 'page' : undefined}
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
                    onClick={() => goTo('league')}
                  >
                    <ArrowLeftRight size={15} aria-hidden="true" />
                    Switch league
                  </button>
                )}
                {isAdmin && league && (
                  <button
                    type="button"
                    className="btn btn-quiet btn-small"
                    onClick={() => goTo('league-settings')}
                    aria-current={screen === 'league-settings' && !showingPlayer ? 'page' : undefined}
                  >
                    <Settings size={15} aria-hidden="true" />
                    Manage league
                  </button>
                )}
                <button type="button" className="btn btn-quiet btn-small" onClick={signOut}>
                  <LogOut size={15} aria-hidden="true" />
                  Sign out
                </button>
              </>
            )}
            <button
              type="button"
              className="btn btn-quiet btn-small btn-icon"
              onClick={() => chooseTheme(theme === 'dark' ? 'light' : 'dark')}
              aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {theme === 'dark' ? (
                <Sun size={16} aria-hidden="true" />
              ) : (
                <Moon size={16} aria-hidden="true" />
              )}
            </button>
          </div>
        </header>

        <ConnectionBanner offline={offline} />

        {turnBanner && (
          <div className="turn-banner" role="status">
            <BellRing size={20} aria-hidden="true" className="turn-banner-icon" />
            <p className="turn-banner-text">
              <strong>It&rsquo;s your turn</strong>
              {matchStatus.opponent ? ` against ${matchStatus.opponent}` : ''} - say you&rsquo;re
              here within the minute.
            </p>
            <div className="turn-banner-actions">
              <button
                type="button"
                className="btn btn-small"
                onClick={handleConfirm}
                disabled={busy}
              >
                I&rsquo;m here
              </button>
              <button
                type="button"
                className="btn btn-small btn-quiet"
                onClick={() => goTo('dashboard')}
              >
                Go to the table
              </button>
            </div>
          </div>
        )}

        {showingPlayer && (
          <PlayerProfile
            key={viewingPlayer}
            userId={viewingPlayer}
            league={league}
            leagues={leagues}
            currentUserId={userId}
            onBack={closePlayer}
          />
        )}

        {screen === 'login' && !user && (
          <LoginScreen
            onLogin={handleLogin}
            onSwitch={() => setView('register')}
            onForgot={() => setView('forgot')}
            busy={busy}
          />
        )}

        {screen === 'register' && !user && (
          <RegisterScreen
            onRegister={handleRegister}
            onSwitch={() => setView('login')}
            onForgot={() => setView('forgot')}
            busy={busy}
          />
        )}

        {screen === 'forgot' && !user && (
          <ForgotPasswordScreen
            onRequestCode={handleRequestCode}
            onReset={handleResetPassword}
            onBack={() => setView('login')}
            busy={busy}
          />
        )}

        {screen === 'add-email' && (
          <AddEmailScreen
            username={user.username}
            onSave={(email) => handleSetEmail(email)}
            onSignOut={signOut}
            busy={busy}
          />
        )}

        {user && !showingPlayer && screen === 'league' && (
          <LeagueSelect
            current={leagueId}
            leagues={leagues}
            profile={profile}
            theme={theme}
            onChoose={chooseLeague}
          />
        )}

        {user &&
          !showingPlayer &&
          screen === 'profile' &&
          (profile ? (
            <ProfileSettings
              // A new picture starts the form over, so the link field never
              // holds a picture that's already gone.
              key={`${profile.user_id}-${profile.profile_picture ?? ''}`}
              profile={profile}
              countries={countries}
              onSave={handleSaveProfile}
              onSetEmail={handleSetEmail}
              onUploadPicture={handleUploadPicture}
              onDeleteAccount={handleDeleteAccount}
              onBack={() => setView(leagueId !== null ? 'dashboard' : 'league')}
              themeChoice={themeChoice}
              onThemeChoice={chooseTheme}
              busy={busy}
            />
          ) : (
            <main className="profile-shell">
              <p className="empty">Loading your profile...</p>
            </main>
          ))}

        {user && !showingPlayer && screen === 'league-settings' && league && (
          <LeagueSettings
            key={league.league_id}
            league={league}
            onChanged={reloadLeagues}
            onBack={() => setView('dashboard')}
            pushToast={pushToast}
          />
        )}

        {user && !showingPlayer && screen === 'dashboard' && leagueId !== null && !league && (
          <main className="profile-shell">
            <p className="empty">Loading the league...</p>
          </main>
        )}

        {user && !showingPlayer && screen === 'dashboard' && league && league.tables.length === 0 && (
          <main className="auth-shell">
            <div className="card">
              <p>{league.name} doesn&rsquo;t have a table set up yet.</p>
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

        {user &&
          !showingPlayer &&
          screen === 'dashboard' &&
          league &&
          league.tables.length > 0 && (
            <main>
              <StatusPanel
                status={matchStatus}
                problem={statusProblem}
                league={league}
                leagues={leagues}
                readOnly={readOnly}
                onUnlock={handleUnlock}
                queueLength={queue.length}
                topPlayers={topPlayers}
                onJoin={handleJoin}
                onLeave={handleLeave}
                onConfirm={handleConfirm}
                onRecord={handleRecord}
                onCancelGame={handleCancelGame}
                onKeepPlaying={handleKeepPlaying}
                onStepDown={handleStepDown}
                onSwitchLeague={chooseLeague}
                busy={busy}
              />

              <div className="grid">
                <TablesCard
                  tables={tables}
                  loaded={loaded.table}
                  league={league}
                  currentUserId={userId}
                  onRemove={isAdmin ? handleRemoveFromTable : null}
                  busy={busy}
                />
                <QueueCard
                  queue={queue}
                  loaded={loaded.queue}
                  currentUsername={user.username}
                  onRemove={isAdmin ? handleRemoveFromQueue : null}
                  busy={busy}
                  manyTables={tables.length > 1}
                />
                <MatchHistoryCard
                  history={history}
                  loaded={loaded.history}
                  league={league}
                  currentUserId={userId}
                />
                <LeaderboardCard
                  players={leaderboard}
                  loaded={loaded.leaderboard}
                  league={league}
                  currentUsername={user.username}
                />
              </div>

              <BadgesCard
                key={`badges-${userId}-${league.league_id}`}
                userId={userId}
                league={league}
                version={badgeVersion}
                title={`Your ${league.name} badges`}
                onFeature={handleFeature}
                busy={busy}
              />
            </main>
          )}

        <ToastStack toasts={toasts} onDismiss={dismissToast} />
      </div>
    </OpenPlayerContext.Provider>
  );
}
