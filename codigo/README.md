# Chest Link 0.5.1

Chest Link is a homebrew tool for copying selected Pokémon or entire boxes between Pokémon Chest storage on DS/DSi and PKSM storage on 3DS. It includes a Nintendo DS app, a 3DS Homebrew Launcher app, and a PC mailbox with a browser interface.

**[Latest public download: Chest Link 0.4.28](https://github.com/kovaleski100/chest-link/releases/tag/v0.4.28)** · [Browse the source code](https://github.com/kovaleski100/chest-link/tree/main)

Chest Link 0.5.1 fixes the DS app getting stuck while searching for the PC on
some DSWifi setups. Updates try the saved PC address first; if it does not
respond, the app searches the network and uses the address it finds. If the
search finds no PC or its address does not respond, it lets the user enter an
IP; only a failed manual connection produces the server-not-found message. The
DS connection and search waits have frame-based limits and can be canceled
with B.

Chest Link leaves original game saves unchanged. You can browse Chest/PKSM banks or read Pokémon boxes from supported `.sav` files on the console's SD/flashcard, then save selected Pokémon to a new Chest Link bank before sending them to the PC.

## Project status

Console-to-PC transfers are working. All six transfer directions have also passed local emulator tests with private FireRed-derived bank records. Console-to-PC was checked through the normal app interface; the other directions used isolated test builds with the normal transfer core. Direct transfers between consoles and PC-to-console delivery still need validation on real hardware.

Keep your existing backups and try one box first. Chest Link creates a new bank at the destination and leaves the source bank intact.

## What each version does

### PC

The PC can act as a mailbox and storage box. Send a copy from either console and leave it on the PC while the other console is turned off. Later, use the browser interface to inspect the stored banks and boxes, select Pokémon, and start delivery to a DS or 3DS. The PC keeps its backup after delivery.

The PC server has one source tree in `codigo/server`. The `PC` folder contains only launchers and `dados`; the package includes the same server source once, with a small launcher in `PC`.

The PC interface includes offline Pokédexes for Generations I and II: Red, Blue, and Yellow cover Kanto; Gold, Silver, and Crystal cover Johto. It can show species received in verified copies stored on the PC and track manual progress in one combined list or separately by game within each generation. The HOME grid uses the names and base sprites in the local catalogue. Regional Dex appears on the left and National Dex on the right, and both counters remain visible when their totals match. Each generation’s National comparison uses the species known by that generation; Generation I covers 151 species and Generation II covers 251. Regional totals come from the regional species lists, including Johto’s regional order. HOME uses the full catalogue for both counters. Species pages include evolution methods, encounter locations, search, and filters for types and version availability. Server-received species count separately from manual progress.

### DS / DSi

The .nds app reads Pokémon Chest banks from the flashcard or SD storage available to the console. Browse boxes, select individual Pokémon or whole boxes, then send the selection to the PC or directly to another console. It can also receive copies from the PC or a 3DS into a new bank that you can open in Pokémon Chest.

On DS and DS Lite, Wi-Fi requires a compatible 2.4 GHz 802.11b network. Open and WEP connections use the NTR radio's established path. The current app also includes an experimental WPA2-Personal/AES-CCMP implementation for the NTR radio; its cryptography and packet handling pass simulated tests, but receiving WPA2 traffic on a physical DS has not yet been validated. A DSi running the app in DSi mode uses the console's native WPA2 networking. A DSi running homebrew in DS mode uses the NTR radio path.

### 3DS

The .3dsx app runs through the Homebrew Launcher and reads PKSM banks from ExtData or the SD card, depending on the PKSM configuration. It can also read Chest banks on the SD card when present. Select Pokémon or boxes to send to the PC or another console, and receive copies into a new bank for PKSM or Chest.

The 3DS uses its own saved Wi-Fi configuration, including WPA/WPA2 and DHCP. Chest Link does not replace the console's network settings.

## Transfer options

| Action | What needs to be on |
| --- | --- |
| Console to console | Both consoles run Chest Link on the same local network. The destination waits; the sender starts the transfer. |
| Console to PC | The sending console and the PC server run on the same local network. The other console may be off. |
| PC to console | The PC server and destination console run on the same local network. Start delivery from the PC interface; the console asks before saving. |

Transfers use the local network and do not need an internet connection or Nintendo services. The network must allow devices to communicate with each other. Guest networks with client isolation may prevent transfers.

The direct console connection uses TCP port 40991. Console-to-PC and PC-to-console mailbox traffic uses TCP port 40992. The browser interface uses TCP port 8765 by default. Do not forward these ports to the internet.

## Installation

You need an existing homebrew setup on your console. The PC mailbox requires Python 3.9 or newer and uses only the Python standard library.

1. Download and extract the Chest Link package to a regular folder on your PC. Do not run the server from inside the ZIP.
2. For DS or DS Lite, copy DS/ChestLink_DS.nds to the flashcard you already use to launch Pokémon Chest.
3. For DSi, copy the same .nds file to the internal SD card and launch it with TWiLight Menu++. Use DSi mode if you need the DSi's WPA2 support.
4. For 3DS, copy the 3ds/ChestLink_3DS folder from the package into the SD card's 3ds folder. The app should be at SD:/3ds/ChestLink_3DS/ChestLink_3DS.3dsx, with the .smdh beside it. Launch Chest Link from the Homebrew Launcher.

### Start the PC mailbox

Extract the package to a permanent folder. The PC folder contains launchers and saved data; its launcher uses the server source in the sibling `codigo/server` folder. Keep the terminal window open while a console is uploading or receiving.

Linux:

~~~sh
cd PC
python3 servidor.py
~~~

Windows: open the PC folder and double-click iniciar-windows.bat. From a terminal in that folder, you can also run:

~~~bat
py -3 servidor.py
~~~

The browser interface opens automatically. The terminal and interface show the PC's local IP address, a six-digit PIN, and the server port. Enter the IP and PIN in Chest Link on the console. If the PC has more than one network address, use the address on the same local network as the consoles.

The server creates PC/dados for its saved PIN, uploaded copies, and delivery records. Keep this folder when updating or moving the server. Backups remain there when the PC is turned off. Start the server again from the same folder to access them.

The PC interface can also be opened from another computer on the same local network. Use the complete local link printed by the server; it contains a private access key. Do not share that link outside the people who should have access.

## Prepare the storage banks

1. Open Pokémon Chest or PKSM.
2. Move the Pokémon you want to transfer into a storage bank and save.
3. Close Chest or PKSM before opening Chest Link.
4. In Chest Link, choose Consultar bancos (Browse banks) to verify that the expected banks and box names appear.

On the 3DS, choose the storage that matches PKSM's configuration:

- PKSM (ExtData) uses PKSM's internal ExtData storage.
- PKSM (SD) uses banks in /3ds/PKSM/banks when PKSM's Use ExtData setting is off.
- Chest (SD) appears when Pokémon Chest banks are present on the SD card, for example through TWiLight Menu++.

If PKSM is configured for ExtData but you receive a copy into PKSM (SD), that copy will appear in PKSM only after PKSM is configured to use SD banks. Check the bank list before transferring.

## Copy Pokémon from game saves

Choose **Ler saves Pokemon** to scan `.sav` files on the SD card or flashcard.
Chest Link checks the save structure and checksums and shows only recognized
Pokémon saves from Generations I–IV; unrelated `.sav` files are ignored. This
reads save files stored on the card, not the live save inside a cartridge or
console title.

The lower screen shows the selected game's boxes and tabs for detected saves;
the upper screen is the Chest Link box being assembled. Select a Pokémon and
press A to add it to the next empty slot, or press Y to replace the draft with
the whole selected box. Use L/R to change boxes, X or a game tab to switch
saves, and B to return. Press START to save the draft as a new bank in the
selected Chest/PKSM storage. Then open **Consultar bancos** to send that bank
to the PC. The source `.sav` and existing banks remain unchanged.

The DS Chest format accepts Generations III–IV for this import; Generation
I–II saves appear when the selected destination is PKSM on the 3DS. The reader
recognizes raw save layouts already represented by the offline Pokédex. Keep
your original save backups before using a newly built version on hardware.

## Use a direct console transfer

1. Open Chest Link on the destination console and leave it on the main screen so its listener is ready.
2. On the source console, choose Consultar bancos (Browse banks), select a bank, and mark Pokémon.
3. Use Y to select the current box, X to select all boxes, and L/R to switch boxes. Press A or tap a Pokémon to select it.
4. Press START or choose the send action, review the selection, then choose Enviar ao outro console (Send to the other console).
5. Enter the destination console's IP address and PIN. The destination shows the offer and asks before saving it.
6. After the new linkNNNN bank appears, close Chest Link and open that bank in Chest or PKSM.

For the first hardware test, send one box and verify the source and destination banks before sending more.

## Use the PC mailbox

1. Start the PC server and note its IP address and PIN.
2. On the source console, choose Enviar ao PC (Send to PC), select Pokémon, and enter the PC address and PIN.
3. The PC confirms when the copy has been stored. The source bank remains unchanged, and the other console can stay off.
4. In the browser interface, select the stored copy, choose the destination DS or 3DS, and select the Pokémon to deliver.
5. Start delivery and enter the destination console's IP and PIN. The console asks before saving. The PC retains the backup.

Uploads without a selected destination stay in the PC mailbox until you explicitly choose DS or 3DS in the interface. The PC does not send a copy automatically, and the console listener does not fetch from the mailbox on its own.

## Backups and data safety

- Transfers create a copy. Chest Link does not delete the source bank.
- Received Pokémon are saved in a new linkNNNN bank. Existing banks are preserved.
- The PC keeps uploaded packages after delivery. It does not modify the console's original Chest or PKSM banks.
- The receiver checks the package size, supported generations, box names, and SHA-256 before import. SHA-256 detects corruption; it does not authenticate the other device or encrypt the connection.
- The PIN is sent over the local network without encryption. Use a network and PC you trust, and do not expose the server to the internet.
- If a transfer is interrupted, check the destination bank list before retrying. A transfer may have been saved even if the final network confirmation was lost.
- Keep your existing backups. The first time you use Chest Link, test with one box.

## Limits

- Reads PKSMBANK formats 1, 2, and 3; writes format 3.
- Up to 500 boxes per bank on supported PKSM and DSi SD storage. A DS/flashcard destination is limited to 50 boxes per transfer.
- PKSM-to-Chest transfers reject Generation I and II records for compatibility with the tested Chest reader. Unknown generations are also rejected.
- Chest Link is a storage and transfer tool. It does not provide PKSM's editing, scripts, or other advanced features.
- The PC HOME grid is built from the local species and sprite catalogue. Generation I includes the 151 Kanto species and Generation II includes all 251 Johto entries in regional order, with game availability, capture tracking, evolution lines, and encounter details for Red/Blue/Yellow and Gold/Silver/Crystal. Progress is kept separately for each generation in the PC data folder.
- The real-hardware status above is limited to the console-to-PC flow. Direct console-to-console and PC-to-console transfer still need hardware validation.

## Build and local validation

From the repository root, or from the codigo folder inside the release ZIP, the console pair is built and validated together. Both console apps use the shared version in include/version.hpp.

~~~sh
make consoles
make console-ports-test test mailbox-test gui-test
make release
~~~

The source includes host-side tests and release checks. A passing local build or test does not establish that a transfer works on real console hardware. The DS and 3DS apps must be released with the same version number.

The [E2E lab guide](tests/e2e/README.md) explains isolated melonDS/Azahar tests and the private FireRed regression matrix. Set `CHESTLINK_FIRERED_SAVE` locally and run `make e2e-firered` after configuring the emulators. Real saves and test artifacts remain outside public fixtures and releases.

See docs/PROTOCOLO.md and docs/FORMATOS.md for protocol and storage details. These documents are currently in Portuguese.

## License

Chest Link is an independent project and is not affiliated with the Pokémon Chest or PKSM maintainers. The code is licensed under GPL-3.0-or-later.
