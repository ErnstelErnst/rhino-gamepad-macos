"""Offline tests: no Rhino, macOS, gamepad, or SDL shared library required."""
import ast
import math
import pathlib
import subprocess
import time
import types
import unittest
from unittest.mock import Mock

from gamepad_bridge import (
    ForegroundDetector, CameraArmingGate, choose_mode, controls_neutral,
    is_rhino, AXES, BUTTONS,
)

# Read functions/constants from the actual Rhino script while avoiding a Rhino
# dependency.  They are executed with the same default constants as shipped.
SCRIPT = pathlib.Path(__file__).resolve().parent / "rhino_gamepad_toggle.py"
AST = ast.parse(SCRIPT.read_text(encoding="utf-8"))
CONSTANTS = {}
for item in AST.body:
    if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
        try:
            CONSTANTS[item.targets[0].id] = ast.literal_eval(item.value)
        except (ValueError, TypeError):
            pass
FUNCTIONS = [n for n in AST.body if isinstance(n, ast.FunctionDef)
             and n.name in ("shaped_stick", "shaped_trigger")]
math_ns = {"math": math, **CONSTANTS}
exec(compile(ast.fix_missing_locations(ast.Module(body=FUNCTIONS, type_ignores=[])), str(SCRIPT), "exec"), math_ns)


class CameraMathTests(unittest.TestCase):
    def test_deadzone_and_center(self):
        self.assertEqual(math_ns["shaped_stick"](0, 0), (0, 0))
        self.assertEqual(math_ns["shaped_stick"](0.11, 0), (0, 0))

    def test_full_deflection_and_diagonals(self):
        shape = math_ns["shaped_stick"]
        self.assertAlmostEqual(shape(1, 0)[0], 1)
        self.assertAlmostEqual(math.hypot(*shape(.6, .8)), 1)
        self.assertLess(shape(.2, 0)[0], .2)

    def test_non_finite_axes(self):
        shape = math_ns["shaped_stick"]
        self.assertEqual(shape(float("nan"), 0), (0.0, 0.0))
        self.assertEqual(shape(float("inf"), 1), (0.0, 0.0))

    def test_triggers(self):
        shape = math_ns["shaped_trigger"]
        self.assertEqual(shape(.03), 0)
        self.assertEqual(shape(float("nan")), 0)
        self.assertAlmostEqual(shape(1), 1)

    def test_known_good_axis_signs(self):
        """Regression guard: these are user-confirmed directional defaults."""
        # AST literal_eval cannot directly parse unary +/-; check semantic code
        # via AST execution of only the four constant assignments.
        wanted = ("ORBIT_YAW_SIGN", "ORBIT_ELEVATION_SIGN",
                  "PAN_HORIZONTAL_SIGN", "PAN_VERTICAL_SIGN")
        assignments = [n for n in AST.body if isinstance(n, ast.Assign)
                       and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                       and n.targets[0].id in wanted]
        local = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=assignments, type_ignores=[])), str(SCRIPT), "exec"), local)
        self.assertEqual(tuple(local[k] for k in wanted), (-1.0, 1.0, 1.0, -1.0))

    def test_camera_code_uses_sign_settings(self):
        camera_class = next(n for n in AST.body if isinstance(n, ast.ClassDef)
                            and n.name == "RhinoGamepad")
        # v0.4.2 extracts camera math into move_camera for shared use in
        # camera and selection modes; ensure the settings still drive it.
        camera_fn = next(n for n in camera_class.body if isinstance(n, ast.FunctionDef)
                         and n.name == "move_camera")
        referenced = {n.id for n in ast.walk(camera_fn) if isinstance(n, ast.Name)}
        self.assertTrue({"ORBIT_YAW_SIGN", "ORBIT_ELEVATION_SIGN",
                         "PAN_HORIZONTAL_SIGN", "PAN_VERTICAL_SIGN"}.issubset(referenced))

    def test_unmodified_speed_profile(self):
        self.assertEqual(CONSTANTS["PRECISION_FACTOR"], .25)
        self.assertEqual(CONSTANTS["STICK_DEADZONE"], .13)
        self.assertEqual(CONSTANTS["STICK_EXPONENT"], 1.7)


