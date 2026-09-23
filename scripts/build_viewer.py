#!/usr/bin/env python3
"""structured_v3.jsonl から表示用データを作り、viewer/index.html（データ埋め込み・1ファイル）を書き出す。

収載: data_class が A / B / AB の論文。データ源への帰属は uses >= 0.5。
円と線は paper_map.py、論文のつながりは paper_links.py で作る。
線にする問いの型は association に加えて policy_evaluation（制度・出来事→アウトカム）とする。
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from paper_links import add_links  # noqa: E402
from paper_map import build_paper_map  # noqa: E402
from fetch_epmc import SOURCES  # noqa: E402

IN_SCOPE = {"A", "B", "AB"}
USE_THRESHOLD = 0.5
schema = json.loads((ROOT / "data/schema_od_v3.json").read_text(encoding="utf-8"))
recs = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data/records.jsonl").open(encoding="utf-8")}
first = [json.loads(l) for l in (ROOT / "data/jev_judgments.jsonl").open(encoding="utf-8")]
structured = [json.loads(l) for l in (ROOT / "data/structured_v3.jsonl").open(encoding="utf-8")]

# Europe PMC の保存分から全著者・誌名略称を引く
epmc = {}
for f in (ROOT / "data/epmc_cache").glob("*.json"):
    for r in json.loads(f.read_text(encoding="utf-8")):
        epmc.setdefault(r.get("pmid") or r.get("doi") or r["id"], r)


def authors_of(r):
    out = []
    for a in (r or {}).get("authorList", {}).get("author", []):
        if a.get("firstName") and a.get("lastName"):
            out.append({"given": a["firstName"], "family": a["lastName"], "name": f'{a["firstName"]} {a["lastName"]}'})
        elif a.get("collectiveName"):
            out.append({"given": "", "family": "", "name": a["collectiveName"]})
        elif a.get("fullName"):
            out.append({"given": a.get("initials", ""), "family": a.get("lastName", ""), "name": a["fullName"]})
    return out


def year(v):
    return int(v) if str(v).isdigit() else None


papers = []
for s in structured:
    if s["data_class"] not in IN_SCOPE:
        continue
    r = recs[s["id"]]
    e = epmc.get(s["id"], {})
    ad = authors_of(e)
    ys, ye = year(s["year_start"]), year(s["year_end"])
    if ys and ye and ys > ye:
        ys, ye = ye, ys
    if ys is None and ye is not None:
        ys = ye
    if ye is None and ys is not None:
        ye = ys
    doi = (r.get("doi") or "").lower() or None
    papers.append({
        "paper_id": f"doi:{doi}" if doi else f"pmid:{r['pmid']}" if r.get("pmid") else f"epmc:{r['id']}",
        "doc_kind": "paper", "title": r["title"].rstrip("."), "journal": r.get("journal"),
        "journal_abbreviation": ((e.get("journalInfo") or {}).get("journal") or {}).get("isoabbreviation"),
        "year": r.get("year"), "doi": doi, "pmid": r.get("pmid"),
        "article_url": f"https://doi.org/{doi}" if doi else (f"https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/" if r.get("pmid") else ""),
        "first_author": ad[0]["family"] if ad else None, "first_author_full": ad[0]["name"] if ad else None,
        "authors": [a["name"] for a in ad], "author_details": ad, "author_aliases": [], "search_aliases": [],
        "data_class": s["data_class"],
        "sources": sorted((k for k, p in s["uses"].items() if p >= USE_THRESHOLD), key=list(SOURCES).index),
        "year_start": ys, "year_end": ye,
        "question_type": s["question_type"], "design": s["design"], "population": s["population"], "unit": s["unit"],
        "exposure_domain": s["exposure_domain"], "outcome_domain": s["outcome_domain"],
        "exposure_conf": s["exposure_domain_conf"], "outcome_conf": s["outcome_domain_conf"],
        "tags": s["tags_yes_final"], "tags_uncertain": s["tags_uncertain"],
        "has_effect_estimate": s["has_effect_estimate"], "input_mode": s["input_mode"],
    })

# 線は association と policy_evaluation。paper_map は association だけを線にするので、型を読み替えて渡す
for p in papers:
    p["_qt"] = p["question_type"]
    if p["question_type"] == "policy_evaluation":
        p["question_type"] = "association"
reviews = json.loads((ROOT / "data/paper_reviews.json").read_text(encoding="utf-8"))
# Claude が提案し直し Jev が支持した新カテゴリ（統計調査・データ基盤、自然現象・地球科学）のタグ
nd3 = json.loads((ROOT / "data/new_domain_review_v3.json").read_text(encoding="utf-8"))
for p in papers:
    for k, prob in nd3["tags"].get(p["paper_id"], {}).items():
        if k in nd3["adopted"] and prob >= 0.5:
            p["tags"] = sorted(set(p["tags"]) | {k})
# concept_unmapped の解消（Jev の選択を Claude が題名・抄録と照合して採用したものだけ）
for x in json.loads((ROOT / "data/unmapped_resolution.json").read_text(encoding="utf-8")):
    if x["adopted"]:
        p = next(q for q in papers if q["paper_id"] == x["paper_id"])
        p[x["role"]] = x["pick"]
        p["tags"] = sorted(set(p["tags"]) | {x["pick"]})
# 線は Jev が「実際に解析した」と判定した組合せだけにする
followup = json.loads((ROOT / "data/jev_followup.json").read_text(encoding="utf-8"))
checked = {}
for c in followup["pair_checks"]:
    checked.setdefault(c["paper_id"], []).append(c)
for pid, cs in checked.items():
    rv = reviews.setdefault(pid, {})
    rv["analysis_pairs"] = [{"exposure": c["exposure"], "outcome": c["outcome"],
                             "evidence": f"Jev: analyzed (confidence {c['confidence']:.2f}, {c['input_mode']})"}
                            for c in cs if c["role"] == "analyzed"]
n_pairs_dropped = sum(1 for c in followup["pair_checks"] if c["role"] != "analyzed")
for p in papers:
    if "evidence" in reviews.get(p["paper_id"], {}):
        p["review"] = {k: reviews[p["paper_id"]][k] for k in ("evidence", "reviewer")}
pm = build_paper_map(papers, schema["domains"], reviews=reviews, separate_domains=["methodology_weighting", "official_statistics_infrastructure"])
for p in papers:
    p["question_type"] = p.pop("_qt")

# paper_links は ROOT/outputs/openalex_works.json を読むので、この案件の data/ を指す仮の root を渡す
link_root = ROOT / "data" / "_links_root"
(link_root / "outputs").mkdir(parents=True, exist_ok=True)
(link_root / "outputs/openalex_works.json").write_text((ROOT / "data/openalex_works.json").read_text(), encoding="utf-8")
links_meta = add_links(papers, link_root)

n_by_class = Counter(p["data_class"] for p in papers)
data = {
    "meta": {
        "n_papers": len(papers), "n_documents": len(papers), "n_collected": len(recs),
        "n_candidates": sum(1 for j in first if j["data_class"] in ("A", "B", "AB", "unclear")),
        "n_by_class": dict(n_by_class), "n_pairs_dropped": n_pairs_dropped,
        "acknowledgement": "本研究は JSPS 科研費 JP23K16359（若手研究「全自治体予測モデルによるCOVID-19流行下の自殺要因の分析」）の助成を受けたものです。",
        "empty_cell_label": "空欄は主分類の登録がないことを示す。副次解析まで確認した結果ではなく、その組合せの研究が存在しないという意味でもない。",
        "method_note": ("Europe PMC の本文を含む全文検索（データ源名 AND Japan）で集めた論文を、Jev（TypeSafe System One, jev-latest）で判定した。"
                        "1回目は題名・抄録で A/B 区分を判定し、候補について2回目にオープンアクセス論文は方法・結果の本文、それ以外は題名・抄録を渡して、"
                        "区分・データ源・データの年・問いの型・デザイン・対象・分析単位・主曝露・主アウトカム・領域タグを判定した。"
                        "テーマは65領域。線は、問いの型が関連の検討または制度・出来事の評価の論文について、主曝露→主アウトカムの組合せを実際に解析したと Jev が判定したものだけを残した。人手の確認前。"),
    },
    "domains": schema["domains"], "domain_labels": schema["domain_labels"], "display_groups": schema["display_groups"],
    "populations": schema["populations"], "designs": schema["designs"], "question_types": schema["question_type"],
    "units": schema["units"], "role_unresolved": schema["role_unresolved"],
    "sources": list(SOURCES), "scales": [], "survey_crosswalk": [],
    "papers": papers, "paper_links_meta": links_meta, **pm,
}
(ROOT / "viewer/data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

tpl = (ROOT / "scripts/viewer_template.html").read_text(encoding="utf-8")
blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
html = (tpl.replace("{{DATA}}", blob)
        .replace("{{STYLE}}", (ROOT / "viewer/style.css").read_text(encoding="utf-8"))
        .replace("{{WES}}", (ROOT / "viewer/wes_zissou.css").read_text(encoding="utf-8"))
        .replace("{{APP}}", (ROOT / "viewer/app.js").read_text(encoding="utf-8")))
(ROOT / "viewer/index.html").write_text(html, encoding="utf-8")
# Artifact 用: 公開時に doctype/head/body の骨組みが付くので、自前の骨組みを外した版を書く
import re  # noqa: E402
art = re.sub(r"^<!doctype html>\s*<html[^>]*><head>", "", html, flags=re.I)
art = re.sub(r'<meta charset="utf-8"><meta name="viewport"[^>]*>', "", art, count=1)
art = art.replace("</head>\n<body>", "", 1).replace("</body></html>", "")
# Artifact の画面ではファイル保存ができないため、保存ボタンを隠す（ローカル版 viewer/index.html では使える）
art = art.replace("<style>{{", "<style>{{", 1)  # placeholder
art = art.replace("</style>", "#export-svg,#export-papers{display:none!important}\n</style>", 1)
(ROOT / "output/dashboard.html").write_text(art, encoding="utf-8")
print(f"papers {len(papers)} {dict(n_by_class)} pairs {len(pm['pairs'])} unmapped {len(pm['unmapped_papers'])} "
      f"links {links_meta} html {len(html)//1024}KB")
