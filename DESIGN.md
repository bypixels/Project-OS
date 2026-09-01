---
name: Project-OS
description: An honest measurement console for a Claude Code / Codex environment — density, status legibility, no decoration.
colors:
  bg: "#F6F7F8"
  panel: "#FFFFFF"
  ink: "#0B0D0F"
  dim: "#5E636A"
  line: "#E2E5E8"
  hover: "#F0F1F3"
  neutral: "#AEB3B9"
  accent: "#0B5FCE"
  accent-soft: "#E7EFFC"
  accent-ink: "#0A4FA8"
  on-accent: "#FFFFFF"
  moss: "#1C7A3E"
  moss-soft: "#E1F2E7"
  amber: "#875806"
  amber-soft: "#F9EDD6"
  rust: "#B22417"
  rust-soft: "#FAE4E1"
  slate: "#3B4A5B"
  slate-soft: "#ECF0F4"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "22px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "-0.02em"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
    fontFeature: "tabular-nums"
  caption:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.3
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.07em"
  mono:
    fontFamily: "ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  chrome: "6px"
  tag: "5px"
  pill: "99px"
  dot: "50%"
spacing:
  hair: "2px"
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "12px"
  row: "14px"
  gutter: "16px"
  pane: "20px"
components:
  button:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.chrome}"
    padding: "6px 12px"
    height: "32px"
  button-hover:
    backgroundColor: "{colors.hover}"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    typography: "{typography.body}"
    rounded: "{rounded.chrome}"
    padding: "6px 12px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "{colors.accent-ink}"
  button-on:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.chrome}"
    padding: "6px 12px"
  button-danger:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.rust}"
    rounded: "{rounded.chrome}"
    padding: "6px 12px"
  chip:
    backgroundColor: "transparent"
    textColor: "{colors.dim}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: "4px 10px"
  chip-on:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent-ink}"
  tab:
    backgroundColor: "transparent"
    textColor: "{colors.dim}"
    typography: "{typography.body}"
    rounded: "{rounded.chrome}"
    padding: "8px 12px"
  tab-on:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent-ink}"
  pill-ok:
    backgroundColor: "{colors.moss-soft}"
    textColor: "{colors.moss}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  pill-warn:
    backgroundColor: "{colors.amber-soft}"
    textColor: "{colors.amber}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  pill-bad:
    backgroundColor: "{colors.rust-soft}"
    textColor: "{colors.rust}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  pill-neutral:
    backgroundColor: "{colors.line}"
    textColor: "{colors.dim}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.chrome}"
    padding: "6px 10px"
  row:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    padding: "6px 14px"
    height: "34px"
  row-selected:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent-ink}"
  stat:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.dim}"
    typography: "{typography.caption}"
    rounded: "{rounded.chrome}"
    padding: "4px 8px"
  box-info:
    backgroundColor: "{colors.slate-soft}"
    textColor: "{colors.slate}"
    typography: "{typography.body}"
    rounded: "{rounded.chrome}"
    padding: "10px 12px"
  box-warn:
    backgroundColor: "{colors.amber-soft}"
    textColor: "{colors.amber}"
    rounded: "{rounded.chrome}"
    padding: "10px 12px"
  box-bad:
    backgroundColor: "{colors.rust-soft}"
    textColor: "{colors.rust}"
    rounded: "{rounded.chrome}"
    padding: "10px 12px"
  evidence-block:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    typography: "{typography.mono}"
    rounded: "{rounded.chrome}"
    padding: "8px 12px"
---

# Design System: Project-OS

## Overview

**Creative North Star: "The Instrument Panel"**

Project-OS looks like what it is: an instrument that reports measurements taken from the
operator's own machine. Instruments do not decorate their readings. The entire visual budget goes
into making a dense screen legible for an hour at a time — a near-monochrome ground of paper white
and near-black, hairline rules instead of boxes, and exactly one saturated color for interaction.
Everything that is colored is colored because it means something.

