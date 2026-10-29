# Validation ? 1.0.0

Release packaging: ZIP output is build/audio-cpp-read-aloud-1.0.0.zip. Unit suite on Calibre 9.17.0: 33 tests, 32 passed, one POSIX-only skip. Real Calibre importer, registration and settings construction passed. No model inference sweep or additional manual theme/scaling acceptance checks were run for this documentation and packaging release. Earlier model evidence remains below.

# Validation ? 0.9.2

MioTTS with the Q8 MioCodec GGUF: HTTP tests using both references matched the requested sentence. Actual Read Aloud backend with saved MioTTS settings, Sample.wav, prewarming, two sentences, Qt playback (muted) and highlighting completed with 0% ASR word error rate. Evidence: validation/miotts-0.9.2/ and validation/ming-read-aloud/reader-0.9.2-offline-clone.json (legacy harness directory name). Unit suite: 32 passed, one skipped.

# Validation ? 0.9.1

33 existing tests: 32 passed, one skipped. Calibre importer/settings checks passed. validation/check_preview_library.py checks reference save/load/remove, draft isolation, profile persistence, preview configuration isolation and stop using real Calibre Qt. Live model speech quality was not retested for this release.

# Validation ? 0.9.0 preview

33 tests: 32 passed, one platform-specific skip. Real Calibre ZIP loading, backend registration and settings construction passed on 9.17.0. The preset persistence fixture now selects by identifier rather than an obsolete row number. No full model sweep was repeated for this UI/release preparation. Manual theme/scaling and long-reading acceptance checks remain in RELEASE.md. Offscreen screenshot rendering lacked usable fonts, so it is not visual acceptance evidence.

# Validation ? plugin 0.6.6

33 unit tests: 32 passed, one POSIX-only test skipped. Calibre ZIP loading and settings UI passed. Custom toolbar icon creation, text-under-icon layout and matching toolbar dimensions passed under real Calibre Qt.

Live DotTTS and MioTTS results: see README and validation/dots-mio/. DotTTS short/full reference transcriptions match the requested sentence. Full-reference speaker cosine: 0.847. Mio directory loading succeeds, but incorrect speech is also reproduced with explicit paths; this is not a speech-quality pass.

# Validation — plugin 0.6.3

Added Ming3 viewer choices for Cloned voice (reference recording), Use plugin
voice settings, and the four built-in voices. Explicit clone/native selections
override saved conditioning for that request without mutating plugin preferences.
Missing reference files produce an error pointing to Voice conditioning.

Calibre 9.17.0: 33 unit tests, 32 passed and one POSIX-only fixture skipped.
The real Calibre importer/backend check verifies the voice names and labels and
that Kokoro does not advertise Ming's clone option. Actual Read Aloud backend
tests with the viewer selection set to clone and US_Emma both completed using
audio.cpp 0.9.3 and the Q8 model. The clone used Sample.wav and recovered the
entire passage in Moonshine ASR (0% word error rate). US_Emma correctly used
the IP template without a reference; its ASR word error rate was 22.2%, with
errors near the end of the passage. These are automated checks, not listening
assessments. Reports: `validation/ming-read-aloud/reader-0.6.3-*-selected-*.json`.

## Previous validation — plugin 0.6.2

Fixed the Read Aloud failure reproduced with the user's 24.25-second stereo
`Sample.wav` and matching `Sample.txt`. With acoustic conditioning enabled by
the transcript, Q8 and BF16 produced silence or unintelligible speech. Changing
the audio format was not a repeatable fix. The full recording works as a speaker
reference without acoustic conditioning; a short excerpt plus transcript also
works. The plugin now uses speaker-only cloning for references over 10 seconds,
retains the full original recording and saved transcript, and explains this in
Voice conditioning. This is a conservative workaround for audio.cpp 0.9.3.

The actual Calibre backend was exercised with the user's settings, Qt networking,
silent prewarming, multiple sentences, highlighting and the physical output
device at muted volume. Offline and streaming full-reference cloning, plus a
4.2-second excerpt with its matching transcript, completed successfully. Local
Moonshine Tiny ASR recovered all words in the test passage (0% WER in each case).
The same recognizer also correctly transcribed the original reference.
CAMPPlus cosine similarity to the original speaker was 0.869 for the generated
clone and 0.216 for an unrelated preset control. This is objective supporting
evidence, not a human listening assessment.

