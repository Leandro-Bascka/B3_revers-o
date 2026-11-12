"""Entrada de dados.

- Universo: as ações mais líquidas segundo o Fundamentus (coluna Liq.2meses), com a lista local como reserva.
- Preços: Yahoo Finance (yfinance), SEM ajuste por proventos (igual ao gráfico da corretora e à grade de strikes).
- Conferência: o último preço do Yahoo é comparado com a cotação do Fundamentus; divergência grande descarta o ativo.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

COLS = ["open", "high", "low", "close", "volume"]
FUNDAMENTUS_URL = "https://www.fundamentus.com.br/resultado.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
PADRAO_TICKER = re.compile(r"^[A-Z]{4}\d{1,2}$")


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


def _norm(txt: Any) -> str:
    """'Liq. Corr.' -> 'liqcorr'; 'Cotação' -> 'cotacao' (sem acento, espaço ou ponto)."""
    t = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)


def _num_br(x: Any) -> float:
    if isinstance(x, (int, float, np.number)):
        return float(x)
    s = str(x).strip().replace("%", "").replace("R$", "").strip()
    if not s or s in ("-", "nan"):
        return float("nan")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def parse_fundamentus(html: str) -> pd.DataFrame:
    """Tabela do resultado.php -> colunas AÇÃO, LIQUIDEZ (R$/dia, média de 2 meses) e COTACAO.

    ATENÇÃO: a página tem 'Liq. Corr.' (liquidez CORRENTE, um índice) antes de 'Liq.2meses'
    (volume negociado). Procurar só por 'liq' pegaria a coluna errada.
    """
    tabelas = pd.read_html(io.StringIO(html), decimal=",", thousands=".")
    if not tabelas:
        raise ValueError("nenhuma tabela encontrada")
    df = tabelas[0]
    nomes = {_norm(c): c for c in df.columns}
    col_papel = nomes.get("papel")
    col_liq = next((nomes[k] for k in nomes if k.startswith("liq2mes")), None)
    col_cot = nomes.get("cotacao")
    if col_papel is None:
        raise ValueError("coluna Papel não encontrada")
    if col_liq is None:
        raise ValueError(f"coluna Liq.2meses não encontrada (colunas: {list(df.columns)})")
    out = pd.DataFrame({
        "AÇÃO": df[col_papel].astype(str).str.strip().str.upper(),
        "LIQUIDEZ": df[col_liq].map(_num_br),
        "COTACAO": df[col_cot].map(_num_br) if col_cot is not None else np.nan,
    })
    out = out[out["AÇÃO"].str.match(PADRAO_TICKER)]
    out = out.dropna(subset=["LIQUIDEZ"])
    return out[out["LIQUIDEZ"] > 0].reset_index(drop=True)


def obter_acoes_mais_liquidas(qtde: int, min_liq: float = 0.0, tentativas: int = 3) -> pd.DataFrame:
    """As `qtde` ações mais negociadas segundo o Fundamentus. DataFrame vazio se falhar."""
    import requests

    ultimo = None
    for t in range(tentativas):
        try:
            r = requests.get(FUNDAMENTUS_URL, headers=HEADERS, timeout=30)
            r.raise_for_status()
            df = parse_fundamentus(r.text)
            df = df[df["LIQUIDEZ"] >= min_liq].sort_values("LIQUIDEZ", ascending=False)
            df = df.drop_duplicates("AÇÃO").head(qtde).reset_index(drop=True)
            if len(df) < 20:
                raise ValueError(f"só {len(df)} ativos após o filtro; página provavelmente mudou")
            return df
        except Exception as e:
            ultimo = e
            log(f"  Fundamentus, tentativa {t + 1}/{tentativas}: {type(e).__name__}: {e}")
            time.sleep(3 * (t + 1))
    log(f"ERRO AO OBTER AÇÕES: {ultimo}")
    return pd.DataFrame()


def baixar_historico(acao: str, periodo: str = "2y", intervalo: str = "1d", tentativas: int = 2) -> Optional[pd.DataFrame]:
    """Histórico de um ativo no Yahoo (sem ajuste por proventos); None se vier vazio/incompleto."""
    import yfinance as yf

    for t in range(tentativas):
        try:
            df = yf.download(acao + ".SA", period=periodo, interval=intervalo,
                             auto_adjust=False, progress=False, threads=False, timeout=20)
            if df is None or df.empty:
                time.sleep(2 * (t + 1))
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.rename(columns=lambda c: str(c).lower())
            return _limpar(df)
        except Exception as e:
            log(f"  {acao}: {type(e).__name__}: {e}")
            time.sleep(2 * (t + 1))
    return None


def validar_historico(
    df: pd.DataFrame, ref_data: Optional[pd.Timestamp] = None, cotacao: Optional[float] = None,
    min_barras: int = 300, tol_cotacao: float = 0.06, max_defasagem: int = 5,
) -> Optional[str]:
    """Motivo de descarte (str) ou None se os dados passam nos controles de qualidade."""
    if len(df) < min_barras:
        return "histórico curto"
    if ref_data is not None and (ref_data - df.index[-1]).days > max_defasagem:
        return "desatualizado"
    rec = df.tail(260)
    if (rec.index.to_series().diff().dt.days > 10).any():
        return "buraco no histórico"
    ruim = (rec["high"] < rec[["open", "close"]].max(axis=1) * 0.995) | (rec["low"] > rec[["open", "close"]].min(axis=1) * 1.005)
    if ruim.mean() > 0.02:
        return "OHLC inconsistente"
    if (rec["close"].pct_change().abs() > 0.40).any():
        return "salto suspeito (desdobramento sem ajuste?)"
    if cotacao and cotacao > 0 and abs(df["close"].iloc[-1] / cotacao - 1) > tol_cotacao:
        return "preço diverge do Fundamentus"
    return None


def baixar_universo(
    tickers: list[str], cotacoes: Optional[dict[str, float]] = None, periodo: str = "2y",
    pausa: float = 0.4, min_barras: int = 300, tol_cotacao: float = 0.06,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Baixa ativo a ativo (uma falha não derruba o lote) e aplica os controles de qualidade.
    Retorna (histórico dos aprovados, {ticker: motivo do descarte})."""
    brutos: dict[str, pd.DataFrame] = {}
    descartes: dict[str, str] = {}
    for k, t in enumerate(tickers, 1):
        d = baixar_historico(t, periodo)
        if d is None:
            descartes[t] = "sem dados no Yahoo"
        else:
            brutos[t] = d
        if k % 25 == 0 or k == len(tickers):
            log(f"  {k}/{len(tickers)} baixados ({len(brutos)} com dados)")
        if k == 10 and not brutos:  # disjuntor: Yahoo fora do ar ou bloqueado, não adianta insistir
            log("ERRO: os 10 primeiros ativos falharam; o Yahoo Finance parece indisponível. Interrompendo.")
            break
        time.sleep(pausa)
    ref = None
    if brutos:
        ref = pd.Series([d.index[-1] for d in brutos.values()]).mode().iloc[0]  # último pregão mais comum
    ok: dict[str, pd.DataFrame] = {}
    for t, d in brutos.items():
        motivo = validar_historico(d, ref, (cotacoes or {}).get(t), min_barras, tol_cotacao)
        if motivo:
            descartes[t] = motivo
        else:
            ok[t] = d
    return ok, descartes


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
