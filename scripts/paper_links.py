"""論文のつながり（Connected Papers 型）の近さを計算する。

約束:
- 近さは「参考文献の重なり（書誌結合）」「収載論文どうしの直接引用」「収載論文からの共引用」と
  「本文確認したテーマの重なり」から作る。共著者は使わない（ほぼ全論文に同じ著者が入るため）。
- 参考文献は OpenAlex（outputs/openalex_works.json）から取得したもの。DOIのない論文、参考文献が
  取得できなかった論文はテーマの重なりだけで結び、basis に "themes" と記録する。
- links は papers 配列の添字で持つ（公開用にIDを置換しても壊れず、データ量も抑える）。
- 近さは研究内容の類似の目安であり、因果・影響関係を意味しない。
"""
import json, math, pathlib

TOP_K = 25
W_CITE, W_THEME = 0.6, 0.4


def _norm_doi(pid):
    return pid[4:].lower() if pid.startswith("doi:") else None


def _themes(p):
    s = set(p.get("map_domains") or [])
    for k in ("exposure_domain", "outcome_domain"):
        if p.get(k): s.add(p[k])
    return s


def add_links(papers, root):
    path = pathlib.Path(root)/"outputs/openalex_works.json"
    oa = json.loads(path.read_text()) if path.exists() else {"works": {}}
    works = oa["works"]
    idx = [i for i, p in enumerate(papers) if p.get("doc_kind") == "paper"]
    info = {}
    for i in idx:
        w = works.get(_norm_doi(papers[i]["paper_id"]) or "")
        info[i] = {"refs": set(w["referenced_works"]) if w else set(),
                   "oa": w["openalex_id"] if w else None, "themes": _themes(papers[i])}
        papers[i]["cited_by_count"] = w.get("cited_by_count") if w else None
        papers[i]["openalex_id"] = w["openalex_id"] if w else None
    by_oa = {v["oa"]: i for i, v in info.items() if v["oa"]}
    # 収載論文から引用されている相手（共引用の計算用）
    cited_by_corpus = {i: set() for i in idx}
    for i, v in info.items():
        for r in v["refs"]:
            if r in by_oa: cited_by_corpus[by_oa[r]].add(i)

    for a in idx:
        A = info[a]; scored = []
        for b in idx:
            if a == b: continue
            B = info[b]
            inter = A["themes"] & B["themes"]; union = A["themes"] | B["themes"]
            theme = len(inter) / len(union) if union else 0.0
            if A["refs"] and B["refs"]:
                shared = len(A["refs"] & B["refs"])
                coupling = shared / math.sqrt(len(A["refs"]) * len(B["refs"]))
                direct = (B["oa"] in A["refs"]) or (A["oa"] in B["refs"])
                ca, cb = cited_by_corpus[a], cited_by_corpus[b]
                n_co = len(ca & cb)
                # 1本の論文から一緒に引用されただけでは近いと扱わない（件数で減衰）
                cocite = n_co / math.sqrt(len(ca) * len(cb)) * min(1.0, n_co / 3) if n_co else 0.0
                cite = min(1.0, 2 * coupling + 0.15 * direct + 0.5 * cocite)
                score = W_CITE * cite + W_THEME * theme
                basis = "citations"
            else:
                shared, direct, score, basis = 0, False, W_THEME * theme, "themes"
            if score > 0:
                scored.append((score, b, shared, len(inter), direct, basis))
        scored.sort(key=lambda t: (-t[0], t[1]))
        # [相手の添字, 近さ×1000, 共有参考文献数, 共有テーマ数, 直接引用(0/1)]
        papers[a]["links"] = [[b, round(s * 1000), sh, th, int(dr)] for s, b, sh, th, dr, _ in scored[:TOP_K]]
        papers[a]["link_basis"] = "citations" if A["refs"] else "themes"
    return {"source": "OpenAlex (https://openalex.org)", "fetched_at": oa.get("fetched_at"),
            "n_with_references": sum(1 for i in idx if info[i]["refs"]),
            "n_theme_only": sum(1 for i in idx if not info[i]["refs"]), "top_k": TOP_K}
