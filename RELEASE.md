# 1.0.0 release

1.0.0 is the release version. This does not mean every catalog model has been validated.
Build output: `build/audio-cpp-read-aloud-1.0.0.zip`; checksum: adjacent `.zip.sha256`.
Calibre support remains 9.16.x and 9.17.x. Test with the bundled audio.cpp 0.9.3
and the smallest working model packages. Preserve historical evidence.

## Release validation checklist

This checklist documents the process, not a claim that every manual scenario has been completed. See TESTING.md for executed checks.

- Install from ZIP into a clean Calibre profile and upgrade from existing settings.
- Check light/dark themes, common Windows scaling settings and smaller screens.
- Exercise preset filtering (including no matches), column sorting, profile switching,
  mode selection, settings save/cancel, reference persistence and toolbar access.
- Read several pages: play/pause/resume/stop, highlighting, punctuation, long sentences,
  prewarm, keep-loaded behavior, idle shutdown and closing the owning viewer.
- Check offline and streaming with models supporting each route; confirm PCM format.
- Verify stale voice selections and unsupported conditioning never leak across families.
- Verify missing models/codecs, unavailable server, HTTP errors and malformed streams
  fail clearly and release owned resources.
- Check model quality separately from valid WAV output. DotTTS/Ming cloning have
  objective supporting evidence; MioTTS requires the GGUF codec on 0.9.3 (fixed in 0.9.2). Include its new speech checks in release evidence.
- Run unit tests and the real Calibre importer check; record environment and results.
- Align metadata, README, changelog and package version; inspect ZIP contents and
  publish a SHA256 checksum. Keep binaries, models and personal reference audio out.

## Future features

Voice preview, named reference voices and local dependency checks are included in 1.0.
Potential next additions: favorite presets, per-book voice preferences, chapter audio export,
and diagnostic reports with private text/paths redacted.
