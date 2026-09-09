# Envelope — phone client

Capture-first Expo client. The two things you do on a phone are check whether
you can afford something and record that you just spent it. Assigning money and
planning months stay in `frontend/`, where a grid earns its place.

## Run it

The API must be reachable from your phone, which means a LAN address or a
deployed host — `localhost` resolves to the phone itself, not your Mac.

```bash
cd mobile
npm install
EXPO_PUBLIC_API_URL="http://192.168.1.x:8000" npx expo start
```

Scan the QR code with Expo Go. Replace the IP with your Mac's LAN address
(`ipconfig getifaddr en0`), or the deployed API URL once one exists.

## Shape

- `src/lib/tokens.ts` — SecureStore only. Never AsyncStorage: these are bearer
  credentials for the entire financial history.
- `src/lib/api.ts` — the only HTTP client. Refresh is **single-flight**; the
  backend rotates refresh tokens and treats a replay as theft, so concurrent
  refreshes would revoke the session. Sends `X-Envelope-Client: native` to get
  body transport rather than the web client's httpOnly cookie.
- `src/lib/money.ts` — integer cents in, string out. No `cents / 100` anywhere.
- `src/screens/BalancesScreen.tsx` — home. Sorted tightest-first, because the
  categories about to go negative are the ones you need to see.
- `src/screens/QuickAddScreen.tsx` — amount focused on mount, outflow by
  default, stays put after saving so you can enter several in a row.

## Not built yet

Receipt capture. `expo-camera` and `expo-image-manipulator` are installed, but
the backend has no receipt endpoint — extraction, validation and reconciliation
against synced transactions all need building server-side first. The camera
screen would be half a feature without it.
