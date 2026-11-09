"""Build and check the plugin using calibre-debug -e in an isolated config dir.

Does not start audio.cpp or change the user's calibre preferences.
"""
from pathlib import Path
from unittest.mock import patch
import zipfile
import ast

from calibre.constants import numeric_version
from calibre.customize.zipplugin import loader
from qt.core import QApplication

ROOT = Path(__file__).resolve().parent.parent
metadata = ast.parse((ROOT / '__init__.py').read_text(encoding='utf-8'))
plugin_class = next(node for node in metadata.body if isinstance(node, ast.ClassDef))
version = next(ast.literal_eval(node.value) for node in plugin_class.body
               if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'version' for t in node.targets))
build = ROOT / 'build'
build.mkdir(exist_ok=True)
archive = build / ('audio-cpp-read-aloud-' + '.'.join(map(str, version)) + '.zip')
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for path in sorted(ROOT.iterdir()):
        if path.suffix == '.py' or path.name.startswith('plugin-import-name-') or path.name in ('README.md', 'TESTING.md', 'CHANGELOG.md', 'RELEASE.md', 'LICENSE'):
            z.write(path, path.name)
    for path in sorted((ROOT / 'tests').glob('*.py')):
        z.write(path, 'tests/' + path.name)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None

plugin = loader.load(str(archive))(str(archive))
plugin.initialize()
from calibre_plugins.audio_cpp_read_aloud import registration
from calibre.gui2.tts import types

assert (9, 16) <= numeric_version[:2] < (10, 0), numeric_version
for version, expected in (((9, 16, 0), True), ((9, 16, 100), True),
                          ((9, 17, 0), True), ((9, 17, 100), True),
                          ((9, 15, 0), False), ((9, 18, 0), True), ((9, 99, 100), True),
                          ((10, 0, 0), False)):
    with patch('calibre.constants.numeric_version', version):
        assert registration.compatible() == expected, version
        assert (registration.ENGINE in types.available_engines()) == expected, version
engines = types.available_engines()
assert registration.ENGINE in engines
assert len(engines) > 1, 'Stock engines must remain available'
factory = types.create_tts_backend
plugin.initialize()
assert types.create_tts_backend is factory
with patch('calibre.customize.ui.is_disabled', return_value=True):
    assert registration.ENGINE not in types.available_engines()

app = QApplication([])
backend = factory(registration.ENGINE)
assert isinstance(backend, types.TTSBackend)
assert factory(registration.ENGINE) is backend
assert backend.server.process is None
from calibre_plugins.audio_cpp_read_aloud.config import SettingsWidget
widget = SettingsWidget()
from calibre_plugins.audio_cpp_read_aloud.model_catalog import CATALOG
from calibre_plugins.audio_cpp_read_aloud.profiles import preset
assert widget.preset_choice.count() == len(CATALOG)
from calibre_plugins.audio_cpp_read_aloud.core import CLONED_VOICE, PLUGIN_VOICE
backend.cfg = preset('ming3_tts')
voices = {v.name: v.human_name for v in backend.available_voices['']}
assert voices[CLONED_VOICE] == 'Cloned voice (reference recording)'
assert voices[PLUGIN_VOICE] == 'Use plugin voice settings'
assert set(backend.cfg['voices']).issubset(voices)
backend.cfg = preset('kokoro')
assert CLONED_VOICE not in {v.name for v in backend.available_voices['']}
for family in CATALOG:
    widget._populate(preset(family))
    widget._ownership_changed()
# Synthetic multiple GPUs: selection is backend-specific and persists on the
# active model without changing other models or the server's default device.
cfg = preset('kokoro')
cfg['server_settings']['backend'] = 'cuda'
cfg['server_settings']['device'] = 3
model = cfg['server_settings']['models'][0]
model.pop('backend', None)
model['device'] = 1
cfg['server_settings']['models'].append(dict(model, id='other', device=7))
widget._populate(cfg)
widget.detected_devices = [('cuda', 0, 'GPU A'), ('cuda', 1, 'GPU B'), ('vulkan', 0, 'Vulkan GPU')]
widget.refresh_device_choices()
assert widget.device.value() == 1
assert widget.device_choices.currentText() == '1: GPU B'
widget.device_choices.setCurrentIndex(widget.device_choices.findData(0))
widget.choose_device()
saved = widget._draft()
assert saved['server_settings']['models'][0]['device'] == 0
assert saved['server_settings']['models'][1]['device'] == 7
assert saved['server_settings']['device'] == 3
widget._populate(saved)
assert widget.device.value() == 0
widget.compute.setCurrentText('vulkan')
assert widget.device_choices.count() == 2
widget.compute.setCurrentText('cpu')
assert not widget.device_row.isEnabled()
widget.mode.setCurrentIndex(1)
widget._ownership_changed()
assert not widget.device_row.isEnabled()
# collect() also rebuilds server JSON: verify that path retains the choice.
cfg['executable'] = __file__
cfg['server_settings']['models'][0]['path'] = __file__
cfg['reference_audio'] = ''
cfg['breeze_voice_mode'] = 'design'
widget._populate(cfg)
widget.device.setValue(2)
assert widget.collect()['server_settings']['models'][0]['device'] == 2
widget.close()
backend.shutdown()
backend.config_timer.stop()
print('PASS: calibre', numeric_version, 'ZIP loading, version/disable guards,')
print('stock engines, idempotent registration, backend construction and settings UI')
print('Archive:', archive)
