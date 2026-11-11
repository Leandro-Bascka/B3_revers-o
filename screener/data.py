"""Entrada de dados: Yahoo Finance (via yfinance), balanços e dados fictícios para teste."""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

COLS = ["open", "high", "low", "close", "volume"]


def log(*a: Any) -> None:
    print(*a, file=sys.stderr, flush=True)


def carregar_tickers(path: Path) -> tuple[list[str], dict[str, str]]:
    tickers: list[str] = []
    setores: dict[str, str] = {}
    for linha in path.read_text(encoding="utf-8").splitlines():
        linha = linha.split("#", 1)[0].strip()
        if not linha:
            continue
        t, _, setor = linha.partition(";")
        t = t.strip().upper()
        if t and t not in setores:
            tickers.append(t)
            setores[t] = setor.strip() or "Outros"
    return tickers, setores


def _limpar(d: pd.DataFrame) -> Optional[pd.DataFrame]:
    d = d.rename(columns=lambda c: str(c).lower())
    if not all(c in d.columns for c in COLS):
        return None
    d = d[COLS].apply(pd.to_numeric, errors="coerce").dropna()
    d = d[(d["volume"] > 0) & (d["close"] > 0)]
    idx = pd.to_datetime(d.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    d.index = idx.normalize()
    d = d[~d.index.duplicated(keep="last")].sort_index()
    return d if len(d) else None


def baixar(
    tickers: list[str], anos: int = 2, lote: int = 20, pausa: float = 1.5, tentativas: int = 3
) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), lote):
        grupo = tickers[i : i + lote]
        syms = [t + ".SA" for t in grupo]
        raw = None
        for tent in range(tentativas):
            try:
                raw = yf.download(
                    syms, period=f"{anos}y", interval="1d", auto_adjust=True,
                    group_by="ticker", progress=False, threads=True,
                )
                if raw is not None and not raw.empty:
                    break
            except Exception as e:  # rede instável / limite de requisições
                log(f"  tentativa {tent + 1} falhou: {type(e).__name__}: {e}")
            time.sleep(3 * (tent + 1))
        if raw is None or raw.empty:
            log(f"lote {i // lote + 1}: sem dados")
            continue
        for t, sym in zip(grupo, syms):
            try:
                d = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
                d = _limpar(d)
            except KeyError:
                d = None
            if d is not None:
                out[t] = d
        log(f"lote {i // lote + 1}/{(len(tickers) + lote - 1) // lote}: {len(out)} ativos acumulados")
        time.sleep(pausa)
    return out


def baixar_indice(anos: int = 2) -> Optional[pd.Series]:
    import yfinance as yf

    for sym in ("^BVSP", "BOVA11.SA"):
        try:
            raw = yf.download(sym, period=f"{anos}y", interval="1d", auto_adjust=True, progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw.rename(columns=lambda c: str(c).lower())
            s = raw["close"].dropna()
            idx = pd.to_datetime(s.index)
            if getattr(idx, "tz", None) is not None:
                idx = idx.tz_localize(None)
            s.index = idx.normalize()
            if len(s) > 100:
                return s.astype(float)
        except Exception as e:
            log(f"índice {sym} indisponível: {type(e).__name__}")
    return None


def balancos(tickers: list[str], manual_path: Path) -> dict[str, str]:
    """Próxima data de resultado. `eventos.json` manual tem prioridade sobre o Yahoo."""
    res: dict[str, str] = {}
    if manual_path.exists():
        try:
            res.update(json.loads(manual_path.read_text(encoding="utf-8")))
        except Exception as e:
            log(f"eventos.json inválido: {e}")
    try:
        import yfinance as yf
    except ImportError:
        return res
    hoje = dt.date.today()
    for t in tickers:
        if t in res:
            continue
        try:
            cal = yf.Ticker(t + ".SA").calendar
            datas = []
            if isinstance(cal, dict):
                datas = cal.get("Earnings Date") or []
            elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                datas = list(cal.loc["Earnings Date"].dropna())
            datas = [pd.Timestamp(x).date() for x in datas]
            futuras = sorted(d for d in datas if d >= hoje)
            if futuras:
                res[t] = futuras[0].isoformat()
        except Exception:
            pass
        time.sleep(0.3)
    return res
