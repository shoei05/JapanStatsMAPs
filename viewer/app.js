/* 日本の公開データ研究マップ ビューア
   構成は JP_Market_Vis（https://mattyamonaca.github.io/JP_Market_Vis/）に倣う。
   力学配置は外部ライブラリを使わず自前で計算する（42ノードなので総当たりで足りる。
   file:// でも動かしたいので CDN 依存を作らない）。

   守る約束:
   - 件数は論文数（paper_id の異なり）。複数テーマ・複数の線に現れる論文を総数で重複計上しない。
   - 円は各テーマを扱う全論文。線は登録された解析の組合せだけ。テーマの共起からは作らない。
   - 辺は「解析上の役割」であって因果ではない。円の大きさ・線の太さは論文数だけを表す。
   - 検索0件と「報告未発見」を区別する。
*/
const D = window.ODMAP;
const $ = (s, r = document) => r.querySelector(s);
const el = (t, c, txt) => { const e = document.createElement(t); if (c) e.className = c; if (txt != null) e.textContent = txt; return e; };
const paperById = Object.fromEntries(D.papers.map(p => [p.paper_id, p]));
const label = k => (D.domain_labels && D.domain_labels[k]) || k;
function paperUrl(p) {
  if (p.doi) return "https://doi.org/" + p.doi;
  try { const url = new URL(p.article_url); return ["https:", "http:"].includes(url.protocol) ? url.href : ""; }
  catch { return ""; }
}
function paperTitle(p,className="t") {
  const url=paperUrl(p), title=el(url?"a":"span",className,p.title);
  if(url){title.href=url;title.target="_blank";title.rel="noopener noreferrer";}
  return title;
}

/* 生成りの紙面で沈まないよう、彩度を落として明度差をつけたテーマ色。 */
const GROUP_COLOR = {
  dependence_preference: "#F21A00", digital_information: "#78B7C5", mental_psychological: "#3B9AB2",  // Zissou1
  relations_social: "#E6A0C4", healthcare_use: "#7294D4",   // GrandBudapest2
  infection_prevention: "#046C9A",                          // Darjeeling2
  lifestyle_physical: "#81A88D", work_socioeconomic: "#972D15",  // Cavalcanti1
  family_sex: "#E1AF00",                                    // Zissou1
  research_methods: "#CDC08C",                              // Moonrise3
  disease_burden: "#9986A5",                                // IsleofDogs1
  healthcare_provision: "#00A08A",                          // Darjeeling1
  population_dynamics: "#DD8D29",                           // FantasticFox1
  environment_economy: "#9C964A",                           // Moonrise3
  data_methods: "#899DA4"                                   // Royal1
};
const groupOf = {};
Object.entries(D.display_groups).forEach(([g, v]) => v.domains.forEach(d => (groupOf[d] = g)));
const colorOf = d => GROUP_COLOR[groupOf[d]] || "#8D8680";  // IsleofDogs1 grey
/* 尺度を領域ごとに表示する。 */
const SCALES_BY_DOMAIN = {};
(D.scales || []).forEach(s => { if (s.domain) (SCALES_BY_DOMAIN[s.domain] = SCALES_BY_DOMAIN[s.domain] || []).push(s); });
const hasScale = d => !!SCALES_BY_DOMAIN[d];
/* 調査票の下位分類（この版では使わない） */
const SURVEY_BY_DOMAIN = {};
(D.survey_crosswalk || []).forEach(r => { if (r.domain) (SURVEY_BY_DOMAIN[r.domain] = SURVEY_BY_DOMAIN[r.domain] || []).push(r); });

const state = { tab: "map", q: "", groups: new Set(), minPapers: 1, verified: false,
                sel: null, selEdge: null, listSel: null, study: "", wave: "", cls: "" };
const CLASS_LABEL = {A: "A 公開集計", B: "B 個票", AB: "A＋B 併用"};
const yearRange = p => (p.year_start && p.year_end) ? (p.year_start === p.year_end ? `${p.year_start}年` : `${p.year_start}〜${p.year_end}年`) : "未記載";

