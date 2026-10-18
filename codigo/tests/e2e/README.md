# Chest Link E2E lab

The lab runs the native Linux PC server, the shared C++ protocol, melonDS and
Azahar using isolated storage. The private FireRed matrix checks actual PK3
records in both emulators, including all six transfer directions and updates.
Normal release executables have a separate UI smoke test.

## Test surfaces

| Surface | What a PASS proves |
| --- | --- |
| `HOST` / `HOST_PROTOCOL` | The native server, APIs, storage and shared protocol work on the PC. |
| `EMULATOR` | The normal core/network/storage code ran inside melonDS or Azahar with a test-only entry point. |
| `EMULATOR_NORMAL_UI` | The normal release executable sent the selected bank through its ordinary UI; the server verified the bytes. |
| Physical console | A separate hardware test is required. Emulator results do not establish radio, flashcard or physical ExtData behavior. |

The isolated probe builder substitutes `tests/e2e/console_probe.cpp` for
`app.cpp` in `build/e2e/console-probe/source` and defines `CHEST_LINK_E2E` there
only. It keeps the existing core, platform, network, protocol, bank and updater
code. Automatic offer acceptance and test configuration exist only in this
pair. Normal release sources, binaries, manifests and confirmations stay intact.

## Requirements

- Linux, Python 3.9+, `make`, a host C++ compiler and Podman as configured for
  paired console builds. The required compiler images must already be available.
- melonDS and Azahar. Set `CHESTLINK_MELONDS` and `CHESTLINK_AZAHAR` to local
  executable paths, or install them on `PATH`.
- A graphical session for emulator runs. The ordinary UI driver additionally
  requires X11, `wmctrl`, Pillow and python-xlib. Structured probe assertions
  use emulator logs, not OCR or desktop screenshots.

