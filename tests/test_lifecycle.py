import ast
import base64
import copy
import importlib
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch
import test_pronunciation as previous

class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        previous.WidgetTests.setUpClass()
        cls.app=previous.WidgetTests.app
        from PyQt6 import QtMultimedia, QtNetwork, QtCore, QtTextToSpeech
        q=sys.modules['qt.core']
        for module in (QtMultimedia,QtNetwork,QtTextToSpeech):
            for name in dir(module): setattr(q,name,getattr(module,name))
        for name in ('calibre.gui2','calibre.gui2.tts','calibre.spell'):
            m=types.ModuleType(name); m.__path__=[];sys.modules[name]=m
        t=types.ModuleType('calibre.gui2.tts.types')
        class Base(QtCore.QObject):
            state_changed=QtCore.pyqtSignal(object)
            saying=QtCore.pyqtSignal(int,int)
            def __init__(self,engine,parent): super().__init__(parent)
        t.TTSBackend=Base
        t.EngineSpecificSettings=types.SimpleNamespace(create_from_config=lambda *a:types.SimpleNamespace(voice_name='',rate=0,volume=1))
        t.Voice=lambda **kwargs:kwargs
        sys.modules[t.__name__]=t
        split=types.ModuleType('calibre.spell.break_iterator')
        split.PARAGRAPH_SEPARATOR='\u2029'
        split.split_into_sentences_for_tts=lambda text,lang:[(0,text)]
        sys.modules[split.__name__]=split
        cls.backend=importlib.import_module(previous.PACKAGE+'.backend')

    def spin(self,predicate):
        deadline=time.monotonic()+3
        while not predicate() and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.005)
        self.assertTrue(predicate())

    def test_silent_prewarm_keep_loaded_and_live_reload(self):
        bodies=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a): pass
            def do_GET(self):
                self.send_response(200);self.end_headers();self.wfile.write(b'{}')
            def do_POST(self):
                bodies.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                for event in ({'type':'speech.audio.delta','audio':base64.b64encode(b'\0'*4800).decode()}, {'type':'speech.audio.done'}):
                    self.wfile.write(b'data: '+json.dumps(event).encode()+b'\n\n')
                self.wfile.write(b'data: [DONE]\n\n')
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        config=copy.deepcopy(previous.WidgetTests.settings.DEFAULTS)
        config.update(prewarm_on_open=True,keep_loaded_while_open=True)
        owned=[]
        class Server:
            process=None
            def __init__(self,cfg): self.closed=0;owned.append(self)
            def start(self): return 'http://127.0.0.1:'+str(http.server_port)
            def close(self): self.closed+=1
        try:
            with patch.object(self.backend,'OwnedServer',Server),patch.object(self.backend,'load_plugin_settings',side_effect=lambda:copy.deepcopy(config)):
                b=self.backend.AudioCpp(parent=self.app)
                marks=[]; b.saying.connect(lambda *v:marks.append(v))
                b.prewarm();self.spin(lambda:not b.active)
                self.assertEqual(len(bodies),1)
                self.assertEqual(bodies[0]['input'],'Ready.')
                self.assertIsNone(b.sink)
                self.assertEqual(marks,[])
                self.assertEqual(len(b.buffer),0)
                self.assertFalse(b.idle.isActive())
                first=b.server
                b.stop();self.assertEqual(first.closed,0)
                b.active=True;config['voice']='michael'
                b._check_settings();self.assertEqual(b.cfg['voice'],'heart')
                b.active=False; b._check_settings()
                self.assertEqual(first.closed,1)
                self.assertEqual(b.cfg['voice'],'michael')
                self.spin(lambda:not b.active)
                b.shutdown();self.assertGreater(b.server.closed,0)
                b.config_timer.stop()
        finally: http.shutdown();http.server_close()

    def test_mutex_prevents_second_start_releases_on_failure(self):
        lock=types.ModuleType('calibre.utils.lock')
        held=[False]
        def acquire(name):
            if held[0]: return None
            held[0]=True
            def release(): held[0]=False
            return release
        lock.create_single_instance_mutex=acquire
        with patch.dict(sys.modules,{'calibre.utils.lock':lock}):
            first=previous.core.OwnedServer({});second=previous.core.OwnedServer({})
            with patch.object(first,'_launch',return_value='local'),patch.object(second,'_launch',return_value='local') as launch:
                first.start()
                with self.assertRaisesRegex(RuntimeError,'another ebook viewer'): second.start()
                launch.assert_not_called()
                first.close();second.start();launch.assert_called_once();second.close()
            with patch.object(first,'_launch',side_effect=ValueError('bad model')):
                with self.assertRaises(ValueError): first.start()
            self.assertFalse(held[0])

    def test_partial_viewer_import_keeps_engine_and_defers_hook(self):
        registration=importlib.import_module(previous.PACKAGE+'.registration')
        module=types.ModuleType(registration.VIEWER)  # In sys.modules, class not defined yet.
        engine=types.ModuleType(registration.TARGET)
        engine.CONFIG_NAME='tts'
        engine.available_engines=lambda:{'stock': 'stock engine'}
        engine.create_tts_backend=lambda *args:'stock backend'
        engine.EngineMetadata=lambda *args,**kw:args[0]
        engine.TrackingCapability=types.SimpleNamespace(Sentence='sentence')
        engine.load_config=lambda *args:{}
        engine.TTSBackend=object
        class Application:
            def __init__(self): self.initialized=True
        gui=types.ModuleType('calibre.gui2');gui.Application=Application
        before=list(sys.meta_path)
        try:
            with patch.dict(sys.modules,{registration.VIEWER:module,registration.TARGET:engine,'calibre.gui2':gui}), patch.object(registration,'enabled',return_value=True), patch.object(registration,'compatible',return_value=True):
                registration.install()
                registration.install()
                self.assertIn('audiocpp_plugin',engine.available_engines())
                self.assertEqual(engine.create_tts_backend('stock'),'stock backend')
                self.assertEqual(sum(isinstance(f,registration.Finder) for f in sys.meta_path),1)
                class Viewer:
                    def __init__(self): self.shutting_down=False
                module.EbookViewer=Viewer
                app=Application()
                self.assertTrue(app.initialized)
                self.assertTrue(Viewer._audio_cpp_startup_hook)
                engine.create_tts_backend=Mock()
                viewer=Viewer()
                self.app.processEvents()
                engine.create_tts_backend.return_value.prewarm.assert_called_once()
        finally: sys.meta_path[:]=before

    def test_optional_startup_failure_does_not_remove_engine(self):
        registration=importlib.import_module(previous.PACKAGE+'.registration')
        before=list(sys.meta_path)
        try:
            with patch.dict(sys.modules,{registration.VIEWER:types.ModuleType(registration.VIEWER)}), patch.object(registration,'enabled',return_value=True), patch.object(registration,'defer_viewer_registration',side_effect=RuntimeError('startup hook failed')), patch('traceback.print_exc') as diagnostic:
                registration.install()
                self.assertTrue(any(isinstance(f,registration.Finder) for f in sys.meta_path))
                diagnostic.assert_called_once()
        finally: sys.meta_path[:]=before

    def test_viewer_hook_idempotent_and_deferred(self):
        registration=importlib.import_module(previous.PACKAGE+'.registration')
        class Viewer:
            def __init__(self): self.shutting_down=False
        module=types.SimpleNamespace(EbookViewer=Viewer)
        t=sys.modules['calibre.gui2.tts.types'];t.create_tts_backend=Mock()
        with patch.object(registration,'enabled',return_value=True):
            registration.register_viewer(module);registration.register_viewer(module)
            viewer=Viewer()
            t.create_tts_backend.assert_not_called()
            self.app.processEvents()
            t.create_tts_backend.assert_called_once_with('audiocpp_plugin')
            t.create_tts_backend.return_value.prewarm.assert_called_once()

if __name__=='__main__': unittest.main()
