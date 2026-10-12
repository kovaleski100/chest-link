#!/usr/bin/env python3
"""Build the bundled, offline Gen-I Pokédex data from public PokéAPI records.

Pokémon names and sprites are taken from the project's existing attributed
catalog. Version-exclusive lists are transcribed from Pokémon Database.
"""
import concurrent.futures
import json
from pathlib import Path
import re
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
API = "https://pokeapi.co/api/v2"
VERSIONS = ("red", "blue", "yellow")
EXCLUSIVE = {
    "red": [23, 24, 43, 44, 45, 56, 57, 58, 59, 123, 125],
    "blue": [27, 28, 37, 38, 52, 53, 69, 70, 71, 126, 127],
}
YELLOW_UNOBTAINABLE = [13, 14, 15, 23, 24, 26, 52, 53, 109, 110, 124, 125, 126]
# PokeAPI reports present-day types; these species had different types in
# Pokémon Red, Blue, and Yellow (before Steel/Fairy existed or were assigned).
GEN1_TYPE_OVERRIDES = {
    35: ["Normal"], 36: ["Normal"], 39: ["Normal"], 40: ["Normal"],
    81: ["Electric"], 82: ["Electric"], 122: ["Psychic"],
}
METHODS = {
    "walk": "Andando", "surf": "Surf", "old-rod": "Vara velha",
    "good-rod": "Vara boa", "super-rod": "Supervara", "gift": "Presente",
    "only-one": "Encontro único", "rock-smash": "Quebra-rochas",
    "npc-trade": "Troca com NPC", "static": "Encontro fixo", "pokeflute": "Poké Flauta",
}
RANDOM_METHODS = {"walk", "surf", "old-rod", "good-rod", "super-rod"}
EVOLUTION_ITEMS = {
    "fire-stone": "Pedra do Fogo", "water-stone": "Pedra da Água",
    "thunder-stone": "Pedra do Trovão", "leaf-stone": "Pedra da Folha",
    "moon-stone": "Pedra da Lua",
}


