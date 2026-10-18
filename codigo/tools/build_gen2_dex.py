#!/usr/bin/env python3
"""Build the bundled offline Gen-II Pokédex from PokéAPI records."""
import concurrent.futures
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
API = "https://pokeapi.co/api/v2"
GAMES = ("gold", "silver", "crystal")

# English-language Gold, Silver, and Crystal. These are the Gold/Silver sides
# of the paired exclusives; Crystal availability is handled separately.
GOLD_EXCLUSIVES = {56, 57, 58, 59, 167, 168, 207, 216, 217, 226}
SILVER_EXCLUSIVES = {37, 38, 52, 53, 165, 166, 225, 227, 231, 232}
CRYSTAL_UNAVAILABLE = {37, 38, 56, 57, 179, 180, 181, 203, 223, 224}

METHODS = {
    "walk": "Andando", "roaming-grass": "Encontro errante", "surf": "Surfe",
    "old-rod": "Vara velha", "good-rod": "Vara boa", "super-rod": "Supervara",
    "headbutt-low": "Cabeçada · árvore baixa", "headbutt-normal": "Cabeçada · árvore média",
    "headbutt-high": "Cabeçada · árvore alta", "rock-smash": "Quebra-Rocha",
    "squirt-bottle": "Regar árvore", "pokeflute": "Poké Flauta", "static": "Encontro fixo",
    "gift": "Presente", "gift-egg": "Ovo recebido", "npc-trade": "Troca no jogo",
}
SPECIAL_METHODS = {"static", "gift", "gift-egg", "npc-trade", "roaming-grass"}
CONDITIONS = {
    "time-morning": "manhã", "time-day": "dia", "time-night": "noite",
    "swarm-yes": "com enxame", "swarm-no": "sem enxame",
    "weekday-friday": "sexta-feira",
    "story-progress-awakened-beasts": "após despertar as feras lendárias",
    "other-virtual-console": "Virtual Console",
}
EVOLUTION_ITEMS = {
    "fire-stone": "Pedra do Fogo", "water-stone": "Pedra da Água",
    "thunder-stone": "Pedra do Trovão", "leaf-stone": "Pedra da Folha",
    "sun-stone": "Pedra do Sol", "moon-stone": "Pedra da Lua",
    "metal-coat": "Revestimento Metálico", "dragon-scale": "Escama de Dragão",
    "kings-rock": "Pedra do Rei", "upgrade": "Melhorador", "up-grade": "Melhorador",
}
GEN2_TYPE_OVERRIDES = {
    35: ["Normal"], 36: ["Normal"], 39: ["Normal"], 40: ["Normal"],
    122: ["Psychic"], 173: ["Normal"], 174: ["Normal"], 175: ["Normal"],
    176: ["Normal", "Flying"], 183: ["Water"], 184: ["Water"],
    209: ["Normal"], 210: ["Normal"],
}
SPECIAL_AREAS = {
    "azalea-town-area": "Cidade de Azalea", "blackthorn-city-area": "Cidade de Blackthorn",
    "burned-tower-1f": "Torre Queimada · 1º andar", "burned-tower-b1f": "Torre Queimada · 1º subsolo",
    "celadon-city-area": "Kanto · Cidade de Celadon", "celadon-city-prize-corner": "Kanto · Cassino de Celadon",
    "cerulean-city-area": "Kanto · Cidade de Cerulean", "cherrygrove-city-area": "Cidade de Cherrygrove",
    "cianwood-city-area": "Cidade de Cianwood", "cianwood-city-manias-house": "Casa de Mania · Cianwood",
    "cinnabar-island-area": "Kanto · Ilha Cinnabar", "dark-cave-blackthorn-city-entrance": "Caverna Escura · entrada de Blackthorn",
    "dark-cave-violet-city-entrance": "Caverna Escura · entrada de Violet", "digletts-cave-area": "Kanto · Caverna dos Diglett",
    "dragons-den-area": "Covil do Dragão", "ecruteak-city-area": "Cidade de Ecruteak",
    "fuchsia-city-area": "Kanto · Cidade de Fuchsia", "goldenrod-city-bills-house": "Casa de Bill · Goldenrod",
    "goldenrod-city-department-store-5f": "Loja de Departamentos de Goldenrod · 5º andar",
    "goldenrod-city-game-corner": "Cassino de Goldenrod", "goldenrod-city-north-gate": "Portão norte de Goldenrod",
    "ice-path-1f": "Caminho de Gelo · 1º andar", "ice-path-b1f": "Caminho de Gelo · 1º subsolo",
    "ice-path-b2f": "Caminho de Gelo · 2º subsolo", "ice-path-b3f": "Caminho de Gelo · 3º subsolo",
    "ilex-forest-area": "Floresta Ilex", "kanto-power-plant-area": "Kanto · Usina Elétrica",
    "lake-of-rage-area": "Lago da Fúria", "mt-moon-1f": "Kanto · Monte Moon · 1º andar",
    "mt-mortar-1f": "Monte Mortar · 1º andar", "mt-mortar-b1f": "Monte Mortar · 1º subsolo",
    "mt-mortar-lower-cave": "Monte Mortar · caverna inferior", "mt-mortar-upper-cave": "Monte Mortar · caverna superior",
    "mt-silver-1f": "Monte Silver · 1º andar", "mt-silver-2f": "Monte Silver · 2º andar",
    "mt-silver-outside": "Monte Silver · área externa", "mt-silver-top": "Monte Silver · cume",
    "national-park-area": "Parque Nacional", "new-bark-town-area": "Cidade de New Bark",
    "olivine-city-area": "Cidade de Olivine", "pallet-town-area": "Kanto · Cidade de Pallet",
    "pewter-city-area": "Kanto · Cidade de Pewter", "roaming-johto-area": "Rotas de Johto · encontro errante",
    "rock-tunnel-1f": "Kanto · Túnel da Rocha · 1º andar", "rock-tunnel-b1f": "Kanto · Túnel da Rocha · 1º subsolo",
    "ruins-of-alph-interior-a": "Ruínas de Alph · interior A", "ruins-of-alph-interior-b": "Ruínas de Alph · interior B",
    "ruins-of-alph-interior-c": "Ruínas de Alph · interior C", "ruins-of-alph-interior-d": "Ruínas de Alph · interior D",
    "ruins-of-alph-outside": "Ruínas de Alph · área externa", "slowpoke-well-1f": "Poço Slowpoke · 1º andar",
    "slowpoke-well-b1f": "Poço Slowpoke · 1º subsolo", "sprout-tower-2f": "Torre Sprout · 2º andar",
    "sprout-tower-3f": "Torre Sprout · 3º andar", "team-rocket-hq-area": "Esconderijo da Equipe Rocket",
    "tohjo-falls-area": "Cataratas Tohjo", "union-cave-1f": "Caverna União · 1º andar",
    "union-cave-b1f": "Caverna União · 1º subsolo", "union-cave-b2f": "Caverna União · 2º subsolo",
    "vermilion-city-area": "Kanto · Cidade de Vermilion", "vermilion-city-ss-anne-dock": "Kanto · Cais do S.S. Anne",
    "violet-city-area": "Cidade de Violet", "violet-city-southwest-house": "Casa a sudoeste de Violet",
    "viridian-city-area": "Kanto · Cidade de Viridian", "whirl-islands-1f": "Ilhas Redemoinho · 1º andar",
    "whirl-islands-b1f": "Ilhas Redemoinho · 1º subsolo", "whirl-islands-b2f": "Ilhas Redemoinho · 2º subsolo",
    "whirl-islands-b3f": "Ilhas Redemoinho · 3º subsolo",
}


