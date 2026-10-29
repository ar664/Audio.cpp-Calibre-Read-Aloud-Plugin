import copy
import importlib
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'plugin' if (ROOT / 'plugin').is_dir() else ROOT
PACKAGE = 'calibre_plugins.audio_cpp_read_aloud'
parent = types.ModuleType('calibre_plugins'); parent.__path__ = []
sys.modules['calibre_plugins'] = parent
package = types.ModuleType(PACKAGE); package.__path__ = [str(SOURCE)]
sys.modules[PACKAGE] = package
core = importlib.import_module(PACKAGE + '.core')
profiles = importlib.import_module(PACKAGE + '.profiles')

def cfg(*pairs, **kw):
    return dict(pronunciations=[dict(text=a, replacement=b) for a,b in pairs], **kw)

class PronunciationTests(unittest.TestCase):
    def test_word_boundaries_case_and_unicode(self):
        c = cfg(('Ann','An'), ('José','ho ZAY'))
        self.assertEqual(core.apply_pronunciations('ANN Annette José, josé!', c), 'An Annette ho ZAY, ho ZAY!')
        c['pronunciation_case_sensitive'] = True
        self.assertEqual(core.apply_pronunciations('ANN Ann José josé', c), 'ANN An ho ZAY josé')

    def test_longest_literal_non_recursive(self):
        c = cfg(('New','old'), ('New York','NY'), ('NY','city'), ('C++',r'see plus \\ plus'))
        self.assertEqual(core.apply_pronunciations('New York NY New C++',c), r'NY city old see plus \\ plus')

    def test_disabled_and_legacy(self):
        self.assertEqual(core.apply_pronunciations('Hello',{}),'Hello')
        self.assertEqual(core.apply_pronunciations('Ann',cfg(('Ann','An'),pronunciation_enabled=False)),'Ann')

    def test_invalid_entries(self):
        for c in (cfg(('Ann','')), cfg(('','An')), cfg(('Ann','An'),('ANN','Anne')), {'pronunciations':'bad'}):
            with self.assertRaises(ValueError): core.pronunciation_entries(c)

    def test_requests_both_models_reference_untouched(self):
        with tempfile.NamedTemporaryFile(suffix='.wav') as wav:
            for name in ('kokoro','breeze'):
                c=profiles.preset(name); c.update(cfg(('Hermione','her MY oh nee')))
                c.update(breeze_voice_mode='reference', reference_audio=wav.name,
                         reference_text='Hermione is here.', breeze_instruction='Hermione voice')
                before=copy.deepcopy(c)
                body=core.speech_request(c,'Hermione is here.')
                self.assertEqual(body['input'],'her MY oh nee is here.')
                self.assertEqual(c,before)
                if name=='breeze':
                    self.assertEqual(body['reference_text'],'Hermione is here.')
                    self.assertEqual(body['options']['instruct'],'Hermione voice')
                    self.assertNotIn('voice',body)
                else: self.assertEqual(body['options']['voice_id'],'af_heart')

    def test_backend_keeps_original_highlight_positions(self):
        import ast
        import collections
        import json
        from unittest.mock import Mock
        tree=ast.parse((SOURCE/'backend.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AudioCpp')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_synthesize')
        module=ast.Module(body=[method],type_ignores=[])
        namespace=dict(speech_request=core.speech_request, SpeechEvents=core.SpeechEvents, WaveResponse=core.WaveResponse,
                       QNetworkRequest=Mock(), json=json)
        exec(compile(module,'backend.py','exec'),namespace)
        backend=Mock()
        backend.segments=collections.deque([(27,'Hermione arrived.')])
        backend.records=[]; backend.total=0
        backend.cfg=profiles.preset('breeze'); backend.cfg.update(cfg(('Hermione','her MY oh nee')))
        backend.settings.voice_name=''; backend.settings.rate=0
        namespace['_synthesize'](backend)
        sent=json.loads(backend.net.post.call_args.args[1])
        self.assertEqual(sent['input'],'her MY oh nee arrived.')
        self.assertEqual(backend.records[0]['offset'],27)
        self.assertEqual(backend.records[0]['length'],len('Hermione arrived.'))

    def test_profile_switch_preserves_dictionary(self):
        c=profiles.preset('kokoro'); c.update(cfg(('Ann','An')))
        switched=profiles.switch_profile(profiles.switch_profile(c,'breeze'),'kokoro')
        self.assertEqual(switched['pronunciations'],c['pronunciations'])

class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['QT_QPA_PLATFORM']='offscreen'
        from PyQt6 import QtCore, QtGui, QtWidgets
        qt=types.ModuleType('qt'); qt.__path__=[]; sys.modules['qt']=qt
        qcore=types.ModuleType('qt.core')
        for module in (QtCore,QtGui,QtWidgets):
            for name in dir(module): setattr(qcore,name,getattr(module,name))
        sys.modules['qt.core']=qcore
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        calibre=types.ModuleType('calibre'); calibre.__path__=[]; sys.modules['calibre']=calibre
        constants=types.ModuleType('calibre.constants'); constants.config_dir='/tmp'; constants.numeric_version=(9,16,0)
        sys.modules['calibre.constants']=constants
        for name in ('calibre.utils','calibre.utils.config'):
            m=types.ModuleType(name); m.__path__=[]; sys.modules[name]=m
        class JSONConfig(dict):
            data={}
            def __init__(self, name): super().__init__(self.data)
            def __enter__(self): return self
            def __exit__(self,*args): self.data.clear(); self.data.update(copy.deepcopy(self))
        sys.modules['calibre.utils.config'].JSONConfig=JSONConfig
        cls.settings=importlib.import_module(PACKAGE+'.settings')
        cls.config=importlib.import_module(PACKAGE+'.config')

    def test_edit_preview_save_reload_and_switch(self):
        from PyQt6.QtWidgets import QTableWidgetItem
        widget=self.config.SettingsWidget()
        widget.mode.setCurrentIndex(1)
        widget.add_pronunciation()
        widget.pronunciation_table.item(0,0).setText('Hermione')
        widget.pronunciation_table.item(0,1).setText('her MY oh nee')
        widget.pronunciation_input.setText('Hermione arrived.')
        widget.preview_pronunciations()
        self.assertEqual(widget.pronunciation_output.toPlainText(),'her MY oh nee arrived.')
        widget.preset_choice.setCurrentIndex(widget.preset_choice.findData('breeze')); widget.use_preset()
        self.assertEqual(widget.pronunciation_table.item(0,0).text(),'Hermione')
        from unittest.mock import patch
        with patch.object(self.config.QMessageBox, 'information'):
            widget.save()
        reloaded=self.config.SettingsWidget()
        self.assertEqual(reloaded.pronunciation_table.item(0,1).text(),'her MY oh nee')
        self.assertEqual(reloaded.collect()['model'],'breeze')
        reloaded.pronunciation_table.selectRow(0); reloaded.remove_pronunciations()
        self.assertEqual(reloaded.pronunciation_values()['pronunciations'],[])
        widget.close(); reloaded.close()

if __name__ == '__main__': unittest.main()
