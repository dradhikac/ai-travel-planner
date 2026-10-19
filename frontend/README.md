# Frontend Application

Next.js, React, and TypeScript frontend web application for AI Travel Concierge.

Phase 1 foundation: responsive application shell with semantic layout, high-contrast theming, and prefers-reduced-motion accessibility. Planning features and LLM workflows will arrive in subsequent phases.

---

## Environment & Resolved Versions

- **Node.js**: `v20.18.0`
- **npm**: `10.8.2`
- **Next.js**: `16.4.2` (App Router)
- **React**: `19.3.0`
- **React DOM**: `19.3.0`
- **TypeScript**: `^5`

---

## Available Scripts

Only scripts defined in `package.json` are listed below:

### 1. Install Dependencies
```bash
npm install
# or for clean CI install:
npm ci
```

### 2. Run Development Server
```bash
npm run dev
```
Starts the Next.js development server at [http://localhost:3000](http://localhost:3000).

### 3. Run Linter
```bash
npm run lint
```
Runs ESLint across the codebase.

### 4. Run TypeScript Check
```bash
npm run typecheck
```
Executes `tsc --noEmit` to verify type safety in `strict` mode.

### 5. Build Production Bundle
```bash
npm run build
```
Compiles and builds the production application.

### 6. Start Production Server
```bash
npm run start
```
Runs the built production server.

---

## Architecture Notes

- **App Router**: Source files reside in `src/app/`.
- **Path Alias**: Import alias `@/*` maps to `./src/*`.
- **Boundary**: Travel discovery and planning assistant only; no booking or reservation mechanisms.
