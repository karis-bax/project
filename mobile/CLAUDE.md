# mobile/ — Expo client

Inherits everything in the root `CLAUDE.md`, including integer-cent money.

- Tokens live in `expo-secure-store`, never AsyncStorage.
- Refresh must stay single-flight (`src/lib/api.ts`). The backend revokes the
  token family on replay, so a second concurrent refresh signs the user out.
- Send `X-Envelope-Client: native` on every request — that selects body
  transport for refresh tokens instead of the web client's httpOnly cookie.
- This client is capture-first. Budget assignment and multi-month planning
  belong in `frontend/`; do not port the envelope grid here.
- Money formatting goes through `src/lib/money.ts`. No `cents / 100`.
