# Live distance persistence results

Generated 2026-11-25T01:57:25.504893+00:00. Both bounded isolated headless runs passed.

| Guest | Admission radius | All five live threshold values | Successful snapshots | Sample window after startup | UTC timestamps |
|---|---|---|---|---|---|
| Screamer Rally | 130,000 | `0x7dea3120` | 14 | 5.04–70.38 s | 2026-11-25T01:53:31.233208+00:00 – 2026-11-25T01:54:36.578742+00:00 |
| Screamer 2 | 104,000 | `0x5095e200` | 11 | 5.04–55.35 s | 2026-11-25T01:55:55.139050+00:00 – 2026-11-25T01:56:45.450791+00:00 |

In both guests, the original far-plane immediate is -43,808 in the original file. The live immediate was -50,000 while all five configured admission thresholds stayed intact. This is an executed scene-setup marker. The checker also matched all five relocated writer operands to the actual live physical CMP immediate addresses, excluding an unrelocated executable-file copy.

Scope: normal CPU core, 16MiB guest RAM, dummy SDL video/audio, software texture output, no GUI or input automation. These runs validate the distance setting's persistence during automatic scene setup; they do not claim a visually observed race, performance, or stability of the release's auto/dynamic CPU core. Widescreen was off in these isolated runs; the distance-only variants exercised the new setter patch independently.

The API bound only127.0.0.1:9091 and received read-only GET requests. Guest RAM was read in atomic16MiB snapshots and was not saved. Shell history was disabled and capture paths pointed into the diagnostic directory. Test copies/configs/logs are under `/private/tmp/screamer-trilogy-update/tests/`; original game resources and user data were untouched. Every emulator started for these diagnostics was stopped; both successful bounded runs exited0.

## Screamer Rally evidence

- Engine bundle: `/private/tmp/screamer-trilogy-update/release/screamerrally/Screamer Rally.app`.
- Derived distance-only executable SHA-256: `7cbc4aba5d23324be3b1623588dfa49feb89692278e143a82a8ca26f527e1e1b`.
- Machine-readable samples: `/private/tmp/screamer-trilogy-update/tests/headless-live-rally/live-readout.json`.
- Runtime log: `/private/tmp/screamer-trilogy-update/tests/headless-live-rally/runtime.log`.
- Test config: `/private/tmp/screamer-trilogy-update/tests/headless-live-rally/dosbox.conf`.

## Screamer 2 evidence

- Engine bundle: `/private/tmp/screamer-trilogy-update/release-v2/screamer2/Screamer 2.app`.
- Derived distance-only executable SHA-256: `b53e735c3b38cca7697c0a95368ddb5b87fd8aee40a183a5c17d89460766b393`.
- Machine-readable samples: `/private/tmp/screamer-trilogy-update/tests/headless-live-screamer2/live-readout.json`.
- Runtime log: `/private/tmp/screamer-trilogy-update/tests/headless-live-screamer2/runtime.log`.
- Test config: `/private/tmp/screamer-trilogy-update/tests/headless-live-screamer2/dosbox.conf`.

[Official0.83.1 HTTP API protocol and atomic snapshot guarantee](https://github.com/dosbox-staging/dosbox-staging/blob/v0.83.1/website/docs/0.83/manual/http-api.md).
