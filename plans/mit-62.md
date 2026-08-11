# MIT-62 — Photo label obscures bird image at large font sizes

## Summary
Move the photo caption out of Bootstrap's absolutely-positioned `.carousel-caption` overlay
and into normal document flow below the image, so it can never cover the bird photo regardless
of the browser's base font-size setting. This matches the reporter's explicit request ("label be
moved off the image") and is a template/CSS-only change — no Python, no data model, no JS.

## Root cause
- `birdle/templates/birdle/bird_display.html:8-9` renders each slide's label inside Bootstrap's
  `.carousel-caption` class, which Bootstrap defines as `position: absolute` (we further pin it
  with `top: auto; bottom: 0;` in `birdle/static/birdle/style.css:78-81`) — i.e. the label is
  drawn *on top of* the image, not beside it.
- The image's height is fixed via viewport units only: `.bird-img { max-height: 25vh; }`
  (`style.css:1-3`) and `.carousel-inner img { height: 25vh; ... }` (`style.css:83-89`). Neither
  rule scales with font size.
- The label itself (`style.css:10-16`, `.img-label`) uses `font-size: large` — a keyword that
  scales with the browser's *root* font-size setting (Firefox's accessibility "Font Size"
  preference), independent of page zoom. Its padding is fixed px, so as the root font grows, the
  label's box (text + padding) grows and wraps, while the absolutely-positioned image height
  stays pinned at 25vh underneath it — the caption box ends up covering a large fraction, or all,
  of the fixed-height image.
- This exactly matches the report: page zoom (which scales `vh` and font together) doesn't help;
  only shrinking the browser's base font size shrinks the overlay enough to stop covering the
  bird.

## Fix
Stop overlaying the label on the image; stack it underneath in normal flow instead.

### Files to touch
1. `birdle/templates/birdle/bird_display.html`
   - Replace the `<div class="carousel-caption align-bottom">...</div>` wrapper (lines 8-10)
     with a plain, non-Bootstrap wrapper, e.g. `<div class="img-label-wrap">`, still holding
     `<span class="img-label">{{ img.label }}</span>`, and keep it as a sibling of `<img>` inside
     `.carousel-item` (after the `<img>` tag) so it renders below the photo in document flow
     instead of overlaid on it.
   - This partial is shared by both the daily game (`daily_bird.html:7`) and practice mode
     (`practice.html:27`), so this single change fixes both surfaces — no duplication needed.

2. `birdle/static/birdle/style.css`
   - Remove the `.carousel-caption { top: auto; bottom: 0; }` rule (`style.css:78-81`) — it's
     orphaned dead code once the template stops using the `.carousel-caption` class (grep
     confirms `.carousel-caption` isn't referenced anywhere else in the codebase).
   - Add a small rule for the new wrapper to keep the label horizontally centered under the
     image, matching its previous centered appearance, e.g.:
     ```css
     .img-label-wrap {
         text-align: center;
         margin-top: 0.5rem;
     }
     ```
   - Leave `.img-label` itself (background, color, padding, `font-size: large`) unchanged — the
     large/accessible font size is fine now that it can no longer collide with the photo; no need
     to suppress the user's font preference.
   - No changes needed to `.bird-img` / `.carousel-inner img` (still fine to keep photos at a
     consistent `25vh` — they're no longer at risk of being obscured).

### Not in scope / left alone
- `.carousel-control-prev` / `.carousel-control-next` (Bootstrap defaults, `top: 0; bottom: 0;`
  relative to `#carouselControls`) will automatically stretch to the new (taller, when a label
  wraps) `.carousel-item` height — no CSS change needed there, but call this out in manual
  verification below since it's a plausible (if minor) visual side effect.
- No Python/view changes — `get_bird_images` (`birdle/views.py:316`) already supplies
  `img.label`/`img.url` unchanged; this is purely a presentation fix.

## Risks / open questions
- None structural. The only real risk is a purely cosmetic one: on very narrow/mobile viewports
  with an unusually long label, the carousel item grows taller than before (label now takes its
  own row instead of overlapping) — that's the intended tradeoff per the reporter's request, but
  worth a quick look at a narrow viewport during manual verification.

## Verification
- `uv run ruff check`, `uv run ruff format --check`, `uv run ty check`, `python manage.py test` —
  standard gate; no test coverage exists for this template/CSS today and none is being added
  (purely presentational, no assertions to write), but the gate must still pass clean.
- Manual/visual check (no automated test covers this):
  1. `python manage.py runserver 8001`, open the daily game (and practice) page.
  2. In devtools, bump the root font size substantially (e.g. `document.documentElement.style.fontSize = '32px'` in the console, or Firefox's a11y "Font Size" preference) and confirm the
     label now sits in its own row below the photo instead of covering it, at both a desktop and
     a narrow/mobile viewport width.
  3. Confirm carousel prev/next arrows still work and multi-photo birds still cycle labels
     correctly per slide.
  4. Confirm the label still looks reasonably centered/unchanged at default font size (visual
     parity check against current behavior, minus the overlap bug).
