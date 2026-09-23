#!/usr/bin/env python3
"""Europe PMC の fullTextXML から Methods / Results を抜き出し data/fulltext/<id>.json に保存する。

対象: 引数の id リスト（既定は 1 回目の判定で A/B/AB/unclear の論文）。取得できない論文は抄録だけで判定する。
"""
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "fulltext"
OUT.mkdir(parents=True, exist_ok=True)
METHODS_RE = re.compile(r"method|material|data|participant|subject|design|setting|population|statistic", re.I)
RESULTS_RE = re.compile(r"result|finding", re.I)
NOT_METHODS_RE = re.compile(r"availability|sharing|statement|supplement", re.I)


def text(el):
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def sections(root):
    body = root.find(".//body")
    if body is None:
        return None
    methods, results = [], []
    for sec in body.findall("./sec"):
        title = (sec.findtext("title") or "").strip()
        stype = sec.get("sec-type", "")
        label = f"{stype} {title}"
        if RESULTS_RE.search(label):
            results.append(text(sec))
        elif METHODS_RE.search(label) and not NOT_METHODS_RE.search(label):
            methods.append(text(sec))
    return {"methods": " ".join(methods), "results": " ".join(results),
            "body_head": "" if methods else text(body)[:12000]}


def fetch(rec):
    path = OUT / (rec["id"].replace("/", "_") + ".json")
    if path.exists():
        return "cached"
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{rec['pmcid']}/fullTextXML"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                raw = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code in (404, 500):  # 500 は全文を配っていない論文で返る（2026-09 確認）
                path.write_text(json.dumps({"status": "no_fulltext" if e.code == 404 else "server_error_500"}), encoding="utf-8")
                return "no_fulltext"
            time.sleep(3 * (attempt + 1))
        except Exception:
            time.sleep(3 * (attempt + 1))
    else:
        return "error"
    try:
        s = sections(ET.fromstring(raw))
    except ET.ParseError:
        s = None
    data = {"status": "ok" if s else "no_body", **(s or {})}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data["status"]


def main():
    recs = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data/records.jsonl").open(encoding="utf-8")}
    ids = [l.strip() for l in open(sys.argv[1])] if len(sys.argv) > 1 else [
        j["id"] for j in map(json.loads, (ROOT / "data/jev_judgments.jsonl").open(encoding="utf-8"))
        if j["data_class"] in ("A", "B", "AB", "unclear")]
    todo = [recs[i] for i in ids if recs[i].get("pmcid")]
    from collections import Counter
    with ThreadPoolExecutor(8) as ex:
        c = Counter(ex.map(fetch, todo))
    print(len(ids), "targets;", len(todo), "with pmcid;", dict(c))


if __name__ == "__main__":
    main()