def fetch(url):
    for attempt in range(5):
        request = urllib.request.Request(url, headers={"User-Agent": "ChestLink/0.3 (offline Gen-I dex data)"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 4:
                raise
            time.sleep(0.6 * (attempt + 1))


def area_name(slug):
    route_center = re.match(r"kanto-route-(\d+)-pokemon-center", slug)
    if route_center:
        return f"Centro Pokémon da Rota {route_center.group(1)}"
    route = re.match(r"kanto-(sea-)?route-(\d+)(?:-(north|south)(?:-|$)|-area$|$)", slug)
    if route:
        name = f"Rota marítima {route.group(2)}" if route.group(1) else f"Rota {route.group(2)}"
        direction = {"north": "norte", "south": "sul"}.get(route.group(3))
        return f"{name} (trecho {direction})" if direction else name
    aliases = {
        "pallet-town-area": "Cidade de Pallet", "celadon-city-area": "Cidade de Celadon",
        "celadon-city-celadon-mansion": "Mansão Celadon", "celadon-city-prize-corner": "Cassino de Celadon",
        "cerulean-city-area": "Cidade de Cerulean", "cerulean-cave-1f": "Caverna de Cerulean · 1º andar",
        "cerulean-cave-2f": "Caverna de Cerulean · 2º andar", "cerulean-cave-b1f": "Caverna de Cerulean · subsolo",
        "cinnabar-island-area": "Ilha Cinnabar", "cinnabar-island-cinnabar-lab": "Laboratório de Cinnabar",
        "digletts-cave": "Caverna dos Diglett", "fuchsia-city-area": "Cidade de Fuchsia",
        "pokemon-tower-3f": "Torre Pokémon · 3º andar", "pokemon-tower-4f": "Torre Pokémon · 4º andar",
        "pokemon-tower-5f": "Torre Pokémon · 5º andar", "pokemon-tower-6f": "Torre Pokémon · 6º andar",
        "pokemon-tower-7f": "Torre Pokémon · 7º andar", "pokemon-mansion-1f": "Mansão Pokémon · 1º andar",
        "pokemon-mansion-2f": "Mansão Pokémon · 2º andar", "pokemon-mansion-3f": "Mansão Pokémon · 3º andar",
        "pokemon-mansion-b1f": "Mansão Pokémon · subsolo", "power-plant": "Usina Elétrica",
        "rock-tunnel-b1f": "Túnel da Rocha · 1º subsolo", "rock-tunnel-b2f": "Túnel da Rocha · 2º subsolo",
        "safari-zone-area-1-east": "Zona do Safári · Área 1 (leste)",
        "safari-zone-area-2-north": "Zona do Safári · Área 2 (norte)",
        "safari-zone-area-3-west": "Zona do Safári · Área 3 (oeste)",
        "safari-zone-middle": "Zona do Safári · centro", "saffron-city-fighting-dojo": "Dojo de Lutas de Saffron",
        "saffron-city-silph-co-7f": "Silph Co. · 7º andar", "seafoam-islands-1f": "Ilhas Seafoam · 1º andar",
        "seafoam-islands-b1f": "Ilhas Seafoam · 1º subsolo", "seafoam-islands-b2f": "Ilhas Seafoam · 2º subsolo",
        "seafoam-islands-b3f": "Ilhas Seafoam · 3º subsolo", "seafoam-islands-b4f": "Ilhas Seafoam · 4º subsolo",
        "underground-path": "Passagem subterrânea", "vermilion-city-area": "Cidade de Vermilion",
        "vermilion-city-ss-anne-dock": "Cais do S.S. Anne", "viridian-city-area": "Cidade de Viridian",
        "viridian-forest-area": "Floresta de Viridian",
        "mt-moon-1f": "Monte Lua · 1º andar", "mt-moon-b1f": "Monte Lua · 1º subsolo",
        "mt-moon-b2f": "Monte Lua · 2º subsolo",
    }
    normalized = slug[6:] if slug.startswith("kanto-") else slug
    if normalized in aliases:
        return aliases[normalized]
    if normalized.removesuffix("-area") in aliases:
        return aliases[normalized.removesuffix("-area")]
    victory = re.match(r"kanto-victory-road-2-(\d)f", slug)
    if victory:
        return f"Estrada da Vitória · {victory.group(1)}º andar"
    value = normalized.removesuffix("-area")
    value = value.replace("sea-route", "sea route").replace("mt-moon", "mount moon")
    value = value.replace("pokemon-mansion", "pokemon mansion")
    return " ".join(part.upper() if part in {"b1f", "b2f", "b3f", "b4f", "1f", "2f", "3f"}
                     else part.capitalize() for part in value.split("-"))


def read_species(species_id):
    pokemon, encounters, species = (
        fetch(f"{API}/pokemon/{species_id}/"),
        fetch(f"{API}/pokemon/{species_id}/encounters"),
        fetch(f"{API}/pokemon-species/{species_id}/"),
    )
    locations = {version: {} for version in VERSIONS}
    for location in encounters:
        area = area_name(location["location_area"]["name"])
        for detail in location["version_details"]:
            version = detail["version"]["name"]
            if version not in locations:
                continue
            methods = {}
            for encounter in detail["encounter_details"]:
                method = encounter["method"]["name"]
                row = methods.setdefault(method, {"chance": 0, "levels": []})
                if method in RANDOM_METHODS:
                    row["chance"] += encounter["chance"]
                row["levels"].extend((encounter["min_level"], encounter["max_level"]))
            for method, row in methods.items():
                if method in RANDOM_METHODS and not row["chance"]:
                    continue
                locations[version].setdefault((area, method), {
                    "area": area, "method": METHODS.get(method, method.replace("-", " ").capitalize()),
                    "rate": row["chance"] if method in RANDOM_METHODS else None,
                    "special": method not in RANDOM_METHODS,
                    "levels": [min(row["levels"]), max(row["levels"])],
                })
    return species_id, {
        "slug": pokemon["name"],
        "types": [entry["type"]["name"].capitalize() for entry in pokemon["types"]],
        "evolutionChain": species["evolution_chain"]["url"],
        "encounters": {version: sorted(rows.values(), key=lambda row: (-(row["rate"] or 0), row["area"], row["method"]))
                       for version, rows in locations.items()},
    }


def evolution_method(details):
    if details.get("min_level"):
        return f"Nível {details['min_level']}"
    if details.get("trigger", {}).get("name") == "trade":
        return "Troca"
    item = details.get("item")
    if item:
        name = item["name"]
        return f"Usar {EVOLUTION_ITEMS.get(name, name.replace('-', ' ').title())}"
    if details.get("min_happiness"):
        return "Amizade alta"
    if details.get("min_beauty"):
        return "Beleza alta"
    return "Condição especial"


def evolution_species_id(node):
    return int(node["species"]["url"].rstrip("/").split("/")[-1])


def evolution_paths(node, species_path=(), methods=()):
    species_id = evolution_species_id(node)
    # Some Gen-I species now evolve from baby Pokémon introduced later (for
    # example, Jynx from Smoochum). Keep the Gen-I species in the catalog,
    # but never add a later-generation parent to a Gen-I evolution line.
    if species_id > 151:
        return [path for child in node.get("evolves_to", [])
                for path in evolution_paths(child, species_path, methods)]
    species_path = (*species_path, species_id)
    children = [child for child in node.get("evolves_to", []) if evolution_species_id(child) <= 151]
    if not children:
        return [{"species": list(species_path), "methods": list(methods)}]
    result = []
    for child in children:
        details = child.get("evolution_details", [])
        detail = next((row for row in details if row.get("version_group", {}).get("name") == "red-blue"),
                      next((row for row in details if row.get("version_group", {}).get("name") == "yellow"),
                           details[0] if details else {}))
        result.extend(evolution_paths(child, species_path, (*methods, evolution_method(detail))))
    return result


def main():
    catalog = json.loads((ROOT / "PC/web/assets/catalog.json").read_text(encoding="utf-8"))
    sprites = json.loads((ROOT / "PC/web/assets/sprites.json").read_text(encoding="utf-8"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as workers:
        records = dict(workers.map(read_species, range(1, 152)))
    chain_urls = sorted({record["evolutionChain"] for record in records.values()})
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as workers:
        chain_data = list(workers.map(fetch, chain_urls))
    evolution_chains = []
    chain_for_species = {}
    for chain in chain_data:
        paths = evolution_paths(chain["chain"])
        chain_id = chain["id"]
        evolution_chains.append({"id": chain_id, "paths": paths})
        for path in paths:
            for species_id in path["species"]:
                chain_for_species[species_id] = chain_id
    species = []
    for species_id in range(1, 152):
        record = records[species_id]
        exclusive_to = "red" if species_id in EXCLUSIVE["red"] else \
                       "blue" if species_id in EXCLUSIVE["blue"] else None
        unavailable = ["yellow"] if species_id in YELLOW_UNOBTAINABLE else []
        available_in = [game for game in VERSIONS if
                        (game == "yellow" and game not in unavailable) or
                        (game in ("red", "blue") and exclusive_to != ("blue" if game == "red" else "red"))]
        species.append({
            "id": species_id,
            "name": catalog["names"][species_id],
            "pokemonDb": f"https://pokemondb.net/pokedex/{record['slug']}",
            "sprite": sprites.get(str(species_id), 0),
            "types": GEN1_TYPE_OVERRIDES.get(species_id, record["types"]),
            "exclusiveTo": exclusive_to,
            "unobtainableIn": unavailable,
            "availableIn": available_in,
            "evolutionChain": chain_for_species[species_id],
            "encounters": record["encounters"],
        })
    data = {
        "generation": 1,
        "games": [
            {"id": "red", "name": "Red", "set": "Red / Blue", "cover": "game-red.png"},
            {"id": "blue", "name": "Blue", "set": "Red / Blue", "cover": "game-blue.png"},
            {"id": "yellow", "name": "Yellow", "set": "Yellow", "cover": "game-yellow.png"},
        ],
        "evolutionChains": evolution_chains,
        "rateNote": "Percentual dos slots aleatórios naquele local e método; não é chance por minuto nem chance de captura. Presentes e eventos aparecem sem percentual.",
        "sources": {
            "pokemonDbDex": "https://pokemondb.net/pokedex/game/red-blue-yellow",
            "pokemonDbGen1Types": "https://pokemondb.net/pokedex/game/red-blue-yellow",
            "pokemonDbCharmander": "https://pokemondb.net/pokedex/charmander",
            "pokemonDbExclusives": "https://pokemondb.net/red-blue/exclusive",
            "pokemonDbYellow": "https://pokemondb.net/yellow",
            "pokeApiEncounters": "https://pokeapi.co/docs/v2#pokemon-encounters",
            "pokeApiEvolutionChains": "https://pokeapi.co/docs/v2#evolution-chains",
            "redCover": "https://archives.bulbagarden.net/wiki/File:Red_EN_boxart.png",
            "blueCover": "https://archives.bulbagarden.net/wiki/File:Blue_EN_boxart.png",
            "yellowCover": "https://bulbapedia.bulbagarden.net/wiki/File:Yellow_EN_boxart.png",
        },
        "species": species,
    }
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    for folder in (ROOT / "PC/web/assets", ROOT / "codigo/server/web/assets"):
        (folder / "dex-gen1.json").write_text(encoded, encoding="utf-8")
    print(f"Generated {len(species)} Gen-I entries ({len(encoded)} bytes).")


if __name__ == "__main__":
    main()
