"""Executa o screener e grava docs/data.json.

Uso:
    python -m screener.run                # universo do Fundamentus + preços do Yahoo (reserva: tickers.txt)
    python -m screener.run --fonte local  # só a lista de tickers.txt
    python -m screener.run --demo         # dados fictícios, só para testar
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from . import data, demo, engine

RAIZ = Path(__file__).resolve().parent.parent


def carregar_config(path: Optional[Path]) -> dict[str, Any]:
    cfg = dict(engine.DEFAULTS)
    p = path or RAIZ / "config.json"
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    return cfg


def processar(dfs, setores, bench, cfg):
    ret20 = {t: float(d["close"].iloc[-1] / d["close"].iloc[-21] - 1) for t, d in dfs.items() if len(d) > 21}
    por_setor: dict[str, list[tuple[str, float]]] = {}
    for t, r in ret20.items():
        por_setor.setdefault(setores.get(t, "Outros"), []).append((t, r))

    resultados, motivos = [], Counter()
    for t, d in dfs.items():
        setor = setores.get(t, "Outros")
        pares = [] if setor == "Outros" else [r for (tt, r) in por_setor.get(setor, []) if tt != t]
        sret = float(np.mean(pares)) if len(pares) >= 2 else None
        try:
            res, motivo = engine.analyze(d, t, setor, bench, sret, cfg)
        except Exception as e:  # um ativo problemático não derruba o lote
            motivos[f"erro: {type(e).__name__}"] += 1
            data.log(f"  {t}: {type(e).__name__}: {e}")
            continue
        if res is None:
            motivos[motivo or "excluído"] += 1
        else:
            resultados.append(res)
    return resultados, motivos


def anexar_balancos(resultados, datas: dict[str, str], hoje: dt.date, dias_alerta: int) -> None:
    for r in resultados:
        s = datas.get(r["ticker"])
        if not s:
            continue
        try:
            d = dt.date.fromisoformat(s)
        except ValueError:
            continue
        dias = (d - hoje).days
        if dias < 0:
            continue
        r["balanco"] = {"data": s, "dias": dias, "alerta": dias <= dias_alerta}
        if dias <= dias_alerta:
            r["avisos"].insert(0, f"Balanço em {dias} dia(s) ({d.strftime('%d/%m')}): o gap pode invalidar a análise técnica")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demo", action="store_true", help="usa dados fictícios (não acessa a internet)")
    ap.add_argument("--out", default=str(RAIZ / "docs" / "data.json"))
    ap.add_argument("--tickers", default=str(RAIZ / "screener" / "tickers.txt"))
    ap.add_argument("--config", default=None)
    ap.add_argument("--fonte", choices=["auto", "fundamentus", "local"], default="auto",
                    help="origem do universo: Fundamentus (mais líquidas), lista local, ou auto (Fundamentus com reserva local)")
    ap.add_argument("--no-earnings", action="store_true", help="não consulta datas de balanço")
    args = ap.parse_args(argv)

    cfg = carregar_config(Path(args.config) if args.config else None)
    tickers, setores = data.carregar_tickers(Path(args.tickers))

    descr: dict[str, str] = {}
    fonte, descartes = "demo", {}
    if args.demo:
        dfs, setores, bench, descr = demo.dados_demo()
        universo = list(dfs)
    else:
        try:
            import lxml, requests, yfinance  # noqa: F401
        except ImportError as e:
            data.log(f"ERRO: falta a biblioteca '{e.name}'. Rode: pip install -r requirements.txt")
            return 1
        cotacoes: dict[str, float] = {}
        universo, fonte = tickers, "lista_local"
        if args.fonte in ("auto", "fundamentus"):
            data.log(f"Buscando as {cfg['qtde_ativos']} ações mais líquidas no Fundamentus...")
            liq = data.obter_acoes_mais_liquidas(int(cfg["qtde_ativos"]), float(cfg["min_liquidez"]))
            if not liq.empty:
                universo, fonte = list(liq["AÇÃO"]), "fundamentus"
                cotacoes = {t: c for t, c in zip(liq["AÇÃO"], liq["COTACAO"]) if c == c and c > 0}
                data.log(f"  {len(universo)} ativos; menor liquidez: R$ {liq['LIQUIDEZ'].min() / 1e6:.1f} mi/dia")
            elif args.fonte == "fundamentus":
                data.log("ERRO: Fundamentus indisponível e --fonte fundamentus não permite reserva.")
                return 1
            else:
                data.log("AVISO: Fundamentus indisponível; usando a lista local (screener/tickers.txt).")
        data.log(f"Baixando {len(universo)} ativos do Yahoo Finance (sem ajuste por proventos)...")
        dfs, descartes = data.baixar_universo(
            universo, cotacoes, min_barras=int(cfg["min_barras"]), tol_cotacao=float(cfg["tol_cotacao"]))
        for t, m in sorted(descartes.items()):
            data.log(f"  descartado {t}: {m}")
        bench = data.baixar_indice()
        if bench is None:
            data.log("AVISO: sem índice de referência; força relativa vs Ibovespa ficará zerada.")
        cobertura = len(dfs) / max(len(universo), 1)
        if cobertura < 0.6:
            data.log(f"ERRO: só {len(dfs)}/{len(universo)} ativos aprovados ({cobertura:.0%}). Abortando para não publicar dados ruins.")
            return 1

    resultados, motivos = processar(dfs, setores, bench, cfg)
    hoje = max(d.index[-1] for d in dfs.values()).date()

    lista = [r for r in resultados if r["score"] >= cfg["limite_score_lista"]]
    motivos["pontuação baixa"] += len(resultados) - len(lista)
    lista.sort(key=lambda r: r["score"], reverse=True)

    if not args.demo and not args.no_earnings and lista:
        datas = data.balancos([r["ticker"] for r in lista], RAIZ / "screener" / "eventos.json")
        anexar_balancos(lista, datas, hoje, int(cfg["dias_alerta_balanco"]))

    if args.demo:
        for r in lista:
            r["leitura"] = f"[Cenário fictício: {descr.get(r['ticker'], '')}] " + r["leitura"]
            r["avisos"].append("DADOS FICTÍCIOS: apenas demonstração")

    por_status = Counter(r["status"] for r in lista)
    brt = dt.timezone(dt.timedelta(hours=-3))
    saida = {
        "versao": 1,
        "demo": bool(args.demo),
        "gerado_em": dt.datetime.now(brt).isoformat(timespec="seconds"),
        "data_pregao": hoje.isoformat(),
        "estatisticas": {
            "fonte_universo": fonte,
            "universo": len(universo),
            "com_dados": len(dfs),
            "sem_dados": sorted(set(universo) - set(dfs)),
            "descartados_qualidade": dict(sorted(descartes.items())),
            "analisados": len(resultados),
            "na_lista": len(lista),
            "por_status": dict(por_status),
            "excluidos_por_motivo": dict(motivos),
        },
        "parametros": {k: cfg[k] for k in ("min_liquidez", "dd_min", "dd_max", "janela_pico", "dias_alerta_balanco", "taxa_livre_risco")},
        "ativos": lista,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    data.log(f"OK: {len(lista)} ativos na lista ({dict(por_status)}) -> {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