Reproduction and evidence: `validation/reproduce_ming_read_aloud.py`,
`validation/check_ming_speaker.py`, and `validation/ming-read-aloud/`.
The unit suite has 32 tests: 31 passed and one POSIX-only fixture skipped.
The 0.6.2 archive passes the real Calibre importer and UI checks.

## Previous version validation

# Validation — plugin 0.6.1

Windows Calibre 9.17.0: 31 automated tests, 30 passed and one POSIX-only
subprocess fixture skipped. Ming-specific checks cover template selection,
all four named voices, reference audio with optional transcripts, categorical
speed, streaming format, and migration of saved placeholder profiles.

Live Ming3-TTS tests used the new `bin/` audio.cpp 0.9.3 build, commit `41c1f8ff`,
with CUDA on an NVIDIA RTX 3070 (8 GB VRAM). All 16 English inference cases
passed through the packaged plugin's request builder and HTTP audio decoder:
default synthesis, four built-in voices, voice design, speaker reference, and
speaker reference with transcript, each in offline and streaming modes. Every
case generated nonempty 44.1 kHz mono audio. This does not assess listening
quality or other languages.

The selected Q8_0 package is 1,742,280,896 bytes, smaller than the published
BF16 package (2,998,284,288 bytes). The GGUF contains the required model assets.
The reproducible live runner is `validation/test_ming3.py`; detailed results,
requests, logs, and WAVs are under `validation/model-tests/`.

```powershell
calibre-debug -e validation/test_ming3.py
```

The installable 0.6.1 ZIP also passes Calibre importer, engine-registration,
backend-construction, and settings-widget checks. Earlier model results below
were obtained with audio.cpp 0.9.2 and have not been rerun with 0.9.3.

## Previous version validation

# Validation — plugin 0.6.0

Windows calibre 9.17.0: 27 automated tests run, 26 pass and one POSIX-only
GPU subprocess fixture is explicitly skipped on Windows. New coverage includes:
- Catalog coverage for every local GGUF TTS spec and four newer upstream families.
- Request construction across all 56 family presets; profile round trips preserve
  paths, reference recordings, options and shared preferences.
- Generic reference/instruction requests and stale voice isolation.
- Fragmented WAV responses at 16/22.05/24/44.1/48 kHz, mono/stereo; rejection of
  malformed/truncated/oversized audio.
- Settings UI catalog entries and complete package directory selection.
- Real Qt HTTP against a mock server: silent offline warmup, repeated requests,
  native 48 kHz stereo detection, PCM output through a fake audio sink and
  original sentence highlighting. Existing streaming/lifecycle tests still pass.
- The built ZIP loads with the real calibre importer and all 56 family settings
  populate in the real settings widget, without starting a model server.

## Live model inference

The original Windows audio.cpp 0.9.2 executable was also exercised with the CUDA
backend on an RTX 3070 (8 GB VRAM): **51 of 51 TTS families supported by the
executable passed**. Fifty models were requested through the plugin's speech
path; MiniMax-H3 passed through its `gen` task. All produced nonempty WAV output.
These are inference smoke tests, not subjective speech-quality evaluations.

The runner selects the smallest published package per family when required
assets are available. PocketTTS used English Q8 because its smaller German Q8
package omits the required `alba.safetensors` embedding. MioTTS was tested with
the MioCodec and WavLM companion assets. Gradium Phonon, Ming 3 Audio, Ming 3
TTS, and XTTS v2 are absent from this executable's loader list; MiraTTS has no
published GGUF package in the bundled catalog. Per-family results and package
inventory are recorded in `validation/model-tests/matrix-results.json` and
`validation/model-downloads.json`.

The mock-server tests above continue to use generated PCM, not live model
output. Model-specific assets, variants, backend support, and speech quality
remain dependent on audio.cpp and the installed packages.

Run the suite in an isolated configuration with `QT_QPA_PLATFORM=offscreen`:

```powershell
calibre-debug -c "import tempfile; tempfile.gettempdir(); import unittest; result=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover('tests')); raise SystemExit(not result.wasSuccessful())"
```

