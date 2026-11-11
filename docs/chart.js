/* Gráfico de candles em canvas: médias, VWAP ancorado, níveis da estrutura, volume e crosshair. */
(function () {
  const fmt = (x) => x.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const dm = (iso) => iso.slice(8, 10) + "/" + iso.slice(5, 7);

  class Chart {
    constructor(canvas, onReadout) {
      this.cv = canvas;
      this.ctx = canvas.getContext("2d");
      this.onReadout = onReadout || (() => {});
      this.serie = null;
      this.niveis = {};
      this.opt = { m21: true, m50: true, m200: true, avwap: true, niveis: true, barras: 120 };
      this.hover = null;
      canvas.addEventListener("pointermove", (e) => this._move(e));
      canvas.addEventListener("pointerdown", (e) => this._move(e));
      canvas.addEventListener("pointerleave", () => { this.hover = null; this.draw(); this.onReadout(null); });
      this.ro = new ResizeObserver(() => this.draw());
      this.ro.observe(canvas.parentElement);
    }
    destroy() { this.ro.disconnect(); }
    set(serie, niveis, opt) { this.serie = serie; this.niveis = niveis || {}; Object.assign(this.opt, opt || {}); this.draw(); }

    _geom() {
      const s = this.serie, n = s.c.length;
      const bars = Math.min(this.opt.barras, n);
      const start = n - bars;
      const w = this.cv.parentElement.clientWidth || 600;
      const h = w < 520 ? 280 : 340;
      const pad = { l: 8, r: 58, t: 26, b: 22 };
      const pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;
      const volH = ph * 0.2, priceH = ph - volH - 6;
      return { n, bars, start, w, h, pad, pw, ph, volH, priceH, step: pw / bars };
    }

    _move(e) {
      if (!this.serie) return;
      const g = this._geom();
      const r = this.cv.getBoundingClientRect();
      const i = Math.floor((e.clientX - r.left - g.pad.l) / g.step);
      if (i < 0 || i >= g.bars) return;
      this.hover = g.start + i;
      this.draw();
      const s = this.serie, k = this.hover;
      this.onReadout({ d: s.d[k], o: s.o[k], h: s.h[k], l: s.l[k], c: s.c[k], v: s.v[k] });
    }

    draw() {
      if (!this.serie) return;
      const s = this.serie, g = this._geom(), ctx = this.ctx, cv = this.cv;
      const css = getComputedStyle(cv);
      const col = (v) => css.getPropertyValue(v).trim();
      const C = {
        ink: col("--ink"), ink2: col("--ink2"), muted: col("--muted"), line: col("--line2"), surface: col("--surface"),
        up: col("--up"), down: col("--down"), warn: col("--warn"), brand: col("--brand"),
        m21: col("--c-m21"), m50: col("--c-m50"), m200: col("--c-m200"), avwap: col("--c-avwap"),
      };
      const dpr = window.devicePixelRatio || 1;
      cv.width = Math.round(g.w * dpr); cv.height = Math.round(g.h * dpr);
      cv.style.height = g.h + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, g.w, g.h);
      ctx.font = "12px system-ui, sans-serif";

      const nv = this.niveis, niv = this.opt.niveis;
      let lo = Infinity, hi = -Infinity;
      for (let i = g.start; i < g.n; i++) {
        if (s.l[i] != null) lo = Math.min(lo, s.l[i]);
        if (s.h[i] != null) hi = Math.max(hi, s.h[i]);
      }
      const base = [lo, hi];
      if (niv) {
        if (nv.stop != null) lo = Math.min(lo, nv.stop);
        if (nv.alvo != null && nv.alvo <= base[1] * 1.12) hi = Math.max(hi, nv.alvo);
      }
      const padY = (hi - lo) * 0.05; lo -= padY; hi += padY;
      const X = (i) => g.pad.l + (i - g.start + 0.5) * g.step;
      const Y = (p) => g.pad.t + (hi - p) / (hi - lo) * g.priceH;

      // grade e eixo de preço
      ctx.textBaseline = "middle"; ctx.textAlign = "left";
      for (let k = 0; k <= 4; k++) {
        const p = lo + (hi - lo) * k / 4, y = Y(p);
        ctx.strokeStyle = C.line; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(g.pad.l, y); ctx.lineTo(g.w - g.pad.r, y); ctx.stroke();
        ctx.fillStyle = C.muted; ctx.fillText(fmt(p), g.w - g.pad.r + 6, y);
      }
      // datas
      ctx.textBaseline = "alphabetic"; ctx.textAlign = "center"; ctx.fillStyle = C.muted;
      for (let k = 0; k < 4; k++) {
        const i = g.start + Math.round((g.bars - 1) * (k + 0.5) / 4);
        ctx.fillText(dm(s.d[i]), X(i), g.h - 6);
      }

      // volume
      let vmax = 1;
      for (let i = g.start; i < g.n; i++) vmax = Math.max(vmax, s.v[i]);
      const vy0 = g.pad.t + g.priceH + 6 + g.volH;
      ctx.fillStyle = C.ink2; ctx.globalAlpha = 0.28;
      const bw = Math.max(1.2, g.step * 0.62);
      for (let i = g.start; i < g.n; i++) {
        const vh = (s.v[i] / vmax) * g.volH;
        ctx.fillRect(X(i) - bw / 2, vy0 - vh, bw, vh);
      }
      ctx.globalAlpha = 1;

      // níveis da estrutura (atrás dos candles)
      const lvl = [];
      if (niv) {
        if (nv.pico != null) lvl.push(["Pico", nv.pico, C.muted, [2, 4]]);
        if (nv.lh != null) lvl.push(["Rompimento", nv.lh, C.warn, []]);
        if (nv.hl != null) lvl.push(["Fundo asc.", nv.hl, C.up, [6, 4]]);
        if (nv.stop != null) lvl.push(["Stop", nv.stop, C.down, [6, 4]]);
        if (nv.alvo != null && nv.alvo <= base[1] * 1.12) lvl.push(["Alvo", nv.alvo, C.up, [2, 4]]);
      }
      for (const [nm, p, color, dash] of lvl) {
        if (p < lo || p > hi) continue;
        const y = Y(p);
        ctx.strokeStyle = color; ctx.lineWidth = 1.2; ctx.setLineDash(dash);
        ctx.beginPath(); ctx.moveTo(g.pad.l, y); ctx.lineTo(g.w - g.pad.r, y); ctx.stroke();
        ctx.setLineDash([]);
      }

      // candles: alta = vazado com contorno; baixa = cheio (não depende só de cor)
      for (let i = g.start; i < g.n; i++) {
        if (s.c[i] == null) continue;
        const x = X(i), up = s.c[i] >= s.o[i];
        const color = up ? C.up : C.down;
        ctx.strokeStyle = color; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, Y(s.h[i])); ctx.lineTo(x, Y(s.l[i])); ctx.stroke();
        const y1 = Y(Math.max(s.o[i], s.c[i])), y2 = Y(Math.min(s.o[i], s.c[i]));
        const hh = Math.max(1, y2 - y1);
        ctx.fillStyle = up ? C.surface : color;
        ctx.fillRect(x - bw / 2, y1, bw, hh);
        ctx.strokeRect(x - bw / 2 + 0.5, y1 + 0.5, Math.max(0, bw - 1), Math.max(0, hh - 1));
      }

      // médias e VWAP
      const line = (arr, color, w, dash) => {
        ctx.strokeStyle = color; ctx.lineWidth = w; ctx.setLineDash(dash || []);
        ctx.beginPath(); let on = false;
        for (let i = g.start; i < g.n; i++) {
          const v = arr[i];
          if (v == null) { on = false; continue; }
          const x = X(i), y = Y(v);
          if (!on) { ctx.moveTo(x, y); on = true; } else ctx.lineTo(x, y);
        }
        ctx.stroke(); ctx.setLineDash([]);
      };
      if (this.opt.m21) line(s.m21, C.m21, 1.5);
      if (this.opt.m50) line(s.m50, C.m50, 1.5);
      if (this.opt.m200) line(s.m200, C.m200, 2);
      if (this.opt.avwap) line(s.avwap, C.avwap, 1.8, [5, 3]);

      // rótulos dos níveis (com halo para legibilidade)
      // (níveis próximos têm os rótulos afastados em 14px para não se sobreporem)
      ctx.textAlign = "left"; ctx.textBaseline = "bottom";
      const rot = lvl.filter(([, p]) => p >= lo && p <= hi).map(([nm, p, color]) => ({ t: nm + " " + fmt(p), y: Y(p) - 3, color }))
        .sort((a, b) => a.y - b.y);
      for (let k = 1; k < rot.length; k++) if (rot[k].y < rot[k - 1].y + 14) rot[k].y = rot[k - 1].y + 14;
      for (const r of rot) {
        ctx.lineWidth = 3; ctx.strokeStyle = C.surface; ctx.strokeText(r.t, g.pad.l + 4, r.y);
        ctx.fillStyle = r.color; ctx.fillText(r.t, g.pad.l + 4, r.y);
      }

      // marcas: pico, fundo, rompimento
      const m = s.marcas || {}, tri = (i, up, color, label) => {
        if (i == null || i < g.start) return;
        const x = X(i), y = up ? Y(s.l[i]) + 9 : Y(s.h[i]) - 9, d = up ? -1 : 1;
        ctx.fillStyle = color; ctx.beginPath();
        ctx.moveTo(x, y + d * -5); ctx.lineTo(x - 5, y + d * 5); ctx.lineTo(x + 5, y + d * 5); ctx.closePath(); ctx.fill();
        ctx.textAlign = "center"; ctx.textBaseline = up ? "top" : "bottom";
        ctx.lineWidth = 3; ctx.strokeStyle = C.surface;
        const ty = up ? y + 8 : y - 8;
        ctx.strokeText(label, x, ty); ctx.fillStyle = C.ink; ctx.fillText(label, x, ty);
      };
      if (niv) {
        tri(m.pico, false, C.muted, "Pico");
        tri(m.fundo, true, C.brand, "Fundo");
        if (m.bos != null && m.bos >= g.start) {
          const x = X(m.bos), y = Y(s.c[m.bos]);
          ctx.fillStyle = C.warn; ctx.beginPath(); ctx.arc(x, y, 4, 0, 6.3); ctx.fill();
        }
      }

      // crosshair
      if (this.hover != null && this.hover >= g.start) {
        const x = X(this.hover);
        ctx.strokeStyle = C.ink2; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.moveTo(x, g.pad.t); ctx.lineTo(x, g.h - g.pad.b); ctx.stroke(); ctx.setLineDash([]);
      }
    }
  }
  window.B3Chart = { Chart, fmt, dm };
})();
