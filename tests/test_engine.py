"""Testes do motor com cenários fictícios determinísticos (rodam sem internet)."""
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from screener import demo, engine, options, run  # noqa: E402

HOJE = dt.date(2026, 11, 11)


@pytest.fixture(scope="module")
def saida():
    dfs, setores, bench, _ = demo.dados_demo(HOJE)
    resultados, motivos = run.processar(dfs, setores, bench, engine.DEFAULTS)
    return {r["ticker"]: r for r in resultados}, motivos


def test_reversao_limpa_e_confirmada(saida):
    r = saida[0]["DEMO3"]
    ck = {i["id"]: i for i in r["checklist"]}
    assert r["status"] == "confirmada"
    assert ck["bos"]["ok"] and ck["hl"]["ok"] and ck["clim"]["ok"]
    assert r["acao"] == "zona_entrada"
    assert r["niveis"]["stop"] < r["niveis"]["hl"] < r["niveis"]["entrada"]


def test_em_formacao_tem_fundo_ascendente_mas_nao_rompeu(saida):
    r = saida[0]["DEMO5"]
    ck = {i["id"]: i for i in r["checklist"]}
    assert r["status"] == "formacao"
    assert ck["hl"]["ok"] and not ck["bos"]["ok"]
    assert r["acao"] == "aguardar_gatilho"


def test_reversao_esticada_pede_reteste(saida):
    r = saida[0]["DEMO10"]
    assert r["acao"] == "aguardar_reteste"
    assert any("esticado" in a.lower() for a in r["avisos"])


def test_ainda_caindo_nao_vira_sinal(saida):
    resultados, _ = saida
    r = resultados.get("DEMO6")
    assert r is None or r["status"] in ("fraca", "observar")


def test_exclusoes_pelo_motivo_certo(saida):
    resultados, motivos = saida
    assert motivos["sem correção (perto da máxima)"] == 1  # DEMO7
    assert motivos["correção rasa"] == 1  # DEMO8
    assert motivos["baixa liquidez"] == 1  # DEMO11
    assert motivos["queda profunda"] == 1  # DEMO12
    for t in ("DEMO7", "DEMO8", "DEMO11", "DEMO12"):
        assert t not in resultados


def test_ranking_prefere_reversao_a_tendencia_de_baixa(saida):
    resultados, _ = saida
    assert resultados["DEMO3"]["score"] > resultados["DEMO9"]["score"]
    assert resultados["DEMO3"]["score"] > resultados["DEMO6"]["score"]


def test_pontuacao_soma_100_e_json_serializavel(saida):
    resultados, _ = saida
    assert sum(g[1] for g in engine.GRUPOS.values()) == 100
    for r in resultados.values():
        assert 0 <= r["score"] <= 100
        assert sum(i["max"] for i in r["checklist"]) == 100
        json.dumps(r, allow_nan=False)  # sem NaN/Infinity (quebraria o JSON no navegador)


def test_sem_indice_de_referencia_nao_quebra():
    dfs, setores, _, _ = demo.dados_demo(HOJE)
    res, _ = engine.analyze(dfs["DEMO3"], "DEMO3", "x", None, None, engine.DEFAULTS)
    assert res is not None and res["status"] in ("confirmada", "formacao")


def test_rsi_e_pivos():
    alta = pd.Series(np.arange(1.0, 60.0))
    assert engine.rsi(alta).iloc[-1] == pytest.approx(100.0)
    h = np.array([1, 2, 3, 9, 3, 2, 1, 2, 3, 4, 5.0])
    assert engine.pivot_highs(h, 3) == [3]
    assert engine.pivot_lows(-h, 3) == [3]


def test_opcoes_vencimento_e_delta():
    assert options.terceira_sexta(2026, 11) == dt.date(2026, 11, 20)
    exp, dte = options.vencimento_alvo(HOJE, 40, 75)
    assert exp.weekday() == 4 and dte >= 40
    d = options.bs_delta(30, 30, 0.2, 0.14, 0.35, call=True)
    assert 0.5 < d < 0.7
    assert options.bs_delta(30, 25, 0.2, 0.14, 0.35, call=False) > -0.15


def test_sugestao_de_put_fica_abaixo_do_suporte(saida):
    r = saida[0]["DEMO3"]
    put = r["opcoes"]["put"]
    assert put["strike"] <= r["niveis"]["hl"]
    assert abs(put["delta"]) <= 0.30
