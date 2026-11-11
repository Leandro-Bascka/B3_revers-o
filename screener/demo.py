"""Dados FICTÍCIOS para testar o motor e o app sem internet.

Cada cenário é desenhado por pivôs (barras antes de hoje, preço) com volume coerente
com a história que ele conta. Os códigos DEMOxx não existem na B3.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import numpy as np
import pandas as pd

PREFIXO = [(520, 45.0)]  # alta de base até o pico, para a MM200 ficar abaixo e subindo

# desc, setor, pivôs, pico(offset), fundo(offset), rampa de volume na queda, clímax, líquido
CENARIOS = {
    "DEMO3": ("Reversão limpa", "Setor Demo A",
              [(75, 100), (66, 90), (60, 95), (46, 82), (40, 88), (28, 76), (18, 86), (10, 83), (2, 91), (0, 89.5)],
              75, 28, (1.15, 0.6), True, True),
    "DEMO4": ("Reversão com varredura de fundo", "Setor Demo A",
              [(80, 100), (66, 88), (58, 94), (40, 86.5), (30, 93), (20, 89), (8, 97), (0, 95.5)],
              80, 40, (1.1, 0.65), True, True),
    "DEMO5": ("Em formação: fundo ascendente, sem rompimento", "Setor Demo A",
              [(70, 100), (62, 92), (56, 96), (34, 80), (24, 87), (14, 83), (0, 86)],
              70, 34, (1.1, 0.65), True, True),
    "DEMO6": ("Ainda caindo", "Setor Demo A",
              [(60, 100), (46, 90), (38, 94), (20, 82), (12, 85), (2, 76), (0, 77.5)],
              60, 2, (0.9, 1.5), False, True),
    "DEMO7": ("Perto da máxima", "Setor Demo B",
              [(30, 98), (18, 94.5), (0, 100)], None, None, None, False, True),
    "DEMO8": ("Lateral", "Setor Demo B",
              [(200, 100), (170, 97), (140, 102), (110, 98), (80, 102), (50, 98), (20, 101.5), (0, 99.5)],
              None, None, None, False, True),
    "DEMO9": ("Tendência de baixa", "Setor Demo B",
              [(260, 100), (200, 85), (180, 90), (120, 72), (100, 76), (50, 62), (35, 66), (0, 60)],
              None, None, None, False, True),
    "DEMO10": ("Reversão já esticada", "Setor Demo A",
               [(75, 100), (66, 90), (60, 95), (46, 82), (40, 88), (28, 76), (18, 86), (12, 83), (8, 91), (0, 97.5)],
               75, 28, (1.15, 0.6), True, True),
    "DEMO11": ("Reversão ilíquida (deve ser excluída)", "Setor Demo B",
               [(75, 100), (66, 90), (60, 95), (46, 82), (40, 88), (28, 76), (18, 86), (10, 83), (2, 91), (0, 89.5)],
               75, 28, (1.15, 0.6), True, False),
    "DEMO12": ("Queda profunda (deve ser excluída)", "Setor Demo B",
               [(120, 100), (0, 40)], None, None, None, False, True),
}


def _caminho(rng, pontos, total, ruido=0.003):
    pts = PREFIXO + pontos
    xs = [total - 1 - b for b, _ in pts]
    ys = np.log([p for _, p in pts])
    base = np.interp(np.arange(total), xs, ys)
    return np.exp(base) * (1 + rng.normal(0, ruido, total))


def _ohlcv(rng, closes, base_vol, pico, fundo, rampa, climax):
    n = len(closes)
    c = closes.copy()
    prev = np.concatenate([[c[0]], c[:-1]])
    o = prev * (1 + rng.normal(0, 0.002, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    mult = np.ones(n)
    il = None
    if pico is not None:
        ip, il = n - 1 - pico, n - 1 - fundo
        mult[ip + 1 : il + 1] = np.linspace(rampa[0], rampa[1], max(il - ip, 1))
        ret = np.diff(c, prepend=c[0])
        mult[il + 1 :] = np.where(ret[il + 1 :] > 0, 1.35, 0.75)
    vol = base_vol * mult * np.exp(rng.normal(0, 0.2, n))
    if climax and il is not None:  # martelo com volume de exaustão no fundo
        o[il], hi[il], lo[il] = c[il] * 0.997, c[il] * 1.004, c[il] * 0.96
        vol[il] = base_vol * 3.4
    return o, hi, lo, c, vol


def dados_demo(hoje: Optional[dt.date] = None):
    hoje = hoje or dt.date.today()
    total = 521
    idx = pd.bdate_range(end=pd.Timestamp(hoje), periods=total)
    rng = np.random.default_rng(20261111)
    dfs, setores, descr = {}, {}, {}
    for t, (desc, setor, pontos, pico, fundo, rampa, climax, liquido) in CENARIOS.items():
        closes = _caminho(rng, pontos, total)
        o, hi, lo, c, vol = _ohlcv(rng, closes, 4_000_000 if liquido else 4_000, pico, fundo, rampa, climax)
        dfs[t] = pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c, "volume": vol}, index=idx)
        setores[t], descr[t] = setor, desc
    # Ibovespa fictício: sobe e devolve ~2% nas últimas 75 barras
    bench = pd.Series(_caminho(rng, [(75, 130.0), (0, 127.0)], total, 0.006) * 1000, index=idx)
    return dfs, setores, bench, descr
