"""Register an internal backend without editing Calibre's installed files.

Import is deferred until Calibre itself imports its TTS types: no QApplication,
GUI imports or server process is created during plugin initialization.
"""
import importlib.abc
import sys

NAME = 'audio.cpp Read Aloud'
ENGINE = 'audiocpp_plugin'
TARGET = 'calibre.gui2.tts.types'
VIEWER = 'calibre.gui2.viewer.ui'


def compatible():
    from calibre.constants import numeric_version
    return tuple(numeric_version[:2]) in ((9, 16), (9, 17))


def enabled():
    from calibre.customize.ui import is_disabled
    return compatible() and not is_disabled(NAME)


def register(module):
    if getattr(module, '_audio_cpp_plugin_registered', False):
        return
    # Be conservative: leave stock TTS alone if the internal interface changes.
    required = ('available_engines', 'create_tts_backend', 'EngineMetadata',
                'TrackingCapability', 'load_config', 'TTSBackend', 'CONFIG_NAME')
    if not compatible() or not all(hasattr(module, name) for name in required):
        return
    original_engines = module.available_engines
    original_factory = module.create_tts_backend
    instances = {}

    def engines():
        result = dict(original_engines())  # Never mutate Calibre's cached dictionary.
        if enabled():
            result[ENGINE] = module.EngineMetadata(
                ENGINE, NAME,
                'Streaming local speech. Configure audio.cpp in Preferences > Plugins.',
                module.TrackingCapability.Sentence,
                allows_choosing_audio_device=False,
                can_synthesize_audio_data=False,
                can_change_pitch=False,
            )
        return result

    def create(force_engine='', config_name=module.CONFIG_NAME):
        selected = force_engine or module.load_config(config_name).get('engine', '')
        if selected == ENGINE and enabled():
            from qt.core import QApplication
            from calibre_plugins.audio_cpp_read_aloud.backend import AudioCpp
            if config_name not in instances:
                instances[config_name] = AudioCpp(ENGINE, QApplication.instance(), config_name=config_name)
            return instances[config_name]
        return original_factory(force_engine, config_name)

    if hasattr(original_engines, 'cache_clear'):
        engines.cache_clear = original_engines.cache_clear
    module.available_engines = engines
    module.create_tts_backend = create
    module._audio_cpp_plugin_registered = True
    # A plugin can also be installed while the TTS settings module is open.
    for name, loaded in tuple(sys.modules.items()):
        if name.startswith('calibre.gui2.tts.') and loaded is not None and loaded is not module:
            if getattr(loaded, 'available_engines', None) is original_engines:
                loaded.available_engines = engines
            if getattr(loaded, 'create_tts_backend', None) is original_factory:
                loaded.create_tts_backend = create


def register_viewer(module):
    viewer = getattr(module, 'EbookViewer', None)
    if viewer is None:
        return False
    if getattr(viewer, '_audio_cpp_startup_hook', False):
        return
    original = viewer.__init__
    def initialize(self, *args, **kwargs):
        original(self, *args, **kwargs)
        from qt.core import QTimer
        def opened():
            if not enabled() or getattr(self, 'shutting_down', False):
                return
            from calibre.gui2.tts.types import create_tts_backend
            backend = create_tts_backend(ENGINE)
            backend.prewarm()
        QTimer.singleShot(0, opened)
    viewer.__init__ = initialize
    viewer._audio_cpp_startup_hook = True
    return True


def defer_viewer_registration():
    # viewer.ui imports customize.ui before defining EbookViewer. Its import is
    # already in flight, so a newly installed finder cannot wrap that loader.
    # Application is constructed later, after viewer.ui has completed importing.
    from calibre.gui2 import Application
    if getattr(Application, '_audio_cpp_application_hook', False):
        return
    original = Application.__init__
    def initialize(self, *args, **kwargs):
        original(self, *args, **kwargs)
        module = sys.modules.get(VIEWER)
        if module is not None:
            register_viewer(module)
    Application.__init__ = initialize
    Application._audio_cpp_application_hook = True


class Loader(importlib.abc.Loader):
    def __init__(self, original):
        self.original = original

    def create_module(self, spec):
        method = getattr(self.original, 'create_module', None)
        return method(spec) if method else None

    def exec_module(self, module):
        self.original.exec_module(module)
        if module.__name__ == VIEWER:
            register_viewer(module)
        else:
            register(module)

    def __getattr__(self, name):
        return getattr(self.original, name)


class Finder(importlib.abc.MetaPathFinder):
    _audio_cpp_finder = True

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in (TARGET, VIEWER):
            return None
        # Preserve Calibre's frozen/extension/zip import machinery.
        for finder in tuple(sys.meta_path):
            if getattr(finder, '_audio_cpp_finder', False):
                continue
            find = getattr(finder, 'find_spec', None)
            spec = find(fullname, path, target) if find else None
            if spec is not None:
                if spec.loader is not None:
                    spec.loader = Loader(spec.loader)
                return spec
        return None


def install():
    if not enabled():
        return
    # Install the engine hook first. Optional prewarming must never prevent
    # the engine from appearing in Read Aloud preferences.
    if not any(getattr(f, '_audio_cpp_finder', False) for f in sys.meta_path):
        sys.meta_path.insert(0, Finder())
    existing = sys.modules.get(TARGET)
    if existing is not None:
        register(existing)
    viewer = sys.modules.get(VIEWER)
    if viewer is not None:
        try:
            if getattr(viewer, 'EbookViewer', None) is not None:
                register_viewer(viewer)
            else:
                defer_viewer_registration()
        except Exception:
            import traceback
            traceback.print_exc()  # Startup diagnostics; engine hook remains installed.
