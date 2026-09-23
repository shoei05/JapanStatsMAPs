#!/usr/bin/env python3
"""v3 判定の残りを Jev で片づける。結果は data/jev_followup.json（build_viewer.py が読む）。

A. concept_unmapped の主曝露・主アウトカム: 63テーマ＋「該当なし」から最も近いものを選ばせる。
B. Claude が抄録で割り当てた5本のテーマ: 各テーマが解析上扱われているかを noul で確かめる。
C. 線（主曝露→主アウトカム）: その組合せを
   analyzed / adjustment_only / background_only / unknown のどれで扱ったかを選ばせる。analyzed の線だけ残す。
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".codex/skills/jev/scripts"))
import jev  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from structure_v2 import make_state  # noqa: E402

schema = json.loads((ROOT / "data/schema_od_v2.json").read_text(encoding="utf-8"))
DOM, LAB = schema["domains"], schema["domain_labels"]
recs = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data/records.jsonl").open(encoding="utf-8")}
data = json.loads((ROOT / "viewer/data.json").read_text(encoding="utf-8"))
reviews = json.loads((ROOT / "data/paper_reviews.json").read_text(encoding="utf-8"))
pid2id = {}
for rid, r in recs.items():
    doi = (r.get("doi") or "").lower()
    pid2id[f"doi:{doi}" if doi else f"pmid:{r['pmid']}" if r.get("pmid") else f"epmc:{rid}"] = rid

ROLE = {
    "analyzed": "この曝露とアウトカムの組合せを、本文の主解析または副次解析で実際に解析している（関連・比較・前後差・回帰などの結果が報告されている）",
    "adjustment_only": "片方が調整変数や層別の区分として使われるだけで、この組合せの関連そのものは解析していない",
    "background_only": "背景・考察・引用でこの組合せに触れるだけ",
    "unknown": "与えられた本文からは判定できない",
}


def job(task):
    kind, pid, extra = task
    state, mode = make_state(recs[pid2id[pid]])
    if kind == "A":
        role = "主曝露（主たる独立変数・要因）" if extra == "exposure_domain" else "主アウトカム（主たる従属変数、または記述の主対象）"
        q = {"pick": {"type": "choice", "criteria": {**DOM, "none": "どのテーマにも当たらない"}, "instructions": (
            f"この論文の{role}は、どのテーマに最も近いか。複数の要素を合成した指標（例: 地域の剥奪指標、健康行動の数）は、"
            "その指標が表す中心の概念のテーマを選ぶ。どれにも当たらなければ none。")}}
    elif kind == "B":
        q = {d: {"type": "noul", "instructions": (
            f"「{DOM[d]}」に属する事柄が、この論文の解析対象・主題として扱われているか。背景での言及だけなら該当しない。")}
             for d in extra}
    else:
        e, o = extra
        q = {"role": {"type": "choice", "criteria": ROLE, "instructions": (
            f"曝露側「{LAB[e]}」（{DOM[e]}）とアウトカム側「{LAB[o]}」（{DOM[o]}）の組合せを、この論文がどう扱っているか。"
            "本文に書かれた事実だけで判断する。")}}
    for attempt in range(5):
        try:
            return kind, pid, extra, mode, jev.call(state, q)["answers"]
        except (SystemExit, Exception) as e:  # noqa: BLE001  通信切れ・一時的なエラーは待って再試行
            err = e
            import time; time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"{kind} {pid}: {err}")


tasks = []
for p in data["papers"]:
    for k in ("exposure_domain", "outcome_domain"):
        if p[k] == "concept_unmapped":
            tasks.append(("A", p["paper_id"], k))
for pid, rv in reviews.items():
    tasks.append(("B", pid, tuple(rv["map_domains"])))
for key, pids in data["pairs"].items():
    e, o = key.split("|")
    for pid in pids:
        tasks.append(("C", pid, (e, o)))
print("tasks", {k: sum(1 for t in tasks if t[0] == k) for k in "ABC"}, flush=True)

with ThreadPoolExecutor(12) as ex:
    res = list(ex.map(job, tasks))

out = {"unmapped_slots": [], "review_checks": [], "pair_checks": []}
for kind, pid, extra, mode, a in res:
    if kind == "A":
        out["unmapped_slots"].append({"paper_id": pid, "role": extra, "pick": a["pick"]["choice"],
                                      "confidence": a["pick"].get("confidence"), "input_mode": mode})
    elif kind == "B":
        out["review_checks"].append({"paper_id": pid, "probs": {d: round(a[d]["noul"], 3) for d in extra}, "input_mode": mode})
    else:
        out["pair_checks"].append({"paper_id": pid, "exposure": extra[0], "outcome": extra[1], "role": a["role"]["choice"],
                                   "confidence": a["role"].get("confidence"), "input_mode": mode})
(ROOT / "data/jev_followup.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
from collections import Counter  # noqa: E402
print("A", Counter(x["pick"] for x in out["unmapped_slots"]).most_common())
print("B", [(x["paper_id"], x["probs"]) for x in out["review_checks"]])
print("C", Counter(x["role"] for x in out["pair_checks"]))
