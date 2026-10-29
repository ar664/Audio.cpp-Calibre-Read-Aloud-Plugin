from calibre.customize.zipplugin import loader
loader.load('audio-cpp-read-aloud-0.9.9.zip')
from qt.core import QApplication,QPoint
from calibre_plugins.audio_cpp_read_aloud.config import SettingsWidget
app=QApplication([])
w=SettingsWidget()
w.tabs.setCurrentIndex(next(i for i in range(w.tabs.count()) if w.tabs.tabText(i)=='Advanced'))
w.resize(1000,800)
w.show()
for _ in range(10): app.processEvents()
content=w.tabs.currentWidget().widget()
fields=(w.language,w.sample_rate,w.channels,w.options)
before=[x.mapTo(content,QPoint()).y() for x in fields]
w.resize(1000,1100)
for _ in range(10): app.processEvents()
after=[x.mapTo(content,QPoint()).y() for x in fields]
assert before==after,(before,after)
assert abs(w.options.width()-w.server_json.width())<2
w.close()
print('PASS: controls remain grouped when resized; JSON editors align at full width')
