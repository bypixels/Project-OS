---
version: 1
slug: "src-project-os-static-index-html"
primary_target: "src/project_os/static/index.html"
related_targets: []
---

# Surface: Projects view (web UI)

Scope: the Projects view inside src/project_os/static/index.html (renderProjects + lane helpers).
Visitor mode: Operate.

Audience & job (user-confirmed, 2026-09-01): comparative inventory across projects — "quién
creció" answerable at a glance. Single representation (the old tiles-grid + duplicate list was
removed by explicit user decision).

Chosen direction: "Carriles" — one table row per project: status dot, name+branch, a 30-day
activity lane (per-day session counts, sequential neutral ramp, one absolute scale shared by all
rows), and sortable inventory columns (agents / skills / uncommitted / worktrees / memory days).
Structure selected by the impeccable surface roll (seed key projects01, mode operate, grain view,
ASSIGNED INDEX 7 of the resonance-ordered candidate list; roll output not persisted — this brief
is the record). The user approved the assigned structure over re-roll and over the category
standard on 2026-09-01.

Memorable moment: the lane column — density is growth, emptiness is abandonment, both measured.

Decisions of record:
- Lane data source is the session transcripts the incremental reader already parses (Claude
  sessions). A project absent from that source within the window is a MEASURED zero (the scan
  covers all transcripts), so an empty lane is honest; only a globally absent activity source
  (e.g. hub aggregate mode) suppresses the lane column entirely. Codex-only activity is out of
  the lane's scope by data availability.
- The heat scale is absolute and shared across rows (never per-row maxima); the ramp is the
  neutral sequential gray, outside the moss/amber/rust state vocabulary and outside identity hues.
- Sizes never render fabricated: unmeasured worktree sizes stay words ("size not measured").

Unresolved: none blocking. Follow-up candidates: a growth delta column (vs previous scan) if the
comparison job ever needs numbers beyond the lane.
