#!/usr/bin/env python3
"""テーマ未分類・concept_unmapped の論文から立てた新テーマ候補を、Jev で2段階に判定する。

1段目: 各論文で候補概念が果たす役割（main / secondary / background_only / absent / unknown）
2段目: main・secondary の論文について、既存テーマとの関係（existing_domain / new_domain / insufficient_evidence）
出力: data/new_domain_review.json
"""
import json
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".codex/skills/jev/scripts"))
import jev  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from structure_v2 import make_state  # noqa: E402

schema = json.loads((ROOT / "data/schema_od_v1.json").read_text(encoding="utf-8"))
CANDIDATES = {
    "environmental_exposure": ("気象・環境曝露", "気温・湿度・日照・季節などの気象条件、大気汚染（PM2.5など）、放射性物質、標高、化学物質など、環境からの曝露。居住環境や地域の社会経済的特徴とは区別する"),
    "climate_carbon": ("環境負荷・脱炭素", "温室効果ガス排出、カーボンフットプリント、エネルギー消費、食品ロス、資源循環など、人の活動が環境に与える負荷"),
    "disability_functioning": ("障害・生活機能", "障害、活動制限、日常生活動作（ADL・IADL）、Washington Group の設問などの生活機能。要介護認定や介護保険サービスの利用とは区別する"),
    "time_use_leisure": ("生活時間・余暇", "生活時間の配分、余暇活動、趣味、ボランティアなどの社会参加。身体活動の量やソーシャルキャピタルとは区別する"),
    "economy_industry": ("経済・産業", "農業生産、観光、産業連関、消費支出、技術普及など、健康以外の経済・産業指標そのもの。個人の所得・貧困とは区別する"),
}
ROLE = {
    "main": "その概念を実際に測定・解析した主曝露・主アウトカム、または論文の主たる研究対象",
    "secondary": "副次的変数・媒介・効果修飾・層別要因として実際に解析している（調整のみではない）",
    "background_only": "背景・考察・引用で言及するだけ、または調整変数としてだけ使う",
    "absent": "この概念は扱われていない",
    "unknown": "与えられた本文から判定できない",
}
FIT = {
    "existing_domain": "既存テーマの定義で意味も範囲も十分に表せる（新テーマは不要）",
    "new_domain": "既存テーマのどれにも収まらない独立した概念で、新テーマとして立てるべき",
    "insufficient_evidence": "判断材料が足りない",
}
recs = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data/records.jsonl").open(encoding="utf-8")}
data = json.loads((ROOT / "viewer/data.json").read_text(encoding="utf-8"))
target_pids = set(json.loads((ROOT / "data/unmapped_target_ids.json").read_text()))
# paper_id から records の id へ
pid2id = {}
for s in map(json.loads, (ROOT / "data/structured_v2.jsonl").open(encoding="utf-8")):
    r = recs[s["id"]]
    doi = (r.get("doi") or "").lower()
    pid2id[f"doi:{doi}" if doi else f"pmid:{r['pmid']}" if r.get("pmid") else f"epmc:{r['id']}"] = s["id"]
ids = [pid2id[p] for p in target_pids]


def stage1(rid):
    state, _ = make_state(recs[rid])
    state["candidates"] = {k: {"label": v[0], "definition": v[1]} for k, v in CANDIDATES.items()}
    q = {k: {"type": "choice", "criteria": ROLE, "instructions": (
        f"stateのcandidatesの「{v[0]}」（定義: {v[1]}）が、この論文の目的と解析で果たす役割を、与えられた本文の事実だけで判断する。"
        "複数なら main、secondary の順に優先する。")} for k, v in CANDIDATES.items()}
    return rid, jev.call(state, q)["answers"]


def stage2(args):
    rid, cand = args
    state, _ = make_state(recs[rid])
    state["candidate"] = {"label": CANDIDATES[cand][0], "definition": CANDIDATES[cand][1]}
    state["existing_domains"] = {k: v for k, v in schema["domains"].items()}
    q = {"fit": {"type": "choice", "criteria": FIT, "instructions": (
        "この論文で主題・副次として扱われている候補概念（stateのcandidate）は、existing_domains のどれかで表せるか。"
        "近い広い領域へ無理に押し込まず、測定している概念が独立していれば new_domain を選ぶ。")},
         "nearest": {"type": "choice", "criteria": {**schema["domains"], "none": "近い既存テーマは無い"}, "instructions": (
        "候補概念に最も近い既存テーマはどれか。")}}
    return rid, cand, jev.call(state, q)["answers"]


with ThreadPoolExecutor(10) as ex:
    s1 = dict(ex.map(stage1, ids))
pairs = [(rid, c) for rid, a in s1.items() for c in CANDIDATES if a[c]["choice"] in ("main", "secondary")]
with ThreadPoolExecutor(10) as ex:
    s2 = list(ex.map(stage2, pairs))

summary = {}
for c, (lab, _) in CANDIDATES.items():
    roles = Counter(a[c]["choice"] for a in s1.values())
    fits = Counter(ans["fit"]["choice"] for rid, cc, ans in s2 if cc == c)
    near = Counter(ans["nearest"]["choice"] for rid, cc, ans in s2 if cc == c)
    summary[c] = {"label": lab, "roles": dict(roles), "fit": dict(fits), "nearest": dict(near.most_common(3))}
out = {"candidates": CANDIDATES, "summary": summary,
       "stage1": {rid: {c: {"role": a[c]["choice"], "confidence": a[c].get("confidence")} for c in CANDIDATES} for rid, a in s1.items()},
       "stage2": [{"id": rid, "candidate": c, "fit": a["fit"]["choice"], "fit_conf": a["fit"].get("confidence"),
                   "nearest": a["nearest"]["choice"]} for rid, c, a in s2]}
(ROOT / "data/new_domain_review.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(ids), "papers")
for c, v in summary.items():
    print(v["label"], "| 役割", v["roles"], "| 採用先", v["fit"], "| 近い既存", v["nearest"])
