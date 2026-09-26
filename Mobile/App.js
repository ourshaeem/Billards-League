/**
 * Billiards & Ping Pong League - the mobile app.
 *
 * The providers, outermost first, each needing the ones above it:
 *   SafeAreaProvider  notches, status bar and home indicator
 *   ToastProvider     short messages over any screen
 *   SessionProvider   who is signed in (token in SecureStore) and their league
 *   LeagueProvider    the league's table and theme
 *   LiveProvider      status, queue and table, polled; join/leave/report
 * then the navigator, which follows the session (src/navigation).
 */
import React from 'react';
import { useFonts } from 'expo-font';
import { SafeAreaProvider } from 'react-native-safe-area-context';
// Only the weights the design uses. Importing each package's main entry
// would bundle every weight - eighteen files for Archivo alone.
import { InstrumentSerif_400Regular } from '@expo-google-fonts/instrument-serif/400Regular';
import { Archivo_400Regular } from '@expo-google-fonts/archivo/400Regular';
import { Archivo_600SemiBold } from '@expo-google-fonts/archivo/600SemiBold';
import { Archivo_700Bold } from '@expo-google-fonts/archivo/700Bold';

import { Splash } from './src/components/Wordmark';
import { AppNavigation } from './src/navigation/RootNavigator';
import { LeagueProvider } from './src/state/LeagueContext';
import { LiveProvider } from './src/state/LiveContext';
import { SessionProvider } from './src/state/SessionContext';
import { ToastProvider } from './src/state/ToastContext';

export default function App() {
  const [fontsLoaded, fontError] = useFonts({
    InstrumentSerif_400Regular,
    Archivo_400Regular,
    Archivo_600SemiBold,
    Archivo_700Bold,
  });

  // If the fonts can't load, carry on in the system font rather than
  // leaving the app on a spinner.
  if (!fontsLoaded && !fontError) return <Splash />;

  return (
    <SafeAreaProvider>
      <ToastProvider>
        <SessionProvider>
          <LeagueProvider>
            <LiveProvider>
              <AppNavigation />
            </LiveProvider>
          </LeagueProvider>
        </SessionProvider>
      </ToastProvider>
    </SafeAreaProvider>
  );
}
