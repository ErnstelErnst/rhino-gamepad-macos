# Publish so other people can find it

## GitHub repository name

`rhino-gamepad-macos` (recommended; if available). Alternatives: `rhino8-gamepad-mac`, `rhino-controller-mac`.

## GitHub short description (About)

Gamepad controller for Rhino 8 on macOS: orbit, pan, zoom, magnetic geometry selection & haptics. Optional voice-to-VS Code agent via Rhino MCP.

## GitHub topics

`rhino3d`, `rhinoceros`, `rhino8`, `macos`, `apple-silicon`, `gamepad`, `controller`, `3d-navigation`, `cad`, `rhinocommon`, `8bitdo`, `mcp`

Add these through GitHub's **About** section > gear icon > Topics. Topics help GitHub discovery, but there is no guarantee of search ranking.

## Suggested public beta release tag

`v0.5.5-beta` — source cleanup with default pan speed 0.8. State explicitly that the snapshot has not been live-retested after the pan adjustment. This is *not* a standard .rhp or Yak Package Manager install.

## Where to post the link

- **McNeel Discourse:** a short forum post in the most suitable Rhino/macOS category, linking this repo. Include macOS/Rhino version and one 20–40-second screen recording. Link: https://discourse.mcneel.com/
- **food4Rhino:** consider a listing linking back to the GitHub release, so someone searching for a Rhino tool finds it even if they do not search GitHub. Link: https://www.food4rhino.com/
- **Reddit:** optionally r/rhino with a demonstration and link; follow community rules.

## Post ready to adapt

**Title:** I made a free gamepad controller for Rhino 8 on Mac (navigation + geometry selection)

Today I was looking for a way to use a gamepad with Rhino 8 on macOS and couldn't find a solution that fit my setup, so I built and tested one with coding agents. I'm putting the code online so the next person searching for it has a starting point.

It supports right-stick orbit, left-stick pan, trigger zoom, and gamepad-driven selection of Rhino faces/edges/objects. Selection can glide magnetically between parts with vibration feedback, or use a visible crosshair. There's also an optional selection-basket-to-VS-Code voice workflow for people using CLI agents and Rhino MCP, but you don't need any AI features for gamepad navigation.

Tested on an Apple Silicon Mac with Rhino 8 and an 8BitDo Ultimate 2 over Bluetooth and 2.4 GHz. It's an experimental, agent-installable beta and other controllers may need mapping or tuning.

Code and setup: [paste GitHub repo URL]

If you try it, I'd be interested in whether your controller is recognized and how navigation/selection feels.

## Discoverability checklist

- [ ] Create a public repository and paste in the GitHub About description and topics above.
- [ ] Keep the words **Rhino 8 / macOS / gamepad / controller / navigation** in the README's first lines.
- [ ] Publish one short real demonstration (ideally controller and Rhino viewport visible). No stock or generated screenshots.
- [ ] Post the GitHub URL in McNeel Discourse and optionally make a food4Rhino listing.
- [ ] Add an Issues tab with clear labels for compatibility reports and control suggestions.
- [ ] Confirm rights to distribute all contributions/assets before releasing under Unlicense; other dependencies keep their own licenses.
