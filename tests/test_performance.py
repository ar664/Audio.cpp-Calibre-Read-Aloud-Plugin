import importlib
import os
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import test_pronunciation as previous
PACKAGE = previous.PACKAGE

class PerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        previous.WidgetTests.setUpClass()
        cls.app=previous.WidgetTests.app
        cls.p=importlib.import_module(PACKAGE+'.performance')

    def backend(self):
        return types.SimpleNamespace(cfg={'model':'breeze','sample_rate':24000,'channels':1},
                                     paused=False,buffer=bytearray(4800))

    def spin(self,predicate,seconds=3):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(predicate())

    def test_timings_and_generation_speed(self):
        now=[10.0]
        m=self.p.Measurements(lambda:now[0])
        now[0]=10.1; m.health()
        now[0]=10.2; m.request()
        now[0]=10.5; m.chunk(24000)
        now[0]=10.6; m.chunk(24000)
        now[0]=11.2; m.finish()
        self.assertAlmostEqual(m.health_ms,100)
        self.assertAlmostEqual(m.first_ms,500)
        self.assertAlmostEqual(m.ttfa_ms,300)
        self.assertAlmostEqual(m.gap_ms,100)
        self.assertAlmostEqual(m.generation_seconds,1)
        self.assertEqual(m.completed_bytes,48000)
        now[0]=20; m.request()
        now[0]=20.2; m.chunk(48000)
        now[0]=20.5; m.finish()
        self.assertAlmostEqual(m.generation_seconds,1.5)
        self.assertEqual(m.completed,2)
        self.assertEqual(m.first_ms,500)

    def test_gpu_parser_multi_device_na(self):
        text=self.p.gpu_lines('0, RTX 3070, 4096, 8192, 75\n1, Other, N/A, 1000, [Not Supported]')
        self.assertIn('4.00 / 8.00 GiB (50.0%)',text)
        self.assertIn('GPU utilization: 75%',text)
        self.assertIn('GPU 1: Other',text)
        self.assertIn('GPU utilization: N/A',text)
        self.assertEqual(self.p.gpu_lines('error'),'GPU: unavailable')

    @unittest.skipIf(os.name == 'nt', 'Fixture uses a POSIX shebang executable')
    def test_async_gpu_query_and_close(self):
        with tempfile.TemporaryDirectory() as directory:
            exe=Path(directory)/'fake-smi'
            exe.write_text('#!/usr/bin/env python3\nprint("0, RTX 3070, 2048, 8192, 42")\n')
            exe.chmod(0o700)
            overlay=self.p.PerformanceOverlay(self.backend())
            overlay.smi=str(exe)
            overlay.begin()
            self.spin(lambda:'42%' in overlay.gpu)
            self.assertIn('25.0%',overlay.label.text())
            overlay.close()
            self.assertFalse(overlay.timer.isActive())
            self.assertFalse(overlay.running)
            self.assertFalse(overlay.isVisible())

    def test_timeout_and_missing_tool(self):
        overlay=self.p.PerformanceOverlay(self.backend())
        overlay.smi=None
        overlay.begin()
        self.assertEqual(overlay.process.state(),self.p.QProcess.ProcessState.NotRunning)
        overlay.close()
        with tempfile.TemporaryDirectory() as directory:
            exe=Path(directory)/'slow-smi'
            exe.write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n')
            exe.chmod(0o700)
            overlay.smi=str(exe); overlay.begin()
            overlay.timeout.start(30)
            self.spin(lambda:overlay.process.state()==self.p.QProcess.ProcessState.NotRunning)
            self.assertIn('unavailable',overlay.gpu)
            overlay.close()

    def test_settings_default_and_roundtrip(self):
        widget=previous.WidgetTests.config.SettingsWidget()
        widget.mode.setCurrentIndex(1)
        self.assertFalse(widget.performance_overlay.isChecked())
        widget.performance_overlay.setChecked(True)
        self.assertTrue(widget.collect()['performance_overlay'])
        widget.preset_choice.setCurrentIndex(0); widget.use_preset()
        self.assertTrue(widget.performance_overlay.isChecked())
        widget.close()

    def test_disabled_overlay_does_not_construct_ui(self):
        import ast
        from test_pronunciation import SOURCE
        tree=ast.parse((SOURCE/'backend.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AudioCpp')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_performance')
        namespace={}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'backend.py','exec'),namespace)
        backend=self.backend(); backend.overlay=None
        with patch.object(self.p,'PerformanceOverlay') as constructor:
            namespace['_performance'](backend,'begin')
            constructor.assert_not_called()
        self.assertIsNone(backend.overlay)

    def test_system_memory(self):
        memory=self.p.system_memory()
        self.assertIsNotNone(memory)
        used,total=memory
        self.assertGreater(total,0)
        self.assertGreaterEqual(used,0)
        self.assertLessEqual(used,total)

if __name__=='__main__': unittest.main()
