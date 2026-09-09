/**
 * Token storage.
 *
 * expo-secure-store only — NEVER AsyncStorage, which is unencrypted. These are
 * bearer credentials for the whole financial history; on iOS this is the
 * Keychain and on Android the Keystore-backed shared preferences.
 */

import * as SecureStore from 'expo-secure-store'

const ACCESS_KEY = 'envelope.access_token'
const REFRESH_KEY = 'envelope.refresh_token'

export async function getAccessToken(): Promise<string | null> {
  return SecureStore.getItemAsync(ACCESS_KEY)
}

export async function getRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(REFRESH_KEY)
}

export async function storeTokens(access: string, refresh: string): Promise<void> {
  await Promise.all([
    SecureStore.setItemAsync(ACCESS_KEY, access),
    SecureStore.setItemAsync(REFRESH_KEY, refresh),
  ])
}

export async function clearTokens(): Promise<void> {
  await Promise.all([
    SecureStore.deleteItemAsync(ACCESS_KEY),
    SecureStore.deleteItemAsync(REFRESH_KEY),
  ])
}
