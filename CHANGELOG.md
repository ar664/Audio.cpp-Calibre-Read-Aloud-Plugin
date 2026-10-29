# Changelog

## 1.0.0

Marked the plugin as the 1.0 release. Build ZIPs now go into build/ and derive their version from plugin metadata. Removed the model-specific Ming3 section from README without changing model support. Added audio.cpp binary selection and runtime instructions based on official v0.9.3 assets.


## 0.9.11

Changed the main toolbar icon label to ?Audio.cpp Read Aloud?.


## 0.9.10

Increased the model preset selector minimum height to 36 logical pixels, growing further for larger fonts.


## 0.9.9

Reorganized Advanced into a compact, top-aligned form followed by full-width JSON editors with labels above. Consistent spacing, shorter labels and a scrollable page keep growing editors from spreading out the controls.


## 0.9.8

Path and value fields now wrap and grow up to four visible lines, including executable, model, eSpeak, working directory, URL and voice lists. Wrapped values remain single logical values; Enter/Tab move focus. Voice conditioning retains its compact fields.


## 0.9.7

Text areas outside Voice conditioning now grow and shrink using rendered line heights, including word wrapping. Advanced editors grow up to twelve visible lines before scrolling, retaining a compact layout for short input. Corrected the earlier line-count-as-pixels sizing calculation.


## 0.9.6

Compacted Advanced tab spacing and JSON editor heights.


## 0.9.5

Editable text boxes outside Voice conditioning expand to fit their contents. Voice and transcript fields remain compact.


## 0.9.4

Moved transcript text-file import beside the reference transcript editor.


## 0.9.3

Added reference transcript import from text files, with encoding and size checks. Added on-demand model dependency checks using local specs/manifests, configured companion paths and MioCodec resolution; reports missing or unverifiable files.


## 0.9.2

Fixed MioTTS codec selection for audio.cpp 0.9.3: use a MioCodec GGUF instead of the legacy raw checkpoint. Accept explicit codec GGUF paths and auto-discover the GGUF package inside/beside MioTTS. Reject ambiguous or raw codec directories with actionable errors. Installed the smallest MioCodec Q8 package locally. HTTP speech tests with the old test reference and Sample.wav both recovered the requested sentence exactly in ASR. Evidence: validation/miotts-0.9.2/.


## 0.9.1

Added voice preview with editable text, playback cancellation and unsaved-settings support. Added named WAV/transcript reference voices shared across presets.


## 0.9.0 ? preview for 1.0

Refreshed settings with a title, grouped sections, consistent control spacing, a clearable preset search and a larger settings window. Prevented applying a preset when filtering produces no selection. Added repository ignore rules, a release checklist and feature roadmap.


## 0.6.12

Added case-insensitive preset filtering across model name, support type and features, plus sortable preset table columns.


## 0.6.11

Moved Browse package directory beside the model path Browse button.


## 0.6.10

Added an Inference mode selector to Server and model. The choices follow the selected model family and update its server configuration entry.


## 0.6.9

Kokoro and Breeze-TTS-2 now use catalog-based family presets, including the full Kokoro voice list and offline defaults. Legacy profile aliases and custom saved server settings remain supported. Known legacy voice lists migrate to catalog voices. Release history moved out of README; added development guidance in AGENTS.md.

## 0.6.7?0.6.8

Removed the prototype import button, hid idle timeout when keeping the server loaded, limited voice conditioning tab visibility and compacted its layout.

## Earlier releases and validation

## Model test results

The original audio.cpp 0.9.2 executable and its GGUF packages were tested on Windows with
Calibre 9.17.0, an NVIDIA RTX 3070 with 8 GB VRAM, and the CUDA backend. The test
used the smallest published package for each family when it could run with its
required files and generated short offline samples.

**Original sweep: 51 of 51 TTS families with available GGUF packages in that executable
passed.** Fifty were exercised through the plugin's speech request path.
MiniMax-H3 was exercised through audio.cpp's `gen` task, which is its supported
audio-generation route. Every passing case produced a nonempty WAV; these smoke
tests confirm inference and output handling, not subjective speech quality.

PocketTTS used the English Q8 package (134 MB) because the smaller German Q8
package omits the required `alba.safetensors` voice embedding. MioTTS was tested
with its required MioCodec and WavLM companion files.

