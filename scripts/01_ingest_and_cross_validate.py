#!/usr/bin/env python3
"""
步驟 2：讀取江明宗原始 ZIP 與歐噴 incomes.csv，執行 ZIP 版本去重與四重交互驗證，
產出統一基準之營利事業捐贈明細表與不重複捐款企業統編清單。
"""

import csv
import io
import json
import os
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIANG_ACC = os.path.join(BASE, "raw/kiang_ardata/data/individual/account")
OPENFUN_CSV = os.path.join(BASE, "raw/openfun/incomes.csv")
OUT_DIR = os.path.join(BASE, "output")

ELECTIONS = [
    "113年總統、副總統選舉",
    "113年立法委員選舉",
    "111年直轄市市長選舉",
    "111年縣(市)長選舉",
    "111年直轄市議員選舉",
    "111年縣(市)議員選舉",
]


def norm_text(val: str) -> str:
    if val is None:
        return ""
    return unicodedata.normalize("NFKC", str(val)).strip()


def norm_key(val: str) -> str:
    if val is None:
        return ""
    return str(val).strip()


def norm_cand_key(val: str) -> str:
    s = norm_text(val)
    for ch in ("．", "·", "‧", "•", "・"):
        s = s.replace(ch, ".")
    return s


def norm_tax_id(val: str) -> str:
    s = norm_text(val)
    return s


def parse_amount(val: str) -> float:
    s = norm_text(val).replace(",", "")
    if not s:
        return 0.0
    return float(s)


