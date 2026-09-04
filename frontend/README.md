# PersonaAI Frontend — Milestone 6

React + TypeScript + Vite + Tailwind, wired to the FastAPI backend from
Milestones 1-5. Dark "command center" aesthetic - a central orbit of your
AI agents, live conversation feed, and a quick "Teach My AI" capture bar.

## Design notes

- **Palette**: near-black base (`#07070C`) with violet/blue/green/amber/pink
  accents per agent type. Type: Space Grotesk (display), Inter (body),
  JetBrains Mono (data/timestamps - reinforces the "telemetry" feel).
- **The orbit** (`src/components/dashboard/AgentOrbit.tsx`) is the signature
  element: your real agents (from `GET /agents`) positioned in a circle
  around an abstract initials avatar, connected by animated gradient lines.
  Everything else on the page stays quiet by comparison.
- **No fabricated data.** Every number on the dashboard (conversation count,
  active agents, knowledge docs ready, integrations connected) comes from a
  real API call. There's no simulated CPU/memory/network panel and no fake
  system-performance sparkline - if there's no real backend value for
  something, it isn't shown as though there is.
- **No photorealistic avatar.** The reference image showed a specific
  person's photo; this uses an abstract glowing initials ring instead - a
  real person's likeness can't and shouldn't be fabricated.

## Running it

```bash
npm install
npm run dev
```

Requires the backend running at `http://localhost:8000` (the dev server
proxies `/api` there - see `vite.config.ts`). For production, either serve
this build behind the same reverse proxy as the API (so `/api` resolves to
it), or adjust `src/lib/api.ts`'s `baseURL`.

## Note on verification

Same caveat as the backend: this sandbox has no network access, so
`npm install` / `vite build` / `tsc` couldn't be run here. An automated
brace/paren/bracket balance check ran clean across every file, and the
more complex components were manually re-reviewed, but a real
`npm run build` on your end is the actual check - let me know what it
turns up.

## What's not built yet

Products, Conversation Training, Analytics, and Billing are placeholder
pages (clearly labeled "not built yet") - they're real backend gaps too
(see the main README's milestone plan), not just missing UI.

## Redesign — Overview dashboard restyle (post-Milestone 8)

The dark "command center" look above was replaced with a light workspace
theme (dark navy sidebar, white content area, purple accent) to match a
reference dashboard design supplied directly. This was a **retheme, not a
rewrite**: `tailwind.config.js` / `index.css` remap the same semantic tokens
every page already used (`base.*`, `ink.*`, `accent.*`), so every existing
page restyled automatically without per-file edits. The sidebar keeps its
own always-dark token group (`nav.*`) since it stays dark in the new design
regardless of the rest of the app.

Hand-rebuilt to match the reference layout precisely, all wired to real
endpoints (nothing fabricated):

- `Sidebar.tsx` — live badge counts (open conversations, active orders),
  AI-usage bar (`/analytics/summary` messages vs. the active plan's
  `max_messages_per_month`), current-plan card.
- `Topbar.tsx` — client-side quick-nav search, notifications bell
  (`NotificationsBell.tsx`, polls `/notifications` + `/notifications/unread-count`),
  avatar menu.
- `DashboardPage.tsx` (Overview) — 4 stat cards with **genuine**
  period-over-period deltas (computed client-side from real `created_at`
  timestamps across two adjacent windows, not simulated), a messages-per-day
  area chart (`/analytics/summary`), a Top Channels donut grouped from real
  `/conversations` data, AI Agents Performance (real message + conversation
  counts per agent — deliberately not a fabricated "resolution rate", since
  the backend doesn't track one), Recent Orders (`/orders`), Quick Actions,
  and a Live Feed (`/notifications`).
- `ProductsPage.tsx` / `AnalyticsPage.tsx` — upgraded from the earlier
  "Coming Soon" placeholders to fully real pages, since the backend already
  supports both (Milestone 7/8a). `training` (Workflows) stays a labeled
  placeholder — that's a genuine, documented backend gap, not a UI gap.
- `NotificationsPage.tsx` — new, full notification list + mark-as-read;
  reachable from "View all" on the Live Feed and from the bell, not linked
  in the sidebar (matching the reference design, which doesn't list it there
  either).

**Not verified**: no network access in the sandbox this was built in, so
`npm install` / `tsc` / a real build could not be run. Every file was
reviewed by hand and checked for balanced brackets; please run
`npm install && npm run build` on your end and tell me what (if anything)
breaks — happy to fix directly.