function paperDomains(p) {
  const domains = Array.isArray(p.map_domains) ? p.map_domains : [p.exposure_domain, p.outcome_domain];
  return [...new Set(domains.filter(d => Object.hasOwn(D.domains, d)))];
}
function paperAuthors(p) {
  return [...new Set((p.authors?.length ? p.authors : [p.first_author_full || p.first_author]).filter(Boolean))];
}
function paperAnalysisPairs(p) {
  return Object.entries(D.pairs).filter(([, ids]) => ids.includes(p.paper_id)).map(([key]) => key.split("|"));
}
function searchText(value) {
  return String(value || "").normalize("NFKC").toLowerCase()
    .normalize("NFD").replace(/(\p{Script=Latin})\p{M}+/gu, "$1").normalize("NFC")
    .replace(/https?:\/\/(?:dx\.)?doi\.org\//g, "").replace(/\bdoi:\s*/g, "")
    .replace(/[,、]/g, " ");
}
function paperSearchText(p) {
  return searchText([p.title,p.first_author,p.first_author_full,...(p.authors||[]),...(p.author_aliases||[]),
    p.journal,p.journal_abbreviation,...(p.journal_aliases||[]),p.doi,
    ...(p.search_aliases||[]),...(p.sources||[]),label(p.exposure_domain),
    label(p.outcome_domain),...paperDomains(p).flatMap(d => [d,label(d)]),...(p.tags||[]).map(label)].join(" "));
}
function paperQueryMatches(p, query) {
  const tokens = searchText(query).split(/\s+/).filter(Boolean), hay = paperSearchText(p);
  const missing = tokens.filter(token => !hay.includes(token));
  if (!missing.length) return true;
  // Initial-only source metadata may match one given-name token, but only when
  // this same author's family name is explicitly in the query. Never expand it.
  if (missing.length !== 1 || !/^[a-z]+(?:-[a-z]+)*$/.test(missing[0])) return false;
  return (p.author_details || []).some(author => {
    const family = searchText(author.family).split(/\s+/).filter(Boolean);
    const initials = searchText(author.given).split(/[.\s-]+/).filter(Boolean);
    return family.length && family.every(token => tokens.includes(token)) &&
      initials.length && initials.every(token => /^[a-z]$/.test(token)) && initials[0] === missing[0][0];
  });
}
function paperMatches(p) {
  if (p.doc_kind !== "paper") return false;
  if (state.verified && !String(p.input_mode || "").startsWith("fulltext")) return false;
  if (state.study && !(p.sources || []).includes(state.study)) return false;
  if (state.cls && p.data_class !== state.cls) return false;
  if (state.wave && !(p.year_start && p.year_start <= +state.wave && +state.wave <= p.year_end)) return false;
  if (state.q && !paperQueryMatches(p, state.q)) return false;
  return true;
}
function filteredPapers() {
  return D.papers.filter(p => paperMatches(p) && (!state.groups.size || paperDomains(p).some(d => state.groups.has(groupOf[d])))).sort((a,b) => (b.year||0)-(a.year||0));
}
function searchResults(g = buildGraph()) {
  const papers = filteredPapers();
  const mapped = new Set(g.nodes.flatMap(n => n.ids));
  return {papers, mappedCount: papers.filter(p => mapped.has(p.paper_id)).length, relatedCount: g.relatedCount};
}
function openPaperList() {
  state.tab = "list"; state.listSel = null; state.sel = state.selEdge = null;
  history.replaceState(null, "", "#list"); refresh(false);
  document.querySelector('#tabs button[data-tab="list"]')?.focus();
}
function renderSearchSummary(g) {
  let box = $("#paper-search-summary");
  if (!box) {
    const stage = $(".content-stage"); if (!stage) return;
    box = el("section", "academic-notice-banner"); box.id = "paper-search-summary";
    const text = el("p", "guide-text"); text.setAttribute("role", "status");
    const button = el("button", "btn-reset", "論文一覧で見る →");
    button.type = "button"; button.onclick = openPaperList;
    box.append(text, button); stage.prepend(box);
  }
  const active = !!state.q.trim() && ["map", "matrix"].includes(state.tab);
  box.style.display = active ? "" : "none";
  if (!active) return;
  const {papers, mappedCount, relatedCount} = searchResults(g);
  box.firstChild.textContent = `検索に一致 ${papers.length} 論文（テーマの円 ${mappedCount} 論文・関連の線 ${relatedCount} 論文）`;
  box.lastChild.disabled = !papers.length;
}
function openSurvey(filters={}) {
  state.tab="survey"; if (filters.source) state.study = filters.source; refresh(false);
}
function openDomain(id, preserveFilters = false) {
  if (!Object.hasOwn(D.domains,id)) return;
  if (!preserveFilters) document.querySelector("#reset").click();
  state.tab="map"; state.sel=id; state.selEdge=null;
  history.replaceState(null,"","#map?domain="+encodeURIComponent(id));
  refresh(true);
}
window.ODMap = {openSurvey,openDomain, openPaper(id) {document.querySelector("#reset").click();state.tab="list";state.listSel=id;state.sel=state.selEdge=null;history.replaceState(null,"","#list");refresh(false);document.querySelector(".card.on")?.scrollIntoView({block:"center"});}};

/* ---------- グラフの組み立て ---------- */
function buildGraph() {
  const papers = filteredPapers(), selected = new Set(papers.map(p => p.paper_id));
  const membership = new Map();
  papers.forEach(p => paperDomains(p).forEach(domain => {
    if (!membership.has(domain)) membership.set(domain, new Set());
    membership.get(domain).add(p.paper_id);
  }));
  const nodes = [...membership].map(([id, ids]) => ({id, n: ids.size, ids: [...ids]}));
  const edges = [];
  Object.entries(D.pairs).forEach(([key, ids]) => {
    const [s, t] = key.split("|");
    const kept = [...new Set(ids)].filter(id => selected.has(id));
    if (kept.length < state.minPapers || !membership.has(s) || !membership.has(t)) return;
    edges.push({s, t, ids: kept, n: kept.length});
  });
  const unmapped = papers.filter(p => !paperDomains(p).length);
  return {nodes, edges, papers, unmapped, paperCount: selected.size,
    relatedCount: new Set(edges.flatMap(e => e.ids)).size};
}

/* ---------- 力学配置（自前） ---------- */
const sim = { nodes: [], edges: [], byId: {}, tx: 0, ty: 0, k: 1, running: 0 };
function layout(g, keepPos) {
  // 初期位置はテーマのグループごとの扇形に置き、表示前に冷却しながら配置を計算しきる（開いた直後に揺れない）
  const prev = keepPos ? Object.fromEntries(sim.nodes.map(n => [n.id, n])) : {};
  const groups = Object.keys(D.display_groups);
  const seed = s => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0; return (h % 1000) / 1000; };
  sim.nodes = g.nodes.map(n => {
    const o = prev[n.id];
    const gi = Math.max(0, groups.indexOf(groupOf[n.id]));
    const a = ((gi + 0.15 + 0.7 * seed(n.id)) / Math.max(1, groups.length)) * Math.PI * 2;
    const r = 140 + 90 * seed(n.id + "r");
    return { ...n, x: o ? o.x : Math.cos(a) * r, y: o ? o.y : Math.sin(a) * r, vx: 0, vy: 0, fixed: false };
  });
  sim.byId = Object.fromEntries(sim.nodes.map(n => [n.id, n]));
  sim.edges = g.edges.map(e => ({ ...e, a: sim.byId[e.s], b: sim.byId[e.t] }));
  const iters = Object.keys(prev).length ? 250 : 500;
  for (let i = 0; i < iters; i++) step(Math.max(0.02, 1 - i / iters));
  sim.running = 0;
  if (cv) fit();
}
function step(alpha = 0.3) {
  const N = sim.nodes, maxV = 18 * alpha + 1;
  for (let i = 0; i < N.length; i++) {
    const a = N[i];
    for (let j = i + 1; j < N.length; j++) {
      const b = N[j];
      let dx = b.x - a.x, dy = b.y - a.y, d2 = dx * dx + dy * dy || 0.01;
      const f = alpha * 9000 / Math.max(d2, 400), d = Math.sqrt(d2);
      const fx = (dx / d) * f, fy = (dy / d) * f;
      a.vx -= fx; a.vy -= fy; b.vx += fx; b.vy += fy;
    }
    a.vx -= a.x * 0.012 * alpha; a.vy -= a.y * 0.012 * alpha;   // 中心へ引き戻す
  }
  sim.edges.forEach(e => {
    if (e.a === e.b) return;                      // 自己ループは力を出さない
    const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y;
    const d = Math.hypot(dx, dy) || 0.01;
    const target = 165 + 70 / Math.sqrt(e.n);
    const f = alpha * (d - target) * 0.006 * Math.min(2, Math.log2(e.n + 1) * 0.5 + 0.5);
    const fx = (dx / d) * f, fy = (dy / d) * f;
    e.a.vx += fx; e.a.vy += fy; e.b.vx -= fx; e.b.vy -= fy;
  });
  N.forEach(n => {
    if (n.fixed) { n.vx = n.vy = 0; return; }
    n.vx *= 0.6; n.vy *= 0.6;
    const v = Math.hypot(n.vx, n.vy); if (v > maxV) { n.vx *= maxV / v; n.vy *= maxV / v; }
    n.x += n.vx; n.y += n.vy;
  });
}