def load_kiang_dedup():
    all_zips = []
    unmatched = []
    for el in ELECTIONS:
        el_dir = os.path.join(KIANG_ACC, el)
        for root, _, files in os.walk(el_dir):
            for fn in sorted(files):
                if not fn.endswith(".zip"):
                    continue
                rel = os.path.relpath(os.path.join(root, fn), el_dir)
                area_raw = os.path.dirname(rel)
                if area_raw == "." or el == "113年總統、副總統選舉":
                    area_raw = ""
                m = re.match(r"^(.+?)_(\d+)(?:_v(\d+))?\.zip$", fn)
                if not m:
                    unmatched.append((el, rel))
                    continue
                cand_raw = m.group(1)
                serial = int(m.group(2))
                ver = int(m.group(3) or 1)
                all_zips.append(
                    {
                        "election": el,
                        "area_raw": area_raw,
                        "area": area_raw.strip(),
                        "cand_raw": cand_raw,
                        "cand": cand_raw.strip(),
                        "serial": serial,
                        "version": ver,
                        "zip_path": os.path.join(root, fn),
                        "zip_name": fn,
                    }
                )

    dedup = {}
    for item in all_zips:
        key = (item["election"], item["area"], item["cand_raw"], item["serial"])
        if key not in dedup or item["version"] > dedup[key]["version"]:
            dedup[key] = item

    return all_zips, list(dedup.values()), unmatched


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    all_zips, dedup_zips, unmatched = load_kiang_dedup()

    serial1_zips = [z for z in dedup_zips if z["serial"] == 1]
    serial_ge2_zips = [z for z in dedup_zips if z["serial"] >= 2]

    # Check serial >= 2 zips for any corporate donations
    s2_corp_rows = 0
    s2_total_rows = 0
    s2_subjects = Counter()
    for z in serial_ge2_zips:
        with zipfile.ZipFile(z["zip_path"]) as zf:
            if "incomes.csv" in zf.namelist():
                with zf.open("incomes.csv") as f:
                    reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                    for row in reader:
                        s2_total_rows += 1
                        subj = norm_text(row.get("收支科目", ""))
                        s2_subjects[subj] += 1
                        if "營利事業" in subj:
                            s2_corp_rows += 1

    # Extract serial == 1 zips
    corp_records = []
    val_b_diffs = []
    val_b_matched = 0
    val_b_total = 0
    cand_total_income_rows = {}
    kiang_cand_corp_stats = {}
    kiang_summary_totals = defaultdict(lambda: {"cands": 0, "summary_corp_gross": 0.0})
    wang_shih_chien_kiang = None
    corr_values = Counter()
    ret_values = Counter()
    bad_tax_ids = []

    for z in serial1_zips:
        el = z["election"]
        area = z["area"]
        cand = z["cand"]
        with zipfile.ZipFile(z["zip_path"]) as zf:
            # Summary file
            summary_corp = 0.0
            summary_total = 0.0
            summary_ret_exp = 0.0
            declare_date = ""
            corr_date = ""
            if "person_incomes and expenditures_first.csv" in zf.namelist():
                with zf.open("person_incomes and expenditures_first.csv") as f:
                    s_reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                    s_rows = list(s_reader)
                    if s_rows:
                        sr = {norm_key(k): norm_text(v) for k, v in s_rows[0].items()}
                        summary_corp = parse_amount(sr.get("營利事業捐贈收入", "0"))
                        summary_total = parse_amount(sr.get("收入小計", "0"))
                        summary_ret_exp = parse_amount(sr.get("返還捐贈支出", "0"))
                        declare_date = sr.get("申報日期", "")
                        corr_date = sr.get("更正日期", "")

            kiang_summary_totals[el]["cands"] += 1
            kiang_summary_totals[el]["summary_corp_gross"] += summary_corp

            inc_rows = []
            if "incomes.csv" in zf.namelist():
                with zf.open("incomes.csv") as f:
                    reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                    for r in reader:
                        nr = {norm_key(k): norm_text(v) for k, v in r.items()}
                        inc_rows.append(nr)

            cand_key = norm_cand_key(cand)
            cand_total_income_rows[(el, area, cand_key)] = len(inc_rows)
            corp_rows = [r for r in inc_rows if "營利事業" in r.get("收支科目", "")]
            detail_corp_sum = sum(parse_amount(r.get("收入金額", "0")) for r in corp_rows)

            val_b_total += 1
            if abs(detail_corp_sum - summary_corp) <= 1.0:
                val_b_matched += 1
            else:
                val_b_diffs.append(
                    {
                        "election": el,
                        "area": area,
                        "candidate": cand,
                        "zip_name": z["zip_name"],
                        "detail_corp_sum": detail_corp_sum,
                        "summary_corp": summary_corp,
                        "diff": detail_corp_sum - summary_corp,
                    }
                )

            c_gross = 0.0
            c_ret = 0.0
            for r in corp_rows:
                amt = parse_amount(r.get("收入金額", "0"))
                ret_flag = r.get("返還/繳庫", "")
                corr_flag = r.get("更正註記", "")
                ret_amt = amt if ret_flag else 0.0
                net_amt = amt - ret_amt
                tid = norm_tax_id(r.get("身分證／統一編號", ""))
                donor = r.get("捐贈者／支出對象", "")
                if not re.match(r"^\d{8}$", tid):
                    bad_tax_ids.append(
                        {
                            "election": el,
                            "area": area,
                            "candidate": cand,
                            "tax_id_raw": tid,
                            "donor_name": donor,
                            "amount": amt,
                        }
                    )
                corr_values[corr_flag] += 1
                ret_values[ret_flag] += 1
                c_gross += amt
                c_ret += ret_amt

                corp_records.append(
                    {
                        "election": el,
                        "area": area,
                        "candidate": cand,
                        "serial_year": r.get("申報序號／年度", ""),
                        "row_seq": r.get("序號", ""),
                        "tx_date": r.get("交易日期", ""),
                        "subject": r.get("收支科目", ""),
                        "donor_name": donor,
                        "tax_id_raw": tid,
                        "tax_id_8": tid if re.match(r"^\d{8}$", tid) else (tid.zfill(8) if re.match(r"^\d{7}$", tid) else ""),
                        "gross_amount": amt,
                        "returned_flag": ret_flag,
                        "returned_amount": ret_amt,
                        "net_amount": net_amt,
                        "method": r.get("捐贈方式", ""),
                        "deposit_date": r.get("存入專戶日期", ""),
                        "money_type": r.get("金錢類", ""),
                        "address": r.get("地址", ""),
                        "corr_flag": corr_flag,
                        "corr_date": r.get("資料更正日期", ""),
                        "zip_name": z["zip_name"],
                        "zip_version": z["version"],
                        "summary_declare_date": declare_date,
                        "summary_corr_date": corr_date,
                    }
                )

            kiang_cand_corp_stats[(el, area, cand_key)] = {
                "count": len(corp_rows),
                "gross": c_gross,
                "returned": c_ret,
                "net": c_gross - c_ret,
                "zip_name": z["zip_name"],
                "summary_corr_date": corr_date,
            }

            if el == "113年立法委員選舉" and area == "臺北市" and cand == "王世堅":
                wang_shih_chien_kiang = {
                    "total_income_rows": len(inc_rows),
                    "corp_rows": len(corp_rows),
                    "corp_gross": c_gross,
                    "corp_returned": c_ret,
                    "corp_net": c_gross - c_ret,
                    "summary_corp": summary_corp,
                    "summary_total": summary_total,
                    "returned_items": [
                        {
                            "donor": r.get("捐贈者／支出對象"),
                            "tax_id": r.get("身分證／統一編號"),
                            "amount": parse_amount(r.get("收入金額", "0")),
                            "flag": r.get("返還/繳庫"),
                        }
                        for r in corp_rows
                        if r.get("返還/繳庫")
                    ],
                }

    # Read OpenFun incomes.csv for target elections
    of_cand_corp_stats = defaultdict(lambda: {"count": 0, "gross": 0.0, "returned": 0.0, "net": 0.0})
    of_all_cands = set()
    wang_shih_chien_of = {"total_income_rows": 0, "corp_rows": 0, "corp_gross": 0.0, "corp_returned": 0.0, "corp_net": 0.0}

    with open(OPENFUN_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            el = norm_text(row.get("選舉名稱", ""))
            if el not in ELECTIONS:
                continue
            area = norm_text(row.get("縣市", ""))
            if el == "113年總統、副總統選舉":
                area = ""
            cand = norm_text(row.get("擬參選人／政黨", ""))
            cand_key = norm_cand_key(cand)
            of_all_cands.add((el, area, cand_key))
            subj = norm_text(row.get("收支科目", ""))
            amt = parse_amount(row.get("收入金額", "0"))
            ret_flag = norm_text(row.get("返還/繳庫", ""))
            ret_amt = amt if ret_flag else 0.0

            if el == "113年立法委員選舉" and area == "臺北市" and cand == "王世堅":
                wang_shih_chien_of["total_income_rows"] += 1
                if "營利事業" in subj:
                    wang_shih_chien_of["corp_rows"] += 1
                    wang_shih_chien_of["corp_gross"] += amt
                    wang_shih_chien_of["corp_returned"] += ret_amt
                    wang_shih_chien_of["corp_net"] += (amt - ret_amt)

            if "營利事業" in subj:
                st = of_cand_corp_stats[(el, area, cand_key)]
                st["count"] += 1
                st["gross"] += amt
                st["returned"] += ret_amt
                st["net"] += (amt - ret_amt)

    # Compare Kiang vs OpenFun candidate-by-candidate
    all_keys = sorted(set(kiang_cand_corp_stats.keys()) | set(of_cand_corp_stats.keys()))
    diff_rows = []
    for k in all_keys:
        ks = kiang_cand_corp_stats.get(k, {"count": 0, "gross": 0.0, "returned": 0.0, "net": 0.0, "zip_name": "", "summary_corr_date": ""})
        os_ = of_cand_corp_stats.get(k, {"count": 0, "gross": 0.0, "returned": 0.0, "net": 0.0})
        if ks["count"] != os_["count"] or abs(ks["gross"] - os_["gross"]) > 0.01 or abs(ks["net"] - os_["net"]) > 0.01:
            diff_rows.append(
                {
                    "election": k[0],
                    "area": k[1],
                    "candidate": k[2],
                    "kiang_zip": ks.get("zip_name", ""),
                    "kiang_corr_date": ks.get("summary_corr_date", ""),
                    "kiang_corp_count": ks["count"],
                    "kiang_corp_gross": ks["gross"],
                    "kiang_corp_net": ks["net"],
                    "openfun_corp_count": os_["count"],
                    "openfun_corp_gross": os_["gross"],
                    "openfun_corp_net": os_["net"],
                    "diff_gross_kiang_minus_openfun": ks["gross"] - os_["gross"],
                    "diff_net_kiang_minus_openfun": ks["net"] - os_["net"],
                }
            )

    # Also check candidates in Kiang missing from OpenFun overall
    kiang_only_zero_income = []
    kiang_only_nonzero_income = []
    for k in sorted(set(kiang_cand_corp_stats.keys()) - of_all_cands):
        cnt = cand_total_income_rows.get(k, 0)
        if cnt == 0:
            kiang_only_zero_income.append(k)
        else:
            kiang_only_nonzero_income.append((k, cnt))

    of_only_cands = sorted(of_all_cands - set(kiang_cand_corp_stats.keys()))

    # Write outputs
    df_corp = pd.DataFrame(corp_records)
    df_corp.to_csv(os.path.join(OUT_DIR, "01_all_corporate_donations.csv"), index=False, encoding="utf-8-sig")

    # Unique donating corporations
    corp_agg = []
    by_tid = defaultdict(list)
    for rec in corp_records:
        tid_key = rec["tax_id_8"] or f"RAW:{rec['tax_id_raw']}:{rec['donor_name']}"
        by_tid[tid_key].append(rec)

    for tid_key, recs in by_tid.items():
        name_cnt = Counter(r["donor_name"] for r in recs if r["donor_name"])
        most_common_name = name_cnt.most_common(1)[0][0] if name_cnt else ""
        all_names = " | ".join(sorted(name_cnt.keys()))
        els = " | ".join(sorted(set(r["election"] for r in recs)))
        cands = set((r["election"], r["area"], r["candidate"]) for r in recs)
        corp_agg.append(
            {
                "tax_id": tid_key,
                "tax_id_raw_set": " | ".join(sorted(set(r["tax_id_raw"] for r in recs))),
                "donor_name_primary": most_common_name,
                "donor_names_all": all_names,
                "donation_count": len(recs),
                "candidate_count": len(cands),
                "total_gross": sum(r["gross_amount"] for r in recs),
                "total_returned": sum(r["returned_amount"] for r in recs),
                "total_net": sum(r["net_amount"] for r in recs),
                "elections": els,
            }
        )
    df_unique = pd.DataFrame(corp_agg).sort_values("total_gross", ascending=False)
    df_unique.to_csv(os.path.join(OUT_DIR, "01_unique_donating_corps.csv"), index=False, encoding="utf-8-sig")

    df_diff = pd.DataFrame(diff_rows)
    df_diff.to_csv(os.path.join(OUT_DIR, "01_cross_validation_diff.csv"), index=False, encoding="utf-8-sig")

    # Election totals comparison
    el_comp = {}
    for el in ELECTIONS:
        k_sub = [v for (e, _, _), v in kiang_cand_corp_stats.items() if e == el]
        o_sub = [v for (e, _, _), v in of_cand_corp_stats.items() if e == el]
        el_comp[el] = {
            "kiang_candidates": sum(1 for (e, _, _) in kiang_cand_corp_stats if e == el),
            "kiang_corp_rows": sum(x["count"] for x in k_sub),
            "kiang_corp_gross": sum(x["gross"] for x in k_sub),
            "kiang_corp_returned": sum(x["returned"] for x in k_sub),
            "kiang_corp_net": sum(x["net"] for x in k_sub),
            "kiang_summary_corp_gross": kiang_summary_totals[el]["summary_corp_gross"],
            "openfun_corp_rows": sum(x["count"] for x in o_sub),
            "openfun_corp_gross": sum(x["gross"] for x in o_sub),
            "openfun_corp_returned": sum(x["returned"] for x in o_sub),
            "openfun_corp_net": sum(x["net"] for x in o_sub),
        }

    # Check historical candidates.csv coverage
    cand_csv_prefixes = set()
    cand_csv_path = os.path.join(BASE, "raw/kiang_ardata/data/candidates.csv")
    if os.path.exists(cand_csv_path):
        with open(cand_csv_path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                cand_csv_prefixes.add(r.get("election", "").split(">")[0].strip())

    report = {
        "zip_stats": {
            "total_zips_in_6_elections": len(all_zips),
            "unmatched_zip_names": unmatched,
            "dedup_zips_total": len(dedup_zips),
            "dedup_serial1_candidates": len(serial1_zips),
            "dedup_serial_ge2_remain_reports": len(serial_ge2_zips),
            "serial_ge2_total_income_rows": s2_total_rows,
            "serial_ge2_corp_rows": s2_corp_rows,
            "serial_ge2_subjects": dict(s2_subjects),
        },
        "validation_a_wang_shih_chien": {
            "expected_from_user_file": {
                "total_income_rows": 207,
                "corp_gross": 4326450.0,
                "corp_returned": 250000.0,
                "corp_net": 4076450.0,
            },
            "kiang_actual": wang_shih_chien_kiang,
            "openfun_actual": wang_shih_chien_of,
            "exact_match": (
                wang_shih_chien_kiang is not None
                and wang_shih_chien_kiang["total_income_rows"] == 207
                and wang_shih_chien_kiang["corp_gross"] == 4326450.0
                and wang_shih_chien_kiang["corp_returned"] == 250000.0
                and wang_shih_chien_kiang["corp_net"] == 4076450.0
                and wang_shih_chien_of["total_income_rows"] == 207
                and wang_shih_chien_of["corp_gross"] == 4326450.0
                and wang_shih_chien_of["corp_returned"] == 250000.0
                and wang_shih_chien_of["corp_net"] == 4076450.0
            ),
        },
        "validation_b_zip_details_vs_summary": {
            "total_candidates_checked": val_b_total,
            "exact_match_within_1_twd": val_b_matched,
            "match_rate_pct": round(100.0 * val_b_matched / val_b_total, 4) if val_b_total else 0,
            "diffs": val_b_diffs,
        },
        "validation_c_kiang_vs_openfun": {
            "corp_diff_candidate_count": len(diff_rows),
            "corp_diffs": diff_rows,
            "kiang_only_zero_income_candidates_count": len(kiang_only_zero_income),
            "kiang_only_nonzero_income_candidates": kiang_only_nonzero_income,
            "openfun_only_candidates": of_only_cands,
            "election_comparison": el_comp,
        },
        "validation_d_baseline_summary": {
            "total_corp_donation_rows": len(corp_records),
            "unique_donating_corps": len(df_unique),
            "corr_flag_unique_values": dict(corr_values),
            "returned_flag_unique_values": dict(ret_values),
            "non_8digit_tax_ids": bad_tax_ids,
            "candidates_csv_election_prefixes": sorted(cand_csv_prefixes),
            "party_metadata_available_for_111_113": False,
        },
    }

    with open(os.path.join(OUT_DIR, "01_cross_validation_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
