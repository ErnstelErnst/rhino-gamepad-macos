# Developer notes (sanitized)

Source baseline: archived Rhino Gamepad macOS **v0.5.5**, comprising an external SDL2 bridge, Rhino 8 Python listener, RhinoCommon picking, Selection Basket, haptics, Eto UI-thread timer and VS Code Agent Link extension.

## Why this layout exists

- Rhino's `RhinoApp.Idle` fired too infrequently for smooth camera navigation in live measurements. `Eto.Forms.UITimer` greatly improved responsiveness; keep RhinoCommon calls on the UI thread.
- Earlier bridge duplicates sent competing session identifiers to UDP 47881. The current bridge has a single-instance advisory lock, but old processes may not honor it.
- Earlier magnetic picking skipped thin geometry and alternated between candidates. The current code includes scan sampling and directional stabilization; behavior is heuristic rather than complete.
- The voice extension previously locked abandoned drafts with HTTP 409. It now has replaceable drafts, expiry, and in-memory idempotent send handling; always treat `sent` as a terminal handoff, not an agent acknowledgement.

## Clean-packaging changes

- Removed stale source diffs and developer references to a specific user's home path.
- Kept Python files in the same directory so RhinoCode sibling imports continue to work.
- No changes to selection algorithms, Rhino scheduler, packet protocol, VS Code extension or haptics in this public-review candidate.
- **Only runtime tuning change:** `PAN_DIST_PER_SEC` from 1.35 to **0.8** in `rhino_gamepad_toggle.py`.
- A new maintainer must validate license/rights before releasing publicly.

Run `python3 -m unittest discover -p 'test_*.py' -q` and `node vscode-extension/test_extension.cjs` before submitting code changes; then test in Rhino on a spare model.
