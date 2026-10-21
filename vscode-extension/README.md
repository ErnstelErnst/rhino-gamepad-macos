# Rhino Gamepad Agent Link v0.5.5

Binds a **specific VS Code terminal** to the Rhino Gamepad voice worker through a loopback-only, bearer-token HTTP connection.

1. Install the VSIX from Extensions → ... → Install from VSIX.
2. Start your AI CLI in a VS Code terminal.
3. Run **Rhino Gamepad: Bind Agent Terminal** from the Command Palette.
4. In VS Code Settings, search **Rhino Gamepad**.

Configuration:
- `rhinoGamepad.autoSend` (default **false**) — deliver dictation immediately without gamepad A.
- `rhinoGamepad.autoSubmit` (default **false**) — press Enter after inserted text, **only if you accept the risk of the CLI falling back to a shell**.
- `rhinoGamepad.draftTTLSeconds` (default **60**) — stale draft expiry.

Pressing A/B after transcription remains available when autoSend is OFF. New drafts replace older unsent drafts. Repeated sends of a completed ID do not reinsert the text during the extension process lifetime.

**No global Enter injection. No proof of agent readiness. No direct calls to Rhino MCP.** The receiver is bound to a known terminal only, and the user/agent is responsible for tool use.
