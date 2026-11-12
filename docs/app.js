(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const nf = (x, d = 2) => (x == null ? "–" : Number(x).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const brl = (x) => (x == null ? "–" : "R$ " + nf(x));
  const pct = (x, d = 1, sign = false) => (x == null ? "–" : (sign && x > 0 ? "+" : "") + nf(x * 100, d) + "%");
  const dbr = (iso) => (iso ? iso.slice(8, 10) + "/" + iso.slice(5, 7) + "/" + iso.slice(0, 4) : "–");

  const ACOES = {
    zona_entrada: "Zona de entrada",
    aguardar_reteste: "Aguardar reteste",
    rr_baixo: "Reteste, R:R baixo",
    aguardar_gatilho: "Aguardar gatilho",
    observar: "Só observar",
  };
  const ABA = { zona_entrada: "zona", aguardar_reteste: "reteste", rr_baixo: "reteste", aguardar_gatilho: "gatilho", observar: "obs" };
  const ABAS = [["todas", "Todas"], ["zona", "Zona de entrada"], ["reteste", "Aguardar reteste"], ["gatilho", "Aguardar gatilho"]];
  const STATUS = { confirmada: "Reversão confirmada", formacao: "Em formação", observar: "Observar", fraca: "Fraca" };
  const GRUPOS = ["estrutura", "contexto", "volume", "forca_relativa", "indicadores", "risco"];
  const ESTR = { alta: "Venda de PUT", "média": "Trava de alta", baixa: "Compra de CALL" };

  // ---------- estado e preferências
  const store = {
    get(k, d) { try { const v = localStorage.getItem("b3rev." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("b3rev." + k, JSON.stringify(v)); } catch (e) { /* modo privado */ } },
  };
  const S = {
    data: null,
    aba: store.get("aba", "todas"), q: "", min: store.get("min", 40), estr: store.get("estr", ""), ord: store.get("ord", "score"),
    bal: store.get("bal", true), favOnly: false, favs: new Set(store.get("favs", [])), tema: store.get("tema", "auto"),
    capital: store.get("capital", 20000), risco: store.get("risco", 1),
    chart: null, atual: null, graf: store.get("graf", { m21: true, m50: true, m200: true, avwap: true, niveis: true, barras: 120 }),
  };

  // ---------- tema
  function aplicaTema() {
    const r = document.documentElement;
    if (S.tema === "auto") r.removeAttribute("data-theme"); else r.setAttribute("data-theme", S.tema);
    $("#btn-theme").textContent = "Tema: " + { auto: "automático", light: "claro", dark: "escuro" }[S.tema];
    if (S.chart) S.chart.draw();
  }
  $("#btn-theme").addEventListener("click", () => {
    S.tema = { auto: "light", light: "dark", dark: "auto" }[S.tema]; store.set("tema", S.tema); aplicaTema();
  });

  // ---------- dados
  async function carregar(forcar) {
    $("#sub").textContent = "Carregando dados…";
    try {
      const r = await fetch("data.json?t=" + (forcar ? Date.now() : Math.floor(Date.now() / 60000)), { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      S.data = await r.json();
      $("#banner").innerHTML = "";
      if (S.data.demo) {
        $("#banner").innerHTML = '<p class="banner">Dados fictícios de demonstração. Os códigos DEMO não existem na B3. O primeiro ciclo do robô no GitHub troca isto por cotações reais.</p>';
      }
    } catch (e) {
      S.data = null;
      $("#banner").innerHTML = '<p class="banner erro">Não foi possível carregar data.json (' + esc(e.message) + '). Rode o workflow "Atualizar screener" no GitHub ou gere o arquivo com python -m screener.run.</p>';
    }
    render();
  }
  $("#btn-refresh").addEventListener("click", () => carregar(true));

  // ---------- filtragem
  const alvoRR = (a) => (a.niveis.rr == null ? -1 : a.niveis.rr);
  function filtrados() {
    if (!S.data) return [];
    const q = S.q.trim().toLowerCase();
    let L = S.data.ativos.filter((a) => {
      if (a.score < S.min) return false;
      if (S.aba !== "todas" && ABA[a.acao] !== S.aba) return false;
      if (q && !(a.ticker.toLowerCase().includes(q) || (a.setor || "").toLowerCase().includes(q))) return false;
      if (S.estr && (!a.opcoes || a.opcoes.regime_vol !== S.estr)) return false;
      if (S.bal && a.balanco && a.balanco.alerta) return false;
      if (S.favOnly && !S.favs.has(a.ticker)) return false;
      return true;
    });
    const cmp = {
      score: (a, b) => b.score - a.score,
      rr: (a, b) => alvoRR(b) - alvoRR(a),
      stop: (a, b) => (a.niveis.risco_pct ?? 9) - (b.niveis.risco_pct ?? 9),
      dia: (a, b) => (b.var_dia ?? 0) - (a.var_dia ?? 0),
    }[S.ord];
    return L.sort(cmp);
  }

  // ---------- lista
  function strip(a) {
    return '<span class="strip" aria-hidden="true">' + GRUPOS.map((g) =>
      '<span class="grp">' + a.checklist.filter((i) => i.grupo === g).map((i) =>
        '<span class="tick ' + (i.ok ? "ok" : i.pts > 0 ? "part" : "") + '" title="' + esc(i.nome + ": " + i.pts + "/" + i.max) + '"></span>').join("") + "</span>").join("") + "</span>";
  }
  function linha(a) {
    const n = a.niveis, up = (a.var_dia ?? 0) >= 0;
    const meta = [];
    if (n.rr != null) meta.push("R:R " + nf(n.rr, 1));
    if (n.risco_pct != null) meta.push("stop " + pct(n.risco_pct, 1));
    const bal = a.balanco && a.balanco.alerta ? ' <span class="alert">Balanço em ' + a.balanco.dias + " d</span>" : "";
    const fav = S.favs.has(a.ticker);
    return '<li class="row"><button class="star" type="button" data-fav="' + esc(a.ticker) + '" aria-pressed="' + fav + '" aria-label="' + (fav ? "Remover " : "Adicionar ") + esc(a.ticker) + ' dos favoritos">' + (fav ? "★" : "☆") + "</button>" +
      '<button class="row-main" type="button" data-open="' + esc(a.ticker) + '" aria-label="Abrir detalhes de ' + esc(a.ticker) + ", pontuação " + a.score + '">' +
      '<span class="c-tk"><span class="tk">' + esc(a.ticker) + '</span><span class="sub">' + esc(a.setor) + "</span></span>" +
      '<span class="c-px"><span class="px">' + brl(a.preco) + '</span><span class="chg ' + (up ? "up" : "down") + '">' + (up ? "▲ " : "▼ ") + pct(Math.abs(a.var_dia ?? 0), 2) + "</span></span>" +
      '<span class="c-strip">' + strip(a) + "</span>" +
      '<span class="c-score score">' + a.score + "<small>de 100</small></span>" +
      '<span class="c-act"><span class="badge a-' + a.acao + '">' + ACOES[a.acao] + '</span><span class="meta">' + esc(meta.join("  ")) + bal + "</span></span>" +
      "</button></li>";
  }
  function abas() {
    const base = S.data ? S.data.ativos : [];
    const cont = (k) => base.filter((a) => k === "todas" ? true : ABA[a.acao] === k).length;
    $("#tabs").innerHTML = ABAS.map(([k, t]) => '<button class="tab" type="button" data-aba="' + k + '" aria-pressed="' + (S.aba === k) + '">' + t + " <b>" + cont(k) + "</b></button>").join("");
  }
  function render() {
    abas();
    const L = filtrados();
    if (S.data) {
      const st = S.data.estatisticas;
      $("#sub").textContent = "Ações que corrigiram e começam a virar. Pregão de " + dbr(S.data.data_pregao) + ": " + st.analisados + " ativos analisados de " + st.universo + ", " + st.na_lista + " na lista. Universo: " + ({ fundamentus: "as mais líquidas segundo o Fundamentus", lista_local: "lista local (Fundamentus indisponível)", demo: "demonstração" }[st.fonte_universo] || "–") + (Object.keys(st.descartados_qualidade || {}).length ? "; " + Object.keys(st.descartados_qualidade).length + " descartados por qualidade de dados." : ".");
    } else $("#sub").textContent = "Sem dados.";
    $("#lista").innerHTML = L.length ? L.map(linha).join("") :
      '<li class="vazio">' + (S.data ? "Nenhum ativo com esses filtros. Reduza a pontuação mínima, desmarque “Ocultar balanço próximo” ou volte para a aba Todas." : "Aguardando dados.") + "</li>";
  }

  // ---------- eventos da lista
  $("#lista").addEventListener("click", (e) => {
    const f = e.target.closest("[data-fav]");
    if (f) {
      const t = f.dataset.fav; S.favs.has(t) ? S.favs.delete(t) : S.favs.add(t);
      store.set("favs", [...S.favs]); render(); return;
    }
    const o = e.target.closest("[data-open]");
    if (o) abrir(o.dataset.open);
  });
  $("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-aba]"); if (!b) return;
    S.aba = b.dataset.aba; store.set("aba", S.aba); render();
  });
  $("#f-q").addEventListener("input", (e) => { S.q = e.target.value; render(); });
  $("#f-min").addEventListener("input", (e) => { S.min = +e.target.value; $("#f-min-v").textContent = S.min; store.set("min", S.min); render(); });
  $("#f-estr").addEventListener("change", (e) => { S.estr = e.target.value; store.set("estr", S.estr); render(); });
  $("#f-ord").addEventListener("change", (e) => { S.ord = e.target.value; store.set("ord", S.ord); render(); });
  $("#f-bal").addEventListener("change", (e) => { S.bal = e.target.checked; store.set("bal", S.bal); render(); });
  $("#f-fav").addEventListener("change", (e) => { S.favOnly = e.target.checked; render(); });

  // ---------- detalhe
  function opcoesHtml(o) {
    if (!o) return "<p>Sem histórico suficiente para estimar a volatilidade.</p>";
    const put = o.put ? brl(o.put.strike) + " <small>(delta " + nf(o.put.delta, 2) + ", " + pct(o.put.dist_pct, 1) + " do preço)</small>" : "–";
    const call = o.call ? brl(o.call.strike) + " <small>(delta " + nf(o.call.delta, 2) + ")</small>" : "–";
    const tr = o.trava ? "compra " + brl(o.trava.compra) + " / venda " + brl(o.trava.venda) : "–";
    return '<dl class="kv">' +
      "<div><dt>Estratégia principal</dt><dd>" + esc(o.estrategia) + "</dd></div>" +
      "<div><dt>Alternativa</dt><dd>" + esc(o.alternativa) + "</dd></div>" +
      "<div><dt>Volatilidade histórica (20d)</dt><dd>" + pct(o.hv20, 0) + " <small>percentil " + nf(o.hv_rank, 0) + " no último ano</small></dd></div>" +
      "<div><dt>Vencimento de referência</dt><dd>" + dbr(o.vencimento) + " <small>" + o.dte + " dias</small></dd></div>" +
      "<div><dt>PUT a vender (abaixo do suporte)</dt><dd>" + put + "</dd></div>" +
      "<div><dt>CALL a comprar (delta ~0,60)</dt><dd>" + call + "</dd></div>" +
      "<div><dt>Trava de alta com CALL</dt><dd>" + tr + "</dd></div></dl>" +
      '<p class="opt-aviso">' + esc(o.aviso) + " Strikes arredondados; a grade real varia por ativo.</p>";
  }
  function checklistHtml(a) {
    return GRUPOS.map((g) => {
      const gr = a.grupos[g], itens = a.checklist.filter((i) => i.grupo === g);
      return '<div class="g-head"><span>' + esc(gr.nome) + "</span><span>" + nf(gr.pts, gr.pts % 1 ? 1 : 0) + " de " + gr.max + '</span></div><div class="bar"><i style="width:' + (gr.pts / gr.max * 100) + '%"></i></div>' +
        itens.map((i) => {
          const k = i.ok ? "ok" : i.pts > 0 ? "part" : "";
          const ic = i.ok ? "✓" : i.pts > 0 ? "◐" : "–";
          const lbl = i.ok ? "atendido" : i.pts > 0 ? "parcial" : "não atendido";
          return '<div class="it ' + k + '"><span class="ic" aria-label="' + lbl + '">' + ic + '</span><span class="nm">' + esc(i.nome) + '</span><span class="pt">' + nf(i.pts, i.pts % 1 ? 1 : 0) + "/" + i.max + '</span><span class="dt">' + esc(i.detalhe) + "</span></div>";
        }).join("");
    }).join("");
  }
  function niveisHtml(a) {
    const n = a.niveis;
    return '<dl class="kv">' +
      "<div><dt>Entrada (preço atual)</dt><dd>" + brl(n.entrada) + "</dd></div>" +
      (n.entrada_reteste ? "<div><dt>Entrada no reteste</dt><dd>" + brl(n.entrada_reteste) + " <small>R:R " + nf(n.rr_reteste, 1) + "</small></dd></div>" : "") +
      "<div><dt>Stop (abaixo do fundo ascendente)</dt><dd>" + brl(n.stop) + " <small>" + pct(n.risco_pct, 1) + " de risco</small></dd></div>" +
      "<div><dt>Alvo 1: topo anterior</dt><dd>" + brl(n.alvo) + " <small>R:R " + nf(n.rr, 1) + "</small></dd></div>" +
      "<div><dt>Alvo 2: extensão 127%</dt><dd>" + brl(n.alvo_ext) + " <small>R:R " + nf(n.rr_ext, 1) + "</small></dd></div>" +
      "<div><dt>Alvo 2R</dt><dd>" + brl(n.alvo_2r) + "</dd></div>" +
      "<div><dt>Correção desde o pico</dt><dd>" + pct(n.queda_pct, 0) + " <small>em " + dbr(n.data_pico) + " a " + dbr(n.data_fundo) + "</small></dd></div>" +
      "<div><dt>Rompimento (último topo descendente)</dt><dd>" + brl(n.lh) + "</dd></div>" +
      "<div><dt>Fundo ascendente</dt><dd>" + brl(n.hl) + "</dd></div></dl>";
  }
  function calcHtml() {
    return '<div class="calc"><label class="field">Capital (R$)<input id="c-cap" type="number" min="0" step="500" inputmode="decimal" value="' + S.capital + '"></label>' +
      '<label class="field">Risco por operação (%)<input id="c-risco" type="number" min="0.1" max="10" step="0.1" inputmode="decimal" value="' + S.risco + '"></label></div><p class="out" id="c-out"></p>';
  }
  function calc() {
    const a = S.atual, o = $("#c-out"); if (!a || !o) return;
    const cap = +$("#c-cap").value, rk = +$("#c-risco").value;
    S.capital = cap; S.risco = rk; store.set("capital", cap); store.set("risco", rk);
    const risco = a.niveis.entrada - a.niveis.stop;
    if (!(cap > 0 && rk > 0 && risco > 0)) { o.textContent = "Informe capital e risco; o stop precisa estar abaixo do preço de entrada."; return; }
    const maxPerda = cap * rk / 100, q = Math.floor(maxPerda / risco), lote = Math.floor(q / 100) * 100;
    const fin = q * a.niveis.entrada;
    o.innerHTML = "Perda máxima aceita: <b>" + brl(maxPerda) + "</b>. Quantidade: <b>" + q + "</b> ações (" + (lote ? lote + " no lote padrão" : "menos de 1 lote padrão, use o fracionário") + "), cerca de <b>" + brl(fin) + "</b>" + (fin > cap ? ", acima do capital: reduza o risco ou escolha outro ponto de entrada" : " (" + pct(fin / cap, 0) + " do capital)") + ".";
  }
  function planoTexto(a) {
    const n = a.niveis;
    return a.ticker + " (" + STATUS[a.status] + ", nota " + a.score + "/100, " + ACOES[a.acao] + ")\n" +
      "Entrada " + brl(n.entrada) + " | Stop " + brl(n.stop) + " (" + pct(n.risco_pct, 1) + ")\n" +
      "Alvo 1 " + brl(n.alvo) + " (R:R " + nf(n.rr, 1) + ") | Alvo 2 " + brl(n.alvo_ext) + " | 2R " + brl(n.alvo_2r) + "\n" +
      "Rompimento " + brl(n.lh) + " | Fundo ascendente " + brl(n.hl) + "\nPregão de " + dbr(a.data);
  }
  function abrir(t, semHash) {
    const a = S.data && S.data.ativos.find((x) => x.ticker === t); if (!a) return;
    S.atual = a;
    const d = $("#drawer"), fav = S.favs.has(a.ticker), up = (a.var_dia ?? 0) >= 0;
    const g = S.graf;
    const chk = (k, txt, cls, dash) => '<label><input type="checkbox" data-g="' + k + '"' + (g[k] ? " checked" : "") + '><span class="sw ' + (dash ? "dash" : "") + '" style="color:var(' + cls + ')"></span>' + txt + "</label>";
    d.innerHTML =
      '<div class="d-head"><div><span class="tk" id="d-tk">' + esc(a.ticker) + '</span><span class="sub">' + esc(a.setor) + " | " + brl(a.preco) + ' <span class="' + (up ? "up" : "down") + '">' + (up ? "▲ " : "▼ ") + pct(Math.abs(a.var_dia ?? 0), 2) + "</span></span></div>" +
      '<div class="acts"><button class="btn" id="d-fav" type="button" aria-pressed="' + fav + '">' + (fav ? "★ Favorito" : "☆ Favoritar") + '</button><button class="btn" id="d-close" type="button">Fechar</button></div></div>' +
      '<div class="d-body">' +
      '<div class="sec"><span class="badge a-' + a.acao + '">' + ACOES[a.acao] + "</span> <span class=\"sub\" style=\"display:inline\">" + STATUS[a.status] + ", nota " + a.score + " de 100</span>" +
      '<p class="leitura">' + esc(a.leitura) + "</p>" +
      (a.avisos.length ? '<ul class="avisos">' + a.avisos.map((x) => "<li>" + esc(x) + "</li>").join("") + "</ul>" : "") + "</div>" +
      '<div class="sec"><h3>Gráfico diário</h3><p class="readout" id="readout" aria-live="off">Passe o dedo ou o mouse sobre os candles.</p>' +
      '<div class="chart-box"><canvas id="cv" role="img" aria-label="Gráfico de candles de ' + esc(a.ticker) + '"></canvas></div>' +
      '<div class="legend">' + chk("m21", "MM21", "--c-m21") + chk("m50", "MM50", "--c-m50") + chk("m200", "MM200", "--c-m200") + chk("avwap", "VWAP do fundo", "--c-avwap", true) + chk("niveis", "Níveis e marcas", "--ink2") +
      '<label>Período <select id="g-barras">' + [60, 120, 160].map((b) => '<option value="' + b + '"' + (g.barras === b ? " selected" : "") + ">" + b + " pregões</option>").join("") + "</select></label></div></div>" +
      '<div class="sec"><h3>Plano da operação</h3>' + niveisHtml(a) + "</div>" +
      '<div class="sec"><h3>Tamanho da posição</h3>' + calcHtml() + '<button class="btn" id="d-copy" type="button" style="margin-top:10px">Copiar plano</button></div>' +
      '<div class="sec"><h3>Checklist de confluência</h3>' + checklistHtml(a) + "</div>" +
      '<div class="sec"><h3>Opções</h3>' + opcoesHtml(a.opcoes) + "</div>" +
      (a.balanco ? '<div class="sec"><h3>Resultado trimestral</h3><p>Próxima divulgação em ' + dbr(a.balanco.data) + " (" + a.balanco.dias + " dias). Confirme no calendário da empresa.</p></div>" : "") +
      "</div>";
    if (!d.open) d.showModal();
    d.scrollTop = 0;
    if (S.chart) S.chart.destroy();
    S.chart = new B3Chart.Chart($("#cv"), (r) => {
      $("#readout").textContent = r ? B3Chart.dm(r.d) + "  abertura " + nf(r.o) + "  máxima " + nf(r.h) + "  mínima " + nf(r.l) + "  fechamento " + nf(r.c) + "  volume " + nf(r.v / 1e6, 2) + " mi" : "Passe o dedo ou o mouse sobre os candles.";
    });
    S.chart.set(a.serie, a.niveis, S.graf);
    calc();
    if (!semHash) history.replaceState(null, "", "#" + a.ticker);
  }
  const dr = $("#drawer");
  dr.addEventListener("click", (e) => {
    if (e.target === dr) return dr.close();
    if (e.target.id === "d-close") return dr.close();
    if (e.target.id === "d-fav") { const t = S.atual.ticker; S.favs.has(t) ? S.favs.delete(t) : S.favs.add(t); store.set("favs", [...S.favs]); abrir(t, true); render(); return; }
    if (e.target.id === "d-copy") {
      const txt = planoTexto(S.atual), b = e.target;
      (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).then(() => { b.textContent = "Plano copiado"; }, () => { b.textContent = "Não foi possível copiar"; });
      setTimeout(() => (b.textContent = "Copiar plano"), 2000);
    }
  });
  dr.addEventListener("input", (e) => {
    if (e.target.id === "c-cap" || e.target.id === "c-risco") calc();
  });
  dr.addEventListener("change", (e) => {
    const k = e.target.dataset && e.target.dataset.g;
    if (k) { S.graf[k] = e.target.checked; }
    else if (e.target.id === "g-barras") { S.graf.barras = +e.target.value; }
    else return;
    store.set("graf", S.graf); S.chart.set(S.atual.serie, S.atual.niveis, S.graf);
  });
  dr.addEventListener("close", () => {
    if (S.chart) { S.chart.destroy(); S.chart = null; }
    history.replaceState(null, "", location.pathname + location.search);
  });

  // ---------- PWA
  let promptInstalar = null;
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); promptInstalar = e; $("#btn-install").hidden = false; });
  $("#btn-install").addEventListener("click", async () => {
    if (!promptInstalar) return; promptInstalar.prompt(); await promptInstalar.userChoice; promptInstalar = null; $("#btn-install").hidden = true;
  });
  if (/iphone|ipad/i.test(navigator.userAgent) && !navigator.standalone) $("#ios-dica").hidden = false;
  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) navigator.serviceWorker.register("sw.js").catch(() => {});

  // ---------- início
  $("#f-min").value = S.min; $("#f-min-v").textContent = S.min; $("#f-estr").value = S.estr; $("#f-ord").value = S.ord; $("#f-bal").checked = S.bal;
  const tq = new URLSearchParams(location.search).get("tema"); // ?tema=dark|light força o tema (útil p/ conferir)
  if (tq === "dark" || tq === "light") S.tema = tq;
  aplicaTema();
  carregar(false).then(() => {
    const h = decodeURIComponent(location.hash.slice(1)).toUpperCase();
    if (h) abrir(h, true);
  });
})();
