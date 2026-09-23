#!/usr/bin/env python3
"""収載候補の論文について、主解析のデータが日本のものかを Jev で判定する（区分の定義に日本であることを明記していなかったため）。

出力: data/japan_check.json {paper_id: 確率}。判定済みは飛ばす。build_viewer.py は 0.5 未満を収載から外す。
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".codex/skills/jev/scripts"))
import jev  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from structure_v2 import make_state  # noqa: E402

OUT = ROOT / "data/japan_check.json"
recs = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data/records.jsonl").open(encoding="utf-8")}
pid2id = {}
for rid, r in recs.items():
    doi = (r.get("doi") or "").lower()
    pid2id[f"doi:{doi}" if doi else f"pmid:{r['pmid']}" if r.get("pmid") else f"epmc:{rid}"] = rid
done = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
papers = json.loads((ROOT / "viewer/data.json").read_text(encoding="utf-8"))["papers"]
todo = [p["paper_id"] for p in papers if p["paper_id"] not in done]
Q = {"japan": {"type": "noul", "instructions": (
    "この論文の主解析に用いたデータは、日本の人口・地域・医療・政府統計のデータか。"
    "日本と他国の比較で日本のデータを含む場合は該当とする。日本以外の国のデータだけを解析している場合は該当しない。")}}


def one(pid):
    state, _ = make_state(recs[pid2id[pid]])
    for attempt in range(5):
        try:
            return pid, round(jev.call(state, Q)["answers"]["japan"]["noul"], 3)
        except (SystemExit, Exception) as e:  # noqa: BLE001
            err = e
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"{pid}: {err}")


with ThreadPoolExecutor(12) as ex:
    for pid, p in ex.map(one, todo):
        done[pid] = p
OUT.write_text(json.dumps(done, ensure_ascii=False, indent=0), encoding="utf-8")
print("judged", len(todo), "non-japan(<0.5)", sum(1 for v in done.values() if v < 0.5))
