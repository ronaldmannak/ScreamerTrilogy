# Verification notes

These results cover the staged native Apple Silicon wrappers and the specific checks below. They do not establish every track, camera, mirror or long-session behavior.

## Automated preparation checks

All **18** independent aspect/distance modes passed: Screamer eight, Screamer 2 four and Screamer Rally six. The [machine-readable report](mode-verification.json) records the results; the harness is [tests/verify-trilogy.py](tests/verify-trilogy.py).

The harness checked the expected executable hashes, valid DOS launch paths, repeated launches and switching enhancements back off. In isolated writable copies it preserved the original executable, `SCREAMER.CFG`, available controls configuration files and a binary `PRESERVE.SAV` sentinel. It also checked legacy preference migration, remembered distance levels and temporary command-line overrides. These checks used disposable test data rather than user saves.

The bundle reports record ARM64 host binaries and verified signatures: [Screamer](screamer-verification.json), [Screamer 2](screamer2-verification.json) and [Rally](screamerrally-verification.json). These are local ad-hoc signatures, not a notarization claim.

## Native options and short visual checks

All three options helpers were visually reviewed with their own original loading-screen backgrounds. The Screamer menu showed Original, +20%, +30% and +40% object-visibility choices. Choosing +30% and clicking Play wrote `distance_level: 2` to a disposable preview settings JSON. Quit cancelled the Screamer 2 and Rally previews without committing changes.

Screamer with widescreen and +40% visibility reached a race; holding Up for five seconds produced clean driving/rendering in that short check. An original-settings baseline also reached the countdown. These observations are brief functional checks and do not certify extended play.

Screamer 2 with widescreen and 2× distance reached the England arcade race using the release auto CPU core. The scene rendered cleanly at 30 seconds elapsed. Rally with widescreen and the experimental 2.5× preset reached and rendered the China arcade race; a short acceleration check advanced along the road. Both sessions quit normally. These are short visual checks, separate from the headless memory checks below.

An earlier unattended Screamer +20% widescreen run eventually reported an invalid opcode during its credit/demo loop after approximately 49 minutes. Its cause has not been isolated. The short successful checks do not resolve that observation, and no long-session stability claim is made.

## Live distance persistence

The [live report](tests/live-distance-results.md) documents isolated headless tests using the normal CPU core, dummy video/audio and widescreen off. Rally's 130,000-unit selection persisted across 14 atomic snapshots; Screamer 2's 104,000-unit selection persisted across 11. Every snapshot checked all five actual relocated threshold immediates. In both games a far-plane marker changed from the original -43,808 to -50,000, establishing that scene setup executed while the selected thresholds remained intact.

These headless tests establish threshold persistence through the observed automatic scene setup. They do not establish a visually observed race, performance, or the release auto/dynamic core's stability. [Distance review](distance-review.md) explains the remaining terrain, culling and signed-arithmetic limits.

## Installed copies

All three apps were installed at their existing paths after CRC-verified ZIP backups of the old apps and source files. The installer left user save and preference directories untouched. It compared the installed file contents and permissions with the staged build, verified deep strict signatures and checked every native binary was ARM64. [Installation report](installation-report.json) records the backup paths and hashes.

A final [installed smoke check](installed-smoke.json) prepared the highest supported preset with widescreen and then the original settings in isolated temporary data directories for each installed app. All passed, saved preferences were not written, and the release configuration did not enable the diagnostic HTTP server.
