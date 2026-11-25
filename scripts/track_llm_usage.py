"""Benchmark and stage-by-stage LLM request/token tracker against the running server."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _request(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    trace_id: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict:
    headers = dict(extra_headers or {})
    data = None
    if trace_id:
        headers["X-Trace-Id"] = trace_id
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} em {url}: {body[:400]}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Rastreia chamadas e tokens de LLM por etapa na aplicação ativa.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--out", default="outputs/llm_tracking_report.json")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    health = _request(f"{base}/api/health")
    print("Health:", json.dumps(health))
    if not health.get("agro_postgres_available"):
        raise SystemExit("PostgreSQL indisponível em /api/health. Suba o banco antes de rodar o tracker.")

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    report: dict = {"base_url": base, "health": health, "scenarios": []}
    no_cache = {"X-No-Cache": "1"}

    # S1: Fluxos interativos de mapa e linha do tempo sem IA
    s1_trace = f"track-s1-no-llm-{stamp}"
    t0 = time.perf_counter()
    _request(f"{base}/api/agro/meta")
    _request(f"{base}/api/agro/choropleth?metric=ibge_soja_producao_t&year=2025&grain=state")
    _request(f"{base}/api/agro/flows?product=soja&year=2022&grain=state")
    _request(
        f"{base}/api/agro/temporal",
        method="POST",
        payload={"metric": "ibge_soja_producao_t", "uf": "MT", "start_year": 2015, "end_year": 2025},
        trace_id=s1_trace,
    )
    _request(f"{base}/api/agro/mapbiomas?year=2025&uf=MT&classes=39")
    s1_track = _request(f"{base}/api/llm/tracker?{urlencode({'trace_id': s1_trace})}")
    report["scenarios"].append({
        "id": "S1",
        "name": "Filtros do Explorar + Linha do Tempo direta + MapBiomas (sem IA)",
        "trace_id": s1_trace,
        "wall_seconds": round(time.perf_counter() - t0, 2),
        "ui_reported_tokens": 0,
        "tracker": s1_track,
    })

    # S2: Pergunta temporal via chat (sem cache para medir gasto real)
    s2_trace = f"track-s2-temporal-{stamp}"
    t0 = time.perf_counter()
    s2_res = _request(
        f"{base}/api/ask",
        method="POST",
        payload={
            "mode": "agro",
            "domain": "auto",
            "k": 6,
            "question": "Mostre a evolução da produção de soja no Mato Grosso entre 2015 e 2025",
        },
        trace_id=s2_trace,
        extra_headers=no_cache,
    )
    s2_track = _request(f"{base}/api/llm/tracker?{urlencode({'trace_id': s2_trace})}")
    report["scenarios"].append({
        "id": "S2",
        "name": "Chat Temporal (Soja MT 2015–2025)",
        "trace_id": s2_trace,
        "wall_seconds": round(time.perf_counter() - t0, 2),
        "ui_reported_tokens": s2_res.get("total_tokens", s2_res.get("input_tokens", 0) + s2_res.get("output_tokens", 0)),
        "available_views": [v.get("key") for v in s2_res.get("available_views", [])],
        "tracker": s2_track,
    })

    # S3: Pergunta SQL + Mapa (sem cache para medir gasto real)
    s3_q = "Quais os 5 municípios do Pará com maiores emissões de mudança de uso da terra em 2024? Mostre no mapa."
    s3_trace = f"track-s3-sql-map-{stamp}"
    t0 = time.perf_counter()
    s3_res = _request(
        f"{base}/api/ask",
        method="POST",
        payload={"mode": "agro", "domain": "auto", "k": 6, "question": s3_q},
        trace_id=s3_trace,
        extra_headers=no_cache,
    )
    s3_track = _request(f"{base}/api/llm/tracker?{urlencode({'trace_id': s3_trace})}")
    report["scenarios"].append({
        "id": "S3",
        "name": "Chat SQL + Mapa (Emissões MUT no Pará em 2024)",
        "trace_id": s3_trace,
        "wall_seconds": round(time.perf_counter() - t0, 2),
        "ui_reported_tokens": s3_res.get("total_tokens", s3_res.get("input_tokens", 0) + s3_res.get("output_tokens", 0)),
        "available_views": [v.get("key") for v in s3_res.get("available_views", [])],
        "tracker": s3_track,
    })

    # S4: Pergunta repetida (cache hit no servidor -> 0 LLM)
    s4_trace = f"track-s4-cache-hit-{stamp}"
    t0 = time.perf_counter()
    s4_res = _request(
        f"{base}/api/ask",
        method="POST",
        payload={"mode": "agro", "domain": "auto", "k": 6, "question": s3_q},
        trace_id=s4_trace,
    )
    s4_track = _request(f"{base}/api/llm/tracker?{urlencode({'trace_id': s4_trace})}")
    report["scenarios"].append({
        "id": "S4",
        "name": "Pergunta repetida (cache hit no servidor)",
        "trace_id": s4_trace,
        "wall_seconds": round(time.perf_counter() - t0, 2),
        "cached_response": bool(s4_res.get("cached_response")),
        "ui_reported_tokens": 0 if s4_res.get("cached_response") else s4_res.get("total_tokens", 0),
        "tracker": s4_track,
    })

    # S5: Chat Só Leis (sem cache para medir gasto real)
    s5_trace = f"track-s5-laws-{stamp}"
    t0 = time.perf_counter()
    s5_res = _request(
        f"{base}/api/ask",
        method="POST",
        payload={
            "mode": "laws",
            "domain": "law",
            "k": 6,
            "question": "Segundo o Código Florestal, como é definida a Reserva Legal?",
        },
        trace_id=s5_trace,
        extra_headers=no_cache,
    )
    s5_track = _request(f"{base}/api/llm/tracker?{urlencode({'trace_id': s5_trace})}")
    report["scenarios"].append({
        "id": "S5",
        "name": "Chat Só Leis (Código Florestal — Reserva Legal)",
        "trace_id": s5_trace,
        "wall_seconds": round(time.perf_counter() - t0, 2),
        "ui_reported_tokens": s5_res.get("total_tokens", s5_res.get("input_tokens", 0) + s5_res.get("output_tokens", 0)),
        "available_views": [v.get("key") for v in s5_res.get("available_views", [])],
        "tracker": s5_track,
    })

    print("\n=== RESUMO DO TRACKER DE LLM ===")
    grand_calls = 0
    grand_ui = 0
    grand_actual = 0
    for sc in report["scenarios"]:
        tot = sc["tracker"]["summary"]["totals"]
        ui_tot = sc["ui_reported_tokens"]
        hidden = tot["total_tokens"] - ui_tot
        grand_calls += tot["calls"]
        grand_ui += ui_tot
        grand_actual += tot["total_tokens"]
        print(
            f"\n[{sc['id']}] {sc['name']} ({sc['wall_seconds']}s)\n"
            f"  Chamadas LLM: {tot['calls']} | Tokens reais: {tot['total_tokens']:,} "
            f"(in={tot['input_tokens']:,}, out={tot['output_tokens']:,}, "
            f"cache_read={tot['cache_read_tokens']:,}, cache_write={tot['cache_creation_tokens']:,}) | "
            f"UI reportado: {ui_tot:,} | Oculto (não somado na UI): {hidden:,}"
        )
        for ev in sc["tracker"]["events"]:
            print(
                f"    - {ev['stage']:28s} | {ev['seconds']:5.2f}s | "
                f"in={ev['input_tokens']:5d} out={ev['output_tokens']:4d} "
                f"sys={ev['system_chars']:5d}ch tools={ev['tools_count']}({ev['tools_chars']}ch) "
                f"msgs={ev['messages_count']}({ev['messages_chars']}ch) "
                f"ret={ev.get('tool_calls_returned', [])} stop={ev.get('stop_reason')}"
            )

    print(
        f"\nTOTAL GERAL: {grand_calls} chamadas LLM | "
        f"{grand_actual:,} tokens reais | {grand_ui:,} reportados na UI | "
        f"diferença oculta: {grand_actual - grand_ui:,} tokens"
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório salvo em {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