def fetch(path):
    url = path if path.startswith("https://") else f"{API}/{path.lstrip('/')}"
    for attempt in range(5):
        request = urllib.request.Request(url, headers={"User-Agent": "ChestLink offline Gen-II dex data"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 4:
                raise
            time.sleep(0.6 * (attempt + 1))


def area_name(slug):
    route = re.match(r"^(johto|kanto)-sea-route-(\d+)", slug)
    if route:
        prefix = "Kanto · " if route.group(1) == "kanto" else ""
        return f"{prefix}Rota marítima {route.group(2)}"
    route = re.match(r"^(johto|kanto)-route-(\d+)", slug)
    if route:
        prefix = "Kanto · " if route.group(1) == "kanto" else ""
        return f"{prefix}Rota {route.group(2)}"
    victory = re.match(r"^kanto-victory-road-1-(\d+)f$", slug)
    if victory:
        return f"Kanto · Estrada da Vitória · {victory.group(1)}º andar"
    if slug in SPECIAL_AREAS:
        return SPECIAL_AREAS[slug]
    floor = re.match(r"^bell-tower-(\d+)f$", slug)
    if floor:
        return f"Campanário · {floor.group(1)}º andar"
    if slug == "bell-tower-roof":
        return "Campanário · telhado"
    return slug.replace("-area", "").replace("-", " ").title()


def format_condition(name, species_names):
    if name in CONDITIONS:
        return CONDITIONS[name]
    coins = re.fullmatch(r"coins-(\d+)", name)
    if coins:
        return f"{int(coins.group(1)):,}".replace(",", ".") + " moedas"
    trade = re.fullmatch(r"trade-(.+)", name)
    if trade:
        return f"por {species_names.get(trade.group(1), trade.group(1).replace('-', ' ').title())}"
    return name.replace("-", " ")


def encounter_rows(encounters, game, species_names):
    rows = {}
    for location in encounters:
        slug = location["location_area"]["name"]
        for version in location["version_details"]:
            if version["version"]["name"] != game:
                continue
            for detail in version["encounter_details"]:
                raw_method = detail["method"]["name"]
                method = METHODS.get(raw_method, raw_method.replace("-", " ").title())
                conditions = [format_condition(value["name"], species_names)
                              for value in detail["condition_values"]]
                if conditions:
                    method += " · " + ", ".join(conditions)
                levels = [detail["min_level"], detail["max_level"]]
                special = raw_method in SPECIAL_METHODS
                rate = None if special else detail["chance"]
                key = (slug, method, levels[0], levels[1])
                if key not in rows:
                    rows[key] = {"area": area_name(slug), "method": method, "rate": rate,
                                 "special": special, "levels": levels}
                elif rate is not None:
                    rows[key]["rate"] = max(rows[key]["rate"] or 0, rate)
    return sorted(rows.values(), key=lambda row: (row["area"], row["method"], row["levels"]))


def evolution_species_id(node):
    return int(node["species"]["url"].rstrip("/").split("/")[-1])


def evolution_method(details, species_names):
    detail = next((row for row in details
                   if (row.get("version_group") or {}).get("name") in {"gold-silver", "crystal"}),
                  details[0] if details else {})
    trigger = (detail.get("trigger") or {}).get("name", "")
    if trigger == "level-up":
        label = f"Nível {detail['min_level']}" if detail.get("min_level") else "Subir de nível"
        if detail.get("min_happiness"):
            label = "Amizade"
            if detail.get("time_of_day"):
                label += " (" + ("dia" if detail["time_of_day"] == "day" else "noite") + ")"
        elif detail.get("time_of_day"):
            label += " (" + ("dia" if detail["time_of_day"] == "day" else "noite") + ")"
        return label
    if trigger == "use-item":
        item = (detail.get("item") or {}).get("name", "item")
        return f"Usar {EVOLUTION_ITEMS.get(item, item.replace('-', ' ').title())}"
    if trigger == "trade":
        held = (detail.get("held_item") or {}).get("name")
        held_label = EVOLUTION_ITEMS.get(held, held.replace("-", " ").title()) if held else None
        return "Troca" + (f" segurando {held_label}" if held_label else "")
    return trigger.replace("-", " ").title() or "Evolui"


def evolution_paths(node, species_names, species_path=(), methods=()):
    current_id = evolution_species_id(node)
    if current_id > 251:
        # Some Gen-II families were later given a baby species (for example,
        # Happiny before Chansey). Ignore that modern root and start at the
        # first species that existed in Johto.
        if species_path:
            return []
        return [path for child in node.get("evolves_to", [])
                for path in evolution_paths(child, species_names)]
    species_path = (*species_path, current_id)
    # Stop each branch at its latest Gen-II member. Later evolutions must not
    # hide a valid final Johto-era species such as Rhydon or Chansey.
    children = [child for child in node.get("evolves_to", [])
                if evolution_species_id(child) <= 251]
    if not children:
        return [{"species": list(species_path), "methods": list(methods)}]
    result = []
    for child in children:
        child_id = evolution_species_id(child)
        edge = (evolution_method(child.get("evolution_details", []), species_names),)
        result.extend(evolution_paths(child, species_names, species_path, (*methods, *edge)))
    return result


def main():
    catalog = json.loads((ROOT / "server/web/assets/catalog.json").read_text(encoding="utf-8"))
    national_names = catalog["names"]
    pokedex = fetch("pokedex/original-johto")
    entries = pokedex["pokemon_entries"]
    regional_ids = [int(row["pokemon_species"]["url"].rstrip("/").split("/")[-1]) for row in entries]
    regional_number = {species_id: index for index, species_id in enumerate(regional_ids, start=1)}
    species_names = {row["pokemon_species"]["name"]: national_names[
        int(row["pokemon_species"]["url"].rstrip("/").split("/")[-1])] for row in entries}
    resources = {}

    def read_species(species_id):
        return species_id, {
            "pokemon": fetch(f"pokemon/{species_id}"),
            "encounters": fetch(f"pokemon/{species_id}/encounters"),
            "species": fetch(f"pokemon-species/{species_id}"),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as workers:
        for species_id, value in workers.map(read_species, range(1, 252)):
            resources[species_id] = value
    species_names.update({resources[i]["pokemon"]["name"]: national_names[i] for i in resources})

    chain_urls = sorted({row["species"]["evolution_chain"]["url"]
                         for row in resources.values()})
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as workers:
        chain_data = list(workers.map(fetch, chain_urls))
    chain_data_by_id = {row["id"]: row for row in chain_data}
    chain_for_species = {
        species_id: int(row["species"]["evolution_chain"]["url"].rstrip("/").split("/")[-1])
        for species_id, row in resources.items()
    }
    chain_families = {}
    for species_id, chain_id in chain_for_species.items():
        chain_families.setdefault(chain_id, []).append(species_id)

    encounter_data = {species_id: {game: encounter_rows(row["encounters"], game, species_names)
                                   for game in GAMES}
                      for species_id, row in resources.items()}
    for species_id in (123, 127):
        for game in GAMES:
            encounter_data[species_id][game].append({
                "area": "Parque Nacional · Concurso de Captura de Insetos",
                "method": "Concurso de captura de insetos", "rate": 5,
                "special": False, "levels": [13, 14],
            })
            encounter_data[species_id][game].sort(
                key=lambda row: (row["area"], row["method"], row["levels"]))

    breeding = {172: "Pikachu ou Raichu", 173: "Clefairy ou Clefable",
                174: "Jigglypuff ou Wigglytuff", 175: "Togetic",
                236: "Hitmonlee, Hitmonchan ou Hitmontop", 238: "Jynx",
                239: "Electabuzz", 240: "Magmar"}
    for species_id, parents in breeding.items():
        for game in GAMES:
            encounter_data[species_id][game].append({
                "area": "Creche Pokémon", "method": f"Ovo por cruzamento com {parents}",
                "rate": None, "special": True, "levels": [5, 5],
            })
            encounter_data[species_id][game].sort(
                key=lambda row: (row["area"], row["method"], row["levels"]))

    # Crystal's Odd Egg can hatch any of these seven baby species.
    for species_id in (172, 173, 174, 236, 238, 239, 240):
        # PokéAPI only labels this as a generic gift egg; preserve the exact
        # Crystal encounter name from the game's documented Odd Egg pool.
        encounter_data[species_id]["crystal"] = [
            row for row in encounter_data[species_id]["crystal"]
            if row["method"] != "Ovo recebido"]
        encounter_data[species_id]["crystal"].append({
            "area": "Creche Pokémon", "method": "Ovo Estranho · presente",
            "rate": None, "special": True, "levels": [5, 5],
        })
        encounter_data[species_id]["crystal"].sort(
            key=lambda row: (row["area"], row["method"], row["levels"]))

    direct = {game: set() for game in GAMES}
    for species_id in resources:
        for game in GAMES:
            if encounter_data[species_id][game]:
                direct[game].add(species_id)
    available = {game: set() for game in GAMES}
    for family in chain_families.values():
        for game in GAMES:
            if set(family) & direct[game]:
                available[game].update(family)
    for species_id in GOLD_EXCLUSIVES:
        available["gold"].add(species_id)
        available["silver"].discard(species_id)
    for species_id in SILVER_EXCLUSIVES:
        available["silver"].add(species_id)
        available["gold"].discard(species_id)
    for species_id in CRYSTAL_UNAVAILABLE:
        available["crystal"].discard(species_id)
    for species_id in (123, 212, 127):
        for game in GAMES:
            available[game].add(species_id)

    species = []
    for species_id in range(1, 252):
        record = resources[species_id]
        avail = [game for game in GAMES if species_id in available[game]]
        exclusive_to = ("gold" if species_id in GOLD_EXCLUSIVES else
                        "silver" if species_id in SILVER_EXCLUSIVES else
                        avail[0] if len(avail) == 1 else None)
        species.append({
            "id": species_id, "regionalId": regional_number[species_id],
            "name": national_names[species_id],
            "pokemonDb": f"https://pokemondb.net/pokedex/{record['pokemon']['name']}",
            "sprite": species_id,
            "types": GEN2_TYPE_OVERRIDES.get(species_id, [
                row["type"]["name"].capitalize()
                for row in sorted(record["pokemon"]["types"], key=lambda row: row["slot"])]),
            "exclusiveTo": exclusive_to,
            "unobtainableIn": [game for game in GAMES if game not in avail],
            "availableIn": avail, "evolutionChain": chain_for_species[species_id],
            "encounters": encounter_data[species_id],
        })

    evolution_chains = []
    for chain_id, chain in sorted(chain_data_by_id.items()):
        paths = evolution_paths(chain["chain"], species_names)
        unique_paths = []
        seen = set()
        for path in paths:
            key = (tuple(path["species"]), tuple(path["methods"]))
            if path["species"] and key not in seen:
                unique_paths.append(path)
                seen.add(key)
        evolution_chains.append({"id": chain_id, "paths": unique_paths})

    data = {
        "generation": 2,
        "games": [
            {"id": "gold", "name": "Gold", "set": "Gold / Silver", "console": "Game Boy Color", "cover": "game-gold.jpg"},
            {"id": "silver", "name": "Silver", "set": "Gold / Silver", "console": "Game Boy Color", "cover": "game-silver.jpg"},
            {"id": "crystal", "name": "Crystal", "set": "Crystal", "console": "Game Boy Color", "cover": "game-crystal.jpg"},
        ],
        "evolutionChains": evolution_chains,
        "rateNote": "As chances são relativas aos encontros daquele local e método; condições de horário, enxame e história podem alterar a disponibilidade.",
        "sources": {
            "pokeApiPokedex": "https://pokeapi.co/api/v2/pokedex/original-johto",
            "pokeApiPokemon": "https://pokeapi.co/api/v2/pokemon/{id}",
            "pokeApiEncounters": "https://pokeapi.co/api/v2/pokemon/{id}/encounters",
            "pokeApiEvolutionChains": "https://pokeapi.co/api/v2/evolution-chain/{id}",
            "pokemonDbJohtoDex": "https://pokemondb.net/pokedex/game/gold-silver-crystal",
            "gscVersionExclusives": "https://altissimo1.github.io/Main-Series/GSC/version-exclusives.html",
            "gscLocations": "https://altissimo1.github.io/Main-Series/GSC/locations.html",
        },
        "species": species,
        "region": {"id": "johto", "name": "Johto", "speciesIds": regional_ids},
    }
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    output = ROOT / "server/web/assets/dex-gen2.json"
    output.write_text(encoded, encoding="utf-8")
    print(f"Generated {len(species)} Gen-II entries ({len(encoded)} bytes).")


if __name__ == "__main__":
    main()
