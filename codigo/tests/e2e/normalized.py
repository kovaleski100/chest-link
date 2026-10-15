"""Private normalized values and cross-platform invariant comparison."""
INVARIANT_FIELDS = (
    "game", "game_version", "trainer_name", "trainer_id", "secret_id",
    "play_time_seconds", "badges_johto", "badges_kanto", "pokedex_seen",
    "pokedex_caught", "party_count", "boxed_pokemon",
)


def _field_value(row, key):
    field = row.get(key, {})
    return field.get("value") if isinstance(field, dict) else None


def normalize_hgss(snapshot):
    trainer = snapshot.get("trainer", {})
    play_time = _field_value(trainer, "playTime") or {}
    badges = snapshot.get("badges", {})
    caught = snapshot.get("pokedex", {}).get("caught", [])
    seen = snapshot.get("pokedex", {}).get("seen", [])
    pokemon = snapshot.get("pokemon", [])
    return {
        "game": snapshot.get("game"),
        "game_version": snapshot.get("gameVersion"),
        "save_sha256": snapshot.get("saveHash"),
        "trainer_name": _field_value(trainer, "name"),
        "trainer_id": _field_value(trainer, "trainerId"),
        "secret_id": _field_value(trainer, "secretId"),
        "play_time_seconds": play_time.get("totalSeconds"),
        "badges_johto": sorted(row["name"] for row in badges.get("johto", [])
                                if row.get("acquired")),
        "badges_kanto": sorted(row["name"] for row in badges.get("kanto", [])
                                if row.get("acquired")),
        "pokedex_seen": sorted(seen),
        "pokedex_caught": sorted(caught),
        "party_count": sum(mon is not None for mon in snapshot.get("party", [])),
        "boxed_pokemon": sum(mon.get("location", {}).get("area") == "box"
                              for mon in pokemon),
    }


def compare_invariants(results):
    """Raise with field names only so private trainer values stay out of logs."""
    if len(results) < 2:
        raise ValueError("A comparação precisa de ao menos dois resultados de plataforma.")
    first = results[0]
    mismatches = [field for field in INVARIANT_FIELDS
                  if any(row.get(field) != first.get(field) for row in results[1:])]
    if mismatches:
        raise ValueError("Campos invariantes diferentes: " + ", ".join(mismatches))
    return {field: True for field in INVARIANT_FIELDS}
