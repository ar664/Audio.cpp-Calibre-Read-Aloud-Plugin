"""Calibre plugin preferences. Does not launch an audio server."""
import copy
import math
import json
import os
import shutil
import subprocess
from pathlib import Path

from qt.core import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QProcess, QPushButton, QSpinBox,
    QTabWidget, QTimer, QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QTreeView, QStandardItemModel, QStandardItem, Qt, QAbstractItemView, QSizePolicy,
    QSortFilterProxyModel,
    QInputDialog, QScrollArea,
)
from calibre_plugins.audio_cpp_read_aloud import settings
from calibre_plugins.audio_cpp_read_aloud.core import local_url, model_family, apply_pronunciations, pronunciation_entries
from calibre_plugins.audio_cpp_read_aloud.profiles import kokoro_server, profile_name, switch_profile
from calibre_plugins.audio_cpp_read_aloud.model_catalog import CATALOG
from calibre_plugins.audio_cpp_read_aloud.registration import compatible


ESPEAK_IMPLICIT_FAMILIES = {'kokoro_tts', 'kitten_tts2'}


def espeak_option_names(family, groups=('request', 'session', 'load')):
    options = CATALOG.get(family, {}).get('options', {})
    return {option.get('name', '') for group in groups for option in options.get(group, [])
            if 'espeak' in option.get('name', '').casefold()}


def model_needs_espeak(family):
    return family in ESPEAK_IMPLICIT_FAMILIES or bool(espeak_option_names(family))


def preset_features(family, spec):
    features = [mode.capitalize() for mode in spec.get('modes', [])]
    options = {o['name'] for group in spec.get('options', {}).values() for o in group}
    if spec.get('voices'):
        features.append('Built-in voices')
    if options & {'reference_text', 'reference_cache_slots', 'multi_reference_cond'}:
        features.append('Reference conditioning')
    if options & {'instruct', 'instruction', 'voice_description', 'description'}:
        features.append('Voice instructions')
    if len(spec.get('languages', [])) > 1:
        features.append('Multilingual')
    if 'speed' in options:
        features.append('Speed control')
    if model_needs_espeak(family):
        features.append('Requires eSpeak')
    return ', '.join(features) or 'See Model help'


