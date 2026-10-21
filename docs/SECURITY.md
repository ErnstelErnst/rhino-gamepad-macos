# Security and privacy

This is experimental CAD/agent glue code, **not a hardened execution sandbox**.

- The bridge uses loopback UDP; the VS Code extension exposes an ephemeral loopback HTTP port and stores a bearer token in a mode-0600 JSON file under the user's Library folder.
- Treat `agent-link.json`, project geometry files, selection metadata, transcript files, agent output, logs, and shell history as sensitive. Never commit or share them.
- The extension sends text to a manually **bound** VS Code terminal. It cannot establish that the AI CLI is waiting for a prompt; if the agent has exited, `autoSubmit=true` may execute dictated text as shell code.
- Auto-send and auto-submit are disabled by default. Don't turn them on unattended in an arbitrary terminal. Use a separate dedicated agent terminal and prefer manual confirmation.
- A successful HTTP `/send` confirms only `Terminal.sendText()` returned, not that the agent performed the operation or that Rhino was changed correctly.
- Voice text is normalized to one line, but that does **not** neutralize shell metacharacters. Avoid global keyboard/Enter fallbacks.
- Some files under `~/Documents/RhinoGamepad/` contain geometry identifiers and metadata that may reveal details of your model. Share only intentionally.
- This repository intentionally contains no live token, project geometry, personal session transcript, or user-home absolute path.
- Before publishing: select a license, verify ownership/third-party rights, inspect all staged files with `git diff --cached` and use the included `tools/audit_release.py` as an additional heuristic (not a guarantee).
