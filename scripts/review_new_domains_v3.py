#!/usr/bin/env python3
"""Claude が抄録で割り当てたテーマを Jev が支持しなかった4本について、Claude が提案し直した新カテゴリを判定する。

1. 4本について、候補概念の役割（main / secondary / background_only / absent / unknown）と、
   既存テーマとの関係（existing_domain / new_domain / insufficient_evidence）を判定する。
2. new_domain が多数の候補を採用し、収載論文すべてで「その候補が解析対象・主題か」を noul で判定する。
出力: data/new_domain_review_v3.json
"""
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".codex/skills/jev/scripts"))
import jev  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from structure_v2 import make_state  # noqa: E402

schema = json.loads((ROOT / "data/schema_od_v2.json").read_text(encoding="utf-8"))
CANDIDATES = {
    "official_statistics_infrastructure": ("統計調査・データ基盤",
        "政府統計調査やデータ資源そのものの方法と整備。調査の参加割合・非参加者の把握、レコードリンケージ、"
        "統計表・データベース・換算係数の構築、推計方法など。重み付け（IPW）や尺度の検証とは区別する"),
    "natural_phenomena": ("自然現象・地球科学",
        "地震・火山・気象などの自然現象そのものの観測・解析。健康や社会への影響を扱う研究（災害の影響、気象・環境曝露）とは区別する"),
}
TARGETS = ["doi:10.1103/physreve.86.046107", "doi:10.11236/jph.66.4_210",
           "doi:10.1371/journal.pone.0286169", "doi:10.3390/foods13070988"]
ROLE = {
    "main": "その概念を実際に測定・解析した主曝露・主アウトカム、または論文の主たる研究対象",
    "secondary": "副次的変数・媒介・効果修飾・層別要因として実際に解析している（調整のみではない）",
    "background_only": "背景・考察・引用で言及するだけ",
    "absent": "この概念は扱われていない",
    "unknown": "与えられた本文から判定できない",
}
FIT = {
    "existing_domain": "既存テーマの定義で意味も範囲も十分に表せる（新テーマは不要）",
    "new_domain": "既存テーマのどれにも収まらない独立した概念で、新テーマとして立てるべき",
    "insufficient_evidence": "判断材料が足りない",
}
recs = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data/records.jsonl").open(encoding="utf-8")}
pid2id = {}
for rid, r in recs.items():
    doi = (r.get("doi") or "").lower()
    pid2id[f"doi:{doi}" if doi else f"pmid:{r['pmid']}" if r.get("pmid") else f"epmc:{rid}"] = rid


def call(state, q):
    for attempt in range(5):
        try:
            return jev.call(state, q)["answers"]
        except (SystemExit, Exception) as e:  # noqa: BLE001
            err = e
            import time; time.sleep(4 * (attempt + 1))
    raise RuntimeError(err)


def stage1(pid):
    state, _ = make_state(recs[pid2id[pid]])
    q = {k: {"type": "choice", "criteria": ROLE, "instructions": (
        f"「{v[0]}」（定義: {v[1]}）が、この論文の目的と解析で果たす役割を、与えられた本文の事実だけで判断する。")}
         for k, v in CANDIDATES.items()}
    return pid, call(state, q)


def stage2(args):
    pid, c = args
    state, _ = make_state(recs[pid2id[pid]])
    state["candidate"] = {"label": CANDIDATES[c][0], "definition": CANDIDATES[c][1]}
    state["existing_domains"] = schema["domains"]
    q = {"fit": {"type": "choice", "criteria": FIT, "instructions": (
        "この論文で主題・副次として扱われている候補概念（stateのcandidate）は、existing_domains の定義のどれかで表せるか。"
        "名前が近くても定義の範囲に入らなければ new_domain を選ぶ。")}}
    return pid, c, call(state, q)


def tag_all(args):
    pid, keys = args
    state, _ = make_state(recs[pid2id[pid]])
    q = {k: {"type": "noul", "instructions": (
        f"「{CANDIDATES[k][1]}」に当たる事柄が、この論文の解析対象・主題として扱われているか。背景での言及だけなら該当しない。")}
         for k in keys}
    return pid, {k: round(v["noul"], 3) for k, v in call(state, q).items()}


with ThreadPoolExecutor(8) as ex:
    s1 = dict(ex.map(stage1, TARGETS))
pairs = [(pid, c) for pid, a in s1.items() for c in CANDIDATES if a[c]["choice"] in ("main", "secondary")]
with ThreadPoolExecutor(8) as ex:
    s2 = list(ex.map(stage2, pairs))
summary = {c: {"label": CANDIDATES[c][0],
               "roles": dict(Counter(a[c]["choice"] for a in s1.values())),
               "fit": dict(Counter(a["fit"]["choice"] for _, cc, a in s2 if cc == c))} for c in CANDIDATES}
adopted = [c for c, v in summary.items() if v["fit"].get("new_domain", 0) > sum(n for k, n in v["fit"].items() if k != "new_domain")]
print("stage1", {p: {c: a[c]["choice"] for c in CANDIDATES} for p, a in s1.items()})
print("summary", summary, "adopted", adopted, flush=True)

tags = {}
if adopted:
    papers = json.loads((ROOT / "viewer/data.json").read_text(encoding="utf-8"))["papers"]
    with ThreadPoolExecutor(12) as ex:
        tags = dict(ex.map(tag_all, [(p["paper_id"], adopted) for p in papers]))
out = {"candidates": CANDIDATES, "targets": TARGETS, "summary": summary, "adopted": adopted,
       "stage1": {p: {c: {"role": a[c]["choice"], "confidence": a[c].get("confidence")} for c in CANDIDATES} for p, a in s1.items()},
       "stage2": [{"paper_id": p, "candidate": c, "fit": a["fit"]["choice"], "confidence": a["fit"].get("confidence")} for p, c, a in s2],
       "tags": tags}
(ROOT / "data/new_domain_review_v3.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
for c in adopted:
    hit = [p for p, t in tags.items() if t[c] >= 0.5]
    print(CANDIDATES[c][0], "該当", len(hit), "うち対象4本", [p for p in TARGETS if p in hit])