Hierarchy comes from three devices only: type weight, spacing, and a status dot. There are no
cards floating over the page, no gradients, no glyph icons, no illustration. The one shadow in the
system belongs to the toast, which floats over the page by definition. Depth is tonal instead —
`panel` (#FFFFFF) sits on `bg` (#F6F7F8) and the seam between them is a 1px `line`. In dark mode
the same relationship inverts (`#131518` on `#0C0D0F`) and nothing else about the system changes.

The quality bar named in PRODUCT.md is Vercel's radical neutrality next to Grafana's
observability-grade density; the failure mode named there is "generic template." The build resolves
that tension by refusing every decorative device the template offers and spending the savings on
status legibility: four semantic hues, each with a soft companion tint, used only to report state.

**Key Characteristics:**
- Near-monochrome ground; one interaction accent (blue); three status hues plus a neutral gray.
- System font stack, no webfonts, no network — the product must work fully offline.
- Tabular numerals globally, so counts do not jitter as they refresh.
- Five type sizes total (11 / 12.5 / 14 / 18 / 22px). No sixth.
- Flat by construction: one shadow in the whole system.
- Monospace marks what was measured; prose stays in the sans face.
- Unknown is written as words, never drawn as a zero or a colored state.

## Colors

Cool near-monochrome neutrals carrying one working blue and three reporting hues, each paired with
a soft tint for filled surfaces.

### Primary
- **Working Blue** (`accent`): the single interaction color. Selected tab, selected row, active
  chip, primary button, focus ring, and the inset marker on a selected row. It never reports
  health — a blue row means "you are here," not "this is fine."
- **Deep Working Blue** (`accent-ink`): text on the soft blue fill, and the primary button's hover
  state. It is the readable form of the accent, never a second accent.
- **Blue Wash** (`accent-soft`): the fill under every selected or active control.

### Secondary
- **Moss** (`moss` / `moss-soft`): measured-good. Valid agents, complete harness, clean state,
  added lines in a diff.
- **Amber** (`amber` / `amber-soft`): measured-warning. Contract warnings, stale documents, partial
  harness, an agent that finished and is waiting for review, and the Codex tool tag.
- **Rust** (`rust` / `rust-soft`): measured-bad. Invalid contract, critical findings, deleted lines
  in a diff, destructive-action buttons.

### Tertiary
- **Slate** (`slate` / `slate-soft`): informational chrome that is not a health verdict — the
  health strip, the info box, the tool tag, the hub banner. It sits deliberately outside the
  green/amber/red vocabulary so an explanation is never mistaken for a reading.

### Neutral
- **Paper** (`bg`) and **Panel** (`panel`): the two ground tones. Panel is content; bg is the
  recessed surround, group headers, and the inside of an evidence block.
- **Ink** (`ink`): body text and the toast's own background (inverted).
- **Dim** (`dim`): secondary text — subtitles, metadata keys, counts, footers, legends.
- **Line** (`line`): every border and divider in the product, at 1px.
- **Hover** (`hover`): the hover ground for rows, tabs and buttons.
- **Gray** (`neutral`): the *unknown* color. It fills the status dot for `document`, `idle`, `none`
  and `unknown`, and darkens an input's border on hover.

### Named Rules
**The State-Only Color Rule.** Moss, amber and rust are reserved for measured state. They may never
be used for emphasis, branding, category, or decoration. If a hue would appear on something that is
not a reading, it is the wrong hue.

**The One Voice Rule.** Blue is the only interaction color and the only accent. Selection, focus,
active nav and the primary action all speak with it; nothing else does.

**The Unknown-Is-Gray Rule.** A thing that was not measured takes the neutral gray dot and says so
in words ("n/a", "size not measured", "never recorded"). Unknown never borrows moss, amber or rust,
and it is never rendered as 0.

**The Identity-Color Rule.** Identity hues live only in the 8px rounded swatch beside an agent's
name — never on a background, never on text, and never in the warm/green arc the status colors own
(moss, amber, rust). It is a second channel, not a louder status: the status dot stays first and
unchanged. The hue is a pure function of the name (hash into 12 fixed stops), so the
same agent is the same color in every list, with nothing stored. The stops are OKLCH hues 195°–338°
(cyan through blue and violet to magenta) at one perceived lightness, so no agent's swatch weighs
more than another's and none of them lands on rust (~30°), amber (~65°) or moss (~150°).

## Typography

**Display / Body Font:** the platform system stack (`-apple-system`, `BlinkMacSystemFont`,
`Segoe UI`, `Roboto`, `Helvetica Neue`, Arial, sans-serif)
**Label / Mono Font:** the platform monospace stack (`ui-monospace`, `SF Mono`, `SFMono-Regular`,
`Menlo`, `Consolas`, monospace)

**Character:** the operator's own OS voice. Choosing the system stack is a product decision, not a
default — the file ships as one offline HTML document with no build step and no CDN, so a webfont
would be a network dependency the product refuses. `font-variant-numeric: tabular-nums` is set on
`body`, so every count, size and duration in the product aligns in a column.

### Hierarchy
- **Display** (650, 22px, 1.2, -0.02em): the current view's title in the top bar. One per screen.
  Below 840px it is visually hidden — the nav already names the view.
- **Headline** (mono, 600, 18px, -0.02em): the detail pane's subject — an agent, skill, document or
  session name. Monospace because the name is an identifier read off disk.
- **Body** (400, 14px, 1.5): the default. Prose, buttons, tabs, row names, empty states. Prose
  blocks cap at 72ch.
- **Caption** (400, 12.5px, ~1.3): metadata, subtitles, footers, chips, stats, form labels, and all
  monospaced evidence.
- **Label** (600, 11px, 0.07em, uppercase): nav group headings and sticky list-group headers. Pills
  share the 11px size at weight 500 but stay sentence case — they carry a status word, not a
  section name.

### Named Rules
**The Mono-Is-Measurement Rule.** Monospace marks something the product measured or generated: a
name on disk, a path, a size, a count, an evidence line, a generated command, a diff. Explanatory
prose stays in the sans face even inside a technical panel. The build enforces this at runtime —
`evidenceHtml()` splits a finding into prose and measured lines and only monospaces the latter.
Monospace is never a costume for "this feels technical."

**The Five-Step Rule.** The ramp is exactly five sizes (11 / 12.5 / 14 / 18 / 22px), exposed as
`--fs-1` through `--fs-5`. A new surface picks one of the five; it does not introduce a sixth, and
it does not hardcode a px value that a step already covers.

## Layout

The shell is a fixed two-level frame: a top bar (56px, 52px below 840px) carrying the product name,
the view title and the global stat row; then a body split into navigation and content.

**Navigation** is a 212px sidebar (`--nav`) above 840px, holding four labeled groups — Status
(health, live, activity), Catalog (agents, skills), Projects (projects, docs), System (harness,
mcp). The groups are a presentation layer only; a view missing from the current mode is filtered
out and an empty group renders nothing.

**Content** is a two-pane grid: a list (`minmax(300px, 1.1fr)`) and a detail pane
(`minmax(290px, 1fr)`), separated by a 1px rule. The list stacks a filter strip (44px min), a
scrolling row region, a footer count and a color legend. The detail pane scrolls independently at
18px/20px padding with a 14px gap between blocks, and pushes its action row to the bottom with
`margin-top: auto`.

**Density.** Rows are 34px at rest (40px on touch), 6px/14px padding, one 8px status dot in a fixed
first column so every dot in the list aligns. Group headers stick to the top of the scroll region.
Long values ellipsize rather than wrap; paths break after a separator (`wbr()`), never mid-token.

**Rhythm.** Spacing steps in use are 2 / 4 / 6 / 8 / 10 / 12 / 14 / 16 / 20px. 6px and 8px are the
intra-component gaps, 14px is the row gutter, 16–20px frames the panes.

**Viewport caps.** Evidence and document previews cap at 60vh, the editor opens at 52vh, and the
project tile grid caps at 30vh — a long body never pushes the actions out of reach.

### Named Rules
**The Two-Pane Rule.** Every view is the same shell: a list that carries clickable headlines and a
detail pane that carries the evidence. A new view adopts the shell; it does not invent a layout.

**The 840 Rule.** One breakpoint, at 840px. Above it: sidebar nav, two panes side by side. Below
it: the nav becomes a horizontal scroller with its scrollbar hidden, the panes stack with a rule
between them, the display title is visually hidden, and every target grows (tabs and rows to 40px,
buttons to 36px). There is no second breakpoint and no tablet-specific case.

## Elevation & Depth

The system is flat by construction. Depth is tonal and linear: `panel` over `bg`, separated by 1px
`line`. Nothing is lifted, and no surface has a resting shadow.

### Shadow Vocabulary
- **Toast float** (`box-shadow: 0 1px 3px rgba(0,0,0,.18)`): the only shadow in the product. The
  toast is fixed over the page and needs to read as detached from it.
- **Selection marker** (`box-shadow: inset 1px 0 0 var(--accent)`): a 1px accent bar inside the
  left edge of a selected row or a toggled button. It is a marker drawn with the shadow property,
  not elevation.

### Named Rules
**The Flat Rule.** Surfaces are flat at rest and flat on hover. Hover changes the ground color
(`hover`) or a border color (`neutral`); it never adds a shadow, a lift, or a scale. If a new
element seems to need elevation, it needs a hairline or a tonal step instead.

**The Motion-Free Rule.** The product has one transition — the toast's 200ms opacity fade, itself
disabled under `prefers-reduced-motion`. Nothing animates on hover, selection, tab change or data
refresh. A screen that repaints once a second must not also be in motion.

## Shapes

One radius does the work: 6px (`--r`) on buttons, inputs, chips' container siblings, stats, boxes,
evidence blocks, tiles and the toast. Fully round (99px) is reserved for the two label shapes that
must read as tokens rather than controls — status pills and filter chips. The tool tag takes 5px,
and the status dot is a circle at 8px.

Borders are always 1px `line`. There are no double rules, no thick strokes, and no border in a
status color; a status is a fill plus a text color, never an outline. Buttons and inputs carry a
visible border at rest so a control is distinguishable from text without hovering.

The status dot is the only icon in the product. There is no icon set, and none is needed: an 8px
circle in one of five colors, decoded by the legend under the list.

## Components

### Buttons
- **Shape:** 6px radius, 32px minimum height (36px on touch), 6px/12px padding.
- **Default:** panel ground, 1px `line` border, ink text. Hover fills with `hover` and darkens the
  border to `neutral`.
- **Primary:** solid accent, white text, weight 500. Hover deepens to `accent-ink`.
- **Toggled (`on`):** blue wash ground, `accent-ink` text, weight 600, plus the 1px inset accent
  marker on its left edge — the same marker a selected row carries, so "active" reads identically
  in both places.
- **Danger:** rust text on the default shell; only the fill on hover turns rust-soft. A destructive
  action is never a solid red button, because project-os never performs the destructive act — it hands
  over the command.
- **Disabled:** 45% opacity, default cursor, hover suppressed.
- **Focus:** 2px accent outline at 2px offset, shared by every focusable element.

### Chips
- **Style:** pill, transparent ground, `line` border, dim text, 12.5px.
- **State:** active fills with blue wash, text goes `accent-ink`, weight 600, border matches the
  fill so the shape reads as solid. Chips are filters; they never trigger an action.

### Pills
- **Style:** pill, 11px, weight 500, sans face inside an otherwise monospaced heading, 2px/8px.
- **State:** the status word carries its soft fill and matching text color (moss / amber / rust),
  or the `line` fill with dim text when the state is "none" or "document." A pill always contains
  a word — it is the readable twin of the dot, not a second dot.

### Cards / Containers
- **Boxes** (`.box`): 6px radius, 10px/12px padding, filled with a soft tint and its matching text
  color, no border. Three semantic variants (warn, bad, info) plus the slate info variant for
  explanation. A box is a statement about state; a paragraph does not get one.
- **Tiles** (`.tile`): 6px radius, `bg` fill, 1px border, 44px min height, in an auto-filling grid
  from 220px.
- **Evidence blocks** (`pre.lines`): mono, 12.5px, `bg` fill inside a 1px border, and they scroll
  sideways rather than wrap — a measured line must stay on one line to stay comparable.
- **Document previews** (`pre.doc`): the same shell but wrapping, capped at 60vh; `.full` removes
  the cap for a document read end to end.

### Inputs / Fields
- **Style:** panel ground, 1px `line` border, 6px radius, 6px/10px padding, inherited body font.
- **Hover:** border darkens to `neutral`.
- **Focus:** border turns accent and the 2px accent outline sits flush (`outline-offset: 0`) so the
  field does not appear to grow.
- **Textarea:** monospace at 12.5px, vertically resizable; the document editor opens at 52vh with a
  2-space tab stop.
- **Error:** rust text at 12.5px under the field, in a slot with a reserved 14px height so
  validation never reflows the form.

### Navigation
- **Sidebar (≥840px):** grouped, each group headed by an 11px uppercase label with 0.07em tracking
  in dim; items are full-width left-aligned buttons at 1px vertical spacing.
- **Item states:** dim at rest; hover takes ink text on the `hover` ground; active takes blue wash,
  `accent-ink` text, weight 600, and `aria-current="page"`.
- **Mobile (<840px):** the same markup becomes a horizontal scroller under the top bar, group
  labels inline with a right-hand divider rule, scrollbar hidden.

### Rows (signature component)
The list row is the product's densest and most repeated surface: an 8px dot, a flexible name in
monospace, and right-aligned dim metadata, on a 1px-ruled 34px band.
- **`.row.cols`** adds two fixed metadata columns (116px and 62px; 84px/54px on mobile) so counts
  align vertically down the whole list.
- **`.row.stack`** switches to top alignment and adds a dim 12.5px subtitle line under the name —
  the finding's own first line of evidence, so the list informs before a click. An empty subtitle
  collapses instead of leaving a gap.
- **Selected:** blue wash, `accent-ink` text throughout, inset accent marker. **Focused:**
  `accent-ink` name at weight 600, no fill — keyboard position is distinguishable from selection.

### Legend
A wrapping strip of dot-plus-word pairs under the list footer at 11px dim, rebuilt per view from
that view's own vocabulary, and hidden entirely when a view has none. The dots are the densest
signal on the screen and would otherwise be undecodable without clicking a row.

### Toast
Inverted: `ink` ground with `bg` text, fixed 22px from the bottom and centered, 6px radius, capped
at 90vw, pointer-events off. It fades in over 200ms and out after 2.6s, and does not animate at all
under `prefers-reduced-motion`.

## Do's and Don'ts

### Do:
- **Do** carry every color through its CSS custom property. Both themes are defined once on
  `:root`; a literal hex in a new rule is a bug in dark mode.
- **Do** pick one of the five type steps (`--fs-1`…`--fs-5`) and one radius (6px, or 99px for a
  token shape).
- **Do** pair every status color with a word — a pill, a legend entry, or the count it labels.
  Color is never the only channel.
- **Do** write unknown as text ("n/a", "size not measured", "never recorded") and give it the
  neutral gray dot.
- **Do** keep exactly one primary button per pane or dialog; every other action is a default
  button. The build holds to this across all eleven of its primary buttons.
- **Do** monospace measured values and generated commands, and leave explanation in the sans face.
- **Do** show a generated command in an evidence block for the user to read and run. project-os never
  runs it.
- **Do** let long values ellipsize, and break paths after a separator.

### Don't:
- **Don't** use moss, amber or rust for anything that is not a measured state — not for emphasis,
  not for a category, not for branding.
- **Don't** introduce a second accent, or restyle the accent per view.
- **Don't** add a resting shadow, a hover lift, or any transition beyond the toast's fade. One
  shadow exists and it belongs to the toast.
- **Don't** render an unmeasured value as 0, an empty bar, or a green check.
- **Don't** add glyph icons or an icon font. The 8px status dot is the icon set, and the product
  ships offline with no external assets.
- **Don't** outline a control in a status color; a state is a fill plus a text color.
- **Don't** wrap an evidence line. It scrolls sideways so it stays comparable to the line above it.
- **Don't** add a breakpoint. There is one, at 840px.
- **Don't** style a control with an inline `style` attribute when a class exists; the few that
  remain in the build are debt, not a pattern.
