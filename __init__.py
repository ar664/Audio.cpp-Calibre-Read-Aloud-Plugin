"""audio.cpp Read Aloud. GPL-3.0-or-later."""
from calibre.customize import InterfaceActionBase


class AudioCppReadAloud(InterfaceActionBase):
    name = 'audio.cpp Read Aloud'
    description = 'Local Read Aloud with audio.cpp GGUF speech models'
    author = 'OpenAI'
    version = (1, 0, 0)
    minimum_calibre_version = (9, 16, 0)
    supported_platforms = ['windows', 'linux', 'osx']
    actual_plugin = 'calibre_plugins.audio_cpp_read_aloud.action:AudioCppAction'

    def initialize(self):
        from calibre_plugins.audio_cpp_read_aloud.registration import install
        install()

    def config_widget(self):
        from calibre_plugins.audio_cpp_read_aloud.config import SettingsWidget
        return SettingsWidget()

    def is_customizable(self):
        return True

    def save_settings(self, widget):
        widget.save()
