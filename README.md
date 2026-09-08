# Palette — Task Board

A small, modern **Vite + React + TypeScript** web app used to bootstrap and
demonstrate this repository's development environment. It's a tiny task board
for design work: add tasks, move them across `To do → In progress → Done`, and
delete them.

## Requirements

- Node.js 22.x
- npm 10.x

## Getting started

```bash
npm ci        # install dependencies from the lockfile
npm run dev   # start the dev server on http://localhost:5173
```

## Scripts

| Command            | Description                                  |
| ------------------ | -------------------------------------------- |
| `npm run dev`      | Start the Vite dev server (host `0.0.0.0`).  |
| `npm run build`    | Type-check and build the production bundle.   |
| `npm run preview`  | Preview the production build.                 |
| `npm run lint`     | Run ESLint.                                   |
| `npm run typecheck`| Type-check without emitting output.          |

## Cloud Agent environment

The Cloud Agent development environment is defined in
[`.cursor/environment.json`](.cursor/environment.json):

- `install`: `npm ci` restores dependencies from `package-lock.json`.
- `terminals.dev`: runs `npm run dev` so the app is available while the agent works.
- `ports`: exposes `5173`.

## Project structure

```
.
├── index.html            # Vite entry HTML
├── src/
│   ├── main.tsx          # React entry point
│   ├── App.tsx           # Task board UI + state
│   ├── App.css           # Component styles
│   └── index.css         # Global styles / theme
├── vite.config.ts
└── .cursor/environment.json
```
