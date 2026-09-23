#!/usr/bin/env python3
"""各論文の題名と抄録を Jev に渡し、データ区分・領域・分析単位を判定する。

使い方: python3 scripts/judge_jev.py [--limit N]
出力: data/jev_judgments.jsonl（pmid ごとに追記、判定済みは飛ばす）
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".codex/skills/jev/scripts"))
import jev  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "data" / "records.jsonl"
OUT = ROOT / "data" / "jev_judgments.jsonl"

QUESTIONS = {
    "data_class": {
        "type": "choice",
        "instructions": (
            "Classify the main data this Japanese study analyzed. "
            "Class A = publicly released aggregated government data anyone can download "
            "(e.g., NDB Open Data, e-Stat statistical tables, published vital statistics tables, published survey summary tables). "
            "Class B = individual-level microdata of official government statistical surveys obtained through secondary-use application "
            "(e.g., Comprehensive Survey of Living Conditions, National Health and Nutrition Survey, Patient Survey microdata). "
            "Restricted = data that are neither A nor B, such as the full NDB claims database under special approval, DPC, JMDC or other commercial claims, "
            "hospital records, or the study's own cohort or survey."
        ),
        "criteria": {
            "A": "Main analysis uses Class A publicly released aggregated data",
            "B": "Main analysis uses Class B government survey microdata",
            "AB": "Main analysis combines Class A and Class B data",
            "restricted": "Main analysis uses restricted data only; A/B sources are at most background",
            "not_empirical": "Not an original empirical analysis (review, protocol, commentary, methods description) or source only cited for comparison",
            "unclear": "Abstract does not allow a judgment",
        },
    },
    "domain": {
        "type": "choice",
        "instructions": "Pick the main health or social topic of the study.",
        "criteria": {
            "mental": "Mental health, suicide, dementia, psychotropic drugs",
            "ncd": "Cardiometabolic disease, diabetes, hypertension, cancer, kidney disease",
            "infection": "Infectious disease, vaccination, antimicrobial use",
            "maternal_child": "Maternal, child, and adolescent health",
            "older_care": "Older adults, long-term care, frailty, caregiving",
            "health_service": "Health care use, prescribing patterns, medical costs, regional variation in care, workforce",
            "behavior": "Health behavior: smoking, alcohol, diet, physical activity, sleep, screening uptake",
            "social": "Income, poverty, employment, household structure, disability, social determinants",
            "oral_other": "Oral health, musculoskeletal, eye, skin, or other specific clinical areas",
        },
    },
    "unit": {
        "type": "choice",
        "instructions": "What is the unit of analysis?",
        "criteria": {
            "individual": "Individual persons or households",
            "prefecture": "Prefectures",
            "municipal": "Municipalities or secondary medical areas",
            "national": "National totals, age/sex strata, or drug/procedure-level national counts",
            "other": "Other or unclear",
        },
    },
}


# 検索に当たったデータ源ごとに「実際に分析に使ったか」を聞くための英語名
SOURCE_EN = {
    "NDBオープンデータ": "NDB Open Data (publicly released aggregated tables of Japan's National Database of Health Insurance Claims)",
    "人口動態統計": "Japan's Vital Statistics (births, deaths, causes of death), as published tables or death/birth record microdata",
    "国勢調査": "Japan's national Population Census",
    "医療施設調査・医師統計": "Survey of Medical Institutions or Statistics/Survey of Physicians, Dentists and Pharmacists",
    "e-Stat・公表統計表": "Official statistical tables published on e-Stat, the portal site of Japanese government statistics",
    "国民生活基礎調査": "Comprehensive Survey of Living Conditions",
    "国民健康・栄養調査": "Japan's National Health and Nutrition Survey",
    "患者調査": "Japan's Patient Survey by the Ministry of Health, Labour and Welfare",
    "社会生活基本調査": "Survey on Time Use and Leisure Activities",
    "就業構造基本調査": "Employment Status Survey",
    "全国家計構造調査・全国消費実態調査": "National Survey of Family Income and Expenditure / National Survey of Family Income, Consumption and Wealth",
    "21世紀出生児縦断調査": "Longitudinal Survey of Babies in 21st Century",
    "中高年者縦断調査": "Longitudinal Survey of Middle-aged and Elderly Persons",
    "歯科疾患実態調査": "Survey of Dental Diseases",
    "乳幼児身体発育調査・学校保健統計": "National Growth Survey on Preschool Children or School Health Statistics",
    "警察庁自殺統計・地域における自殺の基礎資料": "Japan's suicide statistics by the National Police Agency, or the Basic Data on Suicide in the Region published by the Ministry of Health, Labour and Welfare",
    "感染症発生動向調査": "Japan's National Epidemiological Surveillance of Infectious Diseases (NESID)",
    "国民医療費": "Japan's Estimates of National Medical Care Expenditure",
    "介護保険事業状況報告・介護給付費等実態統計": "Status Report on the Long-Term Care Insurance or Survey of Long-term Care Benefit Expenditures",
    "消防庁（救急・火災）": "data from Japan's Fire and Disaster Management Agency (ambulance transport, fire, or disaster statistics)",
    "衛生行政報告例": "Report on Public Health Administration and Services",
    "地域保健・健康増進事業報告": "Report on Regional Public Health Services and Health Promotion Services",
    "病院報告": "the Hospital Report of the Ministry of Health, Labour and Welfare",
    "学校基本調査": "Japan's School Basic Survey",
    "労働力調査": "Japan's Labour Force Survey",
    "賃金構造基本統計調査": "Basic Survey on Wage Structure",
    "住民基本台帳": "population data based on the Basic Resident Register",
}


def judge(rec):
    hits = sorted(rec["search_hits"])
    state = {"title": rec["title"], "abstract": rec["abstract"] or "(no abstract)",
             "publication_types": rec["pubtypes"], "year": rec["year"],
             "note": "The full text (not necessarily the abstract) mentions: " + "; ".join(SOURCE_EN[h] for h in hits)}
    qs = dict(QUESTIONS)
    for i, src in enumerate(hits):
        qs[f"uses_{i}"] = {"type": "noul", "instructions": (
            f"Does this study analyze data from {SOURCE_EN[src]} as part of its own analysis "
            "(not merely citing it for background or comparison)?")}
    for attempt in range(4):
        try:
            res = jev.call(state, qs)
            break
        except (SystemExit, Exception) as e:
            err = str(e)
            import time; time.sleep(3 * (attempt + 1))
    else:
        return {"id": rec["id"], "error": err}
    ans = res["answers"]
    return {"id": rec["id"],
            **{k: ans[k]["choice"] for k in QUESTIONS},
            **{f"{k}_conf": ans[k].get("confidence") for k in QUESTIONS},
            "data_class_probs": ans["data_class"].get("probabilities"),
            "uses": {src: ans[f"uses_{i}"]["noul"] for i, src in enumerate(hits)}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    done = set()
    if OUT.exists():
        done = {json.loads(l)["id"] for l in OUT.open(encoding="utf-8")}
    recs = [json.loads(l) for l in IN.open(encoding="utf-8")]
    recs = [r for r in recs if r["id"] not in done][: a.limit]
    with ThreadPoolExecutor(12) as ex, OUT.open("a", encoding="utf-8") as f:
        for i, row in enumerate(ex.map(judge, recs), 1):
            if "error" in row:
                print("error", row["id"], row["error"][:200], file=sys.stderr)
                continue
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if i % 50 == 0:
                print(i, file=sys.stderr)
    print("judged", len(recs))


if __name__ == "__main__":
    main()
