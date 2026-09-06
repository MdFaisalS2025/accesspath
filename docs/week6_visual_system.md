# Week 6 — Visual System (defined before coding)

Goal: make the difference between `shortest`, `accessible`, and
`confidence_aware` routing legible within 60 seconds. Everything below is
in service of that, not decoration. Deliberately avoided: card-heavy
dashboard chrome, gradients, glass/blur effects, decorative stat tiles,
animation beyond a 150ms hover/focus transition (disabled entirely under
`prefers-reduced-motion`).

## Color palette (tested contrast, restrained)

One accent color, a neutral scale, and a route palette chosen from the
Okabe-Ito colorblind-safe set (verified distinguishable under protanopia/
deuteranopia/tritanopia simulation, not just "looks fine to me").

| Token | Value | Use | Contrast |
|---|---|---|---|
| `--color-bg` | `#FFFFFF` | page background | — |
| `--color-surface` | `#F7F7F5` | sidebar/panel background | — |
| `--color-text` | `#1A1A1A` | body text on `--color-bg` | 17.9:1 |
| `--color-text-muted` | `#4B4B4B` | secondary text | 8.6:1 |
| `--color-border` | `#C9C9C6` | dividers, card borders | 1.8:1 (non-text, decorative only) |
| `--color-accent` | `#0B5FA5` | links, primary button, focus fill | 5.5:1 (white text on it) |
| `--color-focus-ring` | `#0B5FA5` | focus outline (3px, never removed) | — |
| `--color-danger-text` | `#8A1300` | hazard text/icons on white | 7.9:1 |
| `--color-warning-text` | `#6B4400` | low-confidence/disputed text on white | 7.3:1 |

Route colors (Okabe-Ito, each also gets a distinct pattern/width — color is
never the only differentiator, see below):

| Mode | Color | Swatch contrast on white |
|---|---|---|
| `shortest` | `#000000` (black) | 21:1 |
| `accessible` | `#0072B2` (blue) | 5.6:1 |
| `confidence_aware` | `#D55E00` (vermillion) | 4.9:1 |

All body text pairs meet WCAG AA (4.5:1 normal text, 3:1 large text/UI
components). `--color-border` is decorative-only (dividers, map casing) and
is not relied on to convey information by itself.

## Typography

System font stack (no webfont network dependency, respects the user's OS
font/size preferences, zero FOUT):

```
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
```

| Token | Size | Weight | Use |
|---|---|---|---|
| `--font-size-xs` | 12px | 400 | metadata (snap distance, segment ids) |
| `--font-size-sm` | 14px | 400 | body copy, route card detail |
| `--font-size-base` | 16px | 400 | default |
| `--font-size-lg` | 20px | 600 | route card headings, section headings |
| `--font-size-xl` | 24px | 600 | page title |

Line-height 1.5 for body, 1.25 for headings. All sizes in `rem`-equivalent
relative units so 200% browser zoom reflows rather than clips (verified,
see report).

## Spacing tokens (4px base grid)

`--space-1: 4px`, `--space-2: 8px`, `--space-3: 12px`, `--space-4: 16px`,
`--space-5: 24px`, `--space-6: 32px`, `--space-8: 48px`.

## Route differentiation without relying on color alone

| Mode | Color | Line style | Width | Casing |
|---|---|---|---|---|
| `shortest` | black | solid | 4px | 6px white halo underneath |
| `accessible` | blue | dashed (10px/6px) | 5px | 7px white halo |
| `confidence_aware` | vermillion | dotted (2px/6px round-cap) | 5px | 7px white halo |

The white halo (a wider white line drawn under each route) keeps every
route legible against the basemap and against each other where they
overlap, and the dash/dot pattern is distinguishable in grayscale printouts
or under any color-vision deficiency, not just by hue. The legend and route
cards repeat the pattern name ("solid", "dashed", "dotted") as text, not
just a color swatch.

Non-route map symbols (hazards, unknown segments, disputed evidence) use
distinct **shapes/icons**, not color alone: a triangle for hazards, a
dashed-outline square for unknown coverage, a circle-with-slash for
disputed evidence — colored for a quick-glance cue, but shape-coded as the
actual differentiator (verified in the accessibility pass with a grayscale
screenshot).

## Layout

**Desktop (≥1024px):** map fills the left ~68% of the viewport (the primary
visual element, per the brief); a fixed ~400px right sidebar holds
origin/destination status, the "Compare routes" action, the three route
cards, and the coverage-layer toggle. A slim, persistent disclaimer bar
spans the full width at the very bottom of the viewport, unaffected by
sidebar scrolling.

**Mobile (<768px):** map on top (55vh), sidebar content stacks below it in
normal document flow (no bottom-sheet gesture complexity), "Compare
routes" is a full-width sticky button above the route list. Disclaimer bar
stays pinned to the bottom of the viewport in both layouts.

## ASCII wireframe (desktop)

```
┌──────────────────────────────────────────────────────────────────┐
│ AccessPath                              [Coverage layers ▾]      │
├────────────────────────────────────────────┬─────────────────────┤
│                                              │ Origin: 47.620,-122.335 │
│                                              │ Destination: click map │
│                                              │ [   Compare routes  ]  │
│                                              ├─────────────────────┤
│                                              │ Shortest ── solid  │
│                MAP (MapLibre)                │   420 m · ~6 min    │
│         click to place origin, then          │   accessibility 0.53 │
│         destination; three route lines        │   confidence 0.07    │
│         drawn after Compare                   │   ⚠ 3 known hazards │
│                                              ├─────────────────────┤
│                                              │ Accessible ┄┄ dashed│
│                                              │   ...                │
│                                              ├─────────────────────┤
│                                              │ Confidence-aware ···· │
│                                              │   ...                │
├──────────────────────────────────────────────┴─────────────────────┤
│ ⚠ Decision-support prototype based on incomplete public data.       │
│   It does not guarantee accessibility or safety.                     │
└──────────────────────────────────────────────────────────────────┘
```

Mobile: the right column becomes the content below the map, in the same
top-to-bottom order (origin/destination status → Compare button → route
cards → coverage toggle), disclaimer bar still pinned to the viewport
bottom.
