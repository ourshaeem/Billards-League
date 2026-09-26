/**
 * Which screens exist, decided by the session - React Navigation's
 * recommended pattern for sign-in flows. The web app's single `view`
 * variable (login / register / league / dashboard / profile) becomes:
 *
 *   Signed out           SignIn, Register        (a stack)
 *   Signed in, no league ChooseLeague
 *   Signed in, league    Main                    (tabs: Play, Games, Ladder, Profile)
 *                        SwitchLeague            (a modal over the tabs)
 *
 * Because the signed-out screens only exist while signed out, signing
 * out (or a session expiring) can't leave a screen behind that the back
 * button would return to.
 */
import React from 'react';
import { DefaultTheme, NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { StatusBar } from 'expo-status-bar';

import { Splash } from '../components/Wordmark';
import { LoginScreen } from '../screens/LoginScreen';
import { RegisterScreen } from '../screens/RegisterScreen';
import { LeagueSelectScreen } from '../screens/LeagueSelectScreen';
import { useLeague } from '../state/LeagueContext';
import { useSession } from '../state/SessionContext';
import { fonts } from '../theme';
import { MainTabs } from './MainTabs';

const Stack = createNativeStackNavigator();

const APP_NAME = 'Billiards & Ping Pong';

export function AppNavigation() {
  const { status, league } = useSession();
  const { theme, info } = useLeague();

  // Reading the saved session takes a moment at launch. Showing the
  // sign-in screen meanwhile would flash it at people who are signed in.
  if (status === 'restoring') return <Splash />;

  const navigationTheme = {
    ...DefaultTheme,
    colors: {
      ...DefaultTheme.colors,
      primary: theme.accent,
      background: theme.page,
      card: theme.page,
      text: theme.text,
      border: theme.line,
      notification: theme.accent,
    },
  };

  return (
    <NavigationContainer
      theme={navigationTheme}
      // The browser tab's title, in the web preview.
      documentTitle={{ formatter: () => (league ? info.name : APP_NAME) }}
    >
      <StatusBar style="dark" />
      <Stack.Navigator
        screenOptions={{
          headerShown: false,
          headerTitleStyle: { fontFamily: fonts.semibold, color: theme.text },
          headerTintColor: theme.accent,
          contentStyle: { backgroundColor: theme.page },
        }}
      >
        {status === 'signedOut' ? (
          <>
            <Stack.Screen name="SignIn" component={LoginScreen} />
            <Stack.Screen name="Register" component={RegisterScreen} />
          </>
        ) : !league ? (
          <Stack.Screen name="ChooseLeague" component={LeagueSelectScreen} />
        ) : (
          <>
            <Stack.Screen name="Main" component={MainTabs} />
            <Stack.Screen
              name="SwitchLeague"
              component={LeagueSelectScreen}
              options={{ presentation: 'modal', headerShown: true, title: 'Switch league' }}
            />
          </>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