/* ---------- 描画 ---------- */
let cv, ctx, dpr = window.devicePixelRatio || 1;
function fit() {
  if (!sim.nodes.length) return;
  const xs = sim.nodes.map(n => n.x), ys = sim.nodes.map(n => n.y);
  const w = cv.clientWidth, h = cv.clientHeight;
  const bw = Math.max(1, Math.max(...xs) - Math.min(...xs)), bh = Math.max(1, Math.max(...ys) - Math.min(...ys));
  sim.k = Math.min(w / (bw + 190), h / (bh + 190), 2.2);
  sim.tx = w / 2 - ((Math.max(...xs) + Math.min(...xs)) / 2) * sim.k;
  sim.ty = h / 2 - ((Math.max(...ys) + Math.min(...ys)) / 2) * sim.k;
}
const rad = n => 5 + Math.sqrt(n.n) * 2.6;
function draw() {
  const w = cv.clientWidth, h = cv.clientHeight;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = w * dpr; cv.height = h * dpr; }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.save(); ctx.translate(sim.tx, sim.ty); ctx.scale(sim.k, sim.k);
  sim.edges.forEach(e => {
    const on = state.sel && (e.s === state.sel || e.t === state.sel);
    const dim = state.sel && !on;
    ctx.globalAlpha = dim ? 0.07 : 0.45;
    ctx.strokeStyle = colorOf(e.s);
    ctx.lineWidth = Math.min(7, 0.7 + Math.log2(e.n + 1) * 1.5);
    ctx.beginPath();
    if (e.a === e.b) { ctx.arc(e.a.x + 14, e.a.y - 14, 13, 0, Math.PI * 2); }
    else { ctx.moveTo(e.a.x, e.a.y); ctx.lineTo(e.b.x, e.b.y); }
    ctx.stroke();
  });
  ctx.globalAlpha = 1;
  const sorted = [...sim.nodes].sort((a, b) => a.n - b.n);
  sorted.forEach(n => {
    const dim = state.sel && n.id !== state.sel && !sim.edges.some(e => (e.s === state.sel && e.t === n.id) || (e.t === state.sel && e.s === n.id));
    ctx.globalAlpha = dim ? 0.15 : 1;
    ctx.beginPath(); ctx.arc(n.x, n.y, rad(n), 0, Math.PI * 2);
    ctx.fillStyle = colorOf(n.id); ctx.fill();
    ctx.lineWidth = n.id === state.sel ? 2.5 : 1;
    ctx.strokeStyle = n.id === state.sel ? cssVar("--canvas-ink", "#2f3437") : cssVar("--canvas-node-edge", "#ffffff"); ctx.stroke();
    if (hasScale(n.id)) {           // 検証済み尺度で測られている概念
      ctx.beginPath(); ctx.arc(n.x, n.y, rad(n) + 3.2, 0, Math.PI * 2);
      ctx.lineWidth = 1.2; ctx.strokeStyle = cssVar("--canvas-ink", "#2f3437"); ctx.globalAlpha = dim ? 0.12 : 0.55; ctx.stroke();
      ctx.globalAlpha = dim ? 0.15 : 1;
    }
  });
  const top = [...sim.nodes].sort((a, b) => b.n - a.n);
  ctx.globalAlpha = 1;
  const fs = Math.max(10, Math.min(13, 12 / sim.k));
  ctx.font = `${fs}px -apple-system,"Hiragino Sans",sans-serif`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  const placed = [];   // 画面座標での占有矩形。重なるラベルは描かない
  const overlap = (r) => placed.some(q => !(r.x2 < q.x1 || r.x1 > q.x2 || r.y2 < q.y1 || r.y1 > q.y2));
  top.forEach(n => {
    const dim = state.sel && n.id !== state.sel && !sim.edges.some(e => (e.s === state.sel && e.t === n.id) || (e.t === state.sel && e.s === n.id));
    if (dim) return;
    const txt = label(n.id);
    const wpx = ctx.measureText(txt).width;
    const sx = n.x * sim.k + sim.tx, sy = (n.y - rad(n)) * sim.k + sim.ty - 9;
    const half = (wpx * 1) / 2 + 3;
    const box = { x1: sx - half, x2: sx + half, y1: sy - 9, y2: sy + 9 };
    if (overlap(box)) return;
    placed.push(box);
    ctx.save(); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.font = `${fs}px -apple-system,"Hiragino Sans",sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillStyle = cssVar("--canvas-label-bg", "rgba(255,255,255,.9)");
    ctx.fillRect(box.x1, box.y1, box.x2 - box.x1, box.y2 - box.y1);
    ctx.fillStyle = cssVar("--canvas-ink", "#2f3437"); ctx.fillText(txt, sx, sy);
    ctx.restore();
  });
  ctx.restore();
}
function tick() {
  if (state.tab === "map" && sim.running > 0) { step(0.15); sim.running--; }
  if (state.tab === "map") draw(); requestAnimationFrame(tick);
}
const toWorld = (mx, my) => ({ x: (mx - sim.tx) / sim.k, y: (my - sim.ty) / sim.k });
function hit(mx, my) {
  const p = toWorld(mx, my);
  return sim.nodes.find(n => Math.hypot(n.x - p.x, n.y - p.y) <= rad(n) + 4);
}

/* ---------- 画面 ---------- */
function renderStats() {
  const g = buildGraph();
  $("#stats").innerHTML = "";
  [["表示中のテーマ", g.nodes.length, `全${Object.keys(D.domains).length}テーマ`],
   [`表示中 / 全${D.meta.n_papers}論文`, g.paperCount, `関連の線 ${g.relatedCount}論文（${g.edges.length}組）`],
   ["データ源", D.sources.length, `A ${D.meta.n_by_class.A || 0}・B ${D.meta.n_by_class.B || 0}・併用 ${D.meta.n_by_class.AB || 0} 論文`]]
    .forEach(([k, v, sub]) => {
      const d = el("div", "stat"); d.append(el("b", null, Number(v).toLocaleString("ja-JP")), el("span", null, k), el("small", null, sub));
      $("#stats").append(d);
    });
  return g;
}
function renderGroups() {
  const g = $("#groups"); g.innerHTML = "";
  Object.entries(D.display_groups).forEach(([k, v]) => {
    const n = D.papers.filter(p => paperMatches(p) && paperDomains(p).some(d => v.domains.includes(d))).length;
    const b = el("button", "chip" + (state.groups.has(k) ? " on" : ""));
    b.style.setProperty("--c", GROUP_COLOR[k]);
    b.append(el("span", "nm", v.label), el("span", "ct", String(n)));
    b.onclick = () => { state.groups.has(k) ? state.groups.delete(k) : state.groups.add(k); refresh(true); };
    g.append(b);
  });
}
function appendPaperCards(container, papers) {
  papers.forEach(p => {
    const card = el("article", "mini");
    card.append(paperTitle(p), el("div", "m", [p.first_author_full || p.first_author, p.journal, p.year].filter(Boolean).join(" · ")));
    const info = el("button", "paper-details", "データ情報を見る");
    info.onclick = () => {state.listSel = p.paper_id; state.sel = state.selEdge = null; renderDetail();};
    card.append(info);
    if (p.links?.length) { const ln = el("button", "paper-details", "つながりを見る"); ln.onclick = () => openLinks(p.paper_id); card.append(ln); }
    container.append(card);
  });
}
function renderUnmappedPapers(g) {
  let box = $("#unmapped-papers");
  if (!box) {
    const map = $("#pane-map"); if (!map) return;
    box = el("section", "unmapped-papers"); box.id = "unmapped-papers"; map.append(box);
  }
  box.replaceChildren();
  const details = el("details"); details.open = g.unmapped.length > 0;
  details.append(el("summary", null, `テーマ未分類の論文 ${g.unmapped.length}件`));
  const cards = el("div", "unmapped-paper-cards");
  if (g.unmapped.length) appendPaperCards(cards, g.unmapped);
  else cards.append(el("p", "small", g.paperCount ? "現在の条件では、すべての論文をテーマの円から閲覧できます。" : "現在の検索条件に一致する論文がありません。"));
  details.append(cards); box.append(details);
}
function renderDetail() {
  const d = $("#detail"); if (!d) return; d.innerHTML = "";
  if (state.selEdge) {
    const e = state.selEdge;
    d.append(el("h3", null, `${label(e.s)} → ${label(e.t)}`));
    d.append(el("p", "muted small", `${e.ids.length} 論文`));
    appendPaperCards(d, e.ids.map(id => paperById[id]).filter(Boolean));
    return;
  }
  if (state.sel) {
    const papers = filteredPapers().filter(p => paperDomains(p).includes(state.sel));
    d.append(el("h3", null, label(state.sel)));
    d.append(el("p", "muted small", D.domains[state.sel] || ""));
    d.append(el("p", null, `このテーマを扱う ${papers.length} 論文`));
    const bySrc = {}; papers.forEach(p => (p.sources?.length ? p.sources : ["特定不能"]).forEach(x => bySrc[x] = (bySrc[x] || 0) + 1));
    const srcRows = Object.entries(bySrc).sort((a, b) => b[1] - a[1]);
    if (srcRows.length) {
      d.append(el("h4", "sub-h", "使われたデータ源"));
      srcRows.slice(0, 8).forEach(([x, n]) => {
        const c = el("div", "mini"); c.append(el("div", "t", x), el("div", "m", `${n} 論文 · データ源と年で見る →`));
        c.onclick = () => openSurvey({source: x === "特定不能" ? "" : x}); d.append(c);
      });
    }
    const es = buildGraph().edges.filter(e => e.s === state.sel || e.t === state.sel).sort((a, b) => b.n - a.n);
    if (es.length) d.append(el("h4", "sub-h", "登録された解析の組合せ"));
    es.forEach(e => {
      const c = el("div", "mini");
      c.append(el("div", "t", `${label(e.s)} → ${label(e.t)}`), el("div", "m", `${e.n} 論文`));
      c.tabIndex=0;c.setAttribute("role","button");c.onkeydown=ev=>{if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();c.click();}};
      c.onclick = () => { state.selEdge = e; renderDetail(); };
      d.append(c);
    });
    d.append(el("h4", "sub-h", "このテーマの論文"));
    appendPaperCards(d, papers);
    return;
  }
  const p = state.listSel && paperById[state.listSel];
  if (!p) { d.append(el("p", "muted", "円を選ぶとそのテーマの全論文、線を選ぶと解析の組合せを確認できます。")); return; }
  const heading=el("h3");heading.append(paperTitle(p,"paper-title"));d.append(heading);
  d.append(el("div", "m", [p.first_author_full || p.first_author, p.journal, p.year].filter(Boolean).join(" · ")));
  if (paperAuthors(p).length) d.append(el("div", "paper-authors", "著者：" + paperAuthors(p).join(" · ")));
  if (paperUrl(p)) { const a = el("a", "doi", "論文を開く ↗"); a.href = paperUrl(p); a.target = "_blank"; a.rel="noopener noreferrer"; d.append(a); }
  const box = el("div", "kvs");
  const kv = (k, v) => { const r = el("div", "kv"); r.append(el("span", "k", k), el("span", "v", String(v))); box.append(r); };
  kv("問いの型", D.question_types[p.question_type] || p.question_type);
  kv("テーマ", paperDomains(p).map(label).join("、") || "確認中");
  const pairs = paperAnalysisPairs(p);
  if (pairs.length) kv("解析の組合せ", pairs.map(([a,b]) => `${label(a)} → ${label(b)}`).join("\n"));
  kv("対象集団", D.populations[p.population] || p.population);
  kv("デザイン", D.designs[p.design] || p.design);
  kv("分析単位", D.units[p.unit] || p.unit);
  kv("データの区分", CLASS_LABEL[p.data_class] || p.data_class);
  kv("データ源", (p.sources || []).join("、") || "特定不能");
  kv("解析データの年", yearRange(p));
  kv("効果推定値の報告", p.has_effect_estimate);
  kv("判定に使った本文", p.input_mode === "abstract_only" ? "題名・抄録のみ" : "全文（方法・結果）");
  if (p.review) kv("テーマの確認", `${p.review.reviewer}: ${p.review.evidence}`);
  if (p.cited_by_count != null) kv("被引用数（OpenAlex）", p.cited_by_count);
  d.append(box);
  if (p.links?.length && !(state.tab === "links" && lsim.seed === p.paper_id)) { const lb = el("button", "survey-jump", "この論文を起点につながりを見る →"); lb.onclick = () => openLinks(p.paper_id); d.append(lb); }
  d.append(el("p", "muted small", "分類は Jev（TypeSafe System One）による機械判定で、人手の確認前です。結果の数値は収載していません。原著で確認してください。"));
}
function renderList() {
  const box = $("#listpane"); box.innerHTML = "";
  const rows = filteredPapers();
  $("#listcount").textContent = `${rows.length} 論文`;
  if (!rows.length) {
    const e = el("div", "empty");
    e.append(el("p", "big", "現在の検索条件に一致する登録がありません"));
    e.append(el("p", "muted small", "これは「この組合せの研究が存在しない」という意味ではありません。収載範囲と確認状態を確かめてください。"));
    box.append(e); return;
  }
  rows.forEach(p => {
    const c = el("article", "card" + (state.listSel === p.paper_id ? " on" : ""));
    const t = paperTitle(p);
    if (p.title_is_filename) t.append(el("span", "warn", "書誌未整備"));
    c.append(t, el("div", "m", [p.first_author_full || p.first_author, p.journal, p.year].filter(Boolean).join(" · ")));
    const pr = el("div", "paper-topics");
    paperDomains(p).forEach(domain => {const topic = el("span", "tag", label(domain)); topic.style.background = colorOf(domain) + "22"; pr.append(topic);});
    if (!paperDomains(p).length) pr.append(el("span", "tag", "テーマ確認中"));
    c.append(pr);
    const m2 = el("div", "m2");
    m2.append(el("span", "tag", ({association:"関連の検討",multi_factor_exploratory:"複数要因の探索",descriptive_prevalence:"実態の記述",trend:"推移の検討",geographic_variation:"地域差の検討",policy_evaluation:"制度・出来事の評価",scale_validation:"尺度の検証",methodological:"方法の検討",other:"その他"})[p.question_type] || D.question_types[p.question_type] || p.question_type));
    m2.append(el("span", "tag cls-" + p.data_class, CLASS_LABEL[p.data_class] || p.data_class));
    (p.sources || []).forEach(x => m2.append(el("span", "tag", x)));
    m2.append(el("span", "tag", "データ " + yearRange(p)));
    const ft = String(p.input_mode || "").startsWith("fulltext");
    m2.append(el("span", "badge " + (ft ? "ok" : "machine"), ft ? "全文で判定" : "抄録で判定"));
    c.append(m2);
    const info=el("button","paper-details","データ情報を見る");
    info.onclick = () => { state.listSel = p.paper_id; state.sel = null; state.selEdge = null; refresh(); };
    c.append(info);
    if (p.links?.length) { const ln = el("button", "paper-details", "つながりを見る"); ln.onclick = () => openLinks(p.paper_id); c.append(ln); }
    box.append(c);
  });
}
function renderData() {
  const box = $("#datapane"); box.innerHTML = "";
  const sec = (t) => { const h = el("h3", null, t); box.append(h); };
  const kv = (p, k, v) => { const r = el("div", "kv"); r.append(el("span", "k", k), el("span", "v", String(v))); p.append(r); };
  const all = D.papers.filter(p => p.doc_kind === "paper");
  const count = (f, dict) => { const c = {}; all.forEach(p => { const k = f(p); c[k] = (c[k] || 0) + 1; }); const t = el("div", "kvs");
    Object.entries(c).sort((a, b) => b[1] - a[1]).forEach(([k, n]) => kv(t, dict ? (dict[k] || k) : k, n)); box.append(t); };
  sec("収集と判定");
  const t1 = el("div", "kvs");
  kv(t1, "検索で集めた論文（重複除く）", D.meta.n_collected);
  kv(t1, "1回目の判定で候補になった論文", D.meta.n_candidates);
  kv(t1, "収載した論文（A・B・併用）", D.meta.n_papers);
  kv(t1, "全文（方法・結果）で判定した論文", all.filter(p => String(p.input_mode).startsWith("fulltext")).length);
  kv(t1, "題名・抄録だけで判定した論文", all.filter(p => p.input_mode === "abstract_only").length);
  kv(t1, "テーマの円から閲覧できる論文", all.filter(p => paperDomains(p).length).length);
  kv(t1, "解析の組合せがある論文", new Set(Object.values(D.pairs).flat()).size);
  kv(t1, "参考文献を取得できた論文（OpenAlex）", D.paper_links_meta?.n_with_references ?? "-");
  box.append(t1);
  sec("データの区分"); count(p => p.data_class, CLASS_LABEL);
  sec("データ源（1本が複数に数えられる）");
  const ts = el("div", "kvs"); D.sources.forEach(x => kv(ts, x, all.filter(p => (p.sources || []).includes(x)).length)); kv(ts, "特定不能", all.filter(p => !(p.sources || []).length).length); box.append(ts);
  sec("問いの型"); count(p => p.question_type, D.question_types);
  sec("デザイン"); count(p => p.design, D.designs);
  sec("分析単位"); count(p => p.unit, D.units);
  sec("対象集団"); count(p => p.population, D.populations);
  sec("方法");
  box.append(el("p", "small", D.meta.method_note));
  sec("空白の読み方");
  box.append(el("p", "small", D.meta.empty_cell_label));
  sec("謝辞");
  box.append(el("p", "small", D.meta.acknowledgement));
}
/* ---------- データ源と年 ---------- */
function renderSourceYears() {
  const box = $("#survey-root"); box.replaceChildren();
  box.append(el("h2", null, "データ源と年"), el("p", "panel-desc", "各論文が解析したデータの年の範囲を、データ源ごとに重ねた図です。色が濃いほど、その年のデータを使った論文が多いことを示します。セルを押すと、そのデータ源と年で論文一覧を絞り込みます。"));
  const papers = D.papers.filter(p => p.doc_kind === "paper" && (!state.cls || p.data_class === state.cls));
  const ys = papers.flatMap(p => p.year_start ? [p.year_start, p.year_end] : []);
  if (!ys.length) { box.append(el("div", "empty", "年の記載がある論文がありません。")); return; }
  const y0 = Math.max(1950, Math.min(...ys)), y1 = Math.max(...ys);
  const rows = [...D.sources, "特定不能"].map(src => {
    const ps = papers.filter(p => src === "特定不能" ? !(p.sources || []).length : (p.sources || []).includes(src));
    const cnt = {}; ps.forEach(p => { if (!p.year_start) return; for (let y = Math.max(y0, p.year_start); y <= p.year_end; y++) cnt[y] = (cnt[y] || 0) + 1; });
    return {src, n: ps.length, cnt, noYear: ps.filter(p => !p.year_start).length};
  }).filter(r => r.n);
  const max = Math.max(1, ...rows.flatMap(r => Object.values(r.cnt)));
  const scroll = el("div", "matrix-scroll"), table = el("table", "relation-matrix sy-matrix");
  const hr = el("tr"); hr.append(el("th", null, "データ源 ↓ / 年 →"));
  for (let y = y0; y <= y1; y++) { const th = el("th", "sy-y", y % 5 === 0 ? String(y) : ""); th.title = y + "年"; hr.append(th); }
  hr.append(el("th", null, "論文数")); const thead = el("thead"); thead.append(hr); table.append(thead);
  const tb = el("tbody");
  rows.forEach(r => {
    const tr = el("tr"); const th = el("th", null, r.src); th.scope = "row"; tr.append(th);
    for (let y = y0; y <= y1; y++) {
      const v = r.cnt[y] || 0, td = el("td", "sy-c");
      if (v) { td.style.background = `rgba(59,154,178,${(0.12 + 0.85 * Math.sqrt(v / max)).toFixed(3)})`; td.title = `${r.src} ${y}年: ${v} 論文`;
        td.onclick = () => { state.study = r.src === "特定不能" ? "" : r.src; state.wave = String(y); $("#paper-study").value = state.study; ensureYearOption(y); $("#paper-wave").value = state.wave; openPaperList(); }; }
      tr.append(td);
    }
    tr.append(el("td", "sy-n", `${r.n}${r.noYear ? `（年不明 ${r.noYear}）` : ""}`)); tb.append(tr);
  });
  table.append(tb); scroll.append(table); box.append(scroll);
  box.append(el("p", "muted small", "年はJevが本文から判定した「解析に用いたデータの最初の年と最後の年」で、途中の年はすべて使ったものとして塗っています。人手の確認前です。"));
}
function ensureYearOption(y) { if (![...$("#paper-wave").options].some(o => o.value === String(y))) { const o = el("option", null, String(y)); o.value = String(y); $("#paper-wave").append(o); } }
function syncSelection(g) {
  if (state.selEdge) state.selEdge = g.edges.find(e => e.s === state.selEdge.s && e.t === state.selEdge.t) || null;
  if (state.sel && !g.nodes.some(n => n.id === state.sel)) state.sel = null;
  if (state.listSel && !g.papers.some(p => p.paper_id === state.listSel)) state.listSel = null;
}
function refresh(relayout) {
  const g = renderStats(); syncSelection(g); renderGroups(); renderSearchSummary(g);
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === state.tab));
  document.body.classList.toggle("survey-mode",state.tab==="survey");
  document.querySelector(".control-console").hidden=state.tab==="links";
  ["map", "matrix", "survey", "list", "links", "data"].forEach(t => $("#pane-" + t).style.display = state.tab === t ? "" : "none");
  if (state.tab === "map") { if (relayout !== false) layout(g, true); renderUnmappedPapers(g); }
  if (state.tab === "list") renderList();
  if (state.tab === "data") renderData();
  if (state.tab === "matrix") renderMatrix();
  if (state.tab === "links") { renderLinks(); if (!lsim.nodes.length && lsim.seed) buildLinkGraph(); }
  if (state.tab === "survey") renderSourceYears();
  renderDetail();
}

window.addEventListener("DOMContentLoaded", () => {
  cv = $("#cv"); ctx = cv.getContext("2d");
  const ys=D.papers.flatMap(p=>p.year_start?[p.year_start,p.year_end]:[]);
  for(let y=Math.max(...ys);y>=Math.max(1950,Math.min(...ys));y--){const o=el("option",null,y+"年");o.value=String(y);$("#paper-wave").append(o);}
  D.sources.forEach(x=>{const o=el("option",null,x);o.value=x;$("#paper-study").append(o);});
  $("#paper-class").onchange=e=>{state.cls=e.target.value;refresh(true);};
  $("#paper-study").onchange=e=>{state.study=e.target.value;refresh(true);};
  $("#paper-wave").onchange=e=>{state.wave=e.target.value;refresh(true);};
  $("#export-svg").onclick=exportMapSVG;
  $("#export-papers").onclick=exportPapers;
  const readViewHash=()=>{const [t,params=""]=location.hash.slice(1).split("?");if(["map","matrix","survey","list","links","data"].includes(t)){state.tab=t;const pid=new URLSearchParams(params).get("paper");if(t==="links"&&pid&&paperById[pid]){lsim.seed=pid;state.listSel=pid;lsim.nodes=[];}const id=new URLSearchParams(params).get("domain");if(t==="map"&&id&&Object.hasOwn(D.domains,id)){state.sel=id;state.selEdge=null;}}};
  window.addEventListener("hashchange",()=>{readViewHash();refresh(state.tab==="map");});
  readViewHash();
  $("#q").placeholder = "タイトル・著者名・誌名／略称・DOI・領域";
  $("#q").oninput = e => { state.q = e.target.value; refresh(true); };
  $("#minp").oninput = e => { state.minPapers = +e.target.value; $("#minplabel").textContent = e.target.value; refresh(true); };
  $("#verified").onchange = e => { state.verified = e.target.checked; refresh(true); };
  $("#reset").onclick = () => { state.q = ""; $("#q").value = ""; state.groups.clear(); state.minPapers = 1; $("#minp").value = 1; $("#minplabel").textContent = "1"; state.verified = false; $("#verified").checked = false; state.study=state.wave=state.cls="";$("#paper-study").value=$("#paper-wave").value=$("#paper-class").value="";state.listSel=null;state.sel = state.selEdge = null; refresh(true); };
  document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => { state.tab = b.dataset.tab; if(state.tab!=="survey")history.replaceState(null,"","#"+state.tab);refresh(state.tab === "map"); });
  $("#zin").onclick = () => { sim.k *= 1.25; };
  $("#zout").onclick = () => { sim.k /= 1.25; };
  $("#zfit").onclick = () => { fit(); };
  let drag = null, pan = null;
  cv.addEventListener("mousedown", ev => {
    const r = cv.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
    const n = hit(mx, my);
    if (n) { drag = n; n.fixed = true; } else pan = { x: ev.clientX, y: ev.clientY, tx: sim.tx, ty: sim.ty };
  });
  window.addEventListener("mousemove", ev => {
    if (drag) { const r = cv.getBoundingClientRect(); const p = toWorld(ev.clientX - r.left, ev.clientY - r.top); drag.x = p.x; drag.y = p.y; sim.running = Math.max(sim.running, 40); }
    else if (pan) { sim.tx = pan.tx + (ev.clientX - pan.x); sim.ty = pan.ty + (ev.clientY - pan.y); }
  });
  window.addEventListener("mouseup", () => { if (drag) drag.fixed = false; drag = null; pan = null; });
  cv.addEventListener("click", ev => {
    const r = cv.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
    const n = hit(mx, my);
    if (n) { state.sel = state.sel === n.id ? null : n.id; state.selEdge = null; }
    else {
      const p = toWorld(mx, my);
      let best = null, bd = 7 / sim.k;
      sim.edges.forEach(e => {
        if (e.a === e.b) return;
        const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y, L2 = dx * dx + dy * dy;
        let t = ((p.x - e.a.x) * dx + (p.y - e.a.y) * dy) / L2; t = Math.max(0, Math.min(1, t));
        const d = Math.hypot(p.x - (e.a.x + t * dx), p.y - (e.a.y + t * dy));
        if (d < bd) { bd = d; best = e; }
      });
      if (best) { state.selEdge = best; state.sel = null; } else { state.sel = null; state.selEdge = null; }
    }
    renderDetail(); draw();
  });
  cv.addEventListener("wheel", ev => {
    ev.preventDefault();
    const r = cv.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
    const before = toWorld(mx, my);
    sim.k *= ev.deltaY < 0 ? 1.1 : 1 / 1.1;
    sim.k = Math.max(0.2, Math.min(5, sim.k));
    const after = toWorld(mx, my);
    sim.tx += (after.x - before.x) * sim.k; sim.ty += (after.y - before.y) * sim.k;
  }, { passive: false });
  $("#foot").textContent = `日本の公開データ研究マップ ｜ ${D.meta.n_papers}論文 ｜ 分類は機械判定（人手確認前） ｜ 関連の線は因果関係を示しません。 ｜ ${D.meta.acknowledgement}`;
  const g = renderStats(); layout(g, false); refresh(false); tick();
});


function downloadFile(name,text,type) {
  const url=URL.createObjectURL(new Blob([text],{type}));
  const a=el("a");a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);
}
function csvCell(v) {const s=String(v??"");return '"'+(/^[=+@-]/.test(s)?"'":"")+s.replace(/"/g,'""')+'"';}
function exportPapers() {
  const rows=[["タイトル","著者","誌名","出版年","区分","データ源","データの年","問いの型","デザイン","分析単位","テーマ","解析の組合せ","判定に使った本文","DOI","PMID"],...filteredPapers().map(p=>[p.title,paperAuthors(p).join("; "),p.journal,p.year,CLASS_LABEL[p.data_class]||p.data_class,(p.sources||[]).join(" / "),yearRange(p),D.question_types[p.question_type]||p.question_type,D.designs[p.design]||p.design,D.units[p.unit]||p.unit,paperDomains(p).map(label).join(" / "),paperAnalysisPairs(p).map(([a,b])=>`${label(a)} → ${label(b)}`).join(" / "),p.input_mode,p.doi,p.pmid])];
  downloadFile("opendata-map-papers.csv","\uFEFF"+rows.map(r=>r.map(csvCell).join(",")).join("\r\n"),"text/csv;charset=utf-8");
}
function renderMatrix() {
  const box=$("#matrixpane");box.replaceChildren();const g=buildGraph();
  box.append(el("h2",null,"曝露 × アウトカム"),el("p","panel-desc","各セルは登録された解析の組合せの論文数です。行が曝露、列がアウトカム。テーマ名からは、線のない論文も含む全論文を開けます。"));
  box.append(el("p","muted small","空欄は解析の組合せが未確認、または線の最小論文数に満たない箇所です。テーマの共起や因果関係を示す行列ではありません。"));
  if(!g.nodes.length){box.append(el("div","empty",g.unmapped.length ? `テーマ未分類の${g.unmapped.length}論文は、論文一覧から閲覧できます。` : "この条件に一致する論文がありません。"));const list=el("button","survey-jump","論文一覧で見る →");list.onclick=openPaperList;box.append(list);return;}
  const domains=g.nodes.sort((a,b)=>b.n-a.n).map(n=>n.id);const edges=Object.fromEntries(g.edges.map(e=>[e.s+"|"+e.t,e]));
  const scroll=el("div","matrix-scroll");const table=el("table","relation-matrix");table.setAttribute("aria-label","登録された曝露とアウトカム別の論文数");
  const thead=el("thead");const hr=el("tr");const corner=el("th",null,"曝露 ↓ / アウトカム →");hr.append(corner);
  domains.forEach(d=>{const th=el("th");const btn=el("button","matrix-domain",`${label(d)}（${g.nodes.find(n=>n.id===d).n}論文）`);btn.onclick=()=>openDomain(d,true);th.append(btn);th.scope="col";th.style.borderTopColor=colorOf(d);hr.append(th);});thead.append(hr);table.append(thead);
  const tbody=el("tbody");domains.forEach(a=>{const tr=el("tr");const th=el("th",null,label(a));th.scope="row";tr.append(th);domains.forEach(b=>{const td=el("td");const e=edges[a+"|"+b];if(e){const btn=el("button",null,String(e.n));btn.style.background=`rgba(59,154,178,${Math.min(.85,.16+Math.log2(e.n+1)*.13)})`;btn.style.color=e.n>3?"white":"#1f5f6e";btn.setAttribute("aria-label",`${label(a)}から${label(b)}、${e.n}論文`);btn.onclick=()=>{state.sel=null;state.selEdge=e;renderDetail();};td.append(btn);}else{td.textContent="·";td.title="解析の組合せが未確認、または線の最小論文数未満";}tr.append(td);});tbody.append(tr);});table.append(tbody);scroll.append(table);box.append(scroll);
}
function exportMapSVG() {
  const esc=v=>String(v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&apos;"}[c]));
  if(!sim.nodes.length)return;
  const minX=Math.min(...sim.nodes.map(n=>n.x))-140,maxX=Math.max(...sim.nodes.map(n=>n.x))+140;
  const minY=Math.min(...sim.nodes.map(n=>n.y))-100,maxY=Math.max(...sim.nodes.map(n=>n.y))+100;
  let svg=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${minX} ${minY-60} ${maxX-minX} ${maxY-minY+100}" width="1800" role="img"><title>日本の公開データ研究マップ 概念マップ</title><rect x="${minX}" y="${minY-60}" width="${maxX-minX}" height="${maxY-minY+100}" fill="#ffffff"/><g font-family="sans-serif">`;
  svg+=`<text x="${minX+20}" y="${minY-25}" font-size="22" font-weight="700">日本の公開データ研究マップ</text>`;
  sim.edges.forEach(e=>{const attr=`fill="none" stroke="${colorOf(e.s)}" stroke-opacity=".35" stroke-width="${Math.min(7,.7+Math.log2(e.n+1)*1.5)}"`;svg+=e.s===e.t?`<circle cx="${e.a.x+14}" cy="${e.a.y-14}" r="13" ${attr}/>`:`<line x1="${e.a.x}" y1="${e.a.y}" x2="${e.b.x}" y2="${e.b.y}" ${attr}/>`;});
  sim.nodes.forEach(n=>{svg+=`<circle cx="${n.x}" cy="${n.y}" r="${rad(n)}" fill="${colorOf(n.id)}"/><text x="${n.x}" y="${n.y-rad(n)-9}" text-anchor="middle" font-size="13" paint-order="stroke" stroke="#ffffff" stroke-width="4" stroke-linejoin="round" fill="#2f3437">${esc(label(n.id))} (${n.n})</text>`;});
  svg+=`<text x="${minX+20}" y="${maxY+10}" font-size="11">円はテーマの全論文、線は登録された解析の論文数。因果を意味しません。データ源 ${esc(state.study||"すべて")} / データの年 ${esc(state.wave||"すべて")}</text></g></svg>`;
  downloadFile("opendata-map.svg",svg,"image/svg+xml;charset=utf-8");
}

/* ---------- 論文のつながり（Connected Papers 型） ----------
   近さは build 時に計算済み（scripts/paper_links.py）。参考文献の重なり（OpenAlex）と本文確認したテーマの重なりの目安であり、
   影響関係や因果を意味しない。円の色は出版年、大きさは OpenAlex の被引用数。 */
const _cssCache = {};
function cssVar(name, fallback) {
  const key = (document.documentElement.dataset.theme || "light") + name;
  if (!(key in _cssCache)) _cssCache[key] = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return _cssCache[key] || fallback;
}
const lsim = { nodes: [], edges: [], byId: {}, tx: 0, ty: 0, k: 1, running: 0, seed: null, hover: null };
let lcv, lctx;
const linkPapers = D.papers.filter(p => p.doc_kind === "paper");
const PAPER_YEARS = linkPapers.map(p => p.year).filter(Boolean);
const Y_MIN = Math.min(...PAPER_YEARS), Y_MAX = Math.max(...PAPER_YEARS);
const YEAR_RAMP = ["#3A9AB2","#6FB2C1","#91BAB6","#A5C2A3","#BDC881","#DCCB4E","#E3B710","#E79805","#EC7A05","#EF5703","#F11B00"];  // wesanderson Zissou1Continuous
function yearColor(y) {  // Zissou1Continuous。古い論文ほど青、新しい論文ほど赤
  const t = y ? (y - Y_MIN) / Math.max(1, Y_MAX - Y_MIN) : 0, f = t * (YEAR_RAMP.length - 1), i = Math.min(YEAR_RAMP.length - 2, Math.floor(f)), u = f - i;
  const hx = h => [1, 3, 5].map(k => parseInt(h.slice(k, k + 2), 16)), a = hx(YEAR_RAMP[i]), b = hx(YEAR_RAMP[i + 1]);
  return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * u)).join(",")})`;
}
const shortRef = p => `${p.first_author || (p.first_author_full || "").split(" ").pop() || "?"} ${p.year || ""}`.trim();
function linkReason(l) {
  const [, , shared, themes, direct] = l, parts = [];
  if (shared) parts.push(`共通の参考文献 ${shared}件`);
  if (themes) parts.push(`共通テーマ ${themes}`);
  if (direct) parts.push("直接引用あり");
  return parts.join(" · ") || "収載論文からの共引用";
}
function openLinks(id) {
  state.tab = "links"; lsim.seed = id; state.listSel = id; state.sel = state.selEdge = null;
  history.replaceState(null, "", "#links?paper=" + encodeURIComponent(id));
  buildLinkGraph(); refresh(false);
}
function buildLinkGraph() {
  const seed = paperById[lsim.seed];
  if (!seed) { lsim.nodes = []; lsim.edges = []; return; }
  const seedIdx = D.papers.indexOf(seed);
  const ids = [seedIdx, ...(seed.links || []).map(l => l[0])];
  const set = new Set(ids);
  const w = lcv?.clientWidth || 800, h = lcv?.clientHeight || 600;
  lsim.nodes = ids.map((i, k) => {
    const p = D.papers[i], ang = k * 2.399963, r = k ? 120 + 8 * k : 0;
    return { i, id: p.paper_id, p, x: w / 2 + r * Math.cos(ang), y: h / 2 + r * Math.sin(ang), vx: 0, vy: 0, seed: k === 0 };
  });
  lsim.byId = Object.fromEntries(lsim.nodes.map(n => [n.i, n]));
  const seen = new Set(); lsim.edges = [];
  ids.forEach(i => (D.papers[i].links || []).forEach(l => {
    if (!set.has(l[0])) return;
    const key = i < l[0] ? i + "|" + l[0] : l[0] + "|" + i;
    if (seen.has(key)) return; seen.add(key);
    const isSeedEdge = i === seedIdx || l[0] === seedIdx;
    if (!isSeedEdge && l[1] < 250) return;  // 周辺どうしは近さ25以上だけ結ぶ（線の絡まりを防ぐ）
    lsim.edges.push({ a: lsim.byId[i], b: lsim.byId[l[0]], s: l[1] / 1000, seed: isSeedEdge });
  }));
  lsim.running = 320; lsim.k = 1; lsim.tx = 0; lsim.ty = 0;
}
function lstep() {
  const N = lsim.nodes; if (!N.length) return;
  const cx = (lcv.clientWidth || 800) / 2, cy = (lcv.clientHeight || 600) / 2;
  for (let a = 0; a < N.length; a++) for (let b = a + 1; b < N.length; b++) {
    const A = N[a], B = N[b]; let dx = B.x - A.x, dy = B.y - A.y, d2 = dx * dx + dy * dy + 0.01, d = Math.sqrt(d2);
    const f = 2600 / d2; A.vx -= f * dx / d; A.vy -= f * dy / d; B.vx += f * dx / d; B.vy += f * dy / d;
  }
  lsim.edges.forEach(e => {
    const len = 70 + 260 * (1 - Math.min(1, e.s / 0.7));
    const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y, d = Math.hypot(dx, dy) || 1, f = (d - len) * 0.012 * (0.4 + e.s);
    e.a.vx += f * dx / d; e.a.vy += f * dy / d; e.b.vx -= f * dx / d; e.b.vy -= f * dy / d;
  });
  N.forEach(n => {
    if (n.seed) { n.x += (cx - n.x) * 0.2; n.y += (cy - n.y) * 0.2; n.vx = n.vy = 0; return; }
    if (n.fixed) { n.vx = n.vy = 0; return; }
    n.vx += (cx - n.x) * 0.002; n.vy += (cy - n.y) * 0.002;
    n.vx *= 0.82; n.vy *= 0.82; n.x += Math.max(-12, Math.min(12, n.vx)); n.y += Math.max(-12, Math.min(12, n.vy));
  });
}
const lrad = n => 6 + Math.sqrt(n.p.cited_by_count || 0) * 1.6 + (n.seed ? 4 : 0);
const ltoWorld = (mx, my) => ({ x: (mx - lsim.tx) / lsim.k, y: (my - lsim.ty) / lsim.k });
function lhit(mx, my) { const p = ltoWorld(mx, my); return [...lsim.nodes].reverse().find(n => Math.hypot(n.x - p.x, n.y - p.y) <= lrad(n) + 3); }
function ldraw() {
  if (!lcv) return;
  const w = lcv.clientWidth, h = lcv.clientHeight;
  if (lcv.width !== Math.round(w * dpr) || lcv.height !== Math.round(h * dpr)) { lcv.width = Math.round(w * dpr); lcv.height = Math.round(h * dpr); }
  lctx.setTransform(dpr, 0, 0, dpr, 0, 0); lctx.clearRect(0, 0, w, h);
  lctx.save(); lctx.translate(lsim.tx, lsim.ty); lctx.scale(lsim.k, lsim.k);
  const sel = state.listSel, ink = cssVar("--canvas-ink", "#2f3437"), rose = cssVar("--accent-hl", "#F21A00");
  lsim.edges.forEach(e => {
    const on = sel && sel !== lsim.seed && (e.a.id === sel || e.b.id === sel);
    lctx.beginPath(); lctx.moveTo(e.a.x, e.a.y); lctx.lineTo(e.b.x, e.b.y);
    lctx.strokeStyle = on ? rose : cssVar("--canvas-edge", "#9aa7ad");
    lctx.globalAlpha = on ? 0.8 : 0.12 + 0.5 * Math.min(1, e.s / 0.6); lctx.lineWidth = (0.6 + 3 * Math.min(1, e.s / 0.6)) / Math.sqrt(lsim.k);
    lctx.stroke();
  });
  lctx.globalAlpha = 1;
  lsim.nodes.forEach(n => {
    lctx.beginPath(); lctx.arc(n.x, n.y, lrad(n), 0, Math.PI * 2);
    lctx.fillStyle = yearColor(n.p.year); lctx.fill();
    lctx.lineWidth = (n.seed || n.id === sel ? 3 : 1) / Math.sqrt(lsim.k);
    lctx.strokeStyle = n.seed ? rose : n.id === sel ? ink : cssVar("--canvas-node-edge", "#ffffff"); lctx.stroke();
  });
  const fs = Math.max(10, Math.min(12.5, 11.5 / lsim.k));
  lctx.font = `${fs}px ${cssVar("--font-base", "sans-serif")}`; lctx.textAlign = "center"; lctx.textBaseline = "top";
  lsim.nodes.forEach(n => {
    const txt = shortRef(n.p), tw = lctx.measureText(txt).width, y = n.y + lrad(n) + 3;
    lctx.fillStyle = cssVar("--canvas-label-bg", "rgba(255,255,255,.9)"); lctx.fillRect(n.x - tw / 2 - 3, y - 1, tw + 6, fs + 3);
    lctx.fillStyle = n.seed ? rose : ink; lctx.font = `${n.seed ? "700 " : ""}${fs}px ${cssVar("--font-base", "sans-serif")}`; lctx.fillText(txt, n.x, y);
  });
  lctx.restore();
}
function lfit() {
  if (!lsim.nodes.length || !lcv) return;
  const xs = lsim.nodes.map(n => n.x), ys = lsim.nodes.map(n => n.y), w = lcv.clientWidth, h = lcv.clientHeight;
  const bw = Math.max(1, Math.max(...xs) - Math.min(...xs)) + 120, bh = Math.max(1, Math.max(...ys) - Math.min(...ys)) + 120;
  lsim.k = Math.max(0.3, Math.min(1.6, Math.min(w / bw, h / bh)));
  lsim.tx = w / 2 - lsim.k * (Math.min(...xs) + Math.max(...xs)) / 2; lsim.ty = h / 2 - lsim.k * (Math.min(...ys) + Math.max(...ys)) / 2;
}
function ltick() {
  if (state.tab === "links") { if (lsim.running > 0) { lstep(); lsim.running--; if (lsim.running % 20 === 0) lfit(); } ldraw(); }
  requestAnimationFrame(ltick);
}
function renderLinks() {
  const legend = $("#links-legend"), list = $("#link-list"), seed = paperById[lsim.seed];
  const meta = D.paper_links_meta || {};
  legend.replaceChildren();
  const yl = el("div", "legend-years");
  yl.append(el("span", null, `${Y_MIN}`), Object.assign(el("span", "legend-ramp"), { style: `background:linear-gradient(90deg,${YEAR_RAMP.join(",")})` }), el("span", null, `${Y_MAX}年`));
  legend.append(yl, el("p", null, "円の色は出版年、大きさは被引用数（OpenAlex）。線が太く近いほど、参考文献やテーマの重なりが大きい論文です。影響関係や因果は示しません。"));
  list.replaceChildren();
  if (!seed) {
    list.append(el("p", "muted", "起点にする論文を上の欄で探すか、論文一覧の「つながりを見る」から開いてください。"));
    const picks = [...linkPapers].filter(p => p.cited_by_count != null).sort((a, b) => (b.cited_by_count || 0) - (a.cited_by_count || 0)).slice(0, 12);
    list.append(el("h4", "sub-h", "被引用数の多い論文から始める"));
    picks.forEach(p => { const b = el("button", "link-row"); b.append(el("span", "lr-t", p.title), el("span", "lr-m", `${shortRef(p)} · 被引用 ${p.cited_by_count}`)); b.onclick = () => openLinks(p.paper_id); list.append(b); });
    return;
  }
  const head = el("div", "link-seed-card");
  head.append(el("span", "lr-k", "起点"), paperTitle(seed, "paper-title"), el("div", "m", [shortRef(seed), seed.journal, seed.cited_by_count != null ? `被引用 ${seed.cited_by_count}` : null].filter(Boolean).join(" · ")));
  if (seed.link_basis === "themes") head.append(el("p", "muted small", "この論文は参考文献を取得できなかったため、テーマの重なりだけで近さを計算しています。"));
  list.append(head, el("h4", "sub-h", `近い論文 ${(seed.links || []).length}本`));
  (seed.links || []).forEach(l => {
    const p = D.papers[l[0]], row = el("div", "link-row" + (state.listSel === p.paper_id ? " on" : ""));
    const t = el("button", "lr-t", p.title); t.onclick = () => { state.listSel = p.paper_id; renderDetail(); renderLinks(); };
    const re = el("button", "lr-go", "起点にする"); re.onclick = () => openLinks(p.paper_id);
    row.append(t, el("span", "lr-m", `${shortRef(p)} · 近さ ${(l[1] / 10).toFixed(0)} · ${linkReason(l)}`), re);
    list.append(row);
  });
  list.append(el("p", "muted small", `近さ（0〜100）は、参考文献の重なり・直接引用・共引用（${meta.source || "OpenAlex"}、${(meta.fetched_at || "").slice(0, 10)}取得）と、本文確認したテーマの重なりから計算した目安です。参考文献を取得できた論文 ${meta.n_with_references ?? "-"}本、テーマだけで結んだ論文 ${meta.n_theme_only ?? "-"}本。`));
}
function setupLinks() {
  lcv = $("#lcv"); if (!lcv) return; lctx = lcv.getContext("2d");
  const q = $("#link-q"), sug = $("#link-suggest");
  q.oninput = () => {
    const v = q.value.trim(); sug.replaceChildren();
    if (!v) { sug.hidden = true; return; }
    const hits = linkPapers.filter(p => paperQueryMatches(p, v)).slice(0, 8);
    hits.forEach(p => { const b = el("button", null); b.append(el("span", "lr-t", p.title), el("span", "lr-m", shortRef(p))); b.onclick = () => { q.value = ""; sug.hidden = true; openLinks(p.paper_id); }; sug.append(b); });
    if (!hits.length) sug.append(el("p", "muted small", "一致する論文がありません"));
    sug.hidden = false;
  };
  let drag = null, pan = null, moved = false;
  lcv.addEventListener("mousedown", ev => { const r = lcv.getBoundingClientRect(); const n = lhit(ev.clientX - r.left, ev.clientY - r.top); moved = false; if (n && !n.seed) { drag = n; n.fixed = true; } else pan = { x: ev.clientX, y: ev.clientY, tx: lsim.tx, ty: lsim.ty }; });
  window.addEventListener("mousemove", ev => {
    if (drag) { const r = lcv.getBoundingClientRect(), p = ltoWorld(ev.clientX - r.left, ev.clientY - r.top); drag.x = p.x; drag.y = p.y; moved = true; lsim.running = Math.max(lsim.running, 30); }
    else if (pan) { lsim.tx = pan.tx + ev.clientX - pan.x; lsim.ty = pan.ty + ev.clientY - pan.y; moved = true; }
  });
  window.addEventListener("mouseup", () => { if (drag) drag.fixed = false; drag = null; pan = null; });
  lcv.addEventListener("click", ev => { if (moved) return; const r = lcv.getBoundingClientRect(), n = lhit(ev.clientX - r.left, ev.clientY - r.top); if (n) { state.listSel = n.id; renderDetail(); renderLinks(); } });
  lcv.addEventListener("dblclick", ev => { const r = lcv.getBoundingClientRect(), n = lhit(ev.clientX - r.left, ev.clientY - r.top); if (n && !n.seed) openLinks(n.id); });
  lcv.addEventListener("wheel", ev => { ev.preventDefault(); const r = lcv.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top, before = ltoWorld(mx, my); lsim.k = Math.max(0.2, Math.min(5, lsim.k * (ev.deltaY < 0 ? 1.1 : 1 / 1.1))); const after = ltoWorld(mx, my); lsim.tx += (after.x - before.x) * lsim.k; lsim.ty += (after.y - before.y) * lsim.k; }, { passive: false });
  ltick();
}

/* ---------- 表示テーマ（ライト／ダーク） ---------- */
function applyTheme(t, save = true) {
  document.documentElement.dataset.theme = t;
  const b = $("#theme-toggle");
  if (b) { b.textContent = t === "dark" ? "ライトモード" : "ダークモード"; b.setAttribute("aria-pressed", String(t === "dark")); }
  if (save) try { localStorage.setItem("odmap-theme", t); } catch (e) {}
}
window.addEventListener("DOMContentLoaded", () => {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light", false);
  $("#theme-toggle")?.addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
  setupLinks();
});
