"""Run with calibre-debug -e in an isolated configuration (no model loading)."""
from pathlib import Path
import time

from calibre.customize.zipplugin import loader
from qt.core import QApplication

ROOT = Path(__file__).resolve().parent.parent
archive = ROOT / 'build/audio-cpp-read-aloud-1.1.0.zip'
plugin = loader.load(str(archive))(str(archive))
app = QApplication([])
from calibre_plugins.audio_cpp_read_aloud.config import SettingsWidget
from calibre_plugins.audio_cpp_read_aloud.profiles import preset

widget = SettingsWidget()
cfg = preset('kokoro')
cfg['executable'] = str(ROOT / 'bin/audiocpp_server.exe')
cfg['server_settings']['backend'] = 'cuda'
widget._populate(cfg)
widget.detect_devices()
deadline = time.monotonic() + 20
while widget.device_process is not None and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(.01)
assert widget.device_process is None, 'Device discovery did not finish'
assert ('cuda', 0, 'NVIDIA GeForce RTX 3070') in widget.detected_devices
assert widget.device_choices.findData(0) > 0
widget.device_choices.setCurrentIndex(widget.device_choices.findData(0))
widget.choose_device()
assert widget._draft()['server_settings']['models'][0]['device'] == 0
print('PASS: real audio.cpp discovery:', widget.detected_devices)
widget.close()