## Previous version validation

# Validation — plugin 0.5.2

Validated on installed Windows calibre 9.17.0 using an isolated configuration:
- The distributable ZIP loads through calibre's real plugin importer.
- Lazy engine registration and repeated initialization succeed; stock engines remain.
- Version guards accept 9.16.x/9.17.x (including patch builds), reject 9.15,
  9.18 and 10.0; disabling the plugin hides its engine.
- The real TTS factory constructs and reuses the backend; the settings UI constructs.
- No audio.cpp server is started by these checks. ZIP integrity passes.

Run the build/compatibility check from PowerShell in the project directory:

```powershell
$env:CALIBRE_CONFIG_DIRECTORY = Join-Path $PWD 'validation/compat-config'
$env:QT_QPA_PLATFORM = 'offscreen'
calibre-debug -e validation/compatibility.py
```

The existing suite ran under calibre's bundled Python/Qt: 19 of 20 tests passed.
The GPU subprocess test uses a Unix shebang executable and fails on Windows.
Initialize `tempfile.gettempdir()` before running the suite under calibre-debug,
because the tests replace calibre constants with stubs.
Full viewer interaction and live model/audio playback were not tested for this update.

## Previous version validation

# Validation — plugin 0.5.1

20 automated tests pass. Added a regression test for a partially imported viewer
module: engine registration succeeds, stock engines remain available, repeated
installation is idempotent, and Application construction attaches the deferred
viewer hook before the viewer starts. A second test confirms an optional startup
hook error does not prevent engine hook installation. The prior 18 tests pass.

The v0.5.0 failure was also reproduced directly from its distributable ZIP:
install() raised AttributeError when viewer.ui existed without EbookViewer.
Calibre source confirms viewer.ui imports customize.ui before defining EbookViewer,
and viewer.main constructs Application after that import completes.

Tests use real Qt with stubbed Calibre services, not a full Windows Calibre session.

## Previous version validation

# Validation — plugin 0.5.0

18 automated tests pass: the 15 prior regression tests plus:
- Real Qt networking against a mock speech server verifies silent prewarming,
  absence of audio sink/highlight output, keep-loaded Stop/idle behavior, deferred
  settings updates during active reading, automatic reload and shutdown cleanup.
- Two OwnedServer objects using a mocked lock verify duplicate-start refusal,
  release/reacquisition and release after launch failure.
- Viewer constructor hook is deferred and idempotent.

Cross-process exclusion uses Calibre's existing per-user single-instance mutex
(Windows named mutex; platform-specific locking elsewhere). A direct Linux
cross-process mutex test was attempted but the hosted environment denied AF_UNIX
socket creation. Therefore real OS mutex contention and Windows crash cleanup
have NOT been tested here. The tests validate the plugin's handling of lock
acquisition/refusal, not the operating system implementation.

No real Windows viewer, audio.cpp model, or GPU test was possible here. On Windows,
check opening two viewers together, closing the owner, Play in the second viewer,
and changing the selected model while idle and while paused. Upgrade with all old
viewers closed: old plugin versions do not use this lock.

## Previous version validation

# Validation — plugin 0.4.0

15 tests pass (8 pronunciation regression tests and 7 performance tests).
Performance checks cover deterministic latency/speed math, multi-GPU/N/A parsing,
real Qt asynchronous subprocess polling using a fake nvidia-smi executable,
timeout/missing-tool handling, closing/stopping polling, settings/profile retention,
Linux system memory, and disabled mode avoiding overlay construction.
Python modules compile and ZIP integrity is checked.

No Windows Calibre, real NVIDIA hardware, or physical audio testing was performed
in this environment. Windows RAM uses GlobalMemoryStatusEx; live driver telemetry
and window placement/fullscreen behavior should be checked on the user's machine.

## Previous version validation

# Validation — plugin 0.3.0

Eight targeted tests pass in the current build environment:
- Literal matching, whole-word boundaries, Unicode, and case sensitivity.
- Longest phrase priority, punctuation and non-recursive replacements.
- Empty/disabled dictionaries preserve previous behavior; invalid entries fail validation.
- Kokoro and Breeze request generation; reference transcript/instructions remain intact.
- Profile switching retains the shared dictionary.
- Real PyQt6 preferences: entry editing, preview, preset switching, persistence,
  reload, and deletion (Calibre configuration services stubbed).
