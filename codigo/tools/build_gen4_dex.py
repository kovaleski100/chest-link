#!/usr/bin/env python3
"""Build the bundled, offline Generation IV Pokédex from PokéAPI records."""
import concurrent.futures
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
API = "https://pokeapi.co/api/v2"
GAMES = ("diamond", "pearl", "platinum", "heartgold", "soulsilver")
VERSION_PAIRS = (("diamond", "pearl"), ("heartgold", "soulsilver"))
HGSS_FOSSILS = {
    138: ("heartgold", "Helix Fossil"),
    140: ("soulsilver", "Dome Fossil"),
    345: ("soulsilver", "Root Fossil"),
    347: ("heartgold", "Claw Fossil"),
}
HGSS_ENIGMA_STONE_EVENTS = {
    380: "soulsilver",  # Latias: native roaming encounter in HeartGold
    381: "heartgold",   # Latios: native roaming encounter in SoulSilver
}
DP_SINNOH_DEX = (
    387, 388, 389, 390, 391, 392, 393, 394, 395, 396, 397, 398, 399, 400, 401,
    402, 403, 404, 405, 63, 64, 65, 129, 130, 406, 315, 407, 41, 42, 169, 74,
    75, 76, 95, 208, 408, 409, 410, 411, 66, 67, 68, 54, 55, 412, 413, 414, 265,
    266, 267, 268, 269, 415, 416, 417, 418, 419, 420, 421, 422, 423, 214, 190,
    424, 425, 426, 427, 428, 92, 93, 94, 200, 429, 198, 430, 431, 432, 118, 119,
    339, 340, 433, 358, 434, 435, 307, 308, 436, 437, 77, 78, 438, 185, 439, 122,
    440, 113, 242, 173, 35, 36, 441, 172, 25, 26, 163, 164, 442, 443, 444, 445,
    446, 143, 201, 447, 448, 194, 195, 278, 279, 203, 449, 450, 298, 183, 184,
    451, 452, 453, 454, 455, 223, 224, 456, 457, 72, 73, 349, 350, 458, 226, 459,
    460, 215, 461, 480, 481, 482, 483, 484, 490,
)
METHODS = {
    "walk": "Andando", "surf": "Surfe", "old-rod": "Vara velha",
    "good-rod": "Vara boa", "super-rod": "Supervara", "rock-smash": "Quebra-Rocha",
    "headbutt": "Cabeçada", "gift": "Presente", "gift-egg": "Ovo recebido",
    "only-one": "Encontro único", "static": "Encontro fixo", "npc-trade": "Troca no jogo",
    "rock-smash": "Quebra-Rocha", "dark-grass": "Grama escura",
    "honey-tree": "Árvore de mel",
}
SPECIAL_METHODS = {"gift", "gift-egg", "only-one", "static", "npc-trade"}
CONDITIONS = {
    "swarm-yes": "com enxame", "swarm-no": "sem enxame",
    "time-morning": "manhã", "time-day": "dia", "time-night": "noite",
    "radar-on": "com Poké Radar", "radar-off": "sem Poké Radar",
}
EVOLUTION_ITEMS = {
    "fire-stone": "Pedra do Fogo", "water-stone": "Pedra da Água",
    "thunder-stone": "Pedra do Trovão", "leaf-stone": "Pedra da Folha",
    "moon-stone": "Pedra da Lua", "sun-stone": "Pedra do Sol",
    "shiny-stone": "Pedra Brilhante", "dusk-stone": "Pedra do Crepúsculo",
    "dawn-stone": "Pedra da Alvorada", "deep-sea-tooth": "Dente do Mar Profundo",
    "deep-sea-scale": "Escama do Mar Profundo", "dragon-scale": "Escama de Dragão",
    "kings-rock": "Pedra do Rei", "metal-coat": "Revestimento Metálico",
    "up-grade": "Melhorador",
}
# PokeAPI reports present-day types; several earlier species received Fairy
# later, and some species were retyped after Generation IV.
TYPE_OVERRIDES = {
    35: ["Normal"], 36: ["Normal"], 39: ["Normal"], 40: ["Normal"],
    122: ["Psychic"], 173: ["Normal"], 174: ["Normal"], 175: ["Normal"],
    176: ["Normal", "Flying"], 183: ["Water"], 184: ["Water"],
    209: ["Normal"], 210: ["Normal"],
    280: ["Psychic"], 281: ["Psychic"], 282: ["Psychic"],
    298: ["Normal"], 303: ["Steel"],
    468: ["Normal", "Flying"],
}


def version_exclusive_for(available_games):
    """Return the member of a paired release that can obtain the species."""
    available_games = set(available_games)
    for left, right in VERSION_PAIRS:
        if left in available_games and right not in available_games:
            return left
        if right in available_games and left not in available_games:
            return right
    return None


