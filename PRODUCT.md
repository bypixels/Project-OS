# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary today: a single operator (the repo owner) inspecting their own Claude Code / Codex
environment on their machine. Confirmed direction: the product is intended for publication
(open source / third parties), so the UI must explain itself to a first-time visitor with no
context. Secondary: read-only viewers of a shared `cabina hub` snapshot.

## Product Purpose

cabina inspects an agent environment — agents, skills, hooks, docs, sessions, usage, drift
between Claude and Codex — so the operator can see what is installed, what is broken, what is
actually used, and what can safely be archived. Success: the operator trusts what the screen
says enough to act on it (archive, fix a hook, repair drift) using commands cabina generates
but never runs.

## Positioning

It measures, warns and blocks — it never repairs, deletes or edits on its own (invariant stated
in pyproject and enforced by break-tests). Every number is honest: unknown is rendered as
unknown ("n/a", "size not measured"), never as a fake zero. A neighboring tool that auto-fixes
or estimates cannot truthfully copy this claim.

## Operating Context

Typical session (confirmed): long cleanup sessions — ordering the environment, reading skills
before trusting/archiving them, comparing twins, reviewing usage. All four workflows matter and
are confirmed as primary jobs: health check (anything red?), exploring the agent/skill catalog,
monitoring activity/sessions, and managing docs (CLAUDE.md / MEMORY.md with version history).
Local server on 127.0.0.1; `cabina hub` serves a reduced read-only subset of tabs to others.

## Capabilities and Constraints

- One static file: `src/cabina/static/index.html` served with `__TOKEN__`/`__LANG__`
  substitution. No build step, no external dependencies, no CDNs — must work fully offline.
- Zero-dependency Python stdlib server; every write goes through a guard; the UI's only write
  paths are the existing POST routes.
- Two languages, en and es (CR), via the embedded I18N table; both must stay complete.
- HUB mode renders a subset of tabs (no health, live, mcp, docs) and no action buttons.
- Tests assert structural markers of this file (section comments like
  `// ---------- AGENTS ----------`, `esc()` on interpolations, specific literals). A redesign
  must keep those markers or update the tests deliberately.
- Terminology is domain truth: agents, skills, hooks, drift, harness, worktrees, guard.

## Brand Commitments

Visual direction (user decision, 2026-09-01, via impeccable direction round): the category
standard played straight — the canonical modern operations dashboard, executed at full craft,
no irony, no smuggled quirk. Quality bar: the UI must sit alongside **Vercel** (radical
neutral, typography-first) and **Grafana/Datadog** (observability-grade density and status
legibility) without looking out of place. Failure mode to avoid (user-named): looking like a
generic template. Status colors carry state only; navigation may be reorganized (user approved
IA changes: grouped sidebar over 9 flat tabs).

## Evidence on Hand

Real data only — everything shown is measured from the user's own machine. No testimonials,
benchmarks or marketing claims exist; future surfaces must not invent them. Screenshots in
`images/shot1-6.png` (uncommitted, unreferenced).

## Product Principles

1. Honest measurement first: unknown reads as unknown; nothing is ever auto-repaired.
2. The screen must justify trust — a claim without its evidence (count, path, diff) is not shown.
3. Commands are generated for the user to read and run, never executed by cabina.
4. Optimize for the long cleanup session: density, scanability and reading comfort over spectacle.
5. Self-explanatory to a stranger: the intended audience is eventually the public.

## Accessibility & Inclusion

Keyboard focus visible (already present); `prefers-reduced-motion` respected (already present).
No further product-specific requirement established yet — WCAG AA contrast is the working
assumption for a public tool. (Inferred, not user-confirmed.)