**Ming3-TTS follow-up: 16 of 16 cases passed on audio.cpp 0.9.3**
(`41c1f8ff`, CUDA, RTX 3070). Default synthesis, all four built-in voices, voice
design, reference audio, and reference audio with a transcript passed in both
offline and streaming modes, producing nonempty 44.1 kHz mono audio. Tests used
English text and the smallest published package, Q8_0 (1,742,280,896 bytes).
Results are in [`validation/model-tests/ming3-results.json`](validation/model-tests/ming3-results.json).

This brings recorded coverage to **52 families**. The other 51 have not been
retested with 0.9.3. Gradium Phonon, Ming 3 Audio, and XTTS v2 were unavailable in
the original binary; MiraTTS had no published GGUF package in that catalog.
Those four entries remain untested here.

**Read Aloud and cloning fix in 0.6.2:** tested with `Sample.wav` and `Sample.txt`
through the actual Calibre backend, including silent prewarming, sentence
splitting, Qt HTTP requests, highlighting, and the physical audio sink at muted
volume. Full-reference cloning passed in offline and streaming modes; a short
excerpt with its matching transcript also passed. Local Moonshine ASR recovered
the complete test text in all three cases (0% word error rate). CAMPPlus speaker
similarity to the reference was 0.869 for the clone versus 0.216 for a preset
control. These measurements support intelligibility and speaker conditioning;
they do not replace listening to the generated sample.
Reports and WAVs are in `validation/ming-read-aloud/`.

Detailed per-family results, selected packages, audio metadata, timings, and WAV
paths are in [`validation/model-tests/matrix-results.json`](validation/model-tests/matrix-results.json).
The package inventory and exclusions are in
[`validation/model-downloads.json`](validation/model-downloads.json).

## Automated validation

Version 0.6.3 adds the Ming3 clone choice to the viewer. Actual backend tests
confirmed clone and built-in selection: clone output had 0% ASR word error rate;
US_Emma had 22.2%, with recognition errors near the end. See [TESTING.md](TESTING.md).

The 0.6.3 plugin suite ran 33 tests with Calibre 9.17.0: 32 passed and one
POSIX-only GPU subprocess fixture was skipped on Windows. Coverage includes
family request construction, settings and profile persistence, audio decoding,
mock-server playback/lifecycle, and loading the plugin ZIP through Calibre's
importer. See [TESTING.md](TESTING.md) for details and test limitations.

## Settings improvements in 0.6.4

Voice conditioning (mode, instructions, reference WAV and transcript) carries across preset changes. The main Calibre window has an audio.cpp settings toolbar icon. Restart Calibre after updating.

Selecting a GGUF or package directory shows a rough memory estimate (1.5 times weight size plus 1 GiB) and warns when it exceeds available RAM or CUDA VRAM. Directory estimates include all weight files, so packages containing alternate models can overestimate usage. Other GPU backends show that VRAM could not be checked. Actual runtime requirements vary.

The model preset dropdown has Model, Support type, and Model features columns. Support type is the upstream catalog status, not a local test result. Features summarize catalog modes, voices, conditioning controls, languages, speed control, and eSpeak requirements. Hover over a cell to read its full text.

## DotTTS and MioTTS checks in 0.6.6

DotTTS Q8 cloning was checked with Sample.wav and Sample.txt, using both the full 24.25-second recording and a 4.2-second excerpt with its matching transcript. Both generated the requested sentence with 0% ASR word error rate. CAMPPlus speaker similarity for the full-reference output was 0.847, compared with 0.216 for an unrelated voice. These are automated checks, not human listening results.

MioTTS package directories now resolve the main GGUF and locate MioCodec-25Hz-44.1kHz-v2 inside or beside the package. Relative miotts.codec_model_path session options resolve against the selected package; absolute paths remain supported. Select a GGUF directly if a directory contains multiple GGUF variants.

MioTTS loaded successfully using both automatic directory resolution and explicit GGUF/codec paths on audio.cpp 0.9.3. Both produced the same incorrect transcription ("Thank you." instead of the requested sentence), so speech quality remains an open issue independent of directory resolution. Reports and audio are in validation/dots-mio/.

The main-window button uses a custom waveform icon, displays Read Aloud underneath, and follows the existing toolbar icon dimensions.
