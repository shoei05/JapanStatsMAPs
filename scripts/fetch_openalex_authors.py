#!/usr/bin/env python3
"""OpenAlex から全著者のフルネームを DOI 単位で取得し data/openalex_authors.json に保存する。

Europe PMC の著者情報は名（given name）が欠けてイニシャルだけの論文があるため、表示と著者名検索の補完に使う。
"""
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/openalex_authors.json"


def main():
    recs = [json.loads(l) for l in (ROOT / "data/records.jsonl").open(encoding="utf-8")]
    cand = {j["id"] for j in map(json.loads, (ROOT / "data/jev_judgments.jsonl").open(encoding="utf-8"))
            if j["data_class"] in ("A", "B", "AB", "unclear")}
    dois = sorted({r["doi"].lower() for r in recs if r["id"] in cand and r.get("doi")})
    got = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    todo = [d for d in dois if d not in got]
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        q = urllib.parse.urlencode({"filter": "doi:" + "|".join(chunk), "per-page": 50, "select": "doi,authorships",
                                    "mailto": os.environ.get("OPENALEX_MAILTO", "")})
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
            got[doi] = [a["author"]["display_name"] for a in w.get("authorships", []) if a.get("author", {}).get("display_name")]
        time.sleep(0.2)
    OUT.write_text(json.dumps(got, ensure_ascii=False), encoding="utf-8")
    print("dois", len(dois), "with authors", sum(1 for d in dois if got.get(d)))


if __name__ == "__main__":
    main()
