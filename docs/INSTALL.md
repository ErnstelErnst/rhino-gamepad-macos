# Installation (macOS / Rhino 8)

This beta is intended for technical users or a trusted VS Code coding agent. Do not try it first on an important model.

## Prerequisites

- macOS with Rhino 8 supporting Python 3 in ScriptEditor, an SDL2-compatible gamepad, and Python 3 for the separate bridge.
- SDL2 system library. On an Apple Silicon Mac with Homebrew, `brew install sdl2` typically supplies it (approval required). The script also accepts `SDL2_LIBRARY` pointing to a usable SDL2 dylib.
- Optional: VS Code (with a terminal-based AI agent and a **separate** Rhino MCP connection) and the macOS Shortcuts application for Dictate Text.
- Optional: Node.js to run VS Code extension source tests. No Node install is required for the supplied `.vsix`.

## Check before modifying anything

```sh
python3 tools/preflight.py
python3 -m unittest discover -p 'test_*.py' -q
```

From the repository root, identify controller mappings:

```sh
python3 gamepad_bridge.py --list-devices
python3 gamepad_bridge.py --check-focus
```

If multiple controllers appear, specify `--device-index N` when launching the bridge. The 8BitDo can enumerate differently in Bluetooth and 2.4 GHz modes.

## Launch the controller bridge

1. Back up working installations; stop previous Rhino listener and bridge gracefully.
2. From this repository's root, run **one** bridge:

```sh
python3 gamepad_bridge.py
```

Leave that terminal running initially. If Rhino doesn't respond, use `python3 gamepad_bridge.py --diagnose` when the bridge is stopped to see axis/button changes. The bridge communicates only via loopback UDP.

## Start Rhino listener

1. In Rhino 8, open Python 3 ScriptEditor, open `rhino_gamepad_toggle.py` using its **absolute path**, and run it.
2. Expect the gamepad listener ON message. Run the same script again to toggle it OFF.
3. Click the Perspective viewport, orbit with the right stick, pan with the left, and zoom with triggers. Confirm expected controls in a disposable model.
4. RB enters targeting; press A to add geometry to the basket. Y briefly exports geometry metadata. See `CONTROLS.md`.

## Optional VS Code terminal agent and voice input

1. Install `rhino-gamepad-agent-link-0.5.5.vsix` via VS Code → Extensions → Install from VSIX. Reload VS Code.
2. Start the desired CLI coding agent inside a VS Code terminal. Run `Rhino Gamepad: Bind Agent Terminal` and choose that terminal explicitly.
3. Create a Shortcut called `Rhino Agent Dictate`, containing `Dictate Text` followed by `Stop and Output` for the dictated text. Approve microphone permission yourself.
4. Confirm the coding agent's Rhino MCP connection **independently**. The VS Code extension does not create or manage MCP connections.
5. Keep `rhinoGamepad.autoSend` and `rhinoGamepad.autoSubmit` **false** initially. Hold Y to dictate a non-destructive prompt, use manual approval, and confirm the correct terminal receives text.
6. Only if the user understands the shell risk, optionally enable `autoSend`; separately consider `autoSubmit`. The latter appends Enter to the bound terminal and could run arbitrary dictated shell text if the agent has exited.

## Remove / stop

Toggle the Rhino script OFF, stop the bridge with Ctrl+C in its Terminal window, and uninstall the VS Code extension if installed. This project does **not** automatically add a LaunchAgent or alter macOS startup settings. No bulk `pkill` command is required.
