# Development notes

This is a Calibre InterfaceAction plugin with a registered internal TTS backend.
Work from this directory in PowerShell on Windows. No git repository is present.
Do not edit Calibre's installed source files or kill the user's Calibre/viewer processes.

## Architecture

- `__init__.py`: plugin metadata, version and deferred registration.
- `registration.py`: Calibre 9.16/9.17 compatibility guards and backend registration.
- `backend.py`: Qt networking, sentence queue, highlighting and audio playback.
- `core.py`: speech request construction, WAV/SSE decoding, managed server ownership,
  and Mio package resolution. Preserve server mutex and Windows kill-on-close job behavior.
- `profiles.py`, `settings.py`: catalog presets, legacy aliases, saved profiles and migration.
  Preserve custom paths/options. Voice conditioning follows the user across presets.
- `config.py`: settings tabs and catalog dropdown; `action.py`: main-window toolbar.
- `model_catalog.py`: generated catalog; refresh via `validation/build_catalog.py --family NAME`
  against `bin/model_specs`. Do not discard families absent from an older binary's catalog.

## Local environment

Calibre executables: `C:\Program Files\Calibre2`. Tested Calibre version: 9.17.0.
audio.cpp executables and specs: `bin/`, last checked version 0.9.3 (41c1f8ff).
Models: `models/`; use the smallest working package for inference tests.
GPU: RTX 3070, 8 GiB VRAM. Run GPU model tests sequentially and close owned servers.
Live settings: `%APPDATA%\calibre\plugins\audio_cpp_read_aloud.json`.
Live archive: `%APPDATA%\calibre\plugins\audio.cpp Read Aloud.zip`.
Use isolated CALIBRE_CONFIG_DIRECTORY and QT_QPA_PLATFORM=offscreen for automated checks.
Back up the installed archive before replacing it. Users must restart Calibre and viewers
after a plugin update; never claim an already running viewer loaded the new code.

## Validation and packaging

`calibre-debug.exe -e validation/compatibility.py` builds the versioned ZIP in build/,
loads it through Calibre's importer, and checks registration and settings construction.
The archive version is read from `__init__.py`. Include CHANGELOG.md in the ZIP.
Unit suite: run unittest discovery for `tests` using calibre-debug; initialize tempfile
first (`import tempfile; tempfile.gettempdir()`) for the Qt test harness.
Tests stub some Calibre/Qt imports: also use the real importer for integration changes.
Keep release changes in CHANGELOG.md, current usage in README.md, detailed evidence in TESTING.md.

## Model caveats and evidence

- Valid/nonempty WAV output does not establish intelligibility or cloning quality.
  Use local Moonshine ASR and, where useful, speaker embeddings; distinguish these
  measurements from human listening. Historical matrix tests only checked audio generation.
- Sample.wav and Sample.txt are user-provided clone references. Full WAV: 24.25 s,
  stereo 48 kHz. Keep reference text matched to the exact audio excerpt.
- Ming3 uses 44.1 kHz mono; built-in voices require IP template/voice_id.
  Long references with transcripts caused garbled output. The plugin's 10-second
  acoustic-reference cutoff is a conservative workaround, not an upstream hard limit.
  Do not reintroduce the unsuccessful resampling workaround.
- DotTTS short/full reference tests passed ASR; full-reference speaker cosine 0.847.
- MioTTS 0.9.3 needs the MioCodec GGUF package, not the older raw safetensors checkpoint.
  Version 0.9.2 resolves the GGUF codec; HTTP tests now recover the requested text.
  Keep the older failure evidence; see validation/miotts-0.9.2/ for new results.
- Evidence: validation/ming-read-aloud/, validation/dots-mio/, validation/model-tests/.
  Preserve historical results and version labels when adding new runs.
