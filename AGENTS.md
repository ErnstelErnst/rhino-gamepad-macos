# Instructions for a coding agent working in this repository

**Primary goal:** Install and test Rhino Gamepad for the user's macOS workstation **without disrupting existing CAD tools, VS Code terminals or the user's private files**.

## First pass (read-only)

1. Read `README.md`, `docs/INSTALL.md`, `docs/SECURITY.md`, and `docs/KNOWN_LIMITATIONS.md`.
2. Inspect the source and run `python3 tools/preflight.py` (read-only). Determine macOS version, Python, SDL2, VS Code CLI and Rhino presence. Never treat diagnostic output as user approval for changes.
3. Run the offline Python and Node tests if Python/Node are available. Stop and report failures before installing anything.
4. Ask which gamepad is connected and which Rhino version and VS Code terminal-based agent should be used; do not assume the original user's 8BitDo or agent is available.

## Installation with approval

5. If SDL2 is missing, ask before installing with Homebrew. Do not install packages or modify PATH silently.
6. Stop **only clearly identified existing gamepad bridge processes** with the user's consent. Prefer graceful termination, not broad `pkill -9` commands. Avoid duplicate senders on local UDP 47881.
7. Keep the source in its own folder; launch `python3 gamepad_bridge.py --list-devices`, choose the device index, and then start one bridge instance. Do not automatically create background services or LaunchAgents.
8. In Rhino 8 Python 3 ScriptEditor, run the **absolute path** of `rhino_gamepad_toggle.py` in a disposable copy of a model. The same script toggles on/off. Request permission before editing or running Rhino scripts against production models.
9. Optional: install the supplied VSIX from VS Code's Extensions menu. The user must explicitly select **Rhino Gamepad: Bind Agent Terminal** and verify the terminal is running an AI agent (not a shell prompt). If this isn't a trusted agent terminal, skip voice features.
10. Optional: help create a macOS Shortcut named `Rhino Agent Dictate` with `Dictate Text` followed by `Stop and Output`. Let the user grant microphone permissions. Prefer a harmless read-only voice test.

## Mandatory safety practices

- Do not touch the user's current working plugin or replace installed extension settings without prior consent.
- Never request, copy, log, commit or upload model files, transcripts, connection tokens, API credentials, or agent session data.
- `~/Library/Application Support/RhinoGamepad/agent-link.json` is a **runtime secret**; never include it in a repository, screenshot or diagnostic paste.
- `~/Documents/RhinoGamepad/` can contain project geometry metadata and transcripts; it is **not** release material.
- Auto-send / auto-submit **must remain OFF** by default. Explain that `autoSubmit` can turn dictated text into shell commands if the CLI agent exits.
- Do not inject global Enter keystrokes with AppleScript or write arbitrary text to the currently focused terminal.
- Do not assume MCP connectivity from a port alone; ask the user to verify it in their chosen agent.
- Don't assume a particular model unit, display mode, controller mapping, or OS version.
- Rhino calls must remain on Rhino's UI thread; never move camera operations directly to a background worker.

## Confirmation checklist

- The user can start/stop the bridge and toggle the Rhino listener reliably.
- Camera orbit/pan/zoom move in the expected direction. Default `PAN_DIST_PER_SEC=0.8` was requested by the original user but isn't tested on a fresh install.
- RB targeting and A basket selection work on the user's model. D-pad moves candidates where geometry permits.
- Short Y exports basket metadata locally without involving the microphone.
- Optional voice prompt reaches **only the explicitly bound** terminal, with no unexpected automatic execution.
- Record local version, macOS, Rhino, controller mode, observed success/failure; do not commit private diagnostics.

## Compatibility notes

Source scripts intentionally share one directory because RhinoCode imports sibling Python modules. Keep that layout when installing. The bundled VSIX version remains 0.5.5 and is optional. Historical source diffs and user-specific troubleshooting transcripts are deliberately excluded from this clean distribution.
