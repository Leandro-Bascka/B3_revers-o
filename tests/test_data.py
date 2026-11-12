"""Testes da camada de dados (offline): parser do Fundamentus, controles de qualidade e reserva."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from screener import data  # noqa: E402

# Imita o resultado.php: note "Liq. Corr." (índice ~1,5) ANTES de "Liq.2meses" (R$ negociados por dia).
HTML = """
<table><thead><tr>
<th>Papel</th><th>Cotação</th><th>P/L</th><th>Div.Yield</th><th>Mrg. Líq.</th><th>Liq. Corr.</th><th>ROE</th><th>Liq.2meses</th><th>Patrim. Líq</th>
</tr></thead><tbody>
<tr><td>PETR4</td><td>38,50</td><td>5,10</td><td>12,5%</td><td>20,1%</td><td>0,95</td><td>25,0%</td><td>1.234.567.890,00</td><td>400.000.000.000</td></tr>
<tr><td>VALE3</td><td>62,10</td><td>6,00</td><td>8,0%</td><td>18,0%</td><td>1,60</td><td>15,0%</td><td>987.654.321,00</td><td>300.000.000.000</td></tr>
<tr><td>ABCD3</td><td>2,10</td><td>-</td><td>0,0%</td><td>1,0%</td><td>9,90</td><td>1,0%</td><td>150.000,00</td><td>1.000.000</td></tr>
<tr><td>SEMLIQ3</td><td>5,00</td><td>3,00</td><td>1,0%</td><td>1,0%</td><td>2,00</td><td>1,0%</td><td>0,00</td><td>1.000</td></tr>
<tr><td>ITUB4</td><td>34,00</td><td>9,00</td><td>6,0%</td><td>15,0%</td><td>1,10</td><td>20,0%</td><td>1.500.000.000,00</td><td>200.000.000.000</td></tr>
</tbody></table>
"""


def test_parser_usa_liq2meses_e_nao_liq_corr():
    df = data.parse_fundamentus(HTML)
    ordenado = df.sort_values("LIQUIDEZ", ascending=False)
    # ordem correta por volume negociado: ITUB4 > PETR4 > VALE3 > ABCD3 (liquidez corrente daria ABCD3 primeiro)
    assert list(ordenado["AÇÃO"]) == ["ITUB4", "PETR4", "VALE3", "ABCD3"]
    assert ordenado.iloc[0]["LIQUIDEZ"] == pytest.approx(1.5e9)
    assert df.set_index("AÇÃO").loc["PETR4", "COTACAO"] == pytest.approx(38.5)
    assert "SEMLIQ3" not in set(df["AÇÃO"])  # liquidez zero e código fora do padrão


def test_parser_aceita_texto_ou_numero_e_falha_com_clareza():
    assert data._num_br("1.234.567,89") == pytest.approx(1234567.89)
    assert data._num_br(12.5) == 12.5
    assert np.isnan(data._num_br("-"))
    with pytest.raises(ValueError, match="Liq.2meses"):
        data.parse_fundamentus("<table><tr><th>Papel</th><th>Cotação</th></tr><tr><td>PETR4</td><td>1,0</td></tr></table>")


def test_reserva_quando_fundamentus_falha(monkeypatch):
    import requests

    def falha(*a, **k):
        raise requests.ConnectionError("sem rede")

    monkeypatch.setattr(requests, "get", falha)
    monkeypatch.setattr(data.time, "sleep", lambda s: None)
    assert data.obter_acoes_mais_liquidas(10, tentativas=2).empty


def _hist(n=320, ultimo=None, preco=30.0):
    idx = pd.bdate_range(end=pd.Timestamp("2026-11-11"), periods=n)
    c = np.full(n, preco) * (1 + 0.001 * np.sin(np.arange(n)))
    df = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e6}, index=idx)
    return df


REF = pd.Timestamp("2026-11-11")


def test_qualidade_aprova_dado_bom():
    d = _hist()
    assert data.validar_historico(d, REF, cotacao=float(d["close"].iloc[-1])) is None


def test_qualidade_detecta_problemas():
    assert data.validar_historico(_hist(200), REF) == "histórico curto"
    assert data.validar_historico(_hist().iloc[:-10], REF) == "desatualizado"
    d = _hist()
    d.iloc[-100:-88] = np.nan  # 12 pregões sem dados (~16 dias corridos)
    assert data.validar_historico(d.dropna(), REF) == "buraco no histórico"
    d = _hist()
    d.iloc[-50:, :4] = d.iloc[-50:, :4] * 0.5  # desdobramento 2:1 sem ajuste
    assert "salto suspeito" in data.validar_historico(d, REF)
    d = _hist()
    assert data.validar_historico(d, REF, cotacao=float(d["close"].iloc[-1]) * 1.15) == "preço diverge do Fundamentus"
    assert data.validar_historico(d, REF, cotacao=float(d["close"].iloc[-1]) * 1.03) is None  # tolerância