class GrowingTextEdit(QPlainTextEdit):
    """Size to rendered lines, with a scrollable limit for long input."""
    minimum_lines = 2
    maximum_lines = 12

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._fit_contents)
        self.textChanged.connect(self._schedule_fit)
        self.document().documentLayout().documentSizeChanged.connect(self._schedule_fit)
        self._schedule_fit()

    def _schedule_fit(self, *unused):
        self._resize_timer.start(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_resize_timer'):
            self._schedule_fit()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_fit()

    def _fit_contents(self):
        line_height = self.fontMetrics().lineSpacing()
        limit = line_height * self.maximum_lines
        document = self.document()
        layout = document.documentLayout()
        height = 0
        block = document.begin()
        while block.isValid() and height < limit:
            # QPlainTextDocumentLayout.documentSize().height() counts lines,
            # not pixels. Block rectangles account for wrapping and font size.
            height += layout.blockBoundingRect(block).height()
            block = block.next()
        margins = self.contentsMargins()
        padding = 2 * document.documentMargin() + margins.top() + margins.bottom() + 4
        target = math.ceil(min(limit, max(self.minimum_lines * line_height, height)) + padding)
        if self.minimumHeight() != target or self.maximumHeight() != target:
            self.setFixedHeight(target)


class GrowingTextField(GrowingTextEdit):
    """A single logical value displayed across as many wrapped lines as needed."""
    minimum_lines = 1
    maximum_lines = 4

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setTabChangesFocus(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self.setPlainText(' '.join(str(text).splitlines()))

    def insertFromMimeData(self, source):
        self.insertPlainText(' '.join(source.text().strip().splitlines()))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.focusNextChild()
            return
        super().keyPressEvent(event)


class SettingsWidget(QWidget):
    validate_before_accept = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = settings.load()
        self.detector = None
        self.preview_backend = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)
        self.setObjectName('audioCppSettings')
        self.setStyleSheet('''
            QWidget#audioCppSettings QPushButton { padding: 6px 12px; }
            QWidget#audioCppSettings QLineEdit, QWidget#audioCppSettings QComboBox,
            QWidget#audioCppSettings QSpinBox { padding: 4px; }
            QWidget#audioCppSettings QTabBar::tab { padding: 8px 12px; }
            QWidget#audioCppSettings QLabel#sectionTitle { font-weight: bold; margin-top: 8px; }
        ''')
        heading = QLabel('audio.cpp Read Aloud')
        font = heading.font()
        font.setPointSize(font.pointSize() + 5)
        font.setBold(True)
        heading.setFont(font)
        outer.addWidget(heading)
        info = QLabel('1.0 · Local voices for your books\n'
                      'Choose a model and voice below. Saved changes apply when reading is stopped.')
        info.setWordWrap(True)
        outer.addWidget(info)
        if not compatible():
            warning = QLabel('This experimental plugin supports Calibre 9.16.x and 9.17.x only. '
                             'Registration is disabled on this Calibre version.')
            warning.setWordWrap(True)
            outer.addWidget(warning)
        tabs = QTabWidget()
        self.tabs = tabs
        outer.addWidget(tabs)
        general = QWidget()
        form = QFormLayout(general)
        form.setVerticalSpacing(8)
        def section(title):
            label = QLabel(title)
            label.setObjectName('sectionTitle')
            form.addRow(label)
        section('Model')
        tabs.addTab(general, 'Server and model')
        preset_row = QWidget()
        preset_layout = QVBoxLayout(preset_row)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setSpacing(4)
        self.preset_filter = QLineEdit()
        self.preset_filter.setClearButtonEnabled(True)
        self.preset_filter.setPlaceholderText('Filter models by name, support type, or features…')
        preset_layout.addWidget(self.preset_filter)
        preset_controls = QWidget()
        preset_controls_layout = QHBoxLayout(preset_controls)
        preset_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.preset_choice = QComboBox()
        self.preset_choice.setMinimumHeight(max(36, self.preset_choice.fontMetrics().height() + 16))
        preset_model = QStandardItemModel(self.preset_choice)
        preset_model.setHorizontalHeaderLabels(['Model', 'Support type', 'Model features'])
        families = ['kokoro_tts', 'breeze_tts'] + [f for f, s in
            sorted(CATALOG.items(), key=lambda item: item[1]['name'].casefold())
            if f not in ('kokoro_tts', 'breeze_tts')]
        for family in families:
            spec = CATALOG[family]
            row = [QStandardItem(spec['name']), QStandardItem(spec.get('status', 'unknown').capitalize()),
                   QStandardItem(preset_features(family, spec))]
            row[0].setData({'kokoro_tts': 'kokoro', 'breeze_tts': 'breeze'}.get(family, family), Qt.ItemDataRole.UserRole)
            for item in row:
                item.setEditable(False)
                item.setToolTip(item.text())
            row[1].setToolTip('Upstream audio.cpp support status; not a local test result.')
            preset_model.appendRow(row)
        self.preset_proxy = QSortFilterProxyModel(self.preset_choice)
        self.preset_proxy.setSourceModel(preset_model)
        self.preset_proxy.setFilterKeyColumn(-1)
        self.preset_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        preset_view = QTreeView(self.preset_choice)
        preset_view.setRootIsDecorated(False)
        preset_view.setItemsExpandable(False)
        preset_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        preset_view.setUniformRowHeights(True)
        self.preset_choice.setModel(self.preset_proxy)
        self.preset_choice.setView(preset_view)
        self.preset_choice.setModelColumn(0)
        preset_view.header().setStretchLastSection(True)
        preset_view.setSortingEnabled(True)
        preset_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        preset_view.setColumnWidth(0, 260)
        preset_view.setColumnWidth(1, 115)
        preset_view.setMinimumWidth(850)
        self.preset_choice.setMaxVisibleItems(18)
        self.preset_button = QPushButton('Use preset')
        self.preset_button.clicked.connect(self.use_preset)
        preset_controls_layout.addWidget(self.preset_choice)
        preset_controls_layout.addWidget(self.preset_button)
        preset_layout.addWidget(preset_controls)
        self.preset_filter.textChanged.connect(self.preset_proxy.setFilterFixedString)
        form.addRow('Model preset:', preset_row)
        section('Server')
        self.mode = QComboBox()
        self.mode.addItem('Start and stop my local server', 'managed')
        self.mode.addItem('Connect to an existing local server', 'external')
        form.addRow('Server ownership:', self.mode)
        self.exe = self.path_row(form, 'audio.cpp executable:')
        self.compute = QComboBox()
        self.compute.addItems(['cpu', 'cuda', 'vulkan', 'hip', 'rocm', 'metal'])
        form.addRow('Compute backend:', self.compute)
        self.model_file = self.path_row(form, 'Model GGUF file / package:')
        model_path_row = self.model_file.parentWidget()
        self.package_button = QPushButton('Browse package directory')
        self.package_button.clicked.connect(self.choose_model_directory)
        model_path_row.layout().addWidget(self.package_button)
        dependency_button = QPushButton('Check model dependencies')
        dependency_button.clicked.connect(self.check_model_dependencies)
        form.addRow(dependency_button)
        self.inference_mode = QComboBox()
        form.addRow('Inference mode:', self.inference_mode)
        self.memory_notice = QLabel()
        self.memory_notice.setWordWrap(True)
        form.addRow(self.memory_notice)
        self.memory_timer = QTimer(self)
        self.memory_timer.setSingleShot(True)
        self.memory_timer.setInterval(500)
        self.memory_timer.timeout.connect(self.update_memory_notice)
        self.model_file.textChanged.connect(lambda: self.memory_timer.start())
        self.compute.currentTextChanged.connect(lambda: self.memory_timer.start())
        self.model_id = GrowingTextField()
        form.addRow('Server model ID:', self.model_id)
        self.voice = GrowingTextField()
        form.addRow('Default voice / preset:', self.voice)
        self.voices = GrowingTextField()
        form.addRow('Available voices (comma separated):', self.voices)
        self.url = GrowingTextField()
        form.addRow('Existing server URL:', self.url)
        section('Playback and memory')
        self.idle = QSpinBox()
        self.idle.setRange(0, 86400)
        self.idle.setSuffix(' seconds')
        form.addRow('Shutdown after reading finishes:', self.idle)
        idle_label = form.labelForField(self.idle)
        self.idle_label = idle_label
        self.prewarm = QCheckBox('Pre-warm the selected model when a viewer opens')
        self.keep_loaded = QCheckBox('Never shut down the managed server while its viewer is open')
        self.keep_loaded.toggled.connect(self._ownership_changed)
        form.addRow(self.prewarm)
        form.addRow(self.keep_loaded)
        lifetime = QLabel('Pre-warm generates a short silent sample. Only one viewer can own a managed '
                          'server; additional viewers do not start duplicates. Keep loaded retains RAM/VRAM '
                          'after Stop and disables idle shutdown. Closing the owning viewer releases it. '
                          'Settings changes and server failures may still require a restart.')
        lifetime.setWordWrap(True)
        form.addRow(lifetime)
        espeak = QWidget()
        self.espeak_tab = espeak
        ef = QFormLayout(espeak)
        tabs.addTab(espeak, 'eSpeak setup')
        self.espeak_tab_index = tabs.indexOf(espeak)
        notice = QLabel('Some models use eSpeak for phonemization. Use the matching library and data you tested. '
                        'These paths are passed only to the server started by this plugin. '
                        'They do not change your Windows environment.')
        notice.setWordWrap(True)
        ef.addRow(notice)
        self.espeak_library = self.path_row(ef, 'eSpeak library (.dll):')
        self.espeak_data = self.path_row(ef, 'eSpeak data directory:', directory=True)
        package_button = QPushButton('Choose packed eSpeak data (.bin/.gguf)…')
        package_button.clicked.connect(self.choose_data_package)
        ef.addRow(package_button)
        self.find_button = QPushButton('Find eSpeak installed with Python')
        self.find_button.clicked.connect(self.find_espeak)
        ef.addRow(self.find_button)
        self.detect_status = QLabel('No download or installation is performed by this button.')
        self.detect_status.setWordWrap(True)
        ef.addRow(self.detect_status)
        self.breeze_tab = QWidget()
        breeze_layout = QVBoxLayout(self.breeze_tab)
        breeze_layout.setContentsMargins(10, 8, 10, 8)
        breeze_layout.setSpacing(4)
        breeze_fields = QWidget()
        breeze_fields.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        breeze_layout.addWidget(breeze_fields, 0, Qt.AlignmentFlag.AlignTop)
        breeze_layout.addStretch(1)
        bf = QFormLayout(breeze_fields)
        bf.setContentsMargins(0, 0, 0, 0)
        bf.setHorizontalSpacing(8)
        bf.setVerticalSpacing(2)
        bf.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        tabs.addTab(self.breeze_tab, 'Voice conditioning')
        breeze_note = QLabel('Use the model default or a preset voice, or reuse a reference WAV for every '
                             'segment. Some models require a recording and its transcript. Instructions '
                             'apply only to models declaring an instruction option. Consult Model help '
                             'for supported controls; variant-specific settings go in Advanced JSON.')
        breeze_note.setWordWrap(True)
        bf.addRow(breeze_note)
        self.breeze_mode = QComboBox()
        self.breeze_mode.addItem('Use default / preset voice or instructions', 'design')
        self.breeze_mode.addItem('Use a reference recording', 'reference')
        bf.addRow('Voice mode:', self.breeze_mode)
        self.instruction = QPlainTextEdit()
        self.instruction.setFixedHeight(72)
        bf.addRow('Voice / delivery instructions:', self.instruction)
        self.reference_audio = self.path_row(bf, 'Reference WAV:', compact=True)
        self.reference_text = QPlainTextEdit()
        self.reference_text.setFixedHeight(88)
        transcript_row = QWidget()
        transcript_layout = QHBoxLayout(transcript_row)
        transcript_layout.setContentsMargins(0, 0, 0, 0)
        transcript_layout.addWidget(self.reference_text, 1)
        self.transcript_import = QPushButton('Load transcript from text file…')
        self.transcript_import.clicked.connect(self.load_transcript_file)
        transcript_layout.addWidget(self.transcript_import, 0, Qt.AlignmentFlag.AlignTop)
        bf.addRow('Exact recording transcript:', transcript_row)
        self.saved_voices = QComboBox()
        self.saved_voices.setToolTip('Named reference recordings shared across model presets')
        bf.addRow('Saved reference voice:', self.saved_voices)
        voice_buttons = QWidget()
        voice_layout = QHBoxLayout(voice_buttons)
        voice_layout.setContentsMargins(0, 0, 0, 0)
        for label, handler in [('Load', self.load_reference_voice), ('Save as…', self.save_reference_voice),
                               ('Remove', self.remove_reference_voice)]:
            button = QPushButton(label)
            button.clicked.connect(handler)
            voice_layout.addWidget(button)
        bf.addRow(voice_buttons)
        voice_hint = QLabel('Voice library changes are saved with settings. Recordings stay in their original files.')
        voice_hint.setWordWrap(True)
        bf.addRow(voice_hint)
        self.ming_reference_notice = QLabel(
            'Ming3 uses speaker-identity cloning for recordings longer than 10 seconds '
            'to avoid garbled speech with audio.cpp 0.9.3. The full recording is used; '
            'its saved transcript is sent only for shorter recordings.')
        self.ming_reference_notice.setWordWrap(True)
        bf.addRow(self.ming_reference_notice)
        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        tabs.addTab(preview, 'Voice preview')
        preview_layout.addWidget(QLabel('Preview the current model and voice settings before saving.'))
        self.preview_text = GrowingTextEdit('Hello. This is a preview of my reading voice.')
        preview_layout.addWidget(self.preview_text)
        preview_buttons = QHBoxLayout()
        self.preview_play = QPushButton('Play preview')
        self.preview_stop = QPushButton('Stop')
        self.preview_play.clicked.connect(self.play_voice_preview)
        self.preview_stop.clicked.connect(self.stop_voice_preview)
        preview_buttons.addWidget(self.preview_play)
        preview_buttons.addWidget(self.preview_stop)
        preview_buttons.addStretch()
        preview_layout.addLayout(preview_buttons)
        self.preview_status = QLabel('Uses the current unsaved settings. A managed server must be free to start.')
        self.preview_status.setWordWrap(True)
        preview_layout.addWidget(self.preview_status)
        preview_layout.addStretch()
        self.preview_monitor = QTimer(self)
        self.preview_monitor.setInterval(200)
        self.preview_monitor.timeout.connect(self._preview_progress)
        pronunciation = QWidget()
        pf = QVBoxLayout(pronunciation)
        tabs.addTab(pronunciation, 'Pronunciation')
        note = QLabel('Replace whole words or phrases in spoken text for all models and books. '
                      'Use phonetic respellings (for example, Hermione → her MY oh nee). '
                      'The book text and highlighting stay unchanged. Phrases must fit within one spoken segment.')
        note.setWordWrap(True)
        pf.addWidget(note)
        self.pronunciation_enabled = QCheckBox('Enable custom pronunciations')
        self.pronunciation_case = QCheckBox('Match case exactly')
        pf.addWidget(self.pronunciation_enabled)
        pf.addWidget(self.pronunciation_case)
        self.pronunciation_table = QTableWidget(0, 2)
        self.pronunciation_table.setHorizontalHeaderLabels(['Written text', 'Say as'])
        self.pronunciation_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        pf.addWidget(self.pronunciation_table)
        buttons = QHBoxLayout()
        add = QPushButton('Add entry')
        remove = QPushButton('Remove selected entries')
        add.clicked.connect(self.add_pronunciation)
        remove.clicked.connect(self.remove_pronunciations)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        pf.addLayout(buttons)
        self.pronunciation_input = GrowingTextField()
        self.pronunciation_input.setPlaceholderText('Enter sample text to preview replacements')
        pf.addWidget(self.pronunciation_input)
        preview = QPushButton('Preview text (no audio)')
        preview.clicked.connect(self.preview_pronunciations)
        pf.addWidget(preview)
        self.pronunciation_output = GrowingTextEdit()
        self.pronunciation_output.setReadOnly(True)
        pf.addWidget(self.pronunciation_output)
        performance = QWidget()
        perf = QVBoxLayout(performance)
        tabs.addTab(performance, 'Performance')
        self.performance_overlay = QCheckBox('Show performance overlay when Read Aloud starts')
        perf.addWidget(self.performance_overlay)
        note = QLabel('Optional movable window with GPU memory and utilization, system RAM, '
                      'warmup and streaming timings, audio buffer and generation speed. '
                      'NVIDIA hardware metrics use nvidia-smi once per second and include other applications. '
                      'Unavailable counters show N/A. Closing the overlay stops polling until the next Play. '
                      'Copy measurements keeps a text snapshot for model comparisons. '
                      'Settings apply automatically when the viewer is idle.')
        note.setWordWrap(True)
        perf.addWidget(note)
        perf.addStretch()
        advanced = QScrollArea()
        advanced.setWidgetResizable(True)
        advanced.setFrameShape(QScrollArea.Shape.NoFrame)
        advanced_content = QWidget()
        advanced.setWidget(advanced_content)
        advanced_layout = QVBoxLayout(advanced_content)
        advanced_layout.setContentsMargins(12, 10, 12, 10)
        advanced_layout.setSpacing(6)
        af = QFormLayout()
        af.setContentsMargins(0, 0, 0, 0)
        af.setHorizontalSpacing(12)
        af.setVerticalSpacing(6)
        af.setFormAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        af.setLabelAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        af.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        advanced_layout.addLayout(af)
        tabs.addTab(advanced, 'Advanced')
        self.language = GrowingTextField()
        af.addRow('Text language:', self.language)
        self.sample_rate = QSpinBox()
        self.sample_rate.setRange(8000, 192000)
        af.addRow('PCM sample rate:', self.sample_rate)
        self.sample_rate.setToolTip('Native streaming sample rate in Hz. Kokoro uses 24000. Offline WAV supplies its own format.')
        self.channels = QSpinBox()
        self.channels.setRange(1, 2)
        af.addRow('PCM channels:', self.channels)
        self.speed = QCheckBox('Model supports the speed request option')
        af.addRow(self.speed)
        self.cwd = self.path_row(af, 'Working directory (optional):', directory=True)
        self.options = GrowingTextEdit()
        request_label = QLabel('Request options (JSON)')
        request_label.setBuddy(self.options)
        advanced_layout.addWidget(request_label)
        advanced_layout.addWidget(self.options)
        self.server_json = GrowingTextEdit()
        server_label = QLabel('Server configuration (JSON)')
        server_label.setBuddy(self.server_json)
        advanced_layout.addWidget(server_label)
        advanced_layout.addWidget(self.server_json)
        explanation = QLabel('Server and model controls override the matching JSON fields. '
                             'Offline WAV supplies its audio format; streaming uses the PCM settings above. '
                             'Set model-specific task, load_options and session_options in the server JSON.')
        explanation.setWordWrap(True)
        advanced_layout.addWidget(explanation)
        advanced_layout.addStretch(1)
        help_tab = QWidget()
        help_layout = QVBoxLayout(help_tab)
        self.model_help = QPlainTextEdit()
        self.model_help.setReadOnly(True)
        help_layout.addWidget(self.model_help)
        tabs.addTab(help_tab, 'Model help')
        self._populate(self.values)
        self.mode.currentIndexChanged.connect(self._ownership_changed)
        self.breeze_mode.currentIndexChanged.connect(self._ownership_changed)
        self.model_id.textChanged.connect(self._ownership_changed)
        self.server_json.textChanged.connect(self._ownership_changed)
        self.inference_mode.currentIndexChanged.connect(self._inference_mode_changed)
        self._ownership_changed()
        self.preset_choice.currentIndexChanged.connect(
            lambda index: self.preset_button.setEnabled(index >= 0))

    def add_pronunciation(self):
        table = self.pronunciation_table
        row = table.rowCount()
        table.insertRow(row)
        for column in range(2):
            table.setItem(row, column, QTableWidgetItem(''))
        table.setCurrentCell(row, 0)
        table.editItem(table.item(row, 0))

    def choose_model_directory(self):
        path = QFileDialog.getExistingDirectory(self, 'Choose complete model package', self.model_file.text())
        if path:
            self.model_file.setText(path)

    def update_memory_notice(self):
        from calibre_plugins.audio_cpp_read_aloud.performance import system_memory
        path = Path(self.model_file.text().strip())
        if not self.model_file.text().strip() or not path.exists():
            self.memory_notice.clear()
            return
        try:
            files = path.rglob('*') if path.is_dir() else [path]
            size = sum(p.stat().st_size for p in files if p.is_file() and
                       p.suffix.lower() in ('.gguf', '.safetensors', '.bin', '.onnx', '.pt'))
            if not size:
                self.memory_notice.setText('Memory estimate unavailable: no model weights found.')
                return
            estimate = size * 1.5 + 1024**3
            limits = []
            ram = system_memory()
            if ram:
                limits.append(('available RAM', ram[1] - ram[0]))
            gpu_unknown = self.compute.currentText() != 'cpu'
            if self.compute.currentText() == 'cuda':
                smi = shutil.which('nvidia-smi')
                if smi:
                    server = json.loads(self.server_json.toPlainText())
                    selected = next((m for m in server.get('models', []) if m.get('id') == self.model_id.text()), {})
                    device = str(selected.get('device', server.get('device', 0)))
                    result = subprocess.run([smi, '-i', device, '--query-gpu=memory.free',
                        '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=2,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    if result.returncode == 0:
                        limits.append(('available VRAM', float(result.stdout.strip()) * 1024**2))
                        gpu_unknown = False
            risk = [name for name, free in limits if estimate > free]
            text = ('Warning: model may exceed ' + ' and '.join(risk) + '. ') if risk else ''
            text += f'Estimated working memory: {estimate / 1024**3:.1f} GiB (weights: {size / 1024**3:.1f} GiB). '
            text += ', '.join(f'{name}: {free / 1024**3:.1f} GiB' for name, free in limits)
            if gpu_unknown:
                text += '. GPU memory could not be checked'
            text += '. Rough estimate; runtime usage varies. Directory estimates include all weight files, including alternate models.'
            self.memory_notice.setText(text)
        except (OSError, ValueError, subprocess.SubprocessError) as err:
            self.memory_notice.setText('Memory check unavailable: ' + str(err))

    def remove_pronunciations(self):
        rows = {item.row() for item in self.pronunciation_table.selectedIndexes()}
        for row in sorted(rows, reverse=True):
            self.pronunciation_table.removeRow(row)

    def pronunciation_values(self):
        entries = []
        for row in range(self.pronunciation_table.rowCount()):
            cells = [self.pronunciation_table.item(row, c) for c in range(2)]
            term, replacement = [(item.text().strip() if item else '') for item in cells]
            if term or replacement:
                entries.append(dict(text=term, replacement=replacement))
        value = dict(pronunciation_enabled=self.pronunciation_enabled.isChecked(),
                     pronunciation_case_sensitive=self.pronunciation_case.isChecked(),
                     pronunciations=entries)
        pronunciation_entries(value)
        return value

    def preview_pronunciations(self):
        try:
            result = apply_pronunciations(self.pronunciation_input.text(), self.pronunciation_values())
            self.pronunciation_output.setPlainText(result)
        except ValueError as error:
            self.pronunciation_output.setPlainText(str(error))

    def path_row(self, form, title, directory=False, compact=False):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit() if compact else GrowingTextField()
        button = QPushButton('Browse…')
        layout.addWidget(edit)
        layout.addWidget(button)
        def browse():
            if directory:
                chosen = QFileDialog.getExistingDirectory(self, title, edit.text())
            else:
                chosen, _ = QFileDialog.getOpenFileName(self, title, edit.text())
            if chosen:
                edit.setText(chosen)
        button.clicked.connect(browse)
        form.addRow(title, row)
        return edit

    def _populate(self, value):
        self.values = copy.deepcopy(value)
        self._refresh_saved_voices()
        self.prewarm.setChecked(value.get('prewarm_on_open', False))
        self.keep_loaded.setChecked(value.get('keep_loaded_while_open', False))
        self.performance_overlay.setChecked(value.get('performance_overlay', False))
        self.pronunciation_enabled.setChecked(value.get('pronunciation_enabled', True))
        self.pronunciation_case.setChecked(value.get('pronunciation_case_sensitive', False))
        entries = value.get('pronunciations', [])
        self.pronunciation_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            for col, key in enumerate(('text', 'replacement')):
                self.pronunciation_table.setItem(row, col, QTableWidgetItem(entry.get(key, '')))
        self.pronunciation_output.clear()
        family = profile_name(value)
        for index in range(self.preset_proxy.rowCount()):
            if self.preset_proxy.index(index, 0).data(Qt.ItemDataRole.UserRole) == family:
                self.preset_choice.setCurrentIndex(index)
                break
        server = value.get('server_settings') or kokoro_server()
        selected = next((m for m in server.get('models', []) if m.get('id') == value.get('model')), {})
        self.mode.setCurrentIndex(1 if value.get('mode') == 'external' else 0)
        self.exe.setText(value.get('executable', ''))
        compute = selected.get('backend', server.get('backend', 'cpu'))
        if self.compute.findText(compute) < 0:
            self.compute.addItem(compute)
        self.compute.setCurrentText(compute)
        self.model_file.setText(selected.get('path', ''))
        self.model_id.setText(value.get('model', 'kokoro'))
        self.voice.setText(value.get('voice', ''))
        self.voices.setText(', '.join(value.get('voices', [])))
        self.url.setText(value.get('base_url', 'http://127.0.0.1:8080'))
        self.idle.setValue(int(value.get('idle_shutdown_seconds', 60)))
        self.espeak_library.setText(value.get('espeak_library', ''))
        self.espeak_data.setText(value.get('espeak_data', ''))
        self.breeze_mode.setCurrentIndex(1 if value.get('breeze_voice_mode') == 'reference' else 0)
        self.instruction.setPlainText(value.get('breeze_instruction', 'Speak clearly and naturally.'))
        self.reference_audio.setText(value.get('reference_audio', ''))
        self.reference_text.setPlainText(value.get('reference_text', ''))
        self.language.setText(value.get('language', 'en'))
        self.sample_rate.setValue(int(value.get('sample_rate', 24000)))
        self.channels.setValue(int(value.get('channels', 1)))
        self.speed.setChecked(value.get('supports_speed', True))
        self.cwd.setText(value.get('working_directory', ''))
        self.options.setPlainText(json.dumps(value.get('options', {}), indent=2))
        self.server_json.setPlainText(json.dumps(server, indent=2))
        self._refresh_inference_modes()
        family = self._selected_family()
        spec = CATALOG.get(family, {})
        self.model_help.setPlainText(
            f"{spec.get('name', family)}\nUpstream status: {spec.get('status', 'unknown')}\n"
            'Install the complete GGUF package and its required companion assets.\n'
            'New presets use offline WAV with automatic playback format detection.\n'
            'For streaming, set the server entry mode to streaming only if supported,\n'
            'then set the matching native PCM sample rate/channels in Advanced.\n'
            'The installed audio.cpp binary must include this model family.\n'
            'Model docs: https://github.com/0xShug0/audio.cpp/tree/main/docs/models\n\n'
            + json.dumps(spec, ensure_ascii=False, indent=2))

    def check_model_dependencies(self):
        from calibre_plugins.audio_cpp_read_aloud.dependencies import check_dependencies
        try:
            messages = check_dependencies(self._draft())
            QMessageBox.information(self, 'Model dependencies', '\n\n'.join(messages))
        except (OSError, ValueError, TypeError, KeyError) as error:
            QMessageBox.warning(self, 'Dependency check failed', str(error))

    def load_transcript_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load reference transcript',
            str(Path(self.reference_audio.text()).parent), 'Text files (*.txt);;All files (*)')
        if not path:
            return
        try:
            with Path(path).open('rb') as source:
                data = source.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError('Transcript files must be smaller than 1 MiB.')
            encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
            text = data.decode(encoding)
            if '\x00' in text:
                raise ValueError('Choose a plain-text UTF-8 or UTF-16 transcript.')
            self.reference_text.setPlainText(text.strip())
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Cannot load transcript', str(error))

    def _refresh_saved_voices(self, selected=''):
        self.saved_voices.clear()
        for name in sorted(self.values.get('reference_voices', {}), key=str.casefold):
            self.saved_voices.addItem(name)
        if selected:
            self.saved_voices.setCurrentText(selected)

    def save_reference_voice(self):
        audio = self.reference_audio.text().strip()
        if not Path(audio).is_file():
            QMessageBox.warning(self, 'Reference voice', 'Choose an existing reference WAV first.')
            return
        name, accepted = QInputDialog.getText(self, 'Save reference voice', 'Voice name:')
        name = name.strip()
        if not accepted or not name:
            return
        voices = self.values.setdefault('reference_voices', {})
        if name in voices and QMessageBox.question(self, 'Replace reference voice',
                'Replace the saved reference named ' + name + '?') != QMessageBox.StandardButton.Yes:
            return
        voices[name] = dict(audio=str(Path(audio).resolve()), transcript=self.reference_text.toPlainText().strip())
        self._refresh_saved_voices(name)

    def load_reference_voice(self):
        voice = self.values.get('reference_voices', {}).get(self.saved_voices.currentText())
        if voice:
            self.reference_audio.setText(voice['audio'])
            self.reference_text.setPlainText(voice.get('transcript', ''))
            self.breeze_mode.setCurrentIndex(self.breeze_mode.findData('reference'))

    def remove_reference_voice(self):
        self.values.get('reference_voices', {}).pop(self.saved_voices.currentText(), None)
        self._refresh_saved_voices()

    def play_voice_preview(self):
        text = self.preview_text.toPlainText().strip()
        if not text:
            self.preview_status.setText('Enter some text to preview.')
            return
        try:
            cfg = self.collect()
            cfg.update(prewarm_on_open=False, keep_loaded_while_open=False,
                       performance_overlay=False, idle_shutdown_seconds=0)
            self.stop_voice_preview()
            from calibre_plugins.audio_cpp_read_aloud.backend import AudioCpp
            if self.preview_backend is None:
                self.preview_backend = AudioCpp(parent=self, preview_config=cfg)
                self.preview_backend.config_timer.stop()
            else:
                self.preview_backend.preview_config = cfg
                self.preview_backend.reload_after_configure()
            self.preview_status.setText('Loading model and generating preview…')
            self.preview_backend.say(text[:2000])
            self.preview_play.setEnabled(False)
            self.preview_monitor.start()
        except Exception as error:
            self.stop_voice_preview()
            self.preview_status.setText(str(error))

    def _preview_progress(self):
        backend = self.preview_backend
        if backend and not backend.active:
            message = backend.error_message() or 'Preview finished.'
            self.stop_voice_preview()
            self.preview_status.setText(message)

    def stop_voice_preview(self):
        if self.preview_backend is not None:
            self.preview_backend.shutdown()
        self.preview_monitor.stop()
        self.preview_play.setEnabled(True)
        self.preview_status.setText('Preview stopped.')

    def hideEvent(self, event):
        self.stop_voice_preview()
        super().hideEvent(event)

    def _selected_family(self):
        model_id = self.model_id.text().strip()
        try:
            server = json.loads(self.server_json.toPlainText())
            selected = next((model for model in server.get('models', [])
                             if model.get('id') == model_id), None)
            if selected and selected.get('family'):
                return selected['family']
        except (TypeError, ValueError, AttributeError):
            pass
        return model_family(self.values) or 'kokoro_tts'

    def _refresh_inference_modes(self):
        family = self._selected_family()
        supported = CATALOG.get(family, {}).get('modes', ['offline'])
        try:
            server = json.loads(self.server_json.toPlainText())
            model = next((m for m in server.get('models', []) if m.get('id') == self.model_id.text().strip()), {})
            selected = model.get('mode', 'offline')
        except (TypeError, ValueError, AttributeError):
            selected = 'offline'
        if not supported:
            supported = ['offline']
        self.inference_mode.blockSignals(True)
        self.inference_mode.clear()
        for mode in supported:
            self.inference_mode.addItem(mode.capitalize(), mode)
        index = self.inference_mode.findData(selected)
        self.inference_mode.setCurrentIndex(max(0, index))
        self.inference_mode.blockSignals(False)

    def _inference_mode_changed(self):
        try:
            server = json.loads(self.server_json.toPlainText())
            model = next((m for m in server.get('models', []) if m.get('id') == self.model_id.text().strip()), None)
            if model is None:
                return
            model['mode'] = self.inference_mode.currentData()
            self.server_json.blockSignals(True)
            self.server_json.setPlainText(json.dumps(server, indent=2))
            self.server_json.blockSignals(False)
        except (TypeError, ValueError, AttributeError):
            self.server_json.blockSignals(False)

    def _ownership_changed(self):
        self._refresh_inference_modes()
        managed = self.mode.currentData() == 'managed'
        family = self._selected_family()
        breeze = family == 'breeze_tts'
        for widget in (self.exe, self.compute, self.model_file, self.idle,
                       self.espeak_library, self.espeak_data, self.find_button, self.server_json, self.cwd):
            widget.setEnabled(managed)
        self.url.setEnabled(not managed)
        self.prewarm.setEnabled(managed)
        self.keep_loaded.setEnabled(managed)
        never = self.keep_loaded.isChecked()
        self.idle.setVisible(not (managed and never))
        self.idle_label.setVisible(not (managed and never))
        needs_espeak = model_needs_espeak(family)
        if not needs_espeak and self.tabs.currentWidget() is self.espeak_tab:
            self.tabs.setCurrentIndex(0)
        self.tabs.setTabVisible(self.espeak_tab_index, needs_espeak)
        spec = CATALOG.get(family, {})
        request_names = {o.get('name') for o in spec.get('options', {}).get('request', [])}
        conditioned = family == 'breeze_tts' or bool(
            spec.get('voices') or spec.get('default_voice') or
            'clone' in spec.get('tasks', []) or
            request_names & {'reference_text', 'voice_ref', 'instruct', 'instruction',
                             'voice_description', 'description'})
        if not conditioned and self.tabs.currentWidget() is self.breeze_tab:
            self.tabs.setCurrentIndex(0)
        self.tabs.setTabVisible(self.tabs.indexOf(self.breeze_tab), conditioned)
        reference = conditioned and self.breeze_mode.currentData() == 'reference'
        self.ming_reference_notice.setVisible(family == 'ming3_tts' and reference)
        self.reference_audio.setEnabled(reference)
        self.reference_text.setEnabled(reference)
        self.voice.setEnabled(not breeze and not reference)
        self.voices.setEnabled(not breeze and not reference)
        self.speed.setEnabled(not breeze)
        for widget in (self.espeak_library, self.espeak_data, self.find_button):
            widget.setEnabled(managed and needs_espeak)

    def use_preset(self):
        if self.preset_choice.currentData() is None:
            return
        self.stop_voice_preview()
        try:
            value = switch_profile(self._draft(), self.preset_choice.currentData())
            self._populate(value)
            self._ownership_changed()
        except Exception as e:
            QMessageBox.warning(self, 'Cannot switch preset', str(e))

    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose prototype audiocpp.json', '', 'JSON (*.json)')
        if path:
            try:
                self._populate(settings.import_prototype(path))
                self._ownership_changed()
                self.detect_status.setText('Prototype imported. If eSpeak paths are blank, click Find eSpeak. '
                                           'Click OK to save. Idle viewers apply the changes automatically.')
            except Exception as e:
                QMessageBox.warning(self, 'Import failed', str(e))

    def choose_data_package(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose eSpeak data package', '', 'Data (*.bin *.gguf)')
        if path:
            self.espeak_data.setText(path)

    def find_espeak(self):
        if self.detector is not None:
            return
        python = shutil.which('python') or shutil.which('python3') or shutil.which('py')
        if not python:
            self.detect_status.setText('Python was not found on PATH. Browse to your eSpeak library and data instead.')
            return
        process = self.detector = QProcess(self)
        self.find_button.setEnabled(False)
        self.detect_status.setText('Looking up espeakng_loader in your Python installation…')
        script = ('import json, espeakng_loader as e; '
                  'print(json.dumps({"library":e.get_library_path(),"data":e.get_data_path()}))')
        args = ['-c', script]
        if Path(python).stem.lower() == 'py':
            args.insert(0, '-3')
        timeout = QTimer(process)
        timeout.setSingleShot(True)
        timeout.timeout.connect(process.kill)
        def finish(*unused):
            if self.detector is not process:
                return
            timeout.stop()
            self.detector = None
            self.find_button.setEnabled(self.mode.currentData() == 'managed')
            try:
                result = json.loads(bytes(process.readAllStandardOutput()).decode('utf-8'))
                if not Path(result['library']).is_file() or not Path(result['data']).is_dir():
                    raise ValueError('Missing eSpeak files')
                self.espeak_library.setText(result['library'])
                self.espeak_data.setText(result['data'])
                self.detect_status.setText('Found matching eSpeak library and data. Click OK to save.')
            except Exception:
                self.detect_status.setText('Could not find espeakng_loader. In your normal PowerShell run '
                                          'python -m pip install espeakng-loader, then try again. '
                                          'Alternatively browse to the library and data you already use.')
            process.deleteLater()
        process.finished.connect(finish)
        process.errorOccurred.connect(lambda error: finish() if error == QProcess.ProcessError.FailedToStart else None)
        process.start(python, args)
        timeout.start(15000)

    def _draft(self):
        value = copy.deepcopy(self.values)
        value.update(self.pronunciation_values())
        value['prewarm_on_open'] = self.prewarm.isChecked()
        value['keep_loaded_while_open'] = self.keep_loaded.isChecked()
        value['performance_overlay'] = self.performance_overlay.isChecked()
        value.update(mode=self.mode.currentData(), executable=self.exe.text().strip(),
                     model=self.model_id.text().strip(), voice=self.voice.text().strip(),
                     voices=[v.strip() for v in self.voices.text().split(',') if v.strip()],
                     base_url=self.url.text().strip(), idle_shutdown_seconds=self.idle.value(),
                     espeak_library=self.espeak_library.text().strip(), espeak_data=self.espeak_data.text().strip(),
                     language=self.language.text().strip(), sample_rate=self.sample_rate.value(),
                     channels=self.channels.value(), supports_speed=self.speed.isChecked(),
                     working_directory=self.cwd.text().strip(),
                     breeze_voice_mode=self.breeze_mode.currentData(),
                     breeze_instruction=self.instruction.toPlainText().strip(),
                     reference_audio=self.reference_audio.text().strip(),
                     reference_text=self.reference_text.toPlainText().strip())
        value['options'] = json.loads(self.options.toPlainText())
        server = json.loads(self.server_json.toPlainText())
        if not isinstance(server, dict) or not isinstance(server.get('models'), list):
            raise ValueError('Server JSON must contain a models array')
        selected = next((m for m in server['models'] if m.get('id') == value['model']), None)
        if selected is not None:
            selected['path'] = self.model_file.text().strip()
            if 'backend' in selected:
                selected['backend'] = self.compute.currentText()
        server['backend'] = self.compute.currentText()
        value['server_settings'] = server
        value.pop('log_file', None)
        return value

    def collect(self):
        value = self._draft()
        if not value['model']:
            raise ValueError('A model ID is required')
        if not isinstance(value['options'], dict):
            raise ValueError('Request options must be a JSON object')
        if value['mode'] == 'external':
            value['base_url'] = local_url(value['base_url'])
        else:
            if not Path(value['executable']).is_file():
                raise ValueError('Choose the existing audiocpp_server executable')
            if value['working_directory'] and not Path(value['working_directory']).is_dir():
                raise ValueError('Working directory does not exist')
            server = json.loads(self.server_json.toPlainText())
            if not isinstance(server, dict) or not isinstance(server.get('models'), list):
                raise ValueError('Server JSON must contain a models array')
            selected = next((m for m in server['models'] if m.get('id') == value['model']), None)
            if selected is None:
                raise ValueError('Model ID must match an entry in the Advanced server configuration')
            family = selected.get('family') or model_family(value)
            needs_espeak = model_needs_espeak(family)
            model_path = self.model_file.text().strip()
            if not model_path or not (Path(model_path).is_file() or Path(model_path).is_dir()):
                raise ValueError('Choose an existing GGUF file or complete model package directory')
            modes = CATALOG.get(selected.get('family'), {}).get('modes', ['offline', 'streaming'])
            if selected.get('mode', 'offline') not in modes:
                raise ValueError('This family supports these session modes: ' + ', '.join(modes))
            selected['path'] = str(Path(model_path).resolve())
            session_espeak = espeak_option_names(family, groups=('session',))
            if session_espeak:
                session_options = selected.get('session_options')
                if not isinstance(session_options, dict):
                    session_options = {}
                for name, setting in (('espeak_library_path', 'espeak_library'),
                                      ('espeak_data_path', 'espeak_data')):
                    key = f'{family}.{name}'
                    if name in session_espeak and value[setting]:
                        session_options[key] = value[setting]
                selected['session_options'] = session_options
            server['backend'] = self.compute.currentText()
            if 'backend' in selected:
                selected['backend'] = server['backend']
            value['server_settings'] = server
            if needs_espeak and value['espeak_library'] and not Path(value['espeak_library']).is_file():
                raise ValueError('eSpeak library does not exist')
            if needs_espeak and value['espeak_data']:
                p = Path(value['espeak_data'])
                valid_dir = p.is_dir() and (p / 'phontab').is_file()
                valid_package = p.is_file() and p.suffix.lower() in ('.bin', '.gguf')
                if not (valid_dir or valid_package):
                    raise ValueError('Choose espeak-ng-data containing phontab, or a .bin/.gguf data package')
        if model_family(value) == 'breeze_tts':
            value.update(supports_speed=False, sample_rate=24000, channels=1, voice='', voices=list(CATALOG['breeze_tts'].get('voices', [])))
            value['options'].pop('speed', None)
            if value['breeze_voice_mode'] == 'reference':
                p = Path(value['reference_audio'])
                if not p.is_file() or p.suffix.lower() != '.wav':
                    raise ValueError('Choose an existing WAV file for the Breeze reference recording')
                if not value['reference_text']:
                    raise ValueError('Enter the exact words spoken in the reference recording')
                value['reference_audio'] = str(p.resolve())
        elif value['breeze_voice_mode'] == 'reference' and model_family(value) != 'kokoro_tts':
            p = Path(value['reference_audio'])
            if not p.is_file() or p.suffix.lower() != '.wav':
                raise ValueError('Choose an existing WAV file for the reference recording')
            value['reference_audio'] = str(p.resolve())
        return value

    def validate(self):
        try:
            self.collect()
            return True
        except Exception as e:
            QMessageBox.warning(self, 'Check audio.cpp settings', str(e))
            return False

    def save(self):
        settings.save(self.collect())
        QMessageBox.information(self, 'Settings saved',
            'Open viewers check for changes every two seconds and apply them when idle. '
            'Stop active or paused reading to apply changes now. Server changes restart the owned server. '
            'When upgrading the plugin ZIP, close all viewers and restart Calibre first; '
            'older plugin versions cannot apply these updates live.')
