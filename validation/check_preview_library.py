"""Check library draft persistence and preview configuration using real Calibre Qt."""
import copy
from pathlib import Path
from unittest.mock import patch
from calibre.customize.zipplugin import loader
from qt.core import QApplication
ROOT = Path(__file__).resolve().parent.parent
loader.load(str(ROOT / 'audio-cpp-read-aloud-0.9.1.zip'))
from calibre_plugins.audio_cpp_read_aloud import config, backend
from calibre_plugins.audio_cpp_read_aloud.profiles import preset, switch_profile
app = QApplication([])
w = config.SettingsWidget()
w.reference_audio.setText(str(ROOT / 'Sample.wav'))
w.reference_text.setPlainText('Reference words')
with patch.object(config.QInputDialog, 'getText', return_value=('Narrator', True)):
    w.save_reference_voice()
saved = copy.deepcopy(w.values['reference_voices'])
w.reference_audio.clear()
w.load_reference_voice()
assert w.reference_audio.text() == str((ROOT/'Sample.wav').resolve())
assert w.reference_text.toPlainText() == 'Reference words'
assert w.breeze_mode.currentData() == 'reference'
draft = w._draft()
assert switch_profile(draft, 'ming3_tts')['reference_voices'] == saved
other = config.SettingsWidget()
other._populate(draft)
assert other.saved_voices.currentText() == 'Narrator'
other.remove_reference_voice()
assert not other.values['reference_voices']
assert w.values['reference_voices'] == saved
cfg = preset('ming3_tts')
cfg.update(mode='external', base_url='http://127.0.0.1:8080')
b = backend.AudioCpp(parent=w, preview_config=cfg)
b.config_timer.stop()
with patch.object(backend, 'load_plugin_settings', side_effect=AssertionError('Preview read live settings')):
    b._check_settings()
    b.reload_after_configure()
assert b.cfg is cfg
w.preview_backend = b
w.stop_voice_preview()
assert not b.active
b.shutdown()
other.close()
w.close()
print('PASS: reference save/load/remove, draft isolation, cross-preset persistence, preview config isolation and stop')
