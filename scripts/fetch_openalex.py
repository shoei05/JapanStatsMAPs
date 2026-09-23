#!/usr/bin/env python3
"""OpenAlex から参考文献リストと被引用数を DOI 単位で取得し data/openalex_works.json に保存する。

paper_links.py が読む形式（{"fetched_at", "works": {doi: {openalex_id, referenced_works, cited_by_count}}}）に合わせる。
"""
import datetime
import os
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/openalex_works.json"


def main():
    recs = [json.loads(l) for l in (ROOT / "data/records.jsonl").open(encoding="utf-8")]
    cand = {j["id"] for j in map(json.loads, (ROOT / "data/jev_judgments.jsonl").open(encoding="utf-8"))
            if j["data_class"] in ("A", "B", "AB", "unclear")}
    dois = sorted({r["doi"].lower() for r in recs if r["id"] in cand and r.get("doi")})
    works = json.loads(OUT.read_text())["works"] if OUT.exists() else {}
    todo = [d for d in dois if d not in works]
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        q = urllib.parse.urlencode({"filter": "doi:" + "|".join(chunk), "per-page": 50,
                                    "select": "id,doi,referenced_works,cited_by_count", "mailto": os.environ.get("OPENALEX_MAILTO", "")})
        for attempt in range(4):
            try:
                with urllib.request.urlopen("https://api.openalex.org/works?" + q, timeout=60) as r:
                    res = json.load(r)["results"]
                break
            except Exception as e:  # noqa: BLE001
                print("retry", attempt, e, flush=True)
                time.sleep(5 * (attempt + 1))
        else:
            continue
        for w in res:
            doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
            works[doi] = {"openalex_id": w["id"], "referenced_works": w.get("referenced_works") or [],
                          "cited_by_count": w.get("cited_by_count")}
        time.sleep(0.2)
    OUT.write_text(json.dumps({"fetched_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                               "works": works}, ensure_ascii=False), encoding="utf-8")
    print("dois", len(dois), "found", sum(1 for d in dois if d in works),
          "with refs", sum(1 for d in dois if works.get(d, {}).get("referenced_works")))


if __name__ == "__main__":
    main()