Use official downloads:
[melonDS](https://melonds.kuribo64.net/downloads.php),
[Azahar](https://github.com/azahar-emu/azahar/releases).
AppImages may be installed under `~/.local/bin` without root access.
Do not add game ROMs, proprietary BIOS/firmware, keys or NAND to this repository.
Use system files from your own console when required by the emulator.

```sh
export CHESTLINK_MELONDS="$HOME/.local/bin/melonDS"
export CHESTLINK_AZAHAR="$HOME/.local/bin/azahar"
make -C codigo consoles
make -C codigo console-ports-test test mailbox-test gui-test e2e-harness-test
make -C codigo e2e-probe-build
```

### Initial Azahar setup

Use the isolated profile under `codigo/build/e2e/profiles/azahar`, created by:

```sh
make -C codigo e2e-3ds
```

If system files are required, configure that profile using the official
[Artic Setup Tool](https://github.com/azahar-emu/ArticSetupTool) and files from
your own console. The private runner copies this profile's `sysdata`, `nand`
and `qt-config.ini` into each run. It enables custom storage and overrides
`sdmc_directory` to the run's own SD folder. Your everyday Azahar profile is
not used. Boot the isolated profile once before running automated probes.

### melonDS networking

The run profile enables DLDI folder sync, disables external BIOS and selects
Slirp NAT. It saves the virtual `melonAP` SSID. The guest receives
`10.64.0.16`; `10.64.0.1` is the virtual gateway and reaches the host's loopback
services. Use `10.64.0.1` for DS-to-PC and DS-to-Azahar tests in this lab.
Do not substitute the guest's address for the host address.

For inbound DS transfers, stock NAT needs an explicit host-to-guest forward.
The optional builder downloads official open-source melonDS 1.1, checks its
archive hash, adds a small lab-only Slirp forward and builds a local emulator:

```sh
python3 codigo/tests/e2e/build_melonds_forward.py
export CHESTLINK_MELONDS="$PWD/codigo/tests/e2e/melonds_forward.py"
```

The source, executable and compiler cache remain under ignored `build/e2e`.
The dependency image is `localhost/chestlink-melonds-e2e:1.1`. The wrapper runs
it with the isolated profile and X11 display. Only a DS receiver sets
`CHESTLINK_DS_FORWARD=40991`, binding host loopback 40991 to guest 40991.
No router, NetworkManager or host firewall settings are changed. Set
`CHESTLINK_MELONDS_FORWARD_BINARY` or `CHESTLINK_MELONDS_FORWARD_IMAGE` to
use another locally built executable/image. Keep these generated files local.

## Private FireRed regression

Set the path to a private copy of a raw 128 KiB FireRed save:

```sh
export CHESTLINK_FIRERED_SAVE="$HOME/Saves/FireRed.sav"
make -C codigo e2e-firered
```

Without the variable, the private matrix prints `SKIP`. Missing emulators skip
the emulator matrix while the PC scenario still runs. Inbound DS scenarios skip
unless the forwarding wrapper is selected. Every skipped scenario is a limit
of that run, not evidence of a pass.

The test-only read adapter validates complete FRLG save slots and sector/PK3
checksums. It copies the latest slot's encrypted PK3 records into a private
PKSM v3 bank: 14 original boxes plus a 15th box containing a copy of the party.
It does not edit the save or implement a native-save import feature in the
product. Empty slots are canonicalized; occupied PK3 bytes remain unchanged.
The private save is never passed to an HGSS parser.

The matrix runs:

- PC boxes/previews, collection registry, individual selection to both targets,
  delivery ACK, retry, explicit resend, pending cleanup, progress persistence
  and server restart.
- DS and 3DS preview of the same bank.
- DS → PC and 3DS → PC; exact received bank bytes and counts.
- PC → DS and PC → 3DS by mailbox fetch and direct push; imported SHA-256,
  PK3 count, confirmed delivery and preserved PC original.
- DS → 3DS and 3DS → DS directly; both bank hashes, sender preservation and ACK.
- DS and 3DS updates; installed executable hash and preserved private bank.
  The 3DS scenario also verifies the previous executable backup.

To use a different previous 3DS executable for the backup assertion:

```sh
export CHESTLINK_3DS_PREVIOUS_APP="$HOME/Downloads/previous/ChestLink_3DS.3dsx"
```

A release ZIP containing exactly one `ChestLink_3DS.3dsx` is also accepted.
Without this variable, the current executable seeds the installed path while
the test simulates an older version. This tests download/install/backup logic;
it is not a claim about booting an older release.

The complete matrix can reuse the compiled test pair:

```sh
python3 codigo/tests/e2e/firered_suite.py --no-build
python3 codigo/tests/e2e/firered_suite.py --no-build --normal-ui
```

`--normal-ui` additionally navigates the ordinary release binaries on X11.
Pixel checks synchronize menus only; the native PC server's bank bytes and
counts determine PASS. Keep other emulator windows closed so the driver can
identify the lab window. The test copies the release executable into the run
folder so emulator auxiliary save files cannot modify the source directory.

### Individual scenarios

Run from the checkout root after configuring the private save:

```sh
python3 codigo/tests/e2e/pc_firered.py
python3 codigo/tests/e2e/probe_runner.py ds preview
python3 codigo/tests/e2e/probe_runner.py ds upload --ip 10.64.0.1
python3 codigo/tests/e2e/probe_runner.py 3ds upload --ip 127.0.0.1
python3 codigo/tests/e2e/probe_runner.py ds fetch --ip 10.64.0.1
python3 codigo/tests/e2e/probe_runner.py 3ds fetch --ip 127.0.0.1
python3 codigo/tests/e2e/probe_runner.py ds direct_receive
python3 codigo/tests/e2e/probe_runner.py 3ds direct_receive --ip 127.0.0.1
python3 codigo/tests/e2e/paired_transfers.py ds_to_3ds
python3 codigo/tests/e2e/paired_transfers.py 3ds_to_ds
python3 codigo/tests/e2e/probe_runner.py ds update --ip 10.64.0.1
python3 codigo/tests/e2e/probe_runner.py 3ds update --ip 127.0.0.1
python3 codigo/tests/e2e/normal_ui_transfer.py ds --auto-ui
python3 codigo/tests/e2e/normal_ui_transfer.py 3ds --auto-ui
```

Without `--auto-ui`, the normal UI scenario waits for manual navigation:
consult banks → `firered` → X (all boxes) → send to PC → confirm stored IP/PIN.
Do not navigate other user profiles during these tests.

## Existing public scenarios

```sh
make -C codigo e2e-server
make -C codigo e2e-protocol
make -C codigo e2e-ds
make -C codigo e2e-3ds
make -C codigo e2e-ds-to-pc
```

`server_boot` starts a separate native server, checks TCP/web/authenticated API
readiness and closes the port. `protocol_ds_to_pc` uses a generated public bank
and the shared host C++ client. These do not require a real save.
`ds_boot`, `3ds_boot` and the original `ds_to_pc` scenario remain
semiautomatic public-fixture checks. `run.py all` / `make e2e` runs existing
local tests and these scenarios; use the separate FireRed matrix for the
private emulator regression.

`run.py --no-build` uses existing release binaries; `--emulators none` skips
emulators and `--emulators required` requests them in noninteractive runs.
`CHESTLINK_E2E_TIMEOUT_SECONDS` controls the original semiautomatic wait.

The older optional HGSS scaffold recognizes `CHESTLINK_HGSS_SAVE` and is kept
for compatibility with the initial lab specification. `make e2e-hgss` skips
without that variable. Its PC reader and normalized snapshot comparison are
separate from bank transfer tests; console native-save adapters remain absent.
It is not part of the FireRed matrix and does not validate FireRed content.

## Isolation, artifacts and cleanup

Every scenario creates a private `codigo/build/e2e/run-*/` directory with
server data, emulator profiles/storage, logs, artifacts and a `private` area.
The original save is opened for reading and guarded by hash/file metadata
checks before and after each scenario. Source banks and PC backups are checked
again after transfers and updates.

- `artifacts/result.json` records status, surface, reason and nonpersonal metrics.
- Structured emulator details and actual save-derived banks stay in `private/`.
- DS debug output uses short `CHESTLINK_E2E:` fields; Azahar uses its debug log.
- Normal UI navigation failures save only the emulator screens in `private/`.
- `build/` and local fixtures are ignored by Git. Never upload a private run,
  real save or screenshot containing private records to public CI or an issue.

Probe servers use fresh storage and available temporary ports. Normal UI smoke
uses TCP 40992; DS direct reception uses loopback 40991. Check these ports first
and preserve any existing user listener. The normal driver does not stop a
server it did not start. Each run tracks its process groups and container ID,
closes emulator/server processes in `finally`, and preserves artifacts on
failure. AppImage children are cleaned even when their launcher has exited.

## Troubleshooting and limits

- Run `make e2e-probe-build` again after source changes. Release executables are
  built separately with `make consoles`; never publish the probe pair.
- A missing Azahar isolated profile requires the initial setup above.
- A DS receiver timeout with stock melonDS requires NAT forwarding; check
  loopback 40991 is free. A forwarding failure is not a hardware result.
- In the BlocksDS/newlib SDK used here, socket error **113 is ECONNABORTED**.
  Linux uses a different number for this error. Do not label DS error 113 as
  Linux `EHOSTUNREACH` or conclude that the host's internet is down.
- Closing an emulator before its structured result is written is a failure,
  not a pass. Check its run log for the last stage and reason.
- UI smoke depends on the current menu layout and X11 scaling. A navigation
  timeout must be distinguished from a transport failure or byte mismatch.
- Emulators cannot validate physical Wi-Fi/AP support, radio performance,
  actual flashcards, real 3DS ExtData or reboot behavior after updating.
- CI can run host tests and public server/protocol scenarios. Private saves,
  GUI sessions and emulator system files are optional local requirements.
