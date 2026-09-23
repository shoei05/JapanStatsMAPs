#!/usr/bin/env python3
"""題名・抄録・本文抜粋から、区分・データ源・解析データの年・問いの型・デザイン・対象・分析単位・主曝露・主アウトカム・テーマを Jev で判定する。

  - 解析データの年は最初の年・最後の年（choice）で聞く。公的統計は数十年分を使うことがあるため
  - テーマは data/schema_od_v2.json（63テーマ）
入力: オープンアクセス論文は Methods/Results、それ以外は題名・抄録。どちらを使ったかを input_mode に残す。

使い方: zsh -lc 'python3 scripts/structure_v2.py [--limit N] [--ids file]'
出力: data/structured_v3.jsonl（id ごとに追記、処理済みは飛ばす）、生応答は data/jev_responses_v3/
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".codex/skills/jev/scripts"))
import jev  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "data/schema_od_v2.json").read_text(encoding="utf-8"))
DOM = SCHEMA["domains"]
DOM_CHOICE = {**DOM, **SCHEMA["role_unresolved"]}
OUT = ROOT / "data/structured_v3.jsonl"
RESP = ROOT / "data/jev_responses_v3"
RESP.mkdir(exist_ok=True)
YEARS = ["before_1950"] + [str(y) for y in range(1950, 2027)] + ["not_stated"]
T_HI, T_LO = 0.5, 0.15

sys.path.insert(0, str(ROOT / "scripts"))
from judge_jev import SOURCE_EN  # noqa: E402

DATA_CLASS = {
    "A": "主解析のデータが、誰でもダウンロードできる公表集計データ（NDBオープンデータ、e-Stat の統計表、人口動態統計の公表表、公表された調査の集計表など）",
    "B": "主解析のデータが、二次利用申請で得た政府統計調査の個票（国民生活基礎調査、国民健康・栄養調査、患者調査、社会生活基本調査、21世紀出生児縦断調査などの個票、人口動態調査の死亡票・出生票の個票）",
    "AB": "主解析で A と B の両方を組み合わせている",
    "restricted": "主解析のデータが A でも B でもない（NDB 特別抽出、DPC、JMDC などの商用レセプト、病院の記録、独自のコホートや調査、JACSIS など）。A/B のデータは分母・参照値・背景として使うだけ",
    "not_empirical": "独自の実証解析ではない（総説、プロトコル、コメンタリー、レター、方法の解説）",
    "unclear": "与えられた本文からは判定できない",
}


# 公的統計の研究はほぼ全件が年齢・性別で層別・年齢調整するため、この2領域だけ除外条件を足す
DEMOGRAPHIC_NOTE = {
    "demographics_family": "年齢・性別による層別や年齢調整、人口を分母にしただけでは該当しない。婚姻・世帯構成・家族そのものを解析の対象にした場合に限る。",
    "fertility_births_population": "年齢・性別による層別や年齢調整、人口を分母にしただけでは該当しない。出生・人口構造・人口移動そのものを解析の対象にした場合に限る。",
}


def questions(hits):
    q = {
        "data_class": {"type": "choice", "criteria": DATA_CLASS, "instructions": (
            "この論文の主解析に用いたデータはどれか。Methods のデータ・対象の記述で判断する。"
            "e-Stat などの公表値を人口の分母や年齢調整の基準人口としてだけ使い、主解析が別のデータなら restricted。")},
        "question_type": {"type": "choice", "criteria": SCHEMA["question_type"], "instructions": (
            "この論文の主たる問いの型はどれか。標題と目的文で判断する。『〜に関連する要因』のように多数の要因を網羅的に調べていれば "
            "multi_factor_exploratory、有病割合や実態の記述なら descriptive_prevalence、推移なら trend、地域差なら geographic_variation、"
            "制度・政策・災害・パンデミックの前後比較なら policy_evaluation。")},
        "design": {"type": "choice", "criteria": SCHEMA["designs"], "instructions": (
            "主解析の研究デザインはどれか。観察単位が個人か集計単位かをまず確認する。集計値の時系列は time_series、"
            "地域単位の比較は ecological。")},
        "population": {"type": "choice", "criteria": SCHEMA["populations"], "instructions": (
            "主解析の対象集団はどれか。著者が Methods や標題で特定の属性に限定していればその集団。"
            "全体を解析したうえで層別に示しただけなら限定とみなさない。")},
        "unit": {"type": "choice", "criteria": SCHEMA["units"], "instructions": "主解析の観察単位（分析単位）はどれか。"},
        "exposure_domain": {"type": "choice", "criteria": DOM_CHOICE, "instructions": (
            "主曝露（主たる独立変数・要因）が属する領域はどれか。著者が主解析の独立変数として明示したもの、"
            "または標題・目的文に『〜と…の関連』の前者として現れるもの。地域差や推移の研究で、地域や年そのものを比べているだけなら role_absent。"
            "制度改定・パンデミックなどの前後比較では、その制度・出来事の領域。調整変数や層別要因は主曝露ではない。"
            "多数の要因を網羅的に探索する研究は role_absent。主曝露が分かるが一覧に無ければ concept_unmapped、確定できなければ not_determined。")},
        "outcome_domain": {"type": "choice", "criteria": DOM_CHOICE, "instructions": (
            "主アウトカム（主たる従属変数、または記述研究で主に記述した量）が属する領域はどれか。"
            "標題・目的文に現れるもの、次いで最初に報告されるものを優先する。"
            "記述・推移・地域差の研究では、記述の対象となった量（例: 処方量、死亡率、手術件数）の領域を選ぶ。"
            "一覧に無ければ concept_unmapped、確定できなければ not_determined。")},
        "has_effect_estimate": {"type": "noul", "instructions": (
            "オッズ比・リスク比・ハザード比・回帰係数・率比などの効果推定値が信頼区間付きで報告されているか。")},
        "multi_year_data": {"type": "noul", "instructions": "解析に2つ以上の年（時点）のデータを用いているか。"},
        "year_start": {"type": "choice", "criteria": {y: y for y in YEARS}, "instructions": (
            "解析に用いたデータの最初の年はどれか（データの対象年、調査年、統計の年次）。論文の出版年・受理年、引用文献の年は使わない。"
            "年度表記は開始年とする。本文に年が書かれていなければ not_stated。")},
        "year_end": {"type": "choice", "criteria": {y: y for y in YEARS}, "instructions": (
            "解析に用いたデータの最後の年はどれか（データの対象年、調査年、統計の年次）。単年なら最初の年と同じ年を選ぶ。"
            "論文の出版年・受理年、引用文献の年は使わない。本文に年が書かれていなければ not_stated。")},
    }
    for i, src in enumerate(hits):
        q[f"uses_{i}"] = {"type": "noul", "instructions": (
            f"この論文は、{SOURCE_EN[src]} のデータを自らの解析に用いているか（背景・比較のための引用だけなら該当しない。"
            "人口の分母や年齢調整の基準としてだけ用いた場合も該当とする）。")}
    for k, v in DOM.items():
        q[f"t__{k}"] = {"type": "noul", "instructions": (
            f"「{v}」に属する変数が、この論文の解析で曝露・アウトカム・記述の主対象・媒介要因・効果修飾要因・層別要因のいずれかとして扱われているか"
            "（該当する例: 主曝露や主アウトカム、副次アウトカム、交互作用項、層別解析の層）。調整変数としてだけ用いた場合や背景での言及は含めない。"
            + DEMOGRAPHIC_NOTE.get(k, ""))}
    return q


def load_fulltext(rid):
    p = ROOT / "data/fulltext" / (rid.replace("/", "_") + ".json")
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return d if d.get("status") == "ok" else None


def make_state(rec):
    ft = load_fulltext(rec["id"])
    state = {
        "task": "日本の公的統計・公表データを用いた研究論文の題名・抄録・本文抜粋を読み、各質問に答える。",
        "title": rec["title"], "abstract": rec["abstract"] or "(no abstract)",
        "publication_types": rec["pubtypes"], "publication_year": rec["year"],
        "note": "The full text mentions: " + "; ".join(SOURCE_EN[h] for h in sorted(rec["search_hits"])),
    }
    if ft and (ft["methods"] or ft["body_head"]):
        state["methods"] = (ft["methods"] or ft["body_head"])[:12000]
        state["results"] = ft["results"][:6000]
        mode = "fulltext_methods" if ft["methods"] else "fulltext_body"
    else:
        mode = "abstract_only"
    return state, mode


def band(p):
    return "yes" if p >= T_HI else ("no" if p <= T_LO else "uncertain")


def one(rec):
    hits = sorted(rec["search_hits"])
    state, mode = make_state(rec)
    q = questions(hits)
    for attempt in range(5):
        try:
            res = jev.call(state, q, timeout=120)
            break
        except (SystemExit, Exception) as e:  # noqa: BLE001
            err = str(e)
            time.sleep(4 * (attempt + 1))
    else:
        return {"id": rec["id"], "error": err}
    (RESP / (rec["id"].replace("/", "_") + ".json")).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    a = res["answers"]
    ch = lambda k: (a[k]["choice"], round(a[k].get("confidence") or 0, 3))  # noqa: E731
    out = {"id": rec["id"], "input_mode": mode}
    for k in ["data_class", "question_type", "design", "population", "unit", "exposure_domain", "outcome_domain",
              "year_start", "year_end"]:
        out[k], out[k + "_conf"] = ch(k)
    for k in ["has_effect_estimate", "multi_year_data"]:
        out[k], out[k + "_p"] = band(a[k]["noul"]), round(a[k]["noul"], 3)
    out["uses"] = {src: round(a[f"uses_{i}"]["noul"], 3) for i, src in enumerate(hits)}
    tags = {k[3:]: round(v["noul"], 3) for k, v in a.items() if k.startswith("t__")}
    out["tags_yes"] = sorted(k for k, p in tags.items() if p >= T_HI)
    out["tags_uncertain"] = sorted(k for k, p in tags.items() if T_LO < p < T_HI)
    derived = {out[k] for k in ("exposure_domain", "outcome_domain") if out[k] in DOM}
    out["tags_yes_final"] = sorted(set(out["tags_yes"]) | derived)
    out["tag_probs"] = tags
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    recs = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data/records.jsonl").open(encoding="utf-8")}
    if a.ids:
        ids = [l.strip() for l in open(a.ids) if l.strip()]
    else:
        ids = [j["id"] for j in map(json.loads, (ROOT / "data/jev_judgments.jsonl").open(encoding="utf-8"))
               if j["data_class"] in ("A", "B", "AB", "unclear")]
    done = {json.loads(l)["id"] for l in OUT.open(encoding="utf-8")} if OUT.exists() else set()
    todo = [recs[i] for i in ids if i not in done][: a.limit]
    n_err = 0
    with ThreadPoolExecutor(a.workers) as ex, OUT.open("a", encoding="utf-8") as f:
        for i, row in enumerate(ex.map(one, todo), 1):
            if "error" in row:
                n_err += 1
                print("error", row["id"], row["error"][:200], file=sys.stderr, flush=True)
                continue
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if i % 100 == 0:
                print(i, file=sys.stderr, flush=True)
    print("structured", len(todo) - n_err, "errors", n_err)


if __name__ == "__main__":
    main()