def apply_hgss_special_availability(encounters):
    """Correct PokéAPI's HGSS fossil rows and include Enigma Stone encounters.

    Fossil species are version-specific in HGSS. The Enigma Stone event makes
    the opposite Lati available in each game, so neither Lati is version-exclusive.
    """
    for species_id, (game, fossil) in HGSS_FOSSILS.items():
        for version in ("heartgold", "soulsilver"):
            encounters[species_id][version] = []
        encounters[species_id][game].append(dict(
            area="Pewter Museum of Science",
            method=f"Reviver · {fossil}", rate=None, special=True, levels=[20, 20]))

    for species_id, game in HGSS_ENIGMA_STONE_EVENTS.items():
        encounters[species_id][game].append(dict(
            area="Pewter Museum of Science · Enigma Stone",
            method="Encontro de evento", rate=None, special=True, levels=[35, 35]))


def fetch(path):
    url = path if path.startswith("https://") else f"{API}/{path.lstrip('/')}"
    for attempt in range(5):
        request = urllib.request.Request(url, headers={"User-Agent": "ChestLink offline Gen-IV dex data"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 4:
                raise
            time.sleep(0.6 * (attempt + 1))


def _resource_id(url):
    return int(url.rstrip("/").split("/")[-1])


def area_name(slug):
    region = ("Sinnoh · " if slug.startswith("sinnoh-") else
              "Johto · " if slug.startswith("johto-") else "")
    route = re.match(r"^(?:hoenn|kanto|sinnoh|johto)-(?:sea-)?route-(\d+)(?:-(north|south|east|west))?(?:-|$)", slug)
    if route:
        prefix = "Rota marítima " if "sea-route" in slug else "Rota "
        direction = {"north": "norte", "south": "sul", "east": "leste", "west": "oeste"}.get(route.group(2))
        return f"{region}{prefix}{route.group(1)}" + (f" · trecho {direction}" if direction else "")
    names = {
        "petalburg-woods": "Bosque de Petalburg", "granite-cave": "Caverna Granito",
        "fiery-path": "Trilha Ígnea", "jagged-pass": "Trilha Íngreme",
        "meteor-falls": "Cataratas do Meteoro", "new-mauville": "New Mauville",
        "mt-pyre": "Monte Pyre", "shoal-cave": "Caverna Shoal", "sky-pillar": "Pilar Celeste",
        "seafloor-cavern": "Caverna do Fundo do Mar", "rusturf-tunnel": "Túnel Rusturf",
        "victory-road": "Estrada da Vitória", "safari-zone": "Zona do Safári",
        "abandoned-ship": "Navio Abandonado", "scorched-slab": "Gruta Escaldante",
        "altering-cave": "Caverna Altering", "artisan-cave": "Caverna do Artesão",
        "pattern-bush": "Bosque de Padrões", "lost-cave": "Caverna Perdida",
        "water-labyrinth": "Labirinto Aquático", "five-isle-meadow": "Prado da Ilha Cinco",
        "memorial-pillar": "Pilar Memorial", "outcast-island": "Ilha Deserta",
        "green-path": "Trilha Verde", "water-path": "Trilha Aquática",
        "ruin-valley": "Vale das Ruínas", "bond-bridge": "Ponte do Vínculo",
        "berry-forest": "Floresta das Berries", "icefall-cave": "Caverna Icefall",
        "lostelle-house": "Casa de Lostelle", "rocket-warehouse": "Armazém Rocket",
        "tanoby-ruins": "Ruínas Tanoby", "trainer-tower": "Trainer Tower",
    }
    clean = slug.removesuffix("-area")
    for key, value in names.items():
        if key in clean:
            return region + value + clean[len(key):].replace("-", " ").title()
    return region + clean.replace("-", " ").title()


def format_condition(condition):
    name = condition["name"]
    return CONDITIONS.get(name, name.replace("-", " "))


def encounter_rows(encounters, game):
    rows = {}
    for location in encounters:
        slug = location["location_area"]["name"]
        for version in location["version_details"]:
            if version["version"]["name"] != game:
                continue
            for detail in version["encounter_details"]:
                raw_method = detail["method"]["name"]
                method = METHODS.get(raw_method, raw_method.replace("-", " ").title())
                conditions = [format_condition(value) for value in detail.get("condition_values", [])]
                if conditions:
                    method += " · " + ", ".join(conditions)
                levels = [detail["min_level"], detail["max_level"]]
                special = raw_method in SPECIAL_METHODS
                rate = None if special else detail["chance"]
                key = (slug, method, *levels)
                if key not in rows:
                    rows[key] = dict(area=area_name(slug), method=method, rate=rate,
                                     special=special, levels=levels)
                elif rate is not None:
                    rows[key]["rate"] = max(rows[key]["rate"] or 0, rate)
    return sorted(rows.values(), key=lambda row: (row["area"], row["method"], row["levels"]))


def evolution_method(details):
    detail = next((row for row in details
                   if (row.get("version_group") or {}).get("name") in
                   {"diamond-pearl", "platinum", "heartgold-soulsilver"}),
                  details[0] if details else {})
    trigger = (detail.get("trigger") or {}).get("name", "")
    if trigger == "level-up":
        if detail.get("min_happiness"):
            return "Amizade alta"
        return f"Nível {detail['min_level']}" if detail.get("min_level") else "Subir de nível"
    if trigger == "use-item":
        item = (detail.get("item") or {}).get("name", "item")
        return f"Usar {EVOLUTION_ITEMS.get(item, item.replace('-', ' ').title())}"
    if trigger == "trade":
        held = (detail.get("held_item") or {}).get("name")
        held_label = EVOLUTION_ITEMS.get(held, held.replace("-", " ").title()) if held else None
        return "Troca" + (f" segurando {held_label}" if held_label else "")
    return trigger.replace("-", " ").title() or "Evolui"


def evolution_paths(node, names, species_path=(), methods=()):
    species_id = _resource_id(node["species"]["url"])
    if species_id > 493:
        if species_path:
            return []
        return [path for child in node.get("evolves_to", [])
                for path in evolution_paths(child, names)]
    species_path = (*species_path, species_id)
    children = [child for child in node.get("evolves_to", [])
                if _resource_id(child["species"]["url"]) <= 493]
    if not children:
        return [dict(species=list(species_path), methods=list(methods))]
    result = []
    for child in children:
        method = evolution_method(child.get("evolution_details", []))
        result.extend(evolution_paths(child, names, species_path, (*methods, method)))
    return result


def main():
    catalog = json.loads((ROOT / "server/web/assets/catalog.json").read_text(encoding="utf-8"))
    names = catalog["names"]
    platinum_dex = fetch("pokedex/extended-sinnoh")
    johto_dex = fetch("pokedex/updated-johto")
    regional = {
        "sinnoh-dp": dict(id="sinnoh", name="Sinnoh", speciesIds=list(DP_SINNOH_DEX),
                          games=["diamond", "pearl"]),
        "sinnoh-platinum": dict(id="sinnoh", name="Sinnoh", speciesIds=[
            _resource_id(row["pokemon_species"]["url"]) for row in platinum_dex["pokemon_entries"]],
            games=["platinum"]),
        "johto": dict(id="johto", name="Johto", speciesIds=[
            _resource_id(row["pokemon_species"]["url"]) for row in johto_dex["pokemon_entries"]],
            games=["heartgold", "soulsilver"]),
    }

    resources = {}
    def read_species(species_id):
        return species_id, dict(pokemon=fetch(f"pokemon/{species_id}"),
                                encounters=fetch(f"pokemon/{species_id}/encounters"),
                                species=fetch(f"pokemon-species/{species_id}"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as workers:
        for species_id, value in workers.map(read_species, range(1, 494)):
            resources[species_id] = value
    species_names = {row["pokemon"]["name"]: names[index]
                     for index, row in resources.items()}
    chain_urls = sorted({row["species"]["evolution_chain"]["url"]
                         for row in resources.values()})
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as workers:
        chains = list(workers.map(fetch, chain_urls))
    chain_id_for_species = {
        index: _resource_id(row["species"]["evolution_chain"]["url"])
        for index, row in resources.items()}
    families = {}
    for species_id, chain_id in chain_id_for_species.items():
        families.setdefault(chain_id, set()).add(species_id)

    encounters = {species_id: {game: encounter_rows(row["encounters"], game) for game in GAMES}
                  for species_id, row in resources.items()}
    apply_hgss_special_availability(encounters)
    # Mythical event encounters are fixed by distribution; the regular
    # encounter endpoint may omit them. D/P/Pt event locations are included
    # as game availability, but do not create version-exclusive badges.
    special_encounters = {
        490: {"diamond": ("Ovo recebido de Pokémon Ranger", 1),
              "pearl": ("Ovo recebido de Pokémon Ranger", 1)},
        491: {"diamond": ("Ilha da Lua Nova · evento Member Card", 40),
              "pearl": ("Ilha da Lua Nova · evento Member Card", 40),
              "platinum": ("Ilha da Lua Nova · evento Member Card", 50)},
        492: {"diamond": ("Paraíso Floral · evento Oak's Letter", 30),
              "pearl": ("Paraíso Floral · evento Oak's Letter", 30),
              "platinum": ("Paraíso Floral · evento Oak's Letter", 30)},
    }
    for species_id, games in special_encounters.items():
        for game, (area, level) in games.items():
            encounters[species_id][game].append(dict(area=area, method="Encontro de evento",
                                                       rate=None, special=True,
                                                       levels=[level, level]))

    direct = {game: set() for game in GAMES}
    for species_id in resources:
        for game in GAMES:
            if encounters[species_id][game]:
                direct[game].add(species_id)
    available = {game: set() for game in GAMES}
    for family in families.values():
        for game in GAMES:
            if family & direct[game]:
                available[game].update(family)

    regional_numbers = {dex_id: {species: index for index, species in enumerate(
        info["speciesIds"], start=1)} for dex_id, info in regional.items()}
    species = []
    for species_id in range(1, 494):
        record = resources[species_id]
        avail = [game for game in GAMES if species_id in available[game]]
        regional_ids = {game: numbers[species_id]
                        for dex_id, numbers in regional_numbers.items()
                        if species_id in numbers
                        for game in regional[dex_id]["games"]}
        # Platinum is a standalone release, not a member of an exclusive pair.
        exclusive = version_exclusive_for(avail)
        species.append(dict(
            id=species_id, regionalId=next(iter(regional_ids.values()), None),
            regionalIds=regional_ids, name=names[species_id],
            pokemonDb=f"https://pokemondb.net/pokedex/{record['pokemon']['name']}",
            sprite=species_id,
            types=TYPE_OVERRIDES.get(species_id, [row["type"]["name"].capitalize()
                 for row in sorted(record["pokemon"]["types"], key=lambda row: row["slot"])]),
            exclusiveTo=exclusive,
            unobtainableIn=[game for game in GAMES if game not in avail],
            availableIn=avail, evolutionChain=chain_id_for_species[species_id],
            encounters={game: encounters[species_id][game] for game in GAMES},
        ))

    evolution_chains = []
    for chain in chains:
        paths = evolution_paths(chain["chain"], species_names)
        unique, seen = [], set()
        for path in paths:
            key = (tuple(path["species"]), tuple(path["methods"]))
            if path["species"] and key not in seen:
                seen.add(key); unique.append(path)
        evolution_chains.append(dict(id=chain["id"], paths=unique))

    data = {
        "generation": 4,
        "games": [
            {"id": "diamond", "name": "Diamond", "set": "Diamond / Pearl", "console": "Nintendo DS", "cover": "game-diamond.jpg"},
            {"id": "pearl", "name": "Pearl", "set": "Diamond / Pearl", "console": "Nintendo DS", "cover": "game-pearl.jpg"},
            {"id": "platinum", "name": "Platinum", "set": "Platinum", "console": "Nintendo DS", "cover": "game-platinum.jpg"},
            {"id": "heartgold", "name": "HeartGold", "set": "HeartGold / SoulSilver", "console": "Nintendo DS", "cover": "game-heartgold.jpg"},
            {"id": "soulsilver", "name": "SoulSilver", "set": "HeartGold / SoulSilver", "console": "Nintendo DS", "cover": "game-soulsilver.jpg"},
        ],
        "evolutionChains": sorted(evolution_chains, key=lambda row: row["id"]),
        "rateNote": "As chances são relativas aos encontros daquele local e método; encontros especiais podem depender de eventos ou condições da história.",
        "sources": {
            "pokeApiExtendedSinnohDex": "https://pokeapi.co/api/v2/pokedex/extended-sinnoh",
            "pokeApiUpdatedJohtoDex": "https://pokeapi.co/api/v2/pokedex/updated-johto",
            "pokeApiPokemon": "https://pokeapi.co/api/v2/pokemon/{id}",
            "pokeApiEncounters": "https://pokeapi.co/api/v2/pokemon/{id}/encounters",
            "pokeApiEvolutionChains": "https://pokeapi.co/api/v2/evolution-chain/{id}",
            "pokemonDbDiamondPearlDex": "https://pokemondb.net/pokedex/game/diamond-pearl",
            "pokemonDbPlatinumDex": "https://pokemondb.net/pokedex/game/platinum",
            "pokemonDbHGSSDex": "https://pokemondb.net/pokedex/game/heartgold-soulsilver",
            "pokemonDbDPVersionExclusives": "https://pokemondb.net/diamond-pearl/exclusive",
            "pokemonDbHGSSVersionExclusives": "https://pokemondb.net/heartgold-soulsilver/exclusive",
        },
        "species": species,
        "regions": list(regional.values()),
    }
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    output = ROOT / "server/web/assets/dex-gen4.json"
    output.write_text(encoded, encoding="utf-8")
    print(f"Generated {len(species)} Gen-IV entries, {len(evolution_chains)} families ({len(encoded)} bytes).")


if __name__ == "__main__":
    main()
