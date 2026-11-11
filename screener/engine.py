"""Motor de análise: detecta o fim de correções e pontua a CONFLUÊNCIA de sinais.

Pontuação (0-100):
  Estrutura de preço 30 · Contexto/Fibonacci 15 · Volume 20 ·
  Força relativa 15 · Indicadores 15 · Risco/retorno 5

Nenhum sinal isolado confirma reversão; a nota mede quantos sinais independentes
apontam para o mesmo lado, com risco definido (stop) e relação risco/retorno.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
import pandas as pd

from . import options as opt

DEFAULTS: dict[str, Any] = {
    "min_liquidez": 5_000_000,
    "min_barras": 260,
    "janela_pico": 150,
    "dd_min": 0.08,
    "dd_max": 0.45,
    "min_barras_desde_pico": 8,
    "perna_lookback": 120,
    "stop_atr": 0.3,
    "taxa_livre_risco": 0.14,
    "dte_min": 40,
    "dte_max": 75,
    "limite_score_lista": 30,
    "dias_alerta_balanco": 7,
    "barras_grafico": 160,
}

GRUPOS = {
    "estrutura": ("Estrutura de preço", 30),
    "contexto": ("Contexto e Fibonacci", 15),
    "volume": ("Volume", 20),
    "forca_relativa": ("Força relativa", 15),
    "indicadores": ("Indicadores", 15),
    "risco": ("Risco/retorno", 5),
}


# --------------------------------------------------------------------------- indicadores
def sma(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n).mean()


def ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(ad != 0, 100.0).where(au.notna())


def macd(close: pd.Series, f: int = 12, s: int = 26, sig: int = 9):
    m = ema(close, f) - ema(close, s)
    sg = ema(m, sig)
    return m, sg, m - sg


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def pivot_highs(h: np.ndarray, k: int) -> list[int]:
    out = []
    for i in range(k, len(h) - k):
        w = h[i - k : i + k + 1]
        if h[i] == w.max() and int(np.argmax(w)) == k:
            out.append(i)
    return out


def pivot_lows(l: np.ndarray, k: int) -> list[int]:
    out = []
    for i in range(k, len(l) - k):
        w = l[i - k : i + k + 1]
        if l[i] == w.min() and int(np.argmin(w)) == k:
            out.append(i)
    return out


def _brl(x: float) -> str:
    return "R$ " + f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _last_lower_high(h: np.ndarray, l: np.ndarray, ip: int, il: int) -> int:
    """Último topo descendente: o pivô de alta mais recente antes do fundo da correção
    que seja relevante, isto é, que tenha devolvido pelo menos 30% da queda (pico→fundo).
    Repiques menores que isso são ruído e não definem a estrutura."""
    piso = l[il] + 0.30 * (h[ip] - l[il])
    cands = [i for i in pivot_highs(h, 3) if ip < i < il and h[i] >= piso]
    if cands:
        return cands[-1]
    lo = max(ip + 1, il - 20)
    if lo < il:
        return lo + int(np.argmax(h[lo:il]))
    return ip


def _num(x: Any, nd: int = 2) -> Optional[float]:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, nd)


# --------------------------------------------------------------------------- análise
def analyze(
    df: pd.DataFrame,
    ticker: str,
    setor: str,
    bench: Optional[pd.Series],
    sector_ret20: Optional[float],
    cfg: Optional[dict[str, Any]] = None,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Retorna (resultado, None) ou (None, motivo_da_exclusão)."""
    cfg = {**DEFAULTS, **(cfg or {})}
    n = len(df)
    if n < cfg["min_barras"]:
        return None, "histórico curto"

    o, h, l, c, v = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close", "volume"))
    idx = df.index
    liq = float(np.median(c[-20:] * v[-20:]))
    if liq < cfg["min_liquidez"]:
        return None, "baixa liquidez"

    s = pd.Series(c, index=idx)
    m21, m50, m200 = (sma(s, k).to_numpy() for k in (21, 50, 200))

    # ---------------------------------------------------------- 1) a correção
    w0 = n - int(cfg["janela_pico"])
    ip = w0 + int(np.argmax(h[w0:]))
    if n - 1 - ip < cfg["min_barras_desde_pico"]:
        return None, "sem correção (perto da máxima)"
    il = ip + int(np.argmin(l[ip:]))
    dd = 1 - l[il] / h[ip]
    if dd < cfg["dd_min"]:
        return None, "correção rasa"
    if dd > cfg["dd_max"]:
        return None, "queda profunda"
    bars_since_low = n - 1 - il
    peak, low = float(h[ip]), float(l[il])

    # perna de alta anterior (para Fibonacci)
    a0 = max(0, ip - int(cfg["perna_lookback"]))
    is_ = a0 + int(np.argmin(l[a0:ip])) if ip - a0 >= 10 else None
    leg_low = float(l[is_]) if is_ is not None else None
    leg = (peak - leg_low) if leg_low is not None else None
    if leg is not None and leg < 0.05 * peak:
        leg = None
    retr = (peak - low) / leg if leg else None

    # ---------------------------------------------------------- 2) estrutura
    lh_idx = _last_lower_high(h, l, ip, il)
    lh_level = float(h[lh_idx])
    bos_idx = None
    if il + 1 < n:
        acima = np.where(c[il + 1 :] > lh_level)[0]
        if len(acima):
            bos_idx = il + 1 + int(acima[0])
    bos = bos_idx is not None
    bos_active = bos and c[-1] >= lh_level * 0.985

    hl_idx = None
    for i in reversed([i for i in pivot_lows(l, 3) if i > il and i - il >= 3]):
        if l[i] > l[il] * 1.005 and h[il : i + 1].max() >= l[il] * 1.03:
            hl_idx = i
            break
    hl_level = float(l[hl_idx]) if hl_idx is not None else None

    # rejeição no fundo (martelo / engolfo) e varredura de fundo anterior (spring)
    rej, rej_txt = False, ""
    for j in range(max(il - 1, 1), min(il + 3, n)):
        rng = h[j] - l[j]
        if rng <= 0:
            continue
        lw = min(o[j], c[j]) - l[j]
        hammer = lw >= 0.55 * rng and c[j] >= l[j] + 0.5 * rng
        engulf = c[j] > o[j] and c[j - 1] < o[j - 1] and o[j] <= c[j - 1] and c[j] >= o[j - 1]
        if hammer or engulf:
            rej, rej_txt = True, ("martelo" if hammer else "engolfo de alta")
            break
    spring, spring_ref = False, None
    for i in pivot_lows(l, 5):
        if i < il - 2 and i >= max(0, n - 300) and l[il] < l[i] <= l[il] * 1.06:
            if (c[il : min(il + 4, n)] > l[i]).any():
                spring, spring_ref = True, float(l[i])
                break

    # zona de suporte
    zonas: list[tuple[str, float]] = []
    if not np.isnan(m200[il]):
        zonas.append(("MM200", float(m200[il])))
    for i in pivot_lows(l, 5):
        if i < ip and i >= max(0, n - 480):
            zonas.append(("fundo anterior", float(l[i])))
    sup = None
    for nome, z in sorted(zonas, key=lambda t: abs(low / t[1] - 1)):
        if abs(low / z - 1) <= 0.03:
            sup = (nome, z)
            break

    # ---------------------------------------------------------- 3) volume
    vs = pd.Series(v)
    vsma20 = vs.rolling(20).mean().to_numpy()
    dec = v[ip + 1 : il + 1]
    sec_ok, sec_txt = False, "queda curta demais para medir"
    if len(dec) >= 6:
        half = len(dec) // 2
        primeira, segunda = dec[:half].mean(), dec[half:].mean()
        leg_v = v[is_ : ip + 1].mean() if (is_ is not None and ip - is_ >= 5) else float("nan")
        c1 = segunda < primeira * 0.9
        c2 = (not math.isnan(leg_v)) and dec.mean() < leg_v * 0.9
        sec_ok = bool(c1 or c2)
        sec_txt = (
            f"volume da 2ª metade da queda {segunda / primeira * 100:.0f}% da 1ª"
            if primeira > 0
            else "sem dados de volume"
        )
    clim, clim_txt = False, "sem candle de exaustão perto do fundo"
    for j in range(max(il - 4, 21), min(il + 4, n)):
        if math.isnan(vsma20[j - 1]) or vsma20[j - 1] <= 0:
            continue
        rng = h[j] - l[j]
        lw = min(o[j], c[j]) - l[j]
        if v[j] >= 2 * vsma20[j - 1] and rng > 0 and (lw >= 0.4 * rng or c[j] > o[j]):
            clim, clim_txt = True, f"volume {v[j] / vsma20[j - 1]:.1f}x a média com rejeição"
            break
    w = 10
    chg = np.diff(c[-w - 1 :])
    vv = v[-w:]
    up_v, dn_v = float(vv[chg > 0].sum()), float(vv[chg < 0].sum())
    comp_ratio = (up_v / dn_v) if dn_v > 0 else (math.inf if up_v > 0 else 0.0)

    tp = (h + l + c) / 3
    avwap = np.full(n, np.nan)
    cvol = np.cumsum(v[il:])
    avwap[il:] = np.cumsum(tp[il:] * v[il:]) / np.where(cvol == 0, np.nan, cvol)
    avwap_now = float(avwap[-1])
    av_pts, av_txt = 0, "fundo muito recente para ancorar o VWAP"
    if bars_since_low >= 2 and not math.isnan(avwap_now):
        if c[-1] > avwap_now:
            av_pts = 3
            av_txt = f"preço {(c[-1] / avwap_now - 1) * 100:.1f}% acima do VWAP ({_brl(avwap_now)})"
            if l[-10:].min() <= avwap_now * 1.015:
                av_pts = 5
                av_txt += "; testou e defendeu o VWAP"
        else:
            av_txt = f"preço abaixo do VWAP ancorado ({_brl(avwap_now)})"

    seg0 = max(0, n - 120)
    lo_p, hi_p = float(l[seg0:].min()), float(h[seg0:].max())
    poc = None
    if hi_p > lo_p:
        bins = np.linspace(lo_p, hi_p, 41)
        hist, _ = np.histogram(tp[seg0:], bins=bins, weights=v[seg0:])
        b = int(hist.argmax())
        poc = float((bins[b] + bins[b + 1]) / 2)

    # ---------------------------------------------------------- 4) força relativa
    rs_ok, vs_idx_ok, vs_set_ok = False, False, False
    rs_txt = vs_idx_txt = "sem índice de referência"
    r20s = float(c[-1] / c[-21] - 1)
    if bench is not None:
        b = bench.reindex(idx).ffill().bfill().to_numpy(dtype=float)
        if not np.isnan(b).all():
            rs = pd.Series(c / b, index=idx)
            rs_ma = rs.rolling(20).mean()
            rs_ok = bool(rs.iloc[-1] > rs_ma.iloc[-1])
            rs_txt = "linha RS (ativo/Ibovespa) " + ("acima" if rs_ok else "abaixo") + " da média de 20 dias"
            r20b = float(b[-1] / b[-21] - 1)
            vs_idx_ok = r20s > r20b
            vs_idx_txt = f"ativo {r20s * 100:+.1f}% vs Ibovespa {r20b * 100:+.1f}% em 20 pregões"
    if sector_ret20 is not None:
        vs_set_ok = r20s > sector_ret20
        vs_set_txt = f"ativo {r20s * 100:+.1f}% vs média do setor {sector_ret20 * 100:+.1f}% (20 pregões)"
    else:
        vs_set_ok = c[-1] > c[-6]
        vs_set_txt = "setor sem pares suficientes; usado o momentum de 5 pregões"

    # ---------------------------------------------------------- 5) indicadores
    rsi_s = rsi(s)
    rsi_a = rsi_s.to_numpy()
    macd_l, macd_sig, macd_h = (x.to_numpy() for x in macd(s))
    pls = [i for i in pivot_lows(l, 3) if i >= max(n - 100, ip) and n - 1 - i <= 40][-3:]
    div, div_txt = False, "sem divergência entre os últimos fundos"
    for a_i in range(len(pls)):
        for b_i in range(a_i + 1, len(pls)):
            p1, p2 = pls[a_i], pls[b_i]
            if (
                p2 - p1 >= 5
                and l[p2] <= l[p1] * 1.01
                and not np.isnan(rsi_a[p1])
                and rsi_a[p2] >= rsi_a[p1] + 2
            ):
                div = True
                div_txt = f"preço fez fundo igual/menor e o IFR subiu de {rsi_a[p1]:.0f} para {rsi_a[p2]:.0f}"
    rsi_now = float(rsi_a[-1]) if not np.isnan(rsi_a[-1]) else float("nan")
    rsi_min30 = float(np.nanmin(rsi_a[-30:]))
    rsi_pts = 0
    if rsi_now > 50 and rsi_min30 < 40:
        rsi_pts = 3
    elif rsi_now > 45 and rsi_now > rsi_a[-4]:
        rsi_pts = 1
    cross_i = None
    for j in range(n - 1, n - 6, -1):
        if macd_l[j] > macd_sig[j] and macd_l[j - 1] <= macd_sig[j - 1]:
            cross_i = j
            break
    if cross_i is not None:
        macd_pts = 3 if macd_l[cross_i] <= 0 else 2
        macd_txt = f"cruzou o sinal há {n - 1 - cross_i} pregão(ões)" + (
            " (abaixo da linha zero)" if macd_l[cross_i] <= 0 else ""
        )
    elif macd_h[-1] > 0 and macd_h[-1] > macd_h[-2]:
        macd_pts, macd_txt = 1, "histograma positivo e crescente"
    else:
        macd_pts, macd_txt = 0, "sem cruzamento de alta recente"
    ma_pts, ma_parts = 0, []
    if not np.isnan(m21[-1]) and c[-1] > m21[-1] and m21[-1] > m21[-4]:
        ma_pts += 2
        ma_parts.append("acima da MM21 inclinada p/ cima")
    if not np.isnan(m50[-1]) and c[-1] > m50[-1]:
        ma_pts += 1
        ma_parts.append("acima da MM50")

    # ---------------------------------------------------------- 6) risco / retorno
    atr_s = atr(df).to_numpy()
    a = float(atr_s[-1]) if not np.isnan(atr_s[-1]) else float(np.nanmean(h[-14:] - l[-14:]))
    base = hl_level if hl_level is not None else low
    stop = base - float(cfg["stop_atr"]) * a
    entry = float(c[-1])
    risk = entry - stop
    leg_ref = leg if leg else (peak - low)
    target = peak if peak > entry * 1.02 else peak + 0.272 * leg_ref
    rr = (target - entry) / risk if risk > 0 else None
    rr_rt = None
    entry_rt = None
    if bos:
        entry_rt = lh_level * 1.01
        risk_rt = entry_rt - stop
        if risk_rt > 0:
            rr_rt = (target - entry_rt) / risk_rt
    risco_pct = risk / entry if risk > 0 else None
    alvo_2r = entry + 2 * risk if risk > 0 else None
    alvo_ext = peak + 0.272 * leg_ref  # extensão de 127,2% da perna de alta
    rr_ext = (alvo_ext - entry) / risk if risk > 0 else None

    # ---------------------------------------------------------- montagem do checklist
    itens: list[dict[str, Any]] = []

    def add(grupo: str, id_: str, nome: str, pts: float, mx: float, detalhe: str) -> None:
        itens.append(
            {
                "grupo": grupo,
                "id": id_,
                "nome": nome,
                "pts": round(float(pts), 1),
                "max": mx,
                "ok": bool(pts >= mx * 0.5),
                "detalhe": detalhe,
            }
        )

    add(
        "estrutura", "bos", "Rompeu o último topo descendente", 10 if bos_active else 0, 10,
        (f"fechou acima de {_brl(lh_level)}" if bos_active else
         (f"rompeu {_brl(lh_level)} mas voltou a perder o nível" if bos else f"ainda abaixo de {_brl(lh_level)}")),
    )
    add(
        "estrutura", "hl", "Fundo ascendente (higher low)", 10 if hl_idx is not None else 0, 10,
        (f"fundo mais alto em {_brl(hl_level)} (acima da mínima de {_brl(low)})" if hl_idx is not None
         else "ainda não há fundo ascendente confirmado (precisa de 3 pregões de confirmação)"),
    )
    rs_pts_ = (3 if rej else 0) + (2 if spring else 0)
    rs_t = []
    if rej:
        rs_t.append(f"candle de rejeição ({rej_txt})")
    if spring:
        rs_t.append(f"varreu o fundo anterior de {_brl(spring_ref)} e recuperou")
    add("estrutura", "rej", "Rejeição / varredura do fundo", rs_pts_, 5, "; ".join(rs_t) or "sem martelo, engolfo ou falso rompimento no fundo")
    add(
        "estrutura", "sup", "Fundo em zona de suporte", 5 if sup else 0, 5,
        (f"fundo a {abs(low / sup[1] - 1) * 100:.1f}% de {sup[0]} ({_brl(sup[1])})" if sup
         else "fundo longe de MM200 ou de fundos anteriores"),
    )

    t_pts, t_parts = 0, []
    if not np.isnan(m200[-1]) and not np.isnan(m200[-41]) and m200[-1] > m200[-41]:
        t_pts += 3
        t_parts.append("MM200 subindo")
    if not np.isnan(m200[il]) and l[il] >= m200[il] * 0.95:
        t_pts += 3
        t_parts.append("fundo acima/perto da MM200")
    if not np.isnan(m200[-1]) and c[-1] >= m200[-1] * 0.97:
        t_pts += 2
        t_parts.append("preço de volta à MM200")
    add("contexto", "tend", "Tendência maior preservada (MM200)", t_pts, 8, "; ".join(t_parts) or "abaixo da MM200 e sem inclinação de alta")

    if retr is None:
        f_pts, f_txt = 0, "perna de alta anterior curta/indefinida"
    elif 0.382 <= retr <= 0.618:
        f_pts, f_txt = 7, f"retração de {retr * 100:.0f}% da alta anterior (zona ideal 38-62%)"
    elif 0.236 <= retr < 0.382:
        f_pts, f_txt = 4, f"retração rasa de {retr * 100:.0f}% (tendência forte)"
    elif 0.618 < retr <= 0.786:
        f_pts, f_txt = 4, f"retração profunda de {retr * 100:.0f}% (tese mais frágil)"
    else:
        f_pts, f_txt = 0, f"retração de {retr * 100:.0f}% fora da zona saudável"
    add("contexto", "fib", "Retração de Fibonacci saudável", f_pts, 7, f_txt)

    add("volume", "sec", "Volume secando na queda", 4 if sec_ok else 0, 4, sec_txt)
    add("volume", "clim", "Clímax vendedor no fundo", 4 if clim else 0, 4, clim_txt)
    comp_pts = 4 if comp_ratio >= 1.15 else (2 if comp_ratio >= 1.0 else 0)
    add(
        "volume", "comp", "Volume comprador dominante (10 pregões)", comp_pts, 4,
        "volume nas altas = " + ("∞" if math.isinf(comp_ratio) else f"{comp_ratio:.2f}x") + " o das baixas",
    )
    add("volume", "avwap", "Acima do VWAP ancorado no fundo", av_pts, 5, av_txt)
    poc_ok = poc is not None and c[-1] > poc
    add(
        "volume", "poc", "Acima do POC (perfil de volume)", 3 if poc_ok else 0, 3,
        (f"POC em {_brl(poc)}; preço {'acima' if poc_ok else 'abaixo'}" if poc is not None else "sem dados"),
    )

    add("forca_relativa", "rs", "Linha RS acima da média de 20 dias", 5 if rs_ok else 0, 5, rs_txt)
    add("forca_relativa", "idx", "Supera o Ibovespa (20 pregões)", 5 if vs_idx_ok else 0, 5, vs_idx_txt)
    add("forca_relativa", "set", "Supera o setor (20 pregões)", 5 if vs_set_ok else 0, 5, vs_set_txt)

    add("indicadores", "div", "Divergência de alta no IFR", 6 if div else 0, 6, div_txt)
    add(
        "indicadores", "rsi", "IFR recuperou a linha de 50", rsi_pts, 3,
        f"IFR {rsi_now:.0f} (mínima de 30 pregões: {rsi_min30:.0f})",
    )
    add("indicadores", "macd", "MACD cruzou para cima", macd_pts, 3, macd_txt)
    add("indicadores", "ma", "Preço acima das MM21 / MM50", ma_pts, 3, "; ".join(ma_parts) or "abaixo das médias curtas")

    if rr is None:
        rr_pts, rr_txt = 0, "stop acima do preço atual: estrutura ainda não definiu risco"
    else:
        rr_pts = 5 if rr >= 2 else (3 if rr >= 1.5 else (1 if rr >= 1 else 0))
        rr_txt = f"R:R {rr:.1f} até {_brl(target)}"
        if rr_rt is not None:
            rr_txt += f" (no reteste de {_brl(entry_rt)}: {rr_rt:.1f})"
    add("risco", "rr", "Risco/retorno ≥ 1:2", rr_pts, 5, rr_txt)

    grupos = {}
    for g, (nome, mx) in GRUPOS.items():
        pts = sum(i["pts"] for i in itens if i["grupo"] == g)
        grupos[g] = {"nome": nome, "pts": round(pts, 1), "max": mx}
    score = round(sum(g["pts"] for g in grupos.values()))

    # ---------------------------------------------------------- status e leitura
    if bos_active and hl_idx is not None and score >= 65:
        status = "confirmada"
    elif score >= 45 and (hl_idx is not None or bos_active):
        status = "formacao"
    elif score >= 30:
        status = "observar"
    else:
        status = "fraca"

    dist_lh = c[-1] / lh_level - 1
    if status == "confirmada":
        if dist_lh <= 0.04:
            leitura = (f"Estrutura virou: rompeu {_brl(lh_level)} e formou fundo ascendente em {_brl(hl_level)}. "
                       "Preço perto do reteste, melhor zona de risco/retorno.")
        else:
            leitura = (f"Estrutura virou, mas o preço já está {dist_lh * 100:.0f}% acima do nível rompido ({_brl(lh_level)}). "
                       "Esperar o reteste melhora o R:R.")
    elif hl_idx is not None and not bos_active:
        leitura = f"Fundo ascendente em {_brl(hl_level)}. Gatilho: fechamento acima de {_brl(lh_level)}."
    elif bos_active and hl_idx is None:
        leitura = f"Rompeu {_brl(lh_level)}; falta confirmar o fundo ascendente. Stop abaixo de {_brl(low)}."
    else:
        leitura = (f"Correção de {dd * 100:.0f}% em andamento, sem sinais estruturais ainda. "
                   f"Gatilho: fechamento acima de {_brl(lh_level)}.")

    avisos: list[str] = []
    if risco_pct is not None and risco_pct > 0.10:
        avisos.append(f"Stop distante ({risco_pct * 100:.0f}% do preço): espere um reteste")
    if bos_active and dist_lh > 0.08:
        avisos.append("Preço esticado em relação ao nível rompido: aguarde reteste")
    if not np.isnan(m200[-1]) and not np.isnan(m200[-41]) and m200[-1] < m200[-41] and c[-1] < m200[-1]:
        avisos.append("Tendência maior de baixa (abaixo da MM200 em queda)")
    if bars_since_low <= 2 and c[-1] <= low * 1.02:
        avisos.append("Mínima muito recente: sem confirmação de fundo")

    # ação sugerida (separada do status da estrutura: uma reversão pode estar confirmada
    # e mesmo assim não oferecer boa entrada agora)
    if status == "confirmada":
        if dist_lh <= 0.04:
            boa = (rr or 0) >= 1.5 or (rr_ext or 0) >= 2
            acao = "zona_entrada" if boa else "rr_baixo"
        else:
            acao = "aguardar_reteste"
    elif status in ("formacao", "observar"):
        acao = "aguardar_gatilho"
    else:
        acao = "observar"

    # ---------------------------------------------------------- opções
    suporte_ref = hl_level if hl_level is not None else low
    opcoes = opt.sugerir(entry, s, suporte_ref, target, idx[-1].date(), cfg)

    # ---------------------------------------------------------- série p/ gráfico
    m = int(cfg["barras_grafico"])
    off = n - m

    def arr(x: np.ndarray, nd: int = 2) -> list[Optional[float]]:
        return [_num(t, nd) for t in x[-m:]]

    def rel(i: Optional[int]) -> Optional[int]:
        return None if i is None or i - off < 0 else int(i - off)

    serie = {
        "d": [d.strftime("%Y-%m-%d") for d in idx[-m:]],
        "o": arr(o), "h": arr(h), "l": arr(l), "c": arr(c),
        "v": [int(x) for x in v[-m:]],
        "m21": arr(m21), "m50": arr(m50), "m200": arr(m200), "avwap": arr(avwap),
        "marcas": {"pico": rel(ip), "fundo": rel(il), "lh": rel(lh_idx), "hl": rel(hl_idx), "bos": rel(bos_idx)},
    }

    resultado = {
        "ticker": ticker,
        "setor": setor,
        "data": idx[-1].strftime("%Y-%m-%d"),
        "preco": _num(c[-1]),
        "var_dia": _num(c[-1] / c[-2] - 1, 4),
        "liq_mm": _num(liq / 1e6, 1),
        "score": score,
        "status": status,
        "leitura": leitura,
        "acao": acao,
        "grupos": grupos,
        "checklist": itens,
        "niveis": {
            "pico": _num(peak), "fundo": _num(low), "lh": _num(lh_level), "hl": _num(hl_level),
            "stop": _num(stop), "entrada": _num(entry), "entrada_reteste": _num(entry_rt),
            "alvo": _num(target), "alvo_2r": _num(alvo_2r), "alvo_ext": _num(alvo_ext), "rr_ext": _num(rr_ext, 1),
            "rr": _num(rr, 1), "rr_reteste": _num(rr_rt, 1), "risco_pct": _num(risco_pct, 4),
            "queda_pct": _num(dd, 4), "retr": _num(retr, 3), "poc": _num(poc), "avwap": _num(avwap_now),
            "data_pico": idx[ip].strftime("%Y-%m-%d"), "data_fundo": idx[il].strftime("%Y-%m-%d"),
            "pregoes_desde_fundo": int(bars_since_low),
        },
        "opcoes": opcoes,
        "avisos": avisos,
        "balanco": None,
        "serie": serie,
    }
    return resultado, None
