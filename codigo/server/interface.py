"""Local PC box interface. Standard-library HTTP; console TCP is unchanged.

The GUI reads verified snapshots and republishes copies through the same TCP
upload path as a console. It preserves saved bytes; explicit requeue can mark
an identical delivered copy as pending again.
"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import threading
import time
import unicodedata
import uuid
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

try:
    from . import native_saves, pokemon
except ImportError:
    import native_saves
    import pokemon

WEB = Path(__file__).resolve().parent / "web"
ALL_SLOTS = (1 << 30) - 1


def persistent_ui_token(core, data_root):
    path = Path(data_root) / "interface-token.json"
    try:
        saved = core.json_read(path)
    except FileNotFoundError:
        token = secrets.token_urlsafe(32)
        core.atomic_json(path, {"token": token})
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return token
    except (OSError, ValueError, core.MailboxError):
        raise core.MailboxError("Arquivo do link da interface invalido; preserve a pasta de dados.") from None
    token = saved.get("token") if isinstance(saved, dict) and set(saved) == {"token"} else None
    if (not isinstance(token, str) or len(token) != 43 or not token.isascii() or
            any(not (char.isalnum() or char in "_-") for char in token)):
        raise core.MailboxError("Arquivo do link da interface invalido; preserve a pasta de dados.")
    return token


class Interface:
    def __init__(self, core, mailbox, tcp_address, addresses, web_port=8765,
                 web_bind="0.0.0.0", web_addresses=None, hotspot=None):
        self.core, self.mailbox = core, mailbox
        self.native_saves = native_saves.SnapshotRepository(mailbox.root)
        self.hotspot = hotspot
        host, port = tcp_address
        self.tcp_address = ("127.0.0.1" if host == "0.0.0.0" else host, port)
        self.addresses = addresses
        self.token = persistent_ui_token(core, mailbox.root)
        web_addresses = addresses if web_addresses is None else web_addresses
        self.web_addresses = [ip for ip in web_addresses
                              if ip != "0.0.0.0" and not ip.startswith("127.")]
        try:
            self.server = LocalServer((web_bind, web_port), self)
        except OSError:
            if web_port != 8765:
                raise
            self.server = LocalServer((web_bind, 0), self)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": .1}, daemon=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}/#{self.token}"
        self.network_urls = [f"http://{ip}:{self.server.server_port}/#{self.token}"
                             for ip in self.web_addresses]
        self.allowed_hosts = {f"{host}:{self.server.server_port}"
                              for host in ("127.0.0.1", "localhost", *self.web_addresses)}
        if web_bind not in ("0.0.0.0", "127.0.0.1"):
            self.allowed_hosts.add(f"{web_bind}:{self.server.server_port}")
        # Published bank bytes are immutable; metadata changes only on delivery.
        self.verified = {}
        self.verify_lock = threading.Lock()
        self.action_lock = threading.RLock()
        self.species_cache = {}
        self.dex_state_file = self.mailbox.root / "pokedex-state.json"
        self.dex_lock = threading.Lock()
        self.mailbox.on_stored = self.mark_server_captured

    def start(self, open_browser=True):
        self.thread.start()
        if open_browser:
            threading.Thread(target=lambda: webbrowser.open(self.url), daemon=True).start()

    def close(self):
        if self.hotspot:
            with self.action_lock:
                try:
                    self.hotspot.close()
                except RuntimeError as exc:
                    print(f"A rede DS precisa de limpeza manual: {exc}", flush=True)
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(timeout=5)
        self.server.server_close()

    def state(self, can_manage_hotspot=False):
        with self.mailbox.lock:
            rows = sorted(self.mailbox.all_metadata(), key=lambda m: (m["created"], m["id"]), reverse=True)
        data = dict(version="0.4", pin=f"{self.mailbox.pin:06d}", port=self.tcp_address[1],
                    ips=self.addresses, items=rows,
                    unassigned=sum(m["target"] == 0 for m in rows),
                    ds=sum(m["target"] == 1 and not m["delivered"] and not m["queue_cleared"] for m in rows),
                    threeds=sum(m["target"] == 2 and not m["delivered"] and not m["queue_cleared"] for m in rows))
        data["hotspot"] = (self.hotspot.state(can_manage=can_manage_hotspot)
                            if self.hotspot else dict(available=False, running=False,
                                                      canManage=False,
                                                      reason="Controle de rede indisponível."))
        return data

    def checked_item(self, item_id):
        with self.mailbox.lock:
            meta = self.mailbox.metadata(item_id)
        folder = self.mailbox.items / item_id
        signatures = tuple((p.stat().st_size, p.stat().st_mtime_ns) for p in
                           (folder / "bank.bnk", folder / "names.json"))
        with self.verify_lock:
            if self.verified.get(item_id) != signatures:
                self.core.validate_package(folder, meta["offer"], meta["target"])
                self.verified[item_id] = signatures
        return meta, folder

    def box(self, item_id, index):
        with self.mailbox.delivery_lock:
            meta, folder = self.checked_item(item_id)
            if type(index) is not int or not 0 <= index < meta["offer"]["boxes"]:
                raise self.core.MailboxError("Box fora da copia.")
            names = json.loads((folder / "names.json").read_text())
            with (folder / "bank.bnk").open("rb") as f:
                f.seek(16 + index * self.core.BOX_BYTES)
                entries = f.read(self.core.BOX_BYTES)
            return dict(id=item_id, box=index, boxes=meta["offer"]["boxes"], name=names[index],
                        pokemon=[pokemon.preview(entries[i * 336:(i + 1) * 336]) for i in range(30)])

    @staticmethod
    def fit_label(label, suffix):
        value = f"{label}{suffix}"
        while len(value.encode("utf-8")) > 63:
            label = label[:-1]
            value = f"{label}{suffix}"
        return value

    @staticmethod
    def empty_entry(entry):
        return struct.unpack_from("<I", entry)[0] == 0xffffffff

    def publish_organized_bank(self, source_meta, bank_data, names, description):
        names_data = json.dumps(names, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        boxes = len(names)
        if len(bank_data) != 16 + boxes * self.core.BOX_BYTES:
            raise self.core.MailboxError("O banco organizado ficou com tamanho invalido.")
        occupied = generations = 0
        for offset in range(16, len(bank_data), self.core.ENTRY):
            entry = bank_data[offset:offset + self.core.ENTRY]
            generation, = struct.unpack_from("<I", entry)
            if generation == 0xffffffff:
                continue
            occupied += 1
            generations |= 1 << generation
        offer = dict(boxes=boxes, occupied=occupied, generations=generations,
                     bankBytes=len(bank_data), namesBytes=len(names_data),
                     hash=hashlib.sha256(bank_data + names_data).hexdigest())
        target = source_meta["target"]
        self.core.preflight(offer, target)
        item_id = self.core.packet_id(target, offer["hash"])
        final = self.mailbox.items / item_id

        with self.mailbox.lock:
            if final.exists():
                existing = self.mailbox.metadata(item_id)
                self.core.validate_package(final, existing["offer"], existing["target"])
                self.mailbox.notify_stored(final, existing["offer"])
                return dict(id=item_id, boxes=boxes, occupied=occupied, created=False,
                            label=existing["label"])

        size = len(bank_data) + len(names_data)
        with self.mailbox.reserve(size):
            temp = self.mailbox.temp / ("organize-" + uuid.uuid4().hex)
            temp.mkdir()
            try:
                for filename, data in (("bank.bnk", bank_data), ("names.json", names_data)):
                    with (temp / filename).open("xb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                label = self.fit_label(source_meta["label"], " · " + description)
                new_meta = dict(id=item_id, target=target, label=label, offer=offer,
                                created=int(time.time()), delivered=0, queue_cleared=0)
                self.core.json_write_new(temp / "meta.json", new_meta)
                self.core.validate_package(temp, offer, target)
                self.core.sync_dir(temp)
                created = True
                with self.mailbox.lock:
                    if final.exists():
                        existing = self.mailbox.metadata(item_id)
                        self.core.validate_package(final, existing["offer"], existing["target"])
                        new_meta = existing
                        created = False
                    else:
                        os.rename(temp, final)
                        self.core.sync_dir(self.mailbox.items)
                        self.core.sync_dir(self.mailbox.temp)
                self.mailbox.notify_stored(final, offer)
                return dict(id=item_id, boxes=boxes, occupied=occupied,
                            created=created, label=new_meta["label"])
            finally:
                if temp.exists():
                    import shutil
                    shutil.rmtree(temp)

    def organize(self, request):
        if not isinstance(request, dict) or request.get("action") not in ("sort", "compact", "living-dex"):
            raise self.core.MailboxError("Pedido de organizacao invalido.")
        action = request["action"]
        expected = {"id", "action", "box", "by"} if action == "sort" else {"id", "action"}
        if set(request) != expected or not isinstance(request["id"], str):
            raise self.core.MailboxError("Pedido de organizacao invalido.")
        if action == "sort" and type(request["box"]) is not int:
            raise self.core.MailboxError("Box selecionada invalida.")
        if action == "sort" and request["by"] not in ("name", "level", "id"):
            raise self.core.MailboxError("Escolha nome, nivel ou ID do Pokemon para ordenar.")

        with self.mailbox.delivery_lock:
            meta, folder = self.checked_item(request["id"])
            names = json.loads((folder / "names.json").read_text(encoding="utf-8"))
            source = (folder / "bank.bnk").read_bytes()
            if action == "compact":
                # Pack every non-empty record in bank order across box boundaries.
                # This fills earlier holes, preserves relative order, and drops
                # fully empty trailing boxes in the organized copy.
                occupied = [source[offset:offset + self.core.ENTRY]
                            for offset in range(16, len(source), self.core.ENTRY)
                            if not self.empty_entry(source[offset:offset + self.core.ENTRY])]
                boxes = max(1, (len(occupied) + 29) // 30)
                packed = occupied + [b"\xff" * self.core.ENTRY] * (boxes * 30 - len(occupied))
                bank_data = b"PKSMBANK" + struct.pack("<II", 3, boxes) + b"".join(packed)
                return self.publish_organized_bank(meta, bank_data, names[:boxes],
                                                   "espaços otimizados em todas as boxes")

            if action == "sort":
                index = request["box"]
                if not 0 <= index < meta["offer"]["boxes"]:
                    raise self.core.MailboxError("Box fora do banco selecionado.")
                start = 16 + index * self.core.BOX_BYTES
                entries = [source[start + slot * self.core.ENTRY:
                                  start + (slot + 1) * self.core.ENTRY]
                           for slot in range(30)]
                occupied = [(slot, entry, pokemon.preview(entry))
                            for slot, entry in enumerate(entries)
                            if not self.empty_entry(entry)]
                sort_key = request["by"]
                if sort_key == "name":
                    def key(record):
                        summary = record[2]
                        name = unicodedata.normalize("NFD", summary["name"])
                        name = "".join(char for char in name if not unicodedata.combining(char)).casefold()
                        return (not summary["valid"], name, summary["species"])
                    description = "ordenado por nome"
                elif sort_key == "level":
                    def key(record):
                        level = record[2]["level"]
                        return (not record[2]["valid"], level is None,
                                level if level is not None else 0, record[2]["species"])
                    description = "ordenado por nivel"
                else:
                    def key(record):
                        return (not record[2]["valid"], record[2]["species"])
                    description = "ordenado por ID"
                occupied.sort(key=key)
                ordered = [record[1] for record in occupied]
                ordered.extend([b"\xff" * self.core.ENTRY] * (30 - len(ordered)))
                organized = bytearray(source)
                organized[start:start + self.core.BOX_BYTES] = b"".join(ordered)
                return self.publish_organized_bank(meta, bytes(organized), names, description)

            national_slots = max(pokemon.national_species_ids(), default=0)
            if not national_slots:
                raise self.core.MailboxError("O catalogo nao tem especies para mapear.")
            species_entries = {}
            overflow = []
            for offset in range(16, len(source), self.core.ENTRY):
                entry = source[offset:offset + self.core.ENTRY]
                if self.empty_entry(entry):
                    continue
                summary = pokemon.preview(entry)
                species = summary["species"]
                if summary["valid"] and not summary["egg"] and 1 <= species <= national_slots:
                    species_entries.setdefault(species, []).append(entry)
                else:
                    # Eggs and unrecognized records remain in the new copy.
                    overflow.append(entry)
            dex_entries = []
            empty = b"\xff" * self.core.ENTRY
            for species in range(1, national_slots + 1):
                entries = species_entries.get(species)
                # Keep the one-per-species base slot, then place every duplicate
                # directly after it so later species shift by the extra count.
                dex_entries.extend(entries if entries else [empty])
            mapped_slots = len(dex_entries)
            packed = dex_entries + overflow
            occupied_slots = len(packed)
            boxes = (len(packed) + 29) // 30
            if boxes > self.core.MAX_BOXES:
                raise self.core.MailboxError("O banco ficaria maior que o limite de 500 boxes; nenhum registro foi movido.")
            packed.extend([b"\xff" * self.core.ENTRY] * (boxes * 30 - len(packed)))
            bank_data = b"PKSMBANK" + struct.pack("<II", 3, boxes) + b"".join(packed)
            names = []
            for box in range(boxes):
                first = box * 30 + 1
                end = (box + 1) * 30
                last = min(end, mapped_slots)
                if first <= mapped_slots:
                    label = f"Living Dex {first:03d}-{last:03d}"
                    if end > mapped_slots and occupied_slots > mapped_slots:
                        extra_first = max(first, mapped_slots + 1) - mapped_slots
                        extra_last = min(end, occupied_slots) - mapped_slots
                        label += f" + Extras {extra_first:03d}-{extra_last:03d}"
                else:
                    extra_first = first - mapped_slots
                    extra_last = min(end, occupied_slots) - mapped_slots
                    label = f"Extras {extra_first:03d}-{extra_last:03d}"
                names.append(label)
            return self.publish_organized_bank(meta, bank_data, names, "Living Dex")

    def clear_pending(self, request):
        if request != {}:
            raise self.core.MailboxError("Pedido para limpar pendencias invalido.")
        cleared = self.mailbox.clear_pending()
        return dict(cleared=len(cleared))

    @staticmethod
    def empty_dex_state():
        return dict(version=6, mode="unified", unified=[], johtoUnified=[], generation3Unified=[],
                    generation4Unified=[], legacyGreen=[], serverCaptured=[], johtoServerCaptured=[],
                    hoennServerCaptured=[], sinnohServerCaptured=[],
                    individual={game: [] for game in ("red", "blue", "yellow")},
                    johtoIndividual={game: [] for game in ("gold", "silver", "crystal")},
                    generation3Individual={game: [] for game in
                                            ("firered", "leafgreen", "ruby", "sapphire", "emerald")},
                    generation4Individual={game: [] for game in
                                            ("diamond", "pearl", "platinum", "heartgold", "soulsilver")})

    def pokedex_catalog(self, generation=1):
        if type(generation) is not int or generation not in (1, 2, 3, 4):
            raise self.core.MailboxError("Geração da Pokédex inválida.")
        data = json.loads((WEB / f"assets/dex-gen{generation}.json").read_text(encoding="utf-8"))
        detailed = {row["id"]: row for row in data["species"]}
        species = []
        for species_id in pokemon.national_species_ids():
            if species_id in detailed:
                row = dict(detailed[species_id], detailed=True, generation=data["generation"])
            else:
                row = dict(id=species_id, name=pokemon.CATALOG["names"][species_id],
                           sprite=pokemon.FORMS[str(species_id)], types=[], availableIn=[],
                           exclusiveTo=None, unobtainableIn=[], encounters={},
                           pokemonDb=None, evolutionChain=None, detailed=False)
            species.append(row)
        regions = data.get("regions", [data["region"]] if "region" in data else [])
        ids = {row["id"] for row in species}
        regions = [dict(region, speciesIds=[species_id for species_id in region.get(
            "speciesIds", [row["id"] for row in data["species"]]) if species_id in ids],
            games=[game["id"] for game in data["games"] if game["id"] in
                   region.get("games", [item["id"] for item in data["games"]])])
            for region in regions]
        national_ids = pokemon.national_species_ids_for_generation(data["generation"])
        return dict(data, species=species, nationalSpeciesIds=national_ids,
                    nationalSpeciesTotal=len(national_ids),
                    regions=regions)

    def read_dex_state(self):
        try:
            data = json.loads(self.dex_state_file.read_text(encoding="utf-8"),
                              object_pairs_hook=self.core.no_duplicates)
        except FileNotFoundError:
            return self.empty_dex_state()
        migrated = False
        if (not isinstance(data, dict) or data.get("mode") not in ("unified", "individual") or
                not isinstance(data.get("unified"), list) or not isinstance(data.get("individual"), dict)):
            raise self.core.MailboxError("Arquivo de progresso da Pokedex invalido; os dados foram preservados.")
        games1 = ("red", "blue", "yellow")
        games2 = ("gold", "silver", "crystal")
        games3 = ("firered", "leafgreen", "ruby", "sapphire", "emerald")
        games4 = ("diamond", "pearl", "platinum", "heartgold", "soulsilver")
        legacy_individual = {"red", "blue", "yellow", "green"}
        if (data.get("version") == 1 and set(data) == {"version", "mode", "unified", "individual"} and
                set(data.get("individual", {})) == legacy_individual):
            migrated_data = self.empty_dex_state()
            migrated_data.update(mode=data["mode"], unified=data["unified"],
                                 legacyGreen=data["individual"]["green"])
            migrated_data["individual"] = {game: data["individual"][game] for game in games1}
            data = migrated_data
            migrated = True
        elif (data.get("version") == 2 and
              set(data) == {"version", "mode", "unified", "individual", "legacyGreen"} and
              set(data.get("individual", {})) == set(games1)):
            migrated_data = self.empty_dex_state()
            migrated_data.update(mode=data["mode"], unified=data["unified"],
                                 individual=data["individual"], legacyGreen=data["legacyGreen"])
            data = migrated_data
            migrated = True
        elif (data.get("version") == 3 and
              set(data) == {"version", "mode", "unified", "individual", "legacyGreen", "serverCaptured"} and
              set(data.get("individual", {})) == set(games1)):
            migrated_data = self.empty_dex_state()
            old_server = data["serverCaptured"]
            if (not isinstance(old_server, list) or
                    any(type(value) is not int or not 1 <= value <= 251 for value in old_server) or
                    len(old_server) != len(set(old_server))):
                raise self.core.MailboxError("Progresso da Pokedex invalido; os dados foram preservados.")
            migrated_data.update(mode=data["mode"], unified=data["unified"],
                                 individual=data["individual"], legacyGreen=data["legacyGreen"],
                                 serverCaptured=[value for value in old_server if value <= 151],
                                 johtoServerCaptured=old_server)
            data = migrated_data
            migrated = True
        elif data.get("version") == 4:
            base_keys = {"version", "mode", "unified", "johtoUnified", "individual",
                         "johtoIndividual", "legacyGreen", "serverCaptured"}
            if set(data) == base_keys:
                data = dict(data, johtoServerCaptured=data["serverCaptured"])
            elif set(data) != base_keys | {"johtoServerCaptured"}:
                raise self.core.MailboxError("Arquivo de progresso da Pokedex invalido; os dados foram preservados.")
            old_server = data.get("serverCaptured")
            johto_server = data.get("johtoServerCaptured")
            if (set(data.get("individual", {})) != set(games1) or
                    set(data.get("johtoIndividual", {})) != set(games2) or
                    not isinstance(old_server, list) or not isinstance(johto_server, list) or
                    any(type(value) is not int or not 1 <= value <= 251 for value in old_server) or
                    any(type(value) is not int or not 1 <= value <= 251 for value in johto_server) or
                    len(old_server) != len(set(old_server)) or len(johto_server) != len(set(johto_server))):
                raise self.core.MailboxError("Progresso da Pokedex invalido; os dados foram preservados.")
            data = dict(data, version=6,
                        serverCaptured=[value for value in old_server if value <= 151],
                        johtoServerCaptured=sorted(set(johto_server) | set(old_server)),
                        generation3Unified=[],
                        generation3Individual={game: [] for game in games3},
                        hoennServerCaptured=[], generation4Unified=[],
                        generation4Individual={game: [] for game in games4},
                        sinnohServerCaptured=[])
            migrated = True
        elif (data.get("version") == 5 and
              set(data) == {"version", "mode", "unified", "johtoUnified", "generation3Unified",
                            "individual", "johtoIndividual", "generation3Individual", "legacyGreen",
                            "serverCaptured", "johtoServerCaptured", "hoennServerCaptured"} and
              set(data.get("individual", {})) == set(games1) and
              set(data.get("johtoIndividual", {})) == set(games2) and
              set(data.get("generation3Individual", {})) == set(games3)):
            data = dict(data, version=6, generation4Unified=[],
                        generation4Individual={game: [] for game in games4},
                        sinnohServerCaptured=[])
            migrated = True
        elif (data.get("version") != 6 or
              set(data) != {"version", "mode", "unified", "johtoUnified", "generation3Unified",
                            "generation4Unified", "individual", "johtoIndividual", "generation3Individual",
                            "generation4Individual", "legacyGreen", "serverCaptured", "johtoServerCaptured",
                            "hoennServerCaptured", "sinnohServerCaptured"} or
              set(data.get("individual", {})) != set(games1) or
              set(data.get("johtoIndividual", {})) != set(games2) or
              set(data.get("generation3Individual", {})) != set(games3) or
              set(data.get("generation4Individual", {})) != set(games4)):
            raise self.core.MailboxError("Arquivo de progresso da Pokedex invalido; os dados foram preservados.")
        if not isinstance(data.get("legacyGreen"), list):
            raise self.core.MailboxError("Progresso legado da Pokedex invalido; os dados foram preservados.")
        collections = [
            (data["unified"], 151), (data["legacyGreen"], 151),
            (data["serverCaptured"], 151), (data["johtoServerCaptured"], 251),
            (data["hoennServerCaptured"], 386), (data["sinnohServerCaptured"], 493),
            *((values, 151) for values in data["individual"].values()),
            (data["johtoUnified"], 251),
            *((values, 251) for values in data["johtoIndividual"].values()),
            (data["generation3Unified"], 386),
            *((values, 386) for values in data["generation3Individual"].values()),
            (data["generation4Unified"], 493),
            *((values, 493) for values in data["generation4Individual"].values())]
        for values, maximum in collections:
            if (not isinstance(values, list) or any(type(value) is not int or not 1 <= value <= maximum
                                                   for value in values) or len(values) != len(set(values))):
                raise self.core.MailboxError("Progresso da Pokedex invalido; os dados foram preservados.")
        if migrated:
            self.core.atomic_json(self.dex_state_file, data)
        return data

    def mark_server_captured(self, folder, offer):
        species = set()
        with (folder / "bank.bnk").open("rb") as stream:
            stream.seek(16)
            for _ in range(offer["boxes"] * 30):
                entry = stream.read(336)
                if len(entry) != 336:
                    raise self.core.MailboxError("Copia incompleta ao marcar capturas da Pokedex.")
                summary = pokemon.preview(entry)
                if summary["valid"] and 1 <= summary["species"] <= 493:
                    species.add(summary["species"])
        if not species:
            return
        with self.dex_lock:
            data = self.read_dex_state()
            kanto_captured = sorted(set(data["serverCaptured"]) | {species_id for species_id in species
                                                                     if species_id <= 151})
            johto_captured = sorted(set(data["johtoServerCaptured"]) |
                                    {species_id for species_id in species if species_id <= 251})
            hoenn_captured = sorted(set(data["hoennServerCaptured"]) |
                                    {species_id for species_id in species if species_id <= 386})
            sinnoh_captured = sorted(set(data["sinnohServerCaptured"]) |
                                     {species_id for species_id in species if species_id <= 493})
            if (kanto_captured != data["serverCaptured"] or
                    johto_captured != data["johtoServerCaptured"] or
                    hoenn_captured != data["hoennServerCaptured"] or
                    sinnoh_captured != data["sinnohServerCaptured"]):
                data["serverCaptured"] = kanto_captured
                data["johtoServerCaptured"] = johto_captured
                data["hoennServerCaptured"] = hoenn_captured
                data["sinnohServerCaptured"] = sinnoh_captured
                self.core.atomic_json(self.dex_state_file, data)

    def update_pokedex(self, request):
        kanto_games = ("red", "blue", "yellow")
        johto_games = ("gold", "silver", "crystal")
        hoenn_games = ("firered", "leafgreen", "ruby", "sapphire", "emerald")
        sinnoh_games = ("diamond", "pearl", "platinum", "heartgold", "soulsilver")
        games = kanto_games + johto_games + hoenn_games + sinnoh_games
        game_group = {**{game: ("unified", "individual", kanto_games, 151) for game in kanto_games},
                      **{game: ("johtoUnified", "johtoIndividual", johto_games, 251) for game in johto_games},
                      **{game: ("generation3Unified", "generation3Individual", hoenn_games, 386)
                         for game in hoenn_games},
                      **{game: ("generation4Unified", "generation4Individual", sinnoh_games, 493)
                         for game in sinnoh_games}}
        if (not isinstance(request, dict) or set(request) != {"mode", "game", "species", "captured"} or
                request["mode"] not in ("unified", "individual") or request["game"] not in games or
                type(request["species"]) is not int or not 1 <= request["species"] <= game_group.get(
                    request.get("game"), (None, None, None, 0))[3] or
                type(request["captured"]) is not bool):
            raise self.core.MailboxError("Atualizacao da Pokedex invalida.")
        with self.dex_lock:
            data = self.read_dex_state()
            if data["mode"] != request["mode"]:
                for unified_key, individual_key, group_games in (
                        ("unified", "individual", kanto_games),
                        ("johtoUnified", "johtoIndividual", johto_games),
                        ("generation3Unified", "generation3Individual", hoenn_games),
                        ("generation4Unified", "generation4Individual", sinnoh_games)):
                    if request["mode"] == "unified":
                        data[unified_key] = sorted({species for values in data[individual_key].values()
                                                    for species in values})
                    else:
                        for game in group_games:
                            data[individual_key][game] = list(data[unified_key])
                data["mode"] = request["mode"]
            unified_key, individual_key, group_games, _maximum = game_group[request["game"]]
            collection = set(data[unified_key] if data["mode"] == "unified"
                             else data[individual_key][request["game"]])
            if request["captured"]:
                collection.add(request["species"])
            else:
                collection.discard(request["species"])
            if data["mode"] == "unified":
                data[unified_key] = sorted(collection)
                for game in group_games:
                    data[individual_key][game] = list(data[unified_key])
            else:
                data[individual_key][request["game"]] = sorted(collection)
            self.core.atomic_json(self.dex_state_file, data)
        return self.pokedex()

    def pokedex(self):
        with self.dex_lock:
            progress = self.read_dex_state()
        with self.mailbox.lock:
            rows = list(self.mailbox.all_metadata())
        home_counts = {}
        for row in rows:
            meta, folder = self.checked_item(row["id"])
            bank = folder / "bank.bnk"
            signature = (bank.stat().st_size, bank.stat().st_mtime_ns)
            with self.verify_lock:
                cached = self.species_cache.get(row["id"])
                if cached and cached[0] == signature:
                    species_counts = cached[1]
                else:
                    species_counts = None
            if species_counts is None:
                species_counts = {}
                with bank.open("rb") as stream:
                    stream.seek(16)
                    for _ in range(meta["offer"]["boxes"] * 30):
                        entry = stream.read(336)
                        if len(entry) != 336:
                            raise self.core.MailboxError("Copia incompleta ao atualizar a Pokedex.")
                        summary = pokemon.preview(entry)
                        if summary["valid"] and summary["species"] > 0:
                            species_id = summary["species"]
                            species_counts[species_id] = species_counts.get(species_id, 0) + 1
                with self.verify_lock:
                    self.species_cache[row["id"]] = (signature, species_counts)
            for species_id, count in species_counts.items():
                home_counts[species_id] = home_counts.get(species_id, 0) + count
        counts = {species_id: count for species_id, count in home_counts.items() if species_id <= 151}
        johto_counts = {species_id: count for species_id, count in home_counts.items() if species_id <= 251}
        hoenn_counts = {species_id: count for species_id, count in home_counts.items() if species_id <= 386}
        sinnoh_counts = {species_id: count for species_id, count in home_counts.items() if species_id <= 493}
        with self.dex_lock:
            progress = self.read_dex_state()
            captured = sorted(set(progress["serverCaptured"]) | set(counts))
            johto_captured = sorted(set(progress["johtoServerCaptured"]) | set(johto_counts))
            hoenn_captured = sorted(set(progress["hoennServerCaptured"]) | set(hoenn_counts))
            sinnoh_captured = sorted(set(progress["sinnohServerCaptured"]) | set(sinnoh_counts))
            if (captured != progress["serverCaptured"] or johto_captured != progress["johtoServerCaptured"] or
                    hoenn_captured != progress["hoennServerCaptured"] or
                    sinnoh_captured != progress["sinnohServerCaptured"]):
                progress["serverCaptured"] = captured
                progress["johtoServerCaptured"] = johto_captured
                progress["hoennServerCaptured"] = hoenn_captured
                progress["sinnohServerCaptured"] = sinnoh_captured
                self.core.atomic_json(self.dex_state_file, progress)
        return dict(mode=progress["mode"], unified=progress["unified"],
                    individual=progress["individual"], johtoUnified=progress["johtoUnified"],
                    johtoIndividual=progress["johtoIndividual"],
                    generation3Unified=progress["generation3Unified"],
                    generation3Individual=progress["generation3Individual"],
                    generation4Unified=progress["generation4Unified"],
                    generation4Individual=progress["generation4Individual"], serverCounts=counts,
                    johtoServerCounts=johto_counts, hoennServerCounts=hoenn_counts,
                    serverCaptured=progress["serverCaptured"], homeServerCounts=home_counts,
                    johtoServerCaptured=progress["johtoServerCaptured"],
                    hoennServerCaptured=progress["hoennServerCaptured"],
                    sinnohServerCounts=sinnoh_counts,
                    sinnohServerCaptured=progress["sinnohServerCaptured"],
                    homeServerCaptured=sorted(set(progress["serverCaptured"]) |
                                              set(progress["johtoServerCaptured"]) |
                                              set(progress["hoennServerCaptured"]) |
                                              set(progress["sinnohServerCaptured"]) | set(home_counts)),
                    homeSpeciesTotal=len(pokemon.national_species_ids()))

    def requeue(self, request):
        if not isinstance(request, dict) or set(request) != {"id", "target", "masks"}:
            raise self.core.MailboxError("Pedido de selecao invalido.")
        self.core.target_check(request["target"])
        if not isinstance(request["id"], str):
            raise self.core.MailboxError("Identificador invalido.")
        meta, folder = self.checked_item(request["id"])
        masks = request["masks"]
        if not isinstance(masks, list) or len(masks) != meta["offer"]["boxes"] or any(
                type(m) is not int or not 0 <= m <= ALL_SLOTS for m in masks):
            raise self.core.MailboxError("Selecao de slots invalida.")
        included = [i for i, mask in enumerate(masks) if mask]
        if not included:
            raise self.core.MailboxError("Marque Pokemon ou uma box antes de enviar.")
        labels = json.loads((folder / "names.json").read_text())
        bank = bytearray(b"PKSMBANK" + struct.pack("<II", 3, len(included)))
        occupied = generations = 0
        with (folder / "bank.bnk").open("rb") as stream:
            for index in included:
                stream.seek(16 + index * self.core.BOX_BYTES)
                data = bytearray(stream.read(self.core.BOX_BYTES))
                if len(data) != self.core.BOX_BYTES:
                    raise self.core.MailboxError("Copia incompleta no PC.")
                for slot in range(30):
                    if not masks[index] & (1 << slot):
                        data[slot * 336:(slot + 1) * 336] = b"\xff" * 336
                    gen = struct.unpack_from("<I", data, slot * 336)[0]
                    if gen != 0xffffffff:
                        occupied += 1
                        generations |= 1 << gen
                bank.extend(data)
        names = json.dumps([labels[i] for i in included], ensure_ascii=False,
                           separators=(",", ":")).encode()
        offer = dict(boxes=len(included), occupied=occupied, generations=generations,
                     bankBytes=len(bank), namesBytes=len(names), hash=hashlib.sha256(bank + names).hexdigest())
        target = request["target"]
        self.core.preflight(offer, target)
        label = ("PC: " + meta["label"]).encode("utf-8")[:63].decode("utf-8", "ignore").encode("utf-8")
        item_id = self.core.packet_id(target, offer["hash"])
        with socket.create_connection(self.tcp_address, timeout=30) as sock:
            sock.sendall(struct.pack("<8sIII", b"CLMAIL01", 1, self.mailbox.pin, 1))
            self.core.result(sock)
            sock.sendall(struct.pack("<II", target, len(label)) + label + self.core.offer_encode(offer))
            status = self.core.result(sock)
            if status == "READY":
                sock.sendall(bank)
                sock.sendall(names)
                if self.core.result(sock) != item_id:
                    raise self.core.MailboxError("PC nao confirmou a copia esperada.")
            elif status != "STORED " + item_id:
                raise self.core.MailboxError("Resposta de armazenamento invalida.")
        # An archived or previously delivered identical snapshot has the same
        # ID. Explicitly sending it again restores its queue entry; bytes stay intact.
        with self.mailbox.lock:
            queued = self.mailbox.metadata(item_id)
            if queued["delivered"] or queued["queue_cleared"]:
                queued["delivered"] = 0
                queued["queue_cleared"] = 0
                self.core.atomic_json(self.mailbox.items / item_id / "meta.json", queued)
        return dict(id=item_id, boxes=offer["boxes"], occupied=occupied, target=target)

    def send_direct(self, request):
        if not isinstance(request, dict) or set(request) != {"id", "target", "masks", "ip", "pin"}:
            raise self.core.MailboxError("Pedido de envio direto invalido.")
        ip = request["ip"]
        pin = request["pin"]
        if (not isinstance(ip, str) or not ip or len(ip) > 45 or
                type(pin) is not int or not 0 <= pin <= 999999):
            raise self.core.MailboxError("IP ou PIN do console invalido.")
        try:
            socket.inet_pton(socket.AF_INET, ip)
        except OSError:
            raise self.core.MailboxError("IP do console invalido.") from None
        selection = {key: request[key] for key in ("id", "target", "masks")}
        queued = self.requeue(selection)
        meta, folder = self.checked_item(queued["id"])
        try:
            with socket.create_connection((ip, 40991), timeout=30) as sock:
                sock.settimeout(180)
                sock.sendall(struct.pack("<8sII", b"CHESTLNK", 1, pin))
                self.core.result(sock)
                sock.sendall(self.core.offer_encode(meta["offer"]))
                self.core.result(sock)
                for name in ("bank.bnk", "names.json"):
                    with (folder / name).open("rb") as stream:
                        while True:
                            block = stream.read(4096)
                            if not block:
                                break
                            sock.sendall(block)
                received_name = self.core.result(sock)
        except OSError as exc:
            raise self.core.MailboxError("Nao foi possivel conectar ao listener do console: " + str(exc)) from None
        with self.mailbox.lock:
            delivered = self.mailbox.metadata(queued["id"])
            delivered["delivered"] = 1
            self.core.atomic_json(self.mailbox.items / queued["id"] / "meta.json", delivered)
        return dict(id=queued["id"], boxes=queued["boxes"], occupied=queued["occupied"],
                    target=queued["target"], bank=received_name)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, interface):
        self.interface = interface
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, data, mime="application/json; charset=utf-8"):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def local_request(self):
        if self.headers.get("Host") not in self.server.interface.allowed_hosts:
            self.send(403, dict(error="Endereco da interface nao autorizado."))
            return False
        return True

    def authenticated(self):
        supplied = self.headers.get("Authorization", "")
        if not secrets.compare_digest(supplied, "Bearer " + self.server.interface.token):
            self.send(401, dict(error="Abra a interface pelo link exibido no servidor."))
            return False
        return True

    def local_client(self):
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return False

    def do_GET(self):
        if not self.local_request():
            return
        interface = self.server.interface
        url = urlsplit(self.path)
        try:
            if url.path.startswith("/api/"):
                if not self.authenticated():
                    return
                if url.path == "/api/state":
                    self.send(200, interface.state(can_manage_hotspot=self.local_client()))
                elif url.path == "/api/pokedex":
                    self.send(200, interface.pokedex())
                elif url.path == "/api/pokedex/catalog":
                    args = parse_qs(url.query, strict_parsing=bool(url.query))
                    if set(args) - {"generation"} or any(len(values) != 1 for values in args.values()):
                        raise interface.core.MailboxError("Pedido de geração da Pokédex inválido.")
                    generation = int(args.get("generation", ["1"])[0])
                    self.send(200, interface.pokedex_catalog(generation))
                elif url.path == "/api/box":
                    args = parse_qs(url.query, strict_parsing=True)
                    if set(args) != {"id", "box"} or any(len(v) != 1 for v in args.values()):
                        raise interface.core.MailboxError("Pedido de box invalido.")
                    self.send(200, interface.box(args["id"][0], int(args["box"][0])))
                elif url.path == "/api/native-saves/saves":
                    self.send(200, interface.native_saves.list_saves())
                elif url.path == "/api/native-saves/collection":
                    self.send(200, interface.native_saves.collection())
                elif url.path == "/api/native-saves/snapshot":
                    args = parse_qs(url.query, strict_parsing=True)
                    if set(args) != {"id"} or len(args["id"]) != 1:
                        raise interface.core.MailboxError("Selecione um snapshot Native Saves.")
                    self.send(200, interface.native_saves.snapshot(args["id"][0]))
                elif url.path == "/api/native-saves/journey":
                    args = parse_qs(url.query, strict_parsing=True)
                    if set(args) - {"id"} or any(len(value) != 1 for value in args.values()):
                        raise interface.core.MailboxError("Pedido Journey invalido.")
                    self.send(200, interface.native_saves.journey(
                        args["id"][0] if "id" in args else None))
                elif url.path == "/api/native-saves/completion":
                    args = parse_qs(url.query, strict_parsing=True)
                    if set(args) != {"id"} or len(args["id"]) != 1:
                        raise interface.core.MailboxError("Selecione um snapshot Native Saves.")
                    self.send(200, interface.native_saves.completion(args["id"][0]))
                else:
                    self.send(404, dict(error="Tela nao encontrada."))
                return
            relative = "index.html" if url.path == "/" else url.path.lstrip("/")
            if relative not in {"index.html", "app.js", "style.css", "dex.css", "native-saves.css"} and not (
                    relative.startswith("assets/") and relative.count("/") == 1 and
                    relative[7:] in {p.name for p in (WEB / "assets").iterdir() if p.suffix in (".png", ".jpg", ".json")}):
                self.send(404, dict(error="Arquivo nao encontrado."))
                return
            mime = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg", ".json": "application/json"}
            self.send(200, (WEB / relative).read_bytes(), mime[Path(relative).suffix])
        except (interface.core.MailboxError, native_saves.NativeSaveError, OSError,
                ValueError, KeyError, TypeError, RecursionError) as exc:
            self.send(400, dict(error=str(exc)))

    def do_POST(self):
        if not self.local_request() or not self.authenticated():
            return
        interface = self.server.interface
        origin = self.headers.get("Origin")
        if origin != "http://" + self.headers.get("Host", ""):
            self.send(403, dict(error="Origem da pagina invalida."))
            return
        try:
            if self.path == "/api/native-saves/import":
                length = int(self.headers.get("Content-Length", "0"))
                if (not 0 < length <= native_saves.MAX_RAW_SAVE_BYTES or
                        self.headers.get("Content-Type") != "application/octet-stream"):
                    raise interface.core.MailboxError("Arquivo invalido ou maior que 64 MiB.")
                self.connection.settimeout(120)
                data = self.rfile.read(length)
                if len(data) != length:
                    raise interface.core.MailboxError("Upload incompleto; o save nao foi importado.")
                filename = _safe_http_filename(unquote(self.headers.get("X-Filename", "save.bin")))
                game_hint = self.headers.get("X-Game")
                if game_hint is not None and game_hint not in {
                        "red", "blue", "yellow", "gold", "silver", "crystal",
                        "firered", "leafgreen", "ruby", "sapphire", "emerald",
                        "diamond", "pearl", "platinum", "heartgold", "soulsilver"}:
                    raise interface.core.MailboxError("Jogo selecionado para importação inválido.")
                result = interface.native_saves.import_bytes(data, filename=filename,
                                                              locator="upload PC", game_hint=game_hint)
                self.send(200, result)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536 or self.headers.get("Content-Type") != "application/json":
                raise interface.core.MailboxError("Pedido de selecao grande demais ou invalido.")
            self.connection.settimeout(15)
            data = self.rfile.read(length)
            if len(data) != length:
                raise interface.core.MailboxError("Pedido incompleto.")
            request = json.loads(data, object_pairs_hook=interface.core.no_duplicates)
            if self.path not in {"/api/requeue", "/api/send-direct", "/api/clear-pending", "/api/pokedex", "/api/hotspot", "/api/native-saves/journey", "/api/native-saves/delete", "/api/organize"}:
                self.send(404, dict(error="Acao nao encontrada."))
                return
            if self.path == "/api/hotspot":
                if not self.local_client():
                    self.send(403, dict(error="Inicie ou encerre a rede DS pelo navegador deste PC."))
                    return
                if (not isinstance(request, dict) or set(request) != {"action"} or
                        request["action"] not in ("start", "stop")):
                    raise interface.core.MailboxError("Ação da rede DS inválida.")
                if not interface.hotspot:
                    raise interface.core.MailboxError("O controle de rede DS não está disponível.")
                with interface.action_lock:
                    result = (interface.hotspot.start() if request["action"] == "start"
                              else interface.hotspot.stop())
            elif self.path == "/api/pokedex":
                result = interface.update_pokedex(request)
            elif self.path == "/api/native-saves/journey":
                result = interface.native_saves.add_manual_event(request)
            elif self.path == "/api/native-saves/delete":
                if (not isinstance(request, dict) or set(request) != {"sha256"} or
                        not isinstance(request["sha256"], str)):
                    raise interface.core.MailboxError("Selecione um save Native Saves valido para remover.")
                result = interface.native_saves.delete_save(request["sha256"])
            elif self.path == "/api/organize":
                with interface.action_lock:
                    result = interface.organize(request)
            elif self.path == "/api/clear-pending":
                with interface.action_lock:
                    result = interface.clear_pending(request)
            else:
                with interface.action_lock:
                    result = interface.send_direct(request) if self.path == "/api/send-direct" else interface.requeue(request)
            self.send(200, result)
        except (interface.core.MailboxError, native_saves.NativeSaveError,
                OSError, ValueError, KeyError, TypeError,
                RecursionError, RuntimeError) as exc:
            self.send(400, dict(error=str(exc)))


def _safe_http_filename(value):
    value = str(value).replace("\\", "/").split("/")[-1]
    return "".join(char for char in value if char >= " " and char != "\x7f")[:128] or "save.bin"
