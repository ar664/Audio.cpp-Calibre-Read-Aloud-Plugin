# audio.cpp Read Aloud for Calibre

Version 1.0.0 is a Calibre plugin that reads ebook text using a local audio.cpp
speech server. It adds **audio.cpp Read Aloud** to Calibre's existing Read Aloud
engine list and uses the viewer's normal play, pause, stop, voice, and highlighting
controls.

## Compatibility

- Supported Calibre versions: **9.16.x and 9.17.x**. The plugin uses internal
  Calibre TTS interfaces and intentionally does not register on other versions.
- The settings widget and plugin ZIP were validated with Calibre 9.17.0.
- Model support depends on the audio.cpp executable, model files, backend, and
  model-specific companion assets. The plugin does not install or update them.

## Download audio.cpp

Download an executable **bin** package from the [official audio.cpp v0.9.3 release](https://github.com/0xShug0/audio.cpp/releases/tag/v0.9.3), the version used for this plugin's recent model checks. Choose the package matching your operating system and compute backend:

| System / backend | Release asset |
| --- | --- |
| Windows x64, CPU | `audio-v0.9.3-bin-windows-x64-cpu.zip` |
| Windows x64, NVIDIA CUDA 12.4 | `audio-v0.9.3-bin-windows-x64-cuda12.4.zip` |
| Windows x64, NVIDIA CUDA 13.3 | `audio-v0.9.3-bin-windows-x64-cuda13.3.zip` |
| Windows x64, Vulkan | `audio-v0.9.3-bin-windows-x64-vulkan.zip` |
| Linux x64, CPU | `audio-v0.9.3-bin-ubuntu-x64-cpu.tar.gz` |
| Linux x64, Vulkan | `audio-v0.9.3-bin-ubuntu-x64-vulkan.tar.gz` |
| macOS Apple Silicon, Metal | `audio-v0.9.3-bin-macos-arm64-metal.tar.gz` |
| macOS Intel, Metal | `audio-v0.9.3-bin-macos-x64-metal.tar.gz` |

Choose CPU if you do not have a supported GPU/backend. CUDA requires a compatible NVIDIA driver; pick a CUDA version supported by your driver. If CUDA runtime DLLs are missing, download the matching runtime asset (for example, `audio-v0.9.3-cudart-windows-x64-cuda12.4.zip`) and place its DLLs beside the executables. Keep the binary and runtime versions matched. The release also offers portable CPU/Vulkan builds and experimental ROCm test packages; check upstream notes before choosing those.

Extract the whole archive to a permanent folder, such as this project's `bin/`. Keep its backend libraries, `model_specs/` and companion files together. In **audio.cpp executable**, select **audiocpp_server.exe** on Windows or **audiocpp_server** on Linux/macOS, then choose the matching compute backend. The CLI executable is for diagnostics; library-only `lib` packages and source-code archives do not supply the required server setup by themselves. Download GGUF model packages separately into `models/` and run **Check model dependencies** after selecting one.

Windows with CUDA is the locally validated environment; the other package names above are available upstream but have not been validated here.

## Install and configure

1. In Calibre, open **Preferences > Plugins > Load plugin from file** and select
   `audio-cpp-read-aloud-1.0.0.zip`. Restart Calibre and all ebook viewers after installing or updating.
2. Select **Audio.cpp Read Aloud** icon from the main menu **OR** Open **Preferences > Plugins**, select **audio.cpp Read Aloud**, and click
   **Customize plugin**.
3. Choose a **Model preset** and click **Use preset**. Select the audio.cpp
   executable, backend, and model GGUF file or complete package directory. For an
   external server, choose external ownership and enter its URL instead.
4. Set the model's voice and language. Use **Voice conditioning** for a reference
   recording and its exact transcript when the model supports or requires them.
   Instructions only apply to models with an instruction option.
5. Save the settings, open a book, select **audio.cpp Read Aloud** as the engine,
   and press Play.

The preset list covers the TTS families in the bundled model catalog. All presets, including Kokoro and Breeze-TTS-2, use their audio.cpp family settings. Each model profile remembers its model path, options and voices. Voice conditioning carries across preset changes. The **Model help** tab lists catalog languages, voices,
and model options.

New presets default to offline WAV generation. The server returns the generated
sample rate and channel count with the WAV. Existing saved streaming configurations are preserved. Families can use streaming when the audio.cpp model supports it;
choose **Streaming** in **Inference mode** and configure the model's native PCM
rate, channels, and request options under **Advanced**. See the [audio.cpp server
configuration](https://github.com/0xShug0/audio.cpp/blob/main/app/server/README.md)
and [speech API](https://github.com/0xShug0/audio.cpp/blob/main/app/server/api.md)
for model-specific requirements.

The plugin does not download models. Choose a complete package and keep its
tokenizers, codecs, voice embeddings, and other required files in the layout
expected by audio.cpp. Model files are large and may have separate licenses from
the plugin.

## Server and voice settings

- **Managed server** starts and stops the selected local executable. The plugin
  permits one managed server owner at a time; a second viewer cannot start a
  duplicate. Closing the owning viewer stops its server.
- **External server** connects to the supplied URL and does not manage that
  server's lifetime.
- **Idle shutdown** defaults to 60 seconds after reading finishes. Set it to zero
  to shut down immediately. **Pre-warm** loads the selected model when a viewer
  opens. **Keep loaded** retains it while the owning viewer remains open and
  disables idle shutdown.
- **eSpeak setup** appears for models that use eSpeak. These models need a working
  eSpeak library and matching data directory.
  Use **Find eSpeak installed with Python** or select the paths manually. The
  plugin passes these paths to its managed server without changing system
  environment variables.
- The optional performance overlay shows available GPU and system memory,
  utilization, warmup and streaming timings, queued audio, and generation speed.
  GPU readings are device-wide; unavailable counters display N/A.
- Custom pronunciations replace whole words or phrases in spoken text. Enter
  phonetic respellings in **Pronunciation**. Book text and highlight positions
  remain unchanged; matches must fit within one spoken segment.

Advanced settings include request options JSON and the full audio.cpp server
configuration. The selected executable, backend, and model path in the main tab
take precedence over corresponding JSON fields. Use model help and upstream
documentation when setting variant-specific task, load, or session options.

## Validation

See [CHANGELOG.md](CHANGELOG.md) for release history and model test results, and [TESTING.md](TESTING.md) for validation details.

## Logs and removal

The managed server log is `plugins/audio_cpp_read_aloud-server.log`; preferences
are stored in `plugins/audio_cpp_read_aloud.json` under Calibre's configuration
directory. Open it from **Preferences > Miscellaneous > Open calibre
configuration directory**. Book text is sent to the configured local server.

To remove the plugin, close ebook viewers, remove **audio.cpp Read Aloud** under
**Preferences > Plugins**, and restart Calibre. Model and executable files and
saved preferences are not deleted.

Plugin source is provided under GPL-3.0-or-later; see [LICENSE](LICENSE). Calibre,
audio.cpp, and model packages retain their respective licenses.


The Read Aloud toolbar icon opens settings. The preset dropdown shows upstream support type and model features. Voice conditioning appears for families with relevant controls; eSpeak setup appears where required. Never shut down hides the idle timeout.

Model selection displays a rough memory estimate (1.5 times weight size plus 1 GiB), compared with available RAM and CUDA VRAM. Directory totals include alternate weight files.

For MioTTS, select a GGUF or a package containing one GGUF. The plugin locates MioCodec-25Hz-44.1kHz-v2-GGUF inside or beside the package. An explicit miotts.codec_model_path in session_options is also supported. Use a MioCodec GGUF file with audio.cpp 0.9.3; the earlier raw safetensors codec produced incorrect speech. See the changelog for validation.

## Release information

See [RELEASE.md](RELEASE.md) for packaging and release checks, and [TESTING.md](TESTING.md) for validation evidence and its limits.

## Voice preview and reference library

Use **Voice preview** to play up to 2,000 characters using the current unsaved model and voice settings. Stop cancels playback and releases a managed preview server. Close settings to stop it automatically. Another viewer holding the managed server must release it before a preview can start.

Under **Voice conditioning**, choose a reference WAV and transcript, then **Save as?** to name the voice. Select a saved name and click **Load** to use it. **Remove** removes the library entry, not the recording. Library changes persist when you save the settings and are shared across presets.

Use **Check model dependencies** to inspect the selected package against installation manifests and adjacent audio.cpp model specifications, configured companion paths, MioCodec and reference files. Missing metadata is reported as unverified. This is a file check, not an inference test.

**Load transcript from text file?** imports UTF-8 (with or without BOM) or BOM-marked UTF-16 into the editable transcript field. Save settings or a named reference voice to retain the imported text; changes to the source file are not loaded automatically.
