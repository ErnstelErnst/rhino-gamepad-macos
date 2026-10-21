# Controller quick reference

Controls depend on SDL mapping and can vary between hardware/modes. Verify with `gamepad_bridge.py --diagnose`.

| Control | Navigation | Targeting |
| --- | --- | --- |
| Left stick | Pan camera | Magnetic glide or move crosshair |
| Right stick | Orbit | Orbit |
| LT / RT | Zoom out/in | Zoom out/in |
| RB | Enter targeting | Exit targeting |
| A | Frame selected geometry | Add/remove highlighted basket item |
| B | — | Undo basket action |
| LB | Precision movement | Precision movement |
| L3 (held) | — | Temporarily pan with left stick |
| R3 | — | Lock/unlock current target |
| Start (+) | — | Toggle magnetic/crosshair selection |
| D-pad | Depends on model context | Cycle/step candidate geometry |
| Y (tap) | Export basket | Export basket |
| Y (hold) | Optional voice capture | Optional voice capture |

Default `PAN_DIST_PER_SEC` is **0.8**, per the latest user preference. Camera signs, haptic settings, and scan parameters are in the Python source and may require calibration for other controllers.
