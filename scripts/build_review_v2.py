#!/usr/bin/env python3
"""2回目（全項目）の判定から、人手点検表 output/review_sheet_v2.csv を作る。区分ごとに20本を無作為抽出。"""
import csv, json, random
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
recs = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data/records.jsonl").open(encoding="utf-8")}
lab = json.loads((ROOT / "data/schema_od_v1.json").read_text(encoding="utf-8"))["domain_labels"]
S = [json.loads(l) for l in (ROOT / "data/structured_v2.jsonl").open(encoding="utf-8")]
random.seed(20260924)
rows = []
for cls in ["A", "B", "AB", "restricted", "not_empirical", "unclear"]:
    xs = [s for s in S if s["data_class"] == cls]; random.shuffle(xs)
    for s in xs[:20]:
        r = recs[s["id"]]
        rows.append({"id": s["id"], "pmid": r["pmid"] or "", "doi": r["doi"] or "", "year": r["year"], "title": r["title"],
                     "journal": r["journal"], "判定に使った本文": s["input_mode"], "区分": s["data_class"],
                     "データ源": ";".join(k for k, p in s["uses"].items() if p >= 0.5),
                     "データの年": f'{s["year_start"]}-{s["year_end"]}', "問いの型": s["question_type"], "デザイン": s["design"],
                     "対象": s["population"], "分析単位": s["unit"], "主曝露": lab.get(s["exposure_domain"], s["exposure_domain"]),
                     "主アウトカム": lab.get(s["outcome_domain"], s["outcome_domain"]),
                     "テーマ": "、".join(lab.get(t, t) for t in s["tags_yes_final"]),
                     "人手_区分": "", "人手_データ源": "", "人手_データの年": "", "人手_主曝露": "", "人手_主アウトカム": "", "メモ": ""})
with (ROOT / "output/review_sheet_v2.csv").open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("review rows", len(rows))
