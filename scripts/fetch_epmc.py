#!/usr/bin/env python3
"""Europe PMC（本文検索を含む）から日本の公開データ源ごとに論文を集め、data/records.jsonl に保存する。

PubMed の題名・抄録検索では、方法欄にだけデータ源名を書く論文を取りこぼすため、こちらを正とする。
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
SUFFIX = " AND (Japan OR Japanese) AND (SRC:MED OR SRC:PMC)"

SOURCES = {
    "NDBオープンデータ": '"NDB Open Data" OR "NDB open data"',
    "人口動態統計": '("Vital Statistics" AND "Ministry of Health, Labour and Welfare") OR "Vital Statistics of Japan" OR "Japanese Vital Statistics"',
    "国勢調査": '"Population Census" AND "Statistics Bureau"',
    "医療施設調査・医師統計": '"Survey of Medical Institutions" OR "Survey of Physicians, Dentists and Pharmacists" OR "Statistics of Physicians, Dentists and Pharmacists"',
    "e-Stat・公表統計表": '"e-Stat"',
    "国民生活基礎調査": '"Comprehensive Survey of Living Conditions" OR "Comprehensive Survey of the Living Conditions"',
    "国民健康・栄養調査": '"National Health and Nutrition Survey"',
    "患者調査": '"Patient Survey" AND "Ministry of Health, Labour and Welfare"',
    "社会生活基本調査": '"Survey on Time Use and Leisure Activities"',
    "就業構造基本調査": '"Employment Status Survey"',
    "全国家計構造調査・全国消費実態調査": '"National Survey of Family Income" OR "Family Income and Expenditure Survey"',
    "21世紀出生児縦断調査": '"Longitudinal Survey of Babies in 21st Century" OR "Longitudinal Survey of Newborns in the 21st Century" OR "Longitudinal Survey of Babies Born in the 21st Century"',
    "中高年者縦断調査": '"Longitudinal Survey of Middle-aged and Elderly Persons" OR "Longitudinal Survey of Middle-aged and Older Persons"',
    "歯科疾患実態調査": '"Survey of Dental Diseases"',
    "乳幼児身体発育調査・学校保健統計": '"School Health Statistics" OR "National Growth Survey"',
}


def _page(query, cursor):
    params = urllib.parse.urlencode({"query": "(" + query + ")" + SUFFIX, "format": "json", "resultType": "core",
                                     "pageSize": 200, "cursorMark": cursor})
    for attempt in range(8):
        try:
            with urllib.request.urlopen(f"{API}?{params}", timeout=180) as r:
                d = json.load(r)
            if "hitCount" in d and "resultList" in d:
                return d
            print("  bad response", str(d)[:200], flush=True)
        except Exception as e:  # 一時的なエラーは待って再試行
            print("  retry", attempt, e, flush=True)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("Europe PMC failed: " + query)


def search(query):
    """全件を返す。回収件数が hitCount と一致しなければ最初からやり直す。"""
    for _ in range(3):
        cursor, out, total = "*", [], None
        while True:
            d = _page(query, cursor)
            total = d["hitCount"]
            rs = d["resultList"].get("result", [])
            out.extend(rs)
            nxt = d.get("nextCursorMark")
            if not rs or nxt == cursor or len(out) >= total:
                break
            cursor = nxt
        if len(out) == total:
            return out
        print(f"  count mismatch {len(out)}/{total}, retrying", flush=True)
    raise RuntimeError(f"incomplete: {len(out)}/{total} {query}")


def main():
    records = {}
    cache_dir = ROOT / "data" / "epmc_cache"
    cache_dir.mkdir(exist_ok=True)
    for name, term in SOURCES.items():
        cache = cache_dir / f"{name}.json"
        if cache.exists():
            results = json.loads(cache.read_text(encoding="utf-8"))
        else:
            results = search(term)
            cache.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
        n = 0
        for r in results:
            key = r.get("pmid") or r.get("doi") or r["id"]
            rec = records.setdefault(key, {
                "id": key, "pmid": r.get("pmid"), "pmcid": r.get("pmcid"), "doi": r.get("doi"),
                "title": r.get("title", ""), "abstract": r.get("abstractText", ""),
                "journal": (r.get("journalInfo") or {}).get("journal", {}).get("title"),
                "year": int(r["pubYear"]) if str(r.get("pubYear", "")).isdigit() else None,
                "pubtypes": (r.get("pubTypeList") or {}).get("pubType", []),
                "search_hits": [],
            })
            if name not in rec["search_hits"]:
                rec["search_hits"].append(name)
            n += 1
        print(name, n, flush=True)
    out = ROOT / "data" / "records.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in records.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("unique", len(records), "->", out, flush=True)


if __name__ == "__main__":
    main()