class BridgeModeTests(unittest.TestCase):
    def setUp(self):
        self.neutral_axes = {key: 0.0 for key in AXES}
        self.neutral_buttons = {key: False for key in BUTTONS}

    def test_rhino_only_in_foreground(self):
        self.assertTrue(is_rhino("Rhino 8"))
        self.assertTrue(is_rhino("Rhinoceros"))
        self.assertFalse(is_rhino("Terminal"))
        self.assertEqual(choose_mode(True, {}, "Rhino 8"), "rhino")
        self.assertEqual(choose_mode(True, {}, "Safari"), "inactive")
        self.assertEqual(choose_mode(True, {}, ""), "inactive")
        self.assertEqual(choose_mode(False, {}, "Rhino 8"), "inactive")

    def test_explicit_desktop_context(self):
        self.assertEqual(choose_mode(True, {"back": True}, "Rhino 8"), "desktop")
        self.assertEqual(choose_mode(True, {"back": True}, "Safari"), "desktop")
        self.assertEqual(choose_mode(False, {"back": True}, "Rhino 8"), "inactive")

    def test_initial_neutral_gate(self):
        gate = CameraArmingGate()
        axes = dict(self.neutral_axes, rx=.5)
        self.assertFalse(gate.allow("rhino", axes, self.neutral_buttons))
        self.assertFalse(gate.allow("rhino", self.neutral_axes, self.neutral_buttons))
        self.assertTrue(gate.allow("rhino", axes, self.neutral_buttons))

    def test_rearm_after_desktop_and_focus_change(self):
        gate = CameraArmingGate()
        self.assertFalse(gate.allow("rhino", self.neutral_axes, self.neutral_buttons))
        self.assertTrue(gate.allow("rhino", self.neutral_axes, self.neutral_buttons))
        self.assertFalse(gate.allow("desktop", self.neutral_axes, self.neutral_buttons))
        self.assertFalse(gate.allow("rhino", dict(self.neutral_axes, rt=.7), self.neutral_buttons))
        self.assertFalse(gate.allow("rhino", self.neutral_axes, self.neutral_buttons))
        self.assertTrue(gate.allow("rhino", self.neutral_axes, self.neutral_buttons))
        self.assertFalse(gate.allow("inactive", self.neutral_axes, self.neutral_buttons))
        self.assertFalse(gate.allow("rhino", self.neutral_axes, self.neutral_buttons))

    def test_neutral_requires_button_release(self):
        self.assertTrue(controls_neutral(self.neutral_axes, self.neutral_buttons))
        self.assertFalse(controls_neutral(self.neutral_axes, dict(self.neutral_buttons, a=True)))
        self.assertFalse(controls_neutral(dict(self.neutral_axes, lx=.2), self.neutral_buttons))
        self.assertFalse(controls_neutral(dict(self.neutral_axes, lt=.3), self.neutral_buttons))
        self.assertFalse(controls_neutral(dict(self.neutral_axes, rx="bogus"), self.neutral_buttons))


class FocusTests(unittest.TestCase):
    def test_applescript_fallback_success_and_cache(self):
        runner = Mock(return_value=types.SimpleNamespace(returncode=0, stdout="Rhinoceros\n", stderr=""))
        detector = ForegroundDetector(interval_seconds=0.25, run_command=runner, autoload=False)
        # Unit tests run on Linux, where AppKit isn't importable.
        self.assertEqual(detector.provider, "osascript")
        first = time.monotonic()
        self.assertEqual(detector.current(first), "Rhinoceros")
        self.assertEqual(detector.current(first), "Rhinoceros")
        runner.assert_called_once()
        self.assertEqual(detector.current(first + 1), "Rhinoceros")
        self.assertEqual(runner.call_count, 2)
        self.assertIn("System Events", runner.call_args.args[0][2])

    def test_applescript_nonzero_fails_closed(self):
        runner = Mock(return_value=types.SimpleNamespace(returncode=1, stdout="", stderr="Not authorized"))
        detector = ForegroundDetector(run_command=runner, autoload=False)
        self.assertEqual(detector.current(time.monotonic()), "")
        self.assertIn("Not authorized", detector.last_error)
        self.assertEqual(choose_mode(True, {}, detector.cached_name), "inactive")

    def test_applescript_timeout_fails_closed(self):
        runner = Mock(side_effect=subprocess.TimeoutExpired("osascript", 0.8))
        detector = ForegroundDetector(run_command=runner, autoload=False)
        self.assertEqual(detector.current(time.monotonic()), "")
        self.assertIn("osascript", detector.last_error)

    def test_pyobjc_provider_priority_and_failure(self):
        app = Mock()
        app.localizedName.return_value = "Rhino 8"
        workspace = Mock()
        workspace.frontmostApplication.return_value = app
        runner = Mock()
        detector = ForegroundDetector(workspace=workspace, run_command=runner)
        self.assertEqual(detector.provider, "PyObjC")
        self.assertEqual(detector.current(time.monotonic()), "Rhino 8")
        runner.assert_not_called()
        workspace.frontmostApplication.side_effect = RuntimeError("testing error")
        self.assertEqual(detector.current(time.monotonic() + 2), "")
        self.assertIn("AppKit", detector.last_error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
