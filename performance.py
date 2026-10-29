"""Optional local telemetry. No model or monitoring service is started."""
import csv
import ctypes
import math
import os
from pathlib import Path
import shutil
import time

from qt.core import QApplication, QLabel, QProcess, QPushButton, QTimer, Qt, QVBoxLayout, QWidget


def system_memory():
    """Return used/total physical bytes; unavailable platforms return None."""
    try:
        if os.name == 'nt':
            class MemoryStatus(ctypes.Structure):
                _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
                    (name, ctypes.c_uint64) for name in ('total', 'available', 'page_total',
                    'page_available', 'virtual_total', 'virtual_available', 'extended')]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return status.total - status.available, status.total
        values = {}
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, rest = line.split(':', 1)
            values[key] = int(rest.split()[0]) * 1024
        return values['MemTotal'] - values['MemAvailable'], values['MemTotal']
    except (OSError, ValueError, KeyError, AttributeError):
        return None


def gpu_lines(output):
    lines = []
    def number(value):
        try:
            n = float(value)
            return n if math.isfinite(n) and n >= 0 else None
        except ValueError:
            return None
    for row in csv.reader(output.splitlines()):
        if len(row) != 5:
            continue
        index, name, used, total, utilization = [v.strip() for v in row]
        u, t, busy = number(used), number(total), number(utilization)
        memory = f'{u / 1024:.2f} / {t / 1024:.2f} GiB ({100*u/t:.1f}%)' if u is not None and t else 'N/A'
        usage = f'{busy:.0f}%' if busy is not None else 'N/A'
        lines.append(f'GPU {index}: {name}\nVRAM: {memory}  |  GPU utilization: {usage}')
    return '\n'.join(lines) or 'GPU: unavailable'


class Measurements:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.health_ms = self.first_ms = self.ttfa_ms = self.gap_ms = None
        self.request_started = self.last_chunk = None
        self.request_bytes = self.completed_bytes = 0
        self.generation_seconds = 0.0
        self.completed = 0

    def health(self):
        if self.health_ms is None:
            self.health_ms = (self.clock() - self.started) * 1000

    def request(self):
        self.request_started = self.clock()
        self.last_chunk = None
        self.request_bytes = 0
        self.ttfa_ms = self.gap_ms = None

    def chunk(self, size):
        if not size or self.request_started is None:
            return
        now = self.clock()
        if self.last_chunk is None:
            self.ttfa_ms = (now - self.request_started) * 1000
            if self.first_ms is None:
                self.first_ms = (now - self.started) * 1000
        else:
            self.gap_ms = (now - self.last_chunk) * 1000
        self.last_chunk = now
        self.request_bytes += size

    def finish(self):
        if self.request_started is not None:
            self.generation_seconds += self.clock() - self.request_started
            self.completed_bytes += self.request_bytes
            self.completed += 1
            self.request_started = None


class PerformanceOverlay(QWidget):
    def __init__(self, backend):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.backend = backend
        self.setWindowTitle('audio.cpp performance')
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMinimumWidth(410)
        layout = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.label)
        copy = QPushButton('Copy measurements')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.label.text()))
        layout.addWidget(copy)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.process = QProcess(self)
        self.process.finished.connect(self.gpu_finished)
        self.process.errorOccurred.connect(self.gpu_error)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self.gpu_timeout)
        self.smi = shutil.which('nvidia-smi')
        if not self.smi and os.name == 'nt':
            candidate = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'nvidia-smi.exe'
            if candidate.is_file():
                self.smi = str(candidate)
        self.metrics = Measurements()
        self.running = False
        self.gpu = 'GPU: waiting for sample' if self.smi else 'GPU: N/A (nvidia-smi not found)'
        self.ram = None

    def begin(self):
        self.metrics = Measurements()
        self.running = True
        self.show()
        self.timer.start()
        self.refresh()

    def freeze(self):
        self.running = False
        self.timer.stop()
        self.timeout.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        self.render()

    def closeEvent(self, event):
        self.freeze()
        super().closeEvent(event)

    def gpu_timeout(self):
        self.gpu = 'GPU: query timed out'
        self.process.kill()

    def gpu_error(self, error):
        self.timeout.stop()
        self.gpu = 'GPU: unavailable (query failed)'
        self.render()

    def gpu_finished(self, code, status):
        self.timeout.stop()
        if self.running:
            self.gpu = gpu_lines(bytes(self.process.readAllStandardOutput()).decode('utf-8', 'replace')) if code == 0 else 'GPU: unavailable (query failed)'
            self.render()

    def refresh(self):
        self.ram = system_memory()
        self.render()
        if self.running and self.smi and self.process.state() == QProcess.ProcessState.NotRunning:
            self.process.start(self.smi, ['--query-gpu=index,name,memory.used,memory.total,utilization.gpu',
                                          '--format=csv,noheader,nounits'])
            self.timeout.start(2500)

    def render(self):
        b, m = self.backend, self.metrics
        ms = lambda n: '—' if n is None else f'{n:.0f} ms'
        ram = 'N/A'
        if self.ram:
            used, total = self.ram
            ram = f'{used / 2**30:.2f} / {total / 2**30:.2f} GiB ({100*used/total:.1f}%)'
        bps = int(getattr(b, 'audio_rate', b.cfg.get('sample_rate', 24000))) * int(getattr(b, 'audio_channels', b.cfg.get('channels', 1))) * 2
        audio = m.completed_bytes / bps
        speed = f'{audio / m.generation_seconds:.2f}× realtime' if m.generation_seconds > 0 else '—'
        state = 'Paused' if b.paused else ('Reading / loading' if self.running else 'Stopped / finished (last sample)')
        self.label.setText(f'Model: {b.cfg.get("model", "")} | {state}\n\n{self.gpu}\nSystem RAM: {ram}\n'
            f'Hardware metrics include other applications.\n\n'
            f'Server ready: {ms(m.health_ms)}\n'
            f'Warmup / Play → first audio received: {ms(m.first_ms)}\n'
            f'Streaming delay / segment first audio: {ms(m.ttfa_ms)}\n'
            f'Latest audio delivery gap: {ms(m.gap_ms)}\n'
            f'Queued PCM buffer: {len(b.buffer)/bps*1000:.0f} ms\n'
            f'Generation speed: {speed}\n'
            f'Completed segments: {m.completed} | Generated audio: {audio:.1f} s\n'
            f'Client timings include HTTP and lazy model loading.\n'
            f'Generation speed excludes time between requests; higher is better.')
