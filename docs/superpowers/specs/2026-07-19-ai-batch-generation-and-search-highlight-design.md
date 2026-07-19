# AI Batch Generation and Search Highlight Design

## Goal

Ship version 0.8.2 with batch AI generation for multi-selected MODs and a
persistent search-highlight mode.

## Batch AI generation

The existing per-MOD generation RPC remains the only generation API.  When AI
is configured and a context-menu selection contains more than one MOD, the
bottom of the menu exposes `AI Generate (x items)`.  Selecting it processes
the selected IDs in selection order, one at a time, through the existing store
action.  Each successful call updates that MOD's alias and notes.  A failed
item leaves its existing data unchanged; the current store-level error toast
is shown and later IDs continue to run.

The sequential queue deliberately avoids concurrent requests to the user’s
configured AI provider and retains the existing busy-state and notification
behaviour.

## Search-highlight mode

The search toolbar gains a toggle next to the token search control.  Its state
is stored in the existing application settings and restored on startup.

With the toggle off, the two MOD lists retain their current behaviour: only
MODs matching all active search conditions are rendered.  With it on, both
lists retain their normal visible MOD membership and sorting, matching rows
receive a distinct highlight, nonmatching rows are visually muted, and the
first matching row is scrolled into view after the search query or mode
changes.  An empty query does not mute or highlight any row.

## Version and release boundary

Application source, frontend package metadata, Windows version information,
README version text, changelog, translations, and regression tests advance to
0.8.2.  This is source work only: no package is built, no release is created,
and the public update manifest remains at the published 0.8.1 asset so it
continues to advertise a downloadable, hash-verified file.

## Validation

Add Vitest coverage for context-menu availability, batch sequencing and
continuation, persistent highlight settings, search display membership, row
classes, and first-result navigation.  Extend the Python version/changelog
contract for the source-versus-published-manifest boundary.  Run focused tests,
the full frontend suite, backend unittest suite, frontend production build,
and `git diff --check`.
