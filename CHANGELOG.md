# Changes

## Clean agent-installable review package (source baseline 0.5.5)

- Removed history patches and a user-specific home-directory path from developer documentation.
- Added install instructions for human users and coding agents, including `AGENTS.md`, `CLAUDE.md`, preflight and security notes.
- Added release-review guardrails and excluded local generated data with `.gitignore`.
- Changed **one runtime value**: `PAN_DIST_PER_SEC` from `1.35` to `0.8`, reflecting the latest user preference.
- No intentional changes to Rhino selection, camera scheduler, VS Code extension, UDP protocol, or haptics.

## Baseline 0.5.5

- Voice drafts may expire or be replaced; retries in the same VS Code extension process avoid duplicate send.
- Agent terminal must be explicitly bound. Auto-send/submit are optional and OFF by default.
- `Eto.Forms.UITimer`, magnetic picking, haptic selection and basket metadata remain in the Python source.
