"""Main-window access to audio.cpp preferences."""
from calibre.gui2.actions import InterfaceAction
from qt.core import QDialog, QDialogButtonBox, QVBoxLayout, QToolBar, QPixmap, QPainter, QPen, QColor, QIcon, Qt


def toolbar_icon():
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#187d9b'))
    painter.drawRoundedRect(8, 8, 112, 112, 24, 24)
    painter.setPen(QPen(QColor('white'), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for x, height in ((32, 22), (48, 44), (64, 70), (80, 44), (96, 22)):
        painter.drawLine(x, 64-height//2, x, 64+height//2)
    painter.end()
    return QIcon(pixmap)


class AudioCppAction(InterfaceAction):
    name = 'audio.cpp Plugin'
    action_spec = ('audio.cpp settings', 'config.png', 'Configure audio.cpp Read Aloud', None)

    def genesis(self):
        self.qaction.setIcon(toolbar_icon())
        self.qaction.setText('Audio.cpp Read Aloud')
        self.qaction.triggered.connect(self.show_settings)

    def initialization_complete(self):
        existing = self.gui.findChildren(QToolBar)
        self.toolbar = QToolBar(self.gui)
        self.toolbar.setWindowTitle('audio.cpp Read Aloud')
        self.toolbar.setObjectName('audio_cpp_settings_toolbar')
        self.toolbar.addAction(self.qaction)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        if existing:
            self.toolbar.setIconSize(existing[0].iconSize())
            existing[0].iconSizeChanged.connect(self.toolbar.setIconSize)
        self.gui.addToolBar(self.toolbar)

    def show_settings(self):
        from calibre_plugins.audio_cpp_read_aloud.config import SettingsWidget
        from calibre_plugins.audio_cpp_read_aloud import settings
        dialog = QDialog(self.gui)
        dialog.setWindowTitle('audio.cpp Read Aloud settings')
        layout = QVBoxLayout(dialog)
        widget = SettingsWidget(dialog)
        layout.addWidget(widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)
        def save():
            if widget.validate():
                settings.save(widget.collect())
                dialog.accept()
        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        dialog.resize(1000, 860)
        dialog.exec()
