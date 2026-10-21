# Known limits and compatibility notes

- Verified by one user on an Apple Silicon Mac with Rhino 8 and an 8BitDo Ultimate 2 in Switch-compatible mode. No general cross-device compatibility guarantee.
- `Eto.Forms.UITimer` targets 60 Hz camera updates, but the original live test reported approximately 38–45 Hz; actual updates depend on Rhino UI scheduling and scene load.
- Magnetic selection uses bounded Rhino-native picking and heuristics; it may omit narrow, hidden or overlapping subobjects and should not be mistaken for a perfect geometric nearest-neighbor index.
- Independent CAD/model editing happens in Rhino through RhinoCommon/MCP, not through the VS Code terminal extension itself.
- The VS Code prompt receiver cannot prove CLI agent readiness. Auto-submit is inherently unsafe if the agent falls back to a shell.
- A new standalone SDL bridge is not guaranteed exclusive control of the gamepad. Other applications can receive the same HID input.
- RhinoCode caches Python modules. When switching source folders, stop an old listener first; the Rhino toggle script includes a guard against cached modules from other folders.
- Existing legacy bridges may not respect recent single-instance locks. If input goes dead, first identify competing processes carefully and stop the old ones with consent.
- Pan speed **0.8** is a requested clean-release default; camera tuning and full voice integration of this repackaged artifact have not been live-retested.
