"""Apoio para opções: volatilidade histórica (proxy da VI), vencimento e strikes aproximados.

ATENÇÃO: o Yahoo Finance não fornece a cadeia de opções da B3. Aqui usamos a
volatilidade HISTÓRICA (HV) como aproximação da volatilidade implícita (VI) e
o modelo Black-Scholes só para estimar deltas. Os strikes são sugestões de
referência; confira a grade, a VI real, o spread e a liquidez na sua corretora.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Optional

import numpy as np
import pandas as pd


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, call: bool = True) -> float:
    if T <= 0 or sigma <= 0:
        if call:
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    nd = norm_cdf(d1)
    return nd if call else nd - 1.0


def passo_strike(preco: float) -> float:
    """Passo aproximado da grade de strikes (a grade real varia por ativo)."""
    if preco < 10:
        return 0.25
    if preco < 50:
        return 0.50
    return 1.00


def terceira_sexta(ano: int, mes: int) -> dt.date:
    """Opções de ações da B3 vencem na 3ª sexta-feira do mês (feriados deslocam o dia)."""
    d = dt.date(ano, mes, 1)
    primeira_sexta = d + dt.timedelta(days=(4 - d.weekday()) % 7)
    return primeira_sexta + dt.timedelta(days=14)


def vencimento_alvo(hoje: dt.date, dte_min: int, dte_max: int) -> tuple[dt.date, int]:
    """Primeiro vencimento mensal com pelo menos `dte_min` dias corridos."""
    ano, mes = hoje.year, hoje.month
    for _ in range(8):
        exp = terceira_sexta(ano, mes)
        dte = (exp - hoje).days
        if dte >= dte_min:
            return exp, dte
        mes += 1
        if mes > 12:
            mes, ano = 1, ano + 1
    return exp, dte  # type: ignore[possibly-undefined]


def hv_serie(close: pd.Series, janela: int = 20) -> pd.Series:
    lr = np.log(close / close.shift(1))
    return lr.rolling(janela).std() * math.sqrt(252)


def hv_stats(close: pd.Series) -> Optional[dict[str, float]]:
    hv = hv_serie(close).dropna()
    if len(hv) < 60:
        return None
    hist = hv.tail(252)
    atual = float(hv.iloc[-1])
    rank = float((hist < atual).mean() * 100)
    return {"hv20": atual, "hv_rank": rank, "hv_min": float(hist.min()), "hv_max": float(hist.max())}


def sugerir(
    preco: float,
    close: pd.Series,
    suporte: Optional[float],
    alvo: Optional[float],
    hoje: dt.date,
    cfg: dict[str, Any],
) -> Optional[dict[str, Any]]:
    st = hv_stats(close)
    if st is None:
        return None
    r = float(cfg["taxa_livre_risco"])
    exp, dte = vencimento_alvo(hoje, int(cfg["dte_min"]), int(cfg["dte_max"]))
    T = max(dte, 1) / 365.0
    sig = max(st["hv20"], 0.05)
    step = passo_strike(preco)

    # --- PUT vendida: strike abaixo do suporte, |delta| <= 0,30
    ref = suporte if (suporte and suporte < preco) else preco * 0.92
    k = math.floor(ref / step + 1e-9) * step
    put = None
    for _ in range(120):
        d = bs_delta(preco, k, T, r, sig, call=False)
        if abs(d) <= 0.30 or k <= step:
            put = {"strike": round(k, 2), "delta": round(d, 2), "dist_pct": round(k / preco - 1, 4)}
            break
        k -= step

    # --- CALL comprada: delta mais próximo de 0,62 (ATM / levemente ITM)
    lo = math.floor(preco * 0.85 / step) * step
    hi = math.ceil(preco * 1.10 / step) * step
    melhor, melhor_d = None, 9.0
    kk = lo
    while kk <= hi + 1e-9:
        d = bs_delta(preco, kk, T, r, sig, call=True)
        if abs(d - 0.62) < abs(melhor_d - 0.62):
            melhor, melhor_d = kk, d
        kk += step
    call = {"strike": round(melhor, 2), "delta": round(melhor_d, 2)} if melhor is not None else None

    # --- Trava de alta com CALL: compra a `call`, vende perto do alvo
    trava = None
    if call is not None:
        short = math.ceil((alvo or preco * 1.1) / step) * step
        if short <= call["strike"]:
            short = call["strike"] + 4 * step
        d_short = bs_delta(preco, short, T, r, sig, call=True)
        trava = {"compra": call["strike"], "venda": round(short, 2), "delta_venda": round(d_short, 2)}

    rank = st["hv_rank"]
    if rank >= 60:
        principal = "Venda de PUT (prêmio tende a estar caro) ou trava de alta com PUT"
        alternativa = "Ação, entrada escalonada. Evite call 'seca': a queda da VI corrói o prêmio"
        regime = "alta"
    elif rank >= 40:
        principal = "Trava de alta com CALL (reduz custo e efeito da VI)"
        alternativa = "Venda de PUT em strike abaixo do suporte, ou ação"
        regime = "média"
    else:
        principal = "Compra de CALL (prêmio relativamente barato)"
        alternativa = "Trava de alta com CALL para baratear, ou ação"
        regime = "baixa"

    return {
        "hv20": round(st["hv20"], 4),
        "hv_rank": round(rank, 0),
        "regime_vol": regime,
        "vencimento": exp.isoformat(),
        "dte": dte,
        "estrategia": principal,
        "alternativa": alternativa,
        "put": put,
        "call": call,
        "trava": trava,
        "aviso": (
            "HV é só um proxy da VI. Confira a VI real, a grade de strikes, o spread e o "
            "volume da série na sua corretora antes de operar."
        ),
    }
