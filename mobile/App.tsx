/**
 * Envelope — phone client.
 *
 * Capture-first: the two things you do on a phone are check whether you can
 * afford something, and record that you just spent it. Assigning money and
 * planning months stay in the desktop app, where a grid earns its place.
 */

import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'
import { DarkTheme, NavigationContainer } from '@react-navigation/native'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StatusBar } from 'expo-status-bar'
import React from 'react'
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native'
import { SafeAreaProvider } from 'react-native-safe-area-context'

import { AuthProvider, useAuth } from './src/lib/auth'
import { theme } from './src/lib/theme'
import { BalancesScreen } from './src/screens/BalancesScreen'
import { LoginScreen } from './src/screens/LoginScreen'
import { QuickAddScreen } from './src/screens/QuickAddScreen'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // A 401 is handled by the api client's refresh; retrying past that just
      // burns battery on a dead session.
      retry: 1,
    },
  },
})

const Tab = createBottomTabNavigator()

const navTheme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: theme.bg,
    card: theme.surface,
    border: theme.line,
    text: theme.ink,
    primary: theme.accent,
  },
}

function Dot({ color }: { color: string }) {
  return <View style={[styles.dot, { backgroundColor: color }]} />
}

function SignOutButton() {
  const { signOut } = useAuth()
  return (
    <Pressable
      onPress={() => void signOut()}
      style={styles.signOut}
      accessibilityRole="button"
      accessibilityLabel="Sign out"
    >
      <Text style={styles.signOutLabel}>Sign out</Text>
    </Pressable>
  )
}

function Tabs() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: theme.bg },
        headerTitleStyle: { color: theme.ink },
        headerShadowVisible: false,
        headerRight: () => <SignOutButton />,
        tabBarActiveTintColor: theme.accent,
        tabBarInactiveTintColor: theme.inkFaint,
        tabBarStyle: { backgroundColor: theme.surface, borderTopColor: theme.line },
      }}
    >
      <Tab.Screen
        name="Balances"
        component={BalancesScreen}
        options={{
          headerShown: false,
          tabBarIcon: ({ color }) => <Dot color={color} />,
        }}
      />
      <Tab.Screen
        name="Add"
        component={QuickAddScreen}
        options={{
          title: 'New transaction',
          tabBarIcon: ({ color }) => <Dot color={color} />,
        }}
      />
    </Tab.Navigator>
  )
}

function Root() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <View style={styles.splash}>
        <ActivityIndicator color={theme.accent} />
      </View>
    )
  }

  if (!user) return <LoginScreen />

  return (
    <NavigationContainer theme={navTheme}>
      <Tabs />
    </NavigationContainer>
  )
}

export default function App() {
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <StatusBar style="light" />
          <Root />
        </AuthProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  )
}

const styles = StyleSheet.create({
  splash: { flex: 1, backgroundColor: theme.bg, alignItems: 'center', justifyContent: 'center' },
  dot: { width: 8, height: 8, borderRadius: 4 },
  signOut: { paddingHorizontal: 16, paddingVertical: 8 },
  signOutLabel: { color: theme.inkMuted, fontSize: 15 },
})
