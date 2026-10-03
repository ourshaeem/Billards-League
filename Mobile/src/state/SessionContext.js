/**
 * Who is signed in, and which league they're playing this session.
 *
 * The session survives the app being closed: the token is saved to
 * SecureStore on sign-in and read back at launch (storage.js). Until it
 * has been read, status is "restoring" and the app shows nothing rather
 * than flashing the sign-in screen at someone who is signed in.
 *
 * The navigator follows status and league (navigation/RootNavigator.js):
 *   signedOut            -> sign in / register / reset a password
 *   signedIn, needsEmail -> add an email (accounts from before sign-up
 *                           asked for one), before anything else
 *   signedIn, no league  -> choose a league
 *   signedIn, league     -> the league's tabs
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import * as api from '../api';
import { isLeague } from '../leagues';
import { clearSession, loadSession, saveLeague, saveSession } from '../storage';
import { useToast } from './ToastContext';

const SIGNED_OUT = { status: 'signedOut', user: null, league: null, needsEmail: false };

const SessionContext = createContext(null);

export function SessionProvider({ children }) {
  const toast = useToast();
  const [session, setSession] = useState({
    status: 'restoring',
    user: null,
    league: null,
    needsEmail: false,
  });

  // Read by the auth-failure handler, which must not be recreated (and
  // so re-registered) on every change of session.
  const statusRef = useRef(session.status);
  useEffect(() => {
    statusRef.current = session.status;
  }, [session.status]);

  useEffect(() => {
    let cancelled = false;
    loadSession().then((saved) => {
      if (cancelled) return;
      if (saved) {
        api.setAuthToken(saved.token);
        setSession({
          status: 'signedIn',
          user: saved.user,
          league: isLeague(saved.league) ? saved.league : null,
          needsEmail: false,
        });
        // Signed in before emails were asked for? Then ask now. If the
        // profile can't be loaded (offline), ask next time instead of
        // blocking the app.
        api.getProfile().then((res) => {
          if (!cancelled && res.ok && res.data?.profile && !res.data.profile.email) {
            setSession((current) =>
              current.status === 'signedIn' ? { ...current, needsEmail: true } : current,
            );
          }
        });
      } else {
        setSession(SIGNED_OUT);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const signOut = useCallback(async () => {
    api.setAuthToken(null);
    setSession(SIGNED_OUT);
    toast.clear();
    await clearSession();
  }, [toast]);

  // One rejected token anywhere sends the player back to sign in,
  // instead of leaving buttons that fail silently.
  useEffect(() => {
    api.setAuthFailureHandler(() => {
      if (statusRef.current === 'signedIn') {
        toast.push('Your session ended. Please sign in again.', 'error');
      }
      api.setAuthToken(null);
      setSession(SIGNED_OUT);
      clearSession();
    });
    return () => api.setAuthFailureHandler(null);
  }, [toast]);

  /** Signed in - by password, or by a password reset, which answers the same way. */
  const startSession = useCallback(
    async (data) => {
      const user = { user_id: data.user_id, username: data.username };
      api.setAuthToken(data.access_token);
      await saveSession({ token: data.access_token, user });
      // Earlier sign-in errors ("wrong password") no longer apply.
      toast.clear();
      // Every sign-in starts by choosing a league for the session - after
      // adding an email, for an account that has none.
      setSession({ status: 'signedIn', user, league: null, needsEmail: !data.email });
    },
    [toast],
  );

  /** Returns the api result, so the screen can explain a refusal. */
  const signIn = useCallback(
    async (username, password) => {
      const res = await api.login(username, password);
      if (res.ok) await startSession(res.data);
      return res;
    },
    [startSession],
  );

  /** A forgotten password's code and a new password; success signs in. */
  const resetPassword = useCallback(
    async (email, code, password) => {
      const res = await api.resetPassword(email, code, password);
      if (res.ok) await startSession(res.data);
      return res;
    },
    [startSession],
  );

  /** The account has an email now. */
  const emailSaved = useCallback(() => {
    setSession((current) => ({ ...current, needsEmail: false }));
  }, []);

  const chooseLeague = useCallback((league) => {
    if (!isLeague(league)) return;
    setSession((current) => ({ ...current, league }));
    saveLeague(league);
  }, []);

  const value = useMemo(
    () => ({ ...session, signIn, resetPassword, signOut, chooseLeague, emailSaved }),
    [session, signIn, resetPassword, signOut, chooseLeague, emailSaved],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

/** { status, user, league, needsEmail, signIn, resetPassword, signOut, chooseLeague, emailSaved } */
export function useSession() {
  return useContext(SessionContext);
}