- Actual backend synthesis method with mocked network confirms outgoing replacements
  and original highlight offsets/lengths.

All Python modules compile and the installable ZIP passes its integrity check.
The new version has not been run in Windows Calibre or with live audio models here.
The user reported that 0.2.0 worked; the backend, registration, and process lifecycle
files are unchanged. Test source is included under tests/ in this ZIP.

## Historical validation of 0.2.0

# Validation — plugin 0.2.0

The user confirmed the preceding source-patch prototype worked on their Windows
RTX 3070 machine, including the requested playback/lifecycle checks. The plugin
reuses that backend while changing registration, persistence, configuration UI,
and child-process eSpeak environment handling.

## Automated validation in the build environment

- Calibre's **actual 9.16.0 ZIP plugin importer** loads the distributable ZIP and
  discovers its plugin class/import namespace.
- Plugin initialization installs a lazy hook without eagerly importing TTS types
  or starting a server.
- **Actual unpatched Calibre 9.16.0 TTS types/factory source** is loaded through
  that hook. The plugin backend subclasses its TTSBackend and appears in engine
  metadata. Registration is idempotent; disable/version guards work; unrelated
  engine errors still follow the original factory.
- Real PyQt6 settings widgets render; managed prototype import and external
  settings round-trip successfully. Existing prototype JSON is left untouched.
- Real Qt networking/event loop against a local mock speech server verifies
  playback before HTTP completion, sentence offsets, pause/resume, stop/restart,
  stale-response suppression, HTTP errors, and idle cleanup.
- Managed child-process tests verify exit/reuse, inline generated configuration,
  private localhost settings, explicit eSpeak child environment, and no changes
  to the parent environment. External mode never starts or kills a process.
- SSE tests cover all split boundaries, bytewise delivery, errors, invalid base64,
  and truncated responses. Python modules compile; the ZIP is integrity-checked.

**Result: 26 passing tests; 1 Windows-only Job Object test skipped on Linux.**

## Testing boundaries

The stock Linux Calibre 9.16 executable was downloaded for a full installation
test, but fails before Python/plugin startup in this hosted environment because
its `/proc/<pid>/exe` lookup is unavailable. No stock application startup success
is claimed.

The source harness uses Calibre's unmodified ZIP importer and TTS source, real Qt,
and test doubles for surrounding application/configuration services and physical
audio hardware. On the host's Python 3.12, upstream TTS source is compiled with
postponed annotations to accommodate its Python 3.14 forward annotations.

This newly packaged ZIP has not yet been installed in a live Windows Calibre
session here. The Windows Job Object test is included in development tests but
could not run here. There was no new live model/GPU or physical audio benchmark.

## First plugin check on Windows

Install into normal Calibre, import the working prototype settings, save the
eSpeak paths, restart the viewer, and choose **audio.cpp Read Aloud**. Confirm:

1. The new engine appears without `Start-Reader.ps1` or a source override.
2. The existing model speaks with the selected voice.
3. Stop/close terminates the owned server and idle shutdown still works.

If registration fails, include the exact installation/startup traceback, Calibre
version, and whether any `CALIBRE_DEVELOP_FROM` override is still set. For model
errors, include the server log and Read Aloud error text.

## 0.1.1 correction

Added the explicit is_customizable() declaration required by Calibre Preferences.
The regression harness now uses Calibre's actual base customization gate and
checks that it enables this plugin. Settings validate before the dialog closes.

## 0.2.0 Breeze validation

Added tests for instruction-mode payloads, omission of stale Kokoro voice/speed,
reference/transcript validation, the identical reference on every streamed
segment, restoration of both model profiles, and switching back to Kokoro when
Calibre still has a Breeze voice preference saved. These use the real Qt HTTP
path with a mock audio.cpp endpoint; **no live Breeze model inference or VRAM
measurement was performed**. Model configuration/request fields were checked
against audio.cpp documentation/source and the upstream Q4_0 package manifest.
