# Rhino Gamepad for Mac — Gamepad Controller Navigation & Selection in Rhino 8

**Use a gamepad to orbit, pan, zoom, and select geometry in Rhinoceros 8 on macOS.** A free, experimental, source-available tool for Rhino 8 on Apple Silicon Macs, using SDL2, Python, and RhinoCommon.

If you searched for **“Rhino Mac gamepad,” “Rhino 8 controller support,” “Rhino joystick navigation,” or “use a controller in Rhino on macOS,”** this project is meant to give you a working starting point rather than having to develop one from scratch.

**What it does:**

- **Navigate in 3D:** right-stick orbit, left-stick pan, trigger zoom, and a precision modifier.
- **Select with the controller:** magnetic directional gliding or a visible crosshair; target Rhino objects, faces, and edges; collect multiple parts in a Selection Basket.
- **Feel what you're selecting:** optional controller rumble when the highlighted geometry changes and on confirmation.
- **Optional voice-to-agent workflow:** dictate an instruction using macOS Shortcuts, send it to a **designated VS Code terminal-based agent**, and provide selection context. A separate Rhino MCP connection is needed for the agent to operate on Rhino.
- **Use it with a coding agent:** open the repository in VS Code and ask your agent to read [`AGENTS.md`](AGENTS.md) and help with setup.

**Tested setup:** Rhino 8 for Mac, Apple Silicon, 8BitDo Ultimate 2 (Bluetooth and 2.4 GHz). Other Mac and controller combinations are not yet verified. This is a **developer-oriented beta**: Python scripts plus a controller bridge, not a one-click Rhino Package Manager install. The cleaned repository's default pan speed is **0.8**, which has not yet been retested as part of this distributable snapshot.

> **Rhino gamepad navigation works without AI or VS Code.** The VS Code agent link, voice dictation, and Rhino MCP connection are optional extras.

[Install with a coding agent](#install-with-your-coding-agent) · [Manual setup](docs/INSTALL.md) · [Gamepad controls](docs/CONTROLS.md) · [Known limitations](docs/KNOWN_LIMITATIONS.md) · [Security](docs/SECURITY.md)

---

## Install with your coding agent

Clone or download this repository, open the folder in VS Code, and give your trusted coding agent this instruction:

> Read `AGENTS.md`. Perform the non-destructive environment checks and help me install Rhino Gamepad for macOS and Rhino 8. Ask before modifying system settings, installing software, enabling microphone permissions or auto-submit, or stopping existing gamepad processes. Don't overwrite my working Rhino plugin or VS Code settings. Test with a disposable Rhino model.

A coding agent can automate most of the process; **you** still approve macOS permissions, select the actual controller, choose a VS Code terminal, and perform the live camera test.

If you prefer to set it up yourself, follow [Installation](docs/INSTALL.md). The core gamepad and Rhino scripts are Python and don't require the optional voice/VS Code integration.

## Components

- `gamepad_bridge.py`: separate SDL2 controller reader and loopback UDP sender; foreground routing and haptics.
- `rhino_gamepad_toggle.py`: Rhino 8 Python 3 ScriptEditor listener using `Eto.Forms.UITimer` for camera movement; selection basket and magnetic/crosshair targeting.
- `native_picker.py` and supporting modules: RhinoCommon selection and candidate logic.
- `agent_handoff.py`: optional macOS Shortcuts transcription/selection-context handoff.
- `vscode-extension/`: source for VS Code Agent Link. `rhino-gamepad-agent-link-0.5.5.vsix` is its bundled installable build.
- `test_*.py`: offline regression tests. `tools/preflight.py` checks dependencies without modifying your machine.

## Safety, privacy, and limitations

- The connector is **not** a Rhino MCP server; your agent must already have a working Rhino MCP tool connection for CAD operations.
- Voice instructions and basket metadata can be copied or sent to your explicitly bound VS Code terminal. Do not share models, selection context or transcripts without consent.
- Auto-send and auto-submit default **OFF**. Auto-submit can execute dictated text as a shell command if the terminal-based agent has exited. See [Security](docs/SECURITY.md).
- The VS Code extension's `sent` status means text was handed to the chosen terminal, **not** that the AI agent accepted or executed it.
- The repository does **not** contain live tokens, personal model files, session data or user-generated transcripts.
- If you have another controller bridge running, stop it **normally** before starting this one. Competing historical bridges can disrupt input.

## Controls

See [Controls](docs/CONTROLS.md). Left stick pans in navigation mode; right stick orbits; LT/RT zoom. In targeting mode RB enables/disables picking, A adds/removes basket items, Y exports or starts dictation when held.

## Tests

```sh
python3 tools/preflight.py
python3 -m unittest discover -p 'test_*.py' -q
node --check vscode-extension/extension.js
node vscode-extension/test_extension.cjs
```

Python regression tests run without Rhino; the VS Code test mocks the extension API. They do not substitute for tests on a real Mac.

## Sharing and licensing

Released under [The Unlicense](LICENSE), subject to the repository maintainer having rights to distribute the included code. You may use, modify, share, or build on it, including commercially. External dependencies retain their own licenses.

See [Known limitations](docs/KNOWN_LIMITATIONS.md) and [Developer history](docs/DEVELOPER_NOTES.md).
