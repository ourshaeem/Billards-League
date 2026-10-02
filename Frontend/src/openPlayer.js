/**
 * How to open a player's profile: openPlayer(userId). App provides it, so
 * a name anywhere - the ladder, the queue, a game in the history - can
 * open the profile without every card in between passing it down. null
 * where there's no profile to open (signed out).
 */
import { createContext, useContext } from 'react';

export const OpenPlayerContext = createContext(null);

export function useOpenPlayer() {
  return useContext(OpenPlayerContext);
}
