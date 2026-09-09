import React, { useState } from 'react'
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native'

import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { theme } from '../lib/theme'

export function LoginScreen() {
  const { signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (busy) return
    setError(null)
    setBusy(true)
    try {
      await signIn(email.trim(), password)
    } catch (err) {
      // The API returns the same message for unknown email and wrong password
      // on purpose — don't try to be more specific here than it was.
      setError(err instanceof ApiError ? err.detail : 'Could not reach the server.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.card}>
        <Text style={styles.title}>Envelope</Text>
        <Text style={styles.subtitle}>Sign in to your budget</Text>

        <TextInput
          style={styles.input}
          value={email}
          onChangeText={setEmail}
          placeholder="Email"
          placeholderTextColor={theme.inkFaint}
          autoCapitalize="none"
          autoComplete="email"
          keyboardType="email-address"
          inputMode="email"
          returnKeyType="next"
        />
        <TextInput
          style={styles.input}
          value={password}
          onChangeText={setPassword}
          placeholder="Password"
          placeholderTextColor={theme.inkFaint}
          secureTextEntry
          autoComplete="current-password"
          returnKeyType="go"
          onSubmitEditing={submit}
        />

        {error ? (
          <Text style={styles.error} accessibilityLiveRegion="polite">
            {error}
          </Text>
        ) : null}

        <Pressable
          style={({ pressed }) => [styles.button, pressed && styles.buttonPressed]}
          onPress={submit}
          disabled={busy}
          accessibilityRole="button"
        >
          {busy ? (
            <ActivityIndicator color={theme.bg} />
          ) : (
            <Text style={styles.buttonLabel}>Sign in</Text>
          )}
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg, justifyContent: 'center', padding: theme.space(6) },
  card: { gap: theme.space(3) },
  title: { color: theme.ink, fontSize: 40, fontWeight: '800', letterSpacing: -1 },
  subtitle: { color: theme.inkMuted, fontSize: 16, marginBottom: theme.space(4) },
  input: {
    backgroundColor: theme.surface,
    borderColor: theme.line,
    borderWidth: 1,
    borderRadius: theme.radius,
    color: theme.ink,
    fontSize: 17,
    padding: theme.space(4),
  },
  error: { color: theme.danger, fontSize: 14 },
  button: {
    backgroundColor: theme.accent,
    borderRadius: theme.radius,
    padding: theme.space(4),
    alignItems: 'center',
    marginTop: theme.space(2),
  },
  buttonPressed: { opacity: 0.8 },
  buttonLabel: { color: theme.bg, fontSize: 17, fontWeight: '700' },
})
