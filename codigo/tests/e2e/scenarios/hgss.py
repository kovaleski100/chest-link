"""Private HeartGold golden-save smoke and future cross-platform adapter."""
import os

from tests.e2e.normalized import normalize_hgss
from tests.e2e.private_saves import PrivateSaveGuard
from tests.e2e.scenarios.emulator_boot import ScenarioSkipped


def _configured_save():
    configured = os.environ.get("CHESTLINK_HGSS_SAVE", "").strip()
    if not configured:
        raise ScenarioSkipped("CHESTLINK_HGSS_SAVE não configurado; fixture HGSS privada ignorada")
    return PrivateSaveGuard(configured)


def _pc_parse(ctx, guard):
    from server.native_saves import HGSSSaveParser, RawFileSaveSource

    data, source = RawFileSaveSource(guard.path).read()
    snapshot = HGSSSaveParser().parse(data, source)
    normalized = normalize_hgss(snapshot)
    guard.verify_unchanged()
    # Full normalized content remains in a mode-0600 file under the ignored
    # private artifact area. The terminal/result summary only includes counts.
    ctx.artifacts.write_private_json("heartgold/pc-result.json", normalized)
    summary = {
        "game": normalized["game"],
        "game_version": normalized["game_version"],
        "save_sha256": guard.sha256,
        "pokedex_seen": len(normalized["pokedex_seen"]),
        "pokedex_caught": len(normalized["pokedex_caught"]),
        "party_count": normalized["party_count"],
        "boxed_pokemon": normalized["boxed_pokemon"],
    }
    return normalized, summary


def run_pc(ctx):
    guard = _configured_save()
    try:
        _normalized, summary = _pc_parse(ctx, guard)
        guard.verify_unchanged()
    except Exception:
        guard.verify_unchanged()
        raise
    return ctx.artifacts.record(
        "hgss_pc_read", "PASS", "HOST_PRIVATE",
        reason="Parser PC executado somente para leitura; valores pessoais completos foram mantidos em artifact privado.",
        metrics=summary,
        artifacts=[str(ctx.artifacts.path / "private" / "heartgold" / "pc-result.json")],
    )


def run_console_read(ctx, console):
    guard = _configured_save()
    guard.verify_unchanged()
    platform = "DS" if console == "ds" else "3DS"
    raise ScenarioSkipped(
        f"Leitor Native Saves e canal de resultado estruturado para {platform} ainda não existem; "
        f"save privado reconhecido ({guard.size_bytes} bytes, SHA-256 verificado), original somente leitura"
    )


def run_cross_platform(ctx):
    guard = _configured_save()
    try:
        _normalized, summary = _pc_parse(ctx, guard)
        guard.verify_unchanged()
    except Exception:
        guard.verify_unchanged()
        raise
    ctx.artifacts.record(
        "hgss_pc_read", "PASS", "HOST_PRIVATE",
        reason="Parser PC concluído com leitura estável e hash original preservado.",
        metrics=summary,
        artifacts=[str(ctx.artifacts.path / "private" / "heartgold" / "pc-result.json")],
    )
    raise ScenarioSkipped(
        "Parser PC passou; comparação PC == DS == 3DS aguardará os leitores/JSON estruturados de DS e 3DS. "
        f"Hash original verificado: {summary['save_sha256']}"
    )
