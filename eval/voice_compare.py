"""Comparação de modelos multimodais de voz (Etapa 8 de docs/plano_voz.md).

Uso:
    python -m eval.voice_compare
    python -m eval.voice_compare --audios eval/voz/audios --models gemini-3.5-flash-lite,gemini-4-hydrogen
    python -m eval.voice_compare --ids L01,S01,M01 --pausa 5

Roda cada áudio `<ID>.wav` nos modelos selecionados e mede:
- WER (taxa de erro de palavras, usando a normalização de eval/text_metrics.py);
- acerto de nomes (entidades presentes na transcrição);
- acerto por campo extraído (local, commodity, ano, tipo);
- latência por pergunta.

Grava o resumo e o detalhamento linha a linha em `eval/voz/resultados/<data-hora>/`.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import time
import unicodedata

from eval.text_metrics import normalize
from src.config import PROJECT_ROOT
from src.voice import VoiceProviderError, ouvir_pergunta

DEFAULT_GABARITO = PROJECT_ROOT / "eval" / "voz" / "gabarito_voz.jsonl"
DEFAULT_AUDIOS = PROJECT_ROOT / "eval" / "voz" / "audios"
DEFAULT_OUT_ROOT = PROJECT_ROOT / "eval" / "voz" / "resultados"
DEFAULT_MODELS = ("gemini-3.5-flash-lite", "gemini-4-hydrogen")


def _fold(text: str | None) -> str:
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", text.lower().strip())
    return " ".join("".join(c for c in nfd if unicodedata.category(c) != "Mn").split())


def word_error_rate(reference: str, hypothesis: str) -> float:
    """WER = distância de edição em palavras / nº de palavras da referência (com normalize de eval/text_metrics.py)."""
    ref = normalize(reference)
    hyp = normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    m, n = len(ref), len(hyp)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        r_tok = ref[i - 1]
        for j in range(1, n + 1):
            cost = 0 if r_tok == hyp[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n] / m


def entity_hit_rate(expected_entities: list[str], reference: str, hypothesis: str) -> float | None:
    """Fração das entidades citadas na pergunta esperada que aparecem corretamente na transcrição."""
    ref_folded = _fold(reference)
    spoken_entities = [e for e in (expected_entities or []) if _fold(e) and _fold(e) in ref_folded]
    if not spoken_entities:
        return None
    hyp_folded = _fold(hypothesis)
    hits = sum(1 for e in spoken_entities if _fold(e) in hyp_folded)
    return hits / len(spoken_entities)


def field_matches(expected: dict, got: dict) -> dict[str, bool]:
    """Compara local, commodity, ano e tipo extraídos com o gabarito."""
    exp_local = _fold(expected.get("local"))
    got_local = _fold(got.get("local"))
    if not exp_local and not got_local:
        local_ok = True
    elif exp_local and got_local:
        local_ok = (exp_local == got_local) or (exp_local in got_local) or (got_local in exp_local)
    else:
        local_ok = False

    return {
        "local": local_ok,
        "commodity": expected.get("commodity") == got.get("commodity"),
        "ano": expected.get("ano") == got.get("ano"),
        "tipo": expected.get("tipo") == got.get("tipo"),
    }


def load_gabarito(path: Path = DEFAULT_GABARITO) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _call_with_retry(audio: bytes, model: str, max_retries: int = 3, base_backoff: float = 10.0):
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return ouvir_pergunta(audio, "audio/wav", model=model)
        except VoiceProviderError as exc:
            last_err = exc
            msg = str(exc).lower()
            is_rate_limit = any(k in msg for k in ("429", "quota", "rate", "resource_exhausted", "limit"))
            if not is_rate_limit or attempt >= max_retries:
                raise
            wait = base_backoff * (attempt + 1)
            print(f"    [cota] {model}: aguardando {wait:.0f}s antes de tentar novamente...", flush=True)
            time.sleep(wait)
    raise last_err  # pragma: no cover


def _mean(vals: list[float]) -> float | None:
    return (sum(vals) / len(vals)) if vals else None


def _fmt(v: float | None, pct: bool = False) -> str:
    if v is None:
        return "—"
    if pct:
        return f"{100 * v:.1f}%".replace(".", ",")
    return f"{v:.3f}".replace(".", ",")


def write_markdown_report(models: list[str], results_by_model: dict[str, list[dict]], out_path: Path) -> None:
    lines = [
        f"# Comparação de modelos multimodais de voz ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
        "",
        "## Resumo por modelo",
        "",
        "| Modelo | Áudios | Erros | WER médio | Acerto de nomes | Local | Commodity | Ano | Tipo | Tempo médio (s) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for model in models:
        rows = results_by_model.get(model, [])
        ok_rows = [r for r in rows if not r.get("erro")]
        wers = [r["wer"] for r in ok_rows]
        ents = [r["acerto_nomes"] for r in ok_rows if r["acerto_nomes"] is not None]
        times = [r["segundos"] for r in ok_rows]
        f_acc = {
            k: _mean([1.0 if r["campos_ok"][k] else 0.0 for r in ok_rows])
            for k in ("local", "commodity", "ano", "tipo")
        }
        lines.append(
            f"| `{model}` | {len(rows)} | {len(rows) - len(ok_rows)} | {_fmt(_mean(wers), pct=True)} "
            f"| {_fmt(_mean(ents), pct=True)} | {_fmt(f_acc['local'], pct=True)} | {_fmt(f_acc['commodity'], pct=True)} "
            f"| {_fmt(f_acc['ano'], pct=True)} | {_fmt(f_acc['tipo'], pct=True)} | {_fmt(_mean(times))} |"
        )

    lines += ["", "## Detalhe por pergunta", ""]
    for model in models:
        lines += [
            f"### Modelo: `{model}`",
            "",
            "| ID | WER | Nomes | Local | Commodity | Ano | Tipo | Tempo (s) | Transcrição obtida / Erro |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in results_by_model.get(model, []):
            if r.get("erro"):
                lines.append(f"| {r['id']} | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: {r['erro']} |")
                continue
            ok = r["campos_ok"]
            mark = lambda b: "✓" if b else "✗"
            lines.append(
                f"| {r['id']} | {_fmt(r['wer'], pct=True)} | {_fmt(r['acerto_nomes'], pct=True)} "
                f"| {mark(ok['local'])} | {mark(ok['commodity'])} | {mark(ok['ano'])} | {mark(ok['tipo'])} "
                f"| {r['segundos']:.2f} | {r['transcricao'].replace('|', '\\|')} |"
            )
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Compara modelos Gemini na entrada multimodal por voz.")
    ap.add_argument("--gabarito", type=Path, default=DEFAULT_GABARITO)
    ap.add_argument("--audios", type=Path, default=DEFAULT_AUDIOS)
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS), help="Modelos separados por vírgula.")
    ap.add_argument("--ids", help="IDs específicos separados por vírgula (ex.: L01,S01).")
    ap.add_argument("--pausa", type=float, default=4.5, help="Pausa em segundos entre chamadas (cota gratuita).")
    ap.add_argument("--saida", type=Path, help="Pasta de saída (padrão: eval/voz/resultados/<data-hora>).")
    args = ap.parse_args()

    gabarito = load_gabarito(args.gabarito)
    if args.ids:
        wanted = {x.strip().upper() for x in args.ids.split(",") if x.strip()}
        gabarito = [g for g in gabarito if g["id"].upper() in wanted]

    available = [(g, args.audios / f"{g['id']}.wav") for g in gabarito if (args.audios / f"{g['id']}.wav").is_file()]
    if not available:
        raise SystemExit(
            f"Nenhum arquivo <ID>.wav encontrado em {args.audios}. "
            "Ligue VOICE_RECORD_DIR=eval/voz/audios no .env, suba `python -m src.cli serve` e grave os áudios."
        )

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    out_dir = args.saida or (DEFAULT_OUT_ROOT / datetime.now().strftime("%Y-%m-%d_%H%M"))
    out_dir.mkdir(parents=True, exist_ok=True)

    results_by_model: dict[str, list[dict]] = {}
    for model in models:
        print(f"\n=== Modelo: {model} ({len(available)} áudios) ===", flush=True)
        model_rows: list[dict] = []
        for idx, (g, wav_path) in enumerate(available, start=1):
            audio = wav_path.read_bytes()
            print(f"[{idx}/{len(available)}] {g['id']} ...", end=" ", flush=True)
            try:
                res = _call_with_retry(audio, model=model)
                wer = word_error_rate(g["transcricao_esperada"], res.transcricao)
                ent = entity_hit_rate(g.get("entidades") or [], g["transcricao_esperada"], res.transcricao)
                f_ok = field_matches(g, res.to_dict())
                row = {
                    "id": g["id"],
                    "modelo": model,
                    "transcricao_esperada": g["transcricao_esperada"],
                    "transcricao": res.transcricao,
                    "extraido": res.to_dict(),
                    "wer": round(wer, 4),
                    "acerto_nomes": round(ent, 4) if ent is not None else None,
                    "campos_ok": f_ok,
                    "segundos": res.segundos,
                    "erro": None,
                }
                print(
                    f"WER={100*wer:.1f}% tipo={'ok' if f_ok['tipo'] else 'ERR'} "
                    f"comm={'ok' if f_ok['commodity'] else 'ERR'} ({res.segundos:.2f}s)",
                    flush=True,
                )
            except Exception as exc:
                row = {"id": g["id"], "modelo": model, "erro": f"{type(exc).__name__}: {exc}"}
                print(f"ERRO: {row['erro']}", flush=True)
            model_rows.append(row)
            if idx < len(available) and args.pausa > 0:
                time.sleep(args.pausa)
        results_by_model[model] = model_rows

    (out_dir / "detalhes.json").write_text(
        json.dumps(results_by_model, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report_path = out_dir / "relatorio.md"
    write_markdown_report(models, results_by_model, report_path)
    print(f"\nRelatório salvo em: {report_path}")


if __name__ == "__main__":
    main()
