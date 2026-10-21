"""Isolated runtime tests of v0.5.4 scheduling methods without loading Rhino.

These verify startup/fallback/callback lifecycle, not real macOS event cadence.
"""
import ast
import pathlib
import sys
import types
import time
import unittest
from unittest import mock


class Event:
    def __init__(self):
        self.callbacks = []
    def __iadd__(self, fn):
        self.callbacks.append(fn)
        return self
    def __isub__(self, fn):
        self.callbacks.remove(fn)
        return self


class FakeTimer:
    def __init__(self):
        self.Elapsed = Event()
        self.Interval = None
        self.started = False
        self.stopped = False
    def Start(self):
        self.started = True
    def Stop(self):
        self.stopped = True


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.notes = []
        self.app = types.SimpleNamespace(Idle=Event())
        self.rhino = types.SimpleNamespace(RhinoApp=self.app)
        self.sticky = {}
        self.timer_instances = []
        test = self
        def create_timer():
            timer = FakeTimer()
            test.timer_instances.append(timer)
            return timer
        self.eto = types.ModuleType('Eto')
        self.eto_forms = types.ModuleType('Eto.Forms')
        self.eto_forms.UITimer = create_timer
        self.eto.Forms = self.eto_forms
        self.mock_modules = mock.patch.dict(sys.modules, {'Eto': self.eto, 'Eto.Forms': self.eto_forms})
        self.mock_modules.start()

        # Compile exact production scheduling methods into a tiny test class.
        path = pathlib.Path(__file__).with_name('rhino_gamepad_toggle.py')
        source = ast.parse(path.read_text(encoding='utf-8'))
        appclass = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'RhinoGamepad')
        names = {'start','stop','on_idle','on_timer','on_scheduler_tick'}
        funcs = [n for n in appclass.body if isinstance(n, ast.FunctionDef) and n.name in names]
        cls = ast.ClassDef(name='SchedulerUnderTest', bases=[], keywords=[], body=funcs, decorator_list=[])
        scope = dict(Rhino=self.rhino, time=time, feedback=self.notes.append,
                     CAMERA_SCHEDULER='eto', TARGET_CAMERA_HZ=60.0,
                     sc=types.SimpleNamespace(sticky=self.sticky), KEY='test_key')
        code = compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), 'exec')
        exec(code, scope)
        self.Cls = scope['SchedulerUnderTest']
        self.globals = scope

    def tearDown(self):
        self.mock_modules.stop()

    def controller(self):
        c = self.Cls()
        c.running = False
        c.scheduler = None
        c.timer = None
        c.handler = c.on_idle
        c.timer_handler = c.on_timer
        c.picker = types.SimpleNamespace(close=lambda doc: None)
        c.basket = types.SimpleNamespace(reset=lambda: None)
        c.document = None
        c.sock = types.SimpleNamespace(close=lambda: None)
        c.pending_basket_press = None
        c.last_tick = None
        c.update_called = 0
        def update():
            c.update_called += 1
        c.update = update
        return c

    def test_starts_timer_on_ui_and_stops(self):
        c = self.controller()
        c.start()
        self.assertEqual(c.scheduler, 'eto')
        self.assertAlmostEqual(c.timer.Interval, 1 / 60)
        self.assertTrue(c.timer.started)
        self.assertEqual(len(c.timer.Elapsed.callbacks), 1)
        self.assertFalse(self.app.Idle.callbacks)
        c.on_timer(None, None)
        self.assertEqual(c.update_called, 1)
        t = c.timer
        c.stop()
        self.assertTrue(t.stopped)
        self.assertEqual(t.Elapsed.callbacks, [])
        c.on_timer(None,None)
        self.assertEqual(c.update_called, 1)

    def test_eager_idle_fallback_when_timer_unavailable(self):
        c = self.controller()
        def fail():
            raise RuntimeError('timer unavailable')
        self.eto_forms.UITimer = fail
        c.start()
        self.assertEqual(c.scheduler, 'idle')
        self.assertEqual(len(self.app.Idle.callbacks), 1)
        c.on_idle(None, None)
        self.assertEqual(c.update_called, 1)
        c.stop()
        self.assertFalse(self.app.Idle.callbacks)

    def test_forced_idle_comparison_mode(self):
        self.globals['CAMERA_SCHEDULER']='idle'
        c = self.controller()
        c.start()
        self.assertEqual(c.scheduler, 'idle')
        self.assertFalse(self.timer_instances)
        c.stop()
        self.assertFalse(self.app.Idle.callbacks)

    def test_runtime_error_stops_listener_and_detaches_timer(self):
        c = self.controller()
        c.start()
        self.sticky['test_key'] = c
        def fail():
            raise ValueError('bad update')
        c.update = fail
        timer = c.timer
        c.on_timer(None,None)
        self.assertTrue(timer.stopped)
        self.assertEqual(timer.Elapsed.callbacks, [])
        self.assertNotIn('test_key', self.sticky)
        self.assertFalse(c.running)


if __name__ == '__main__':
    unittest.main()
