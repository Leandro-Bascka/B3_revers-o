# Reversões B3

Screener que procura ações da B3 que **corrigiram e começam a virar**, para você avaliar pontos de entrada em ação, compra de call ou venda de PUT.

- Um robô no GitHub baixa os preços todo dia útil depois do fechamento, pontua cada ativo e publica `data.json`.
- O app (PWA em `docs/`) lê esse arquivo e funciona no PC e no celular. Dá para instalar na tela inicial.
- Cada ativo recebe uma nota de 0 a 100 por **confluência** de sinais, um checklist, níveis de stop e alvo, e uma sugestão de estrutura com opções.

> Material educativo, não é recomendação de investimento. Nenhum sinal garante resultado. Veja "Limites" abaixo.

## Publicar no GitHub (uma vez, uns 5 minutos)

1. Crie um repositório (pode ser privado, mas o Pages gratuito exige repositório público, a menos que você tenha plano pago) e envie todos os arquivos desta pasta para a branch `main`.
2. Em **Settings, Pages**, escolha **Source: GitHub Actions**.
3. Em **Actions, Atualizar screener**, clique em **Run workflow**. Leva alguns minutos.
4. Quando terminar, o endereço aparece em Settings, Pages (algo como `https://seu-usuario.github.io/nome-do-repo/`).
5. No celular, abra o endereço: no Android, use **Instalar app**; no iPhone (Safari), **Compartilhar, Adicionar à Tela de Início**.

Depois disso o robô roda sozinho às 18:30 (Brasília), de segunda a sexta. O GitHub pode atrasar agendamentos em alguns minutos e **desativa agendamentos de repositórios sem nenhuma atividade por 60 dias** (basta reativar na aba Actions).

O repositório já traz um `docs/data.json` de **demonstração com dados fictícios** (tickers `DEMOxx`), só para o app abrir de imediato. Ele é substituído na primeira execução.

## Como a nota é calculada

| Bloco | Pts | O que olha |
|---|---|---|
| Estrutura de preço | 30 | rompeu o último topo descendente (10), fundo ascendente (10), rejeição ou varredura do fundo (5), fundo em zona de suporte (5) |
| Contexto e Fibonacci | 15 | MM200 preservada (8), retração de 38 a 62% da alta anterior (7) |
| Volume | 20 | volume secando na queda (4), clímax vendedor (4), volume comprador dominante (4), acima do VWAP ancorado no fundo (5), acima do POC (3) |
| Força relativa | 15 | linha RS vs Ibovespa (5), supera o Ibovespa em 20 pregões (5), supera o setor (5) |
| Indicadores | 15 | divergência de alta no IFR (6), IFR voltando acima de 50 (3), cruzamento do MACD (3), acima das MM21/MM50 (3) |
| Risco/retorno | 5 | R:R de pelo menos 1:2 até o topo anterior |

**Status da estrutura:** *confirmada* (rompeu o topo, tem fundo ascendente e nota de 65 ou mais), *em formação*, *observar*.

**Ação sugerida** (separada do status, porque uma reversão pode estar confirmada e mesmo assim não oferecer boa entrada agora):

- *Zona de entrada*: perto do nível rompido, com R:R aceitável.
- *Aguardar reteste*: já esticou mais de 4% acima do nível rompido, ou o R:R está baixo.
- *Aguardar gatilho*: ainda falta romper o topo ou confirmar o fundo ascendente.

**Filtros automáticos:** liquidez mediana abaixo de R$ 5 milhões/dia, correção rasa (menos de 8%), queda profunda (mais de 45%) e ativos perto da máxima ficam de fora. Tudo é ajustável em `config.json`.

O stop fica abaixo do fundo ascendente (ou da mínima, se ele ainda não existe), com folga de 0,3 ATR.

## Opções

O Yahoo não fornece a cadeia de opções da B3. Por isso o app:

- usa a **volatilidade histórica de 20 dias** (e seu percentil no último ano) como aproximação da volatilidade implícita; percentil alto indica venda de PUT ou trava, baixo indica compra de call;
- estima o **delta** por Black-Scholes e sugere strikes de referência: PUT abaixo do suporte com delta de até 0,30; CALL com delta perto de 0,60; trava com a venda perto do alvo;
- usa o vencimento mensal (3ª sexta-feira) com pelo menos 40 dias.

São pontos de partida. **Confira a VI real, a grade de strikes, o spread e o volume da série** na sua corretora antes de operar.

## Rodar no seu computador

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m screener.run              # dados reais; grava docs/data.json
python -m screener.run --demo       # dados fictícios, sem internet
python -m pytest -q tests           # testes do motor
cd docs && python -m http.server    # abre em http://localhost:8000
```

## Personalizar

- `screener/tickers.txt`: lista de ativos e setores (`TICKER;Setor`). Códigos que o Yahoo não conhecer aparecem em `sem_dados` no `data.json`; fusões e mudanças de código acontecem, então revise a lista de tempos em tempos.
- `config.json`: liquidez mínima, faixa de correção, distância do stop, taxa livre de risco usada no delta (ajuste para a Selic atual), vencimento.
- `screener/eventos.json`: datas de balanço que você quiser forçar, por exemplo `{"PETR4": "2026-11-12"}`. Têm prioridade sobre o Yahoo. Ativos com balanço em até 7 dias ficam ocultos por padrão no app.

## Limites (leia)

- **Os dados vêm do Yahoo Finance** (gratuito e não oficial): podem ter atraso, buracos ou ajustes de proventos diferentes dos da sua plataforma. Se menos de 60% dos ativos vierem, o robô aborta e não publica nada, mantendo a última versão.
- **A data de balanço do Yahoo costuma ser incompleta para a B3.** Confira o calendário de resultados antes de entrar, ou preencha `eventos.json`.
- **Não há backtest.** Os critérios foram traduzidos de práticas comuns de análise técnica, mas os pesos e limiares são escolhas, não resultado de otimização. Antes de usar dinheiro real, confira os sinais em gráficos históricos e ajuste `config.json`.
- O motor foi validado com cenários sintéticos (11 testes). A primeira execução com dados reais deve ser conferida visualmente, ativo a ativo, contra o seu gráfico.
- O pivô de fundo ascendente só é reconhecido 3 pregões depois de formado; o sinal chega com esse atraso por desenho.
