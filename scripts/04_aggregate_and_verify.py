#!/usr/bin/env python3
"""
步驟 5：依據光電機構清冊 (03_solar_entities_master.csv) 彙總統計各選舉與候選人收受光電政治獻金情形，
並與歐噴 incomes.csv 執行獨立雙源對帳。

產出：
- output/04_donation_details_matched.csv
- output/04_candidate_donations_tier1.csv
- output/04_candidate_donations_tier1_tier2.csv
- output/04_election_summary.csv
- output/04_company_summary.csv
- output/04_dual_source_solar_reconciliation.csv
"""

import csv
import os
import re
import unicodedata
from collections import defaultdict

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "output")
OPENFUN_CSV = os.path.join(BASE, "raw/openfun/incomes.csv")

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


def parse_amount(val: str) -> float:
    s = norm_text(val).replace(",", "")
    return float(s) if s else 0.0


def aggregate_candidates(df_sub: pd.DataFrame) -> pd.DataFrame:
    if df_sub.empty:
        return pd.DataFrame(
            columns=[
                "election",
                "area",
                "candidate",
                "tier_scope",
                "gross_amount",
                "returned_amount",
                "net_amount",
                "donation_count",
                "corp_count",
                "donors_detail",
            ]
        )
    rows = []
    for (el, area, cand), grp in df_sub.groupby(["election", "area", "candidate"], dropna=False):
        area_s = "" if pd.isna(area) else str(area)
        # Detail by company
        comp_lines = []
        for (tid, nm, tier), cgrp in grp.groupby(["tax_id", "gcis_name", "tier"]):
            cg = cgrp["gross_amount"].sum()
            cn = cgrp["net_amount"].sum()
            cr = cgrp["returned_amount"].sum()
            if cr > 0:
                comp_lines.append((cn, f"{nm}({tid},{tier}):毛額{int(cg):,}/返還{int(cr):,}/淨額{int(cn):,}"))
            else:
                comp_lines.append((cn, f"{nm}({tid},{tier}):{int(cn):,}"))
        comp_lines.sort(key=lambda x: -x[0])
        rows.append(
            {
                "election": el,
                "area": area_s,
                "candidate": cand,
                "gross_amount": grp["gross_amount"].sum(),
                "returned_amount": grp["returned_amount"].sum(),
                "net_amount": grp["net_amount"].sum(),
                "donation_count": len(grp),
                "corp_count": grp["tax_id"].nunique(),
                "donors_detail": " ; ".join(x[1] for x in comp_lines),
            }
        )
    out = pd.DataFrame(rows)
    el_order = {e: i for i, e in enumerate(ELECTIONS)}
    out["_el_ord"] = out["election"].map(el_order)
    out = out.sort_values(["_el_ord", "net_amount", "gross_amount"], ascending=[True, False, False]).drop(columns=["_el_ord"])
    return out


def main():
    df_all = pd.read_csv(
        os.path.join(OUT_DIR, "01_all_corporate_donations.csv"),
        dtype={"tax_id_raw": str, "tax_id_8": str},
        encoding="utf-8-sig",
    ).fillna({"area": "", "returned_flag": "", "tax_id_8": ""})

    df_master = pd.read_csv(
        os.path.join(OUT_DIR, "03_solar_entities_master.csv"),
        dtype={"tax_id": str},
        encoding="utf-8-sig",
    ).fillna("")

    df_all["tax_id"] = df_all["tax_id_8"].where(df_all["tax_id_8"] != "", df_all["tax_id_raw"])
    master_cols = [
        "tax_id",
        "tier",
        "gcis_name",
        "rep_name",
        "associations",
        "official_lists",
        "core_codes",
        "aux_codes",
        "classification_reason",
    ]
    df_matched = df_all.merge(df_master[master_cols], on="tax_id", how="inner")

    detail_cols = [
        "election",
        "area",
        "candidate",
        "serial_year",
        "tx_date",
        "donor_name",
        "tax_id",
        "gcis_name",
        "tier",
        "gross_amount",
        "returned_flag",
        "returned_amount",
        "net_amount",
        "method",
        "deposit_date",
        "associations",
        "official_lists",
        "core_codes",
        "aux_codes",
        "classification_reason",
        "zip_name",
        "zip_version",
    ]
    df_matched_out = df_matched[detail_cols].sort_values(["tier", "election", "net_amount"], ascending=[True, True, False])
    df_matched_out.to_csv(os.path.join(OUT_DIR, "04_donation_details_matched.csv"), index=False, encoding="utf-8-sig")

    # Candidate aggregations
    df_t1 = aggregate_candidates(df_matched[df_matched["tier"] == "Tier 1"])
    df_t1["tier_scope"] = "Tier 1"
    df_t1.to_csv(os.path.join(OUT_DIR, "04_candidate_donations_tier1.csv"), index=False, encoding="utf-8-sig")

    df_t12 = aggregate_candidates(df_matched[df_matched["tier"].isin(["Tier 1", "Tier 2"])])
    df_t12["tier_scope"] = "Tier 1 + Tier 2"
    df_t12.to_csv(os.path.join(OUT_DIR, "04_candidate_donations_tier1_tier2.csv"), index=False, encoding="utf-8-sig")

    # Election summary
    el_rows = []
    for el in ELECTIONS + ["合計"]:
        sub_all = df_all if el == "合計" else df_all[df_all["election"] == el]
        sub_m = df_matched if el == "合計" else df_matched[df_matched["election"] == el]

        def stats(frame):
            if frame.empty:
                return 0, 0, 0, 0.0, 0.0, 0.0
            cands = frame[["election", "area", "candidate"]].drop_duplicates().shape[0]
            corps = frame["tax_id"].nunique()
            rows = len(frame)
            g = frame["gross_amount"].sum()
            r = frame["returned_amount"].sum()
            n = frame["net_amount"].sum()
            return cands, corps, rows, g, r, n

        all_g = sub_all["gross_amount"].sum()
        all_n = sub_all["net_amount"].sum()
        all_rows = len(sub_all)
        all_corps = sub_all["tax_id"].nunique()
        all_cands = sub_all[["election", "area", "candidate"]].drop_duplicates().shape[0]

        t1_s = stats(sub_m[sub_m["tier"] == "Tier 1"])
        t2_s = stats(sub_m[sub_m["tier"] == "Tier 2"])
        t12_s = stats(sub_m[sub_m["tier"].isin(["Tier 1", "Tier 2"])])
        t3_s = stats(sub_m[sub_m["tier"] == "Tier 3"])

        el_rows.append(
            {
                "election": el,
                "all_corp_candidates": all_cands,
                "all_corp_count": all_corps,
                "all_corp_rows": all_rows,
                "all_corp_gross": all_g,
                "all_corp_net": all_n,
                "tier1_candidates": t1_s[0],
                "tier1_corps": t1_s[1],
                "tier1_rows": t1_s[2],
                "tier1_gross": t1_s[3],
                "tier1_returned": t1_s[4],
                "tier1_net": t1_s[5],
                "tier1_share_of_all_corp_net_pct": round(100.0 * t1_s[5] / all_n, 4) if all_n else 0.0,
                "tier2_candidates": t2_s[0],
                "tier2_corps": t2_s[1],
                "tier2_rows": t2_s[2],
                "tier2_gross": t2_s[3],
                "tier2_returned": t2_s[4],
                "tier2_net": t2_s[5],
                "tier12_candidates": t12_s[0],
                "tier12_corps": t12_s[1],
                "tier12_rows": t12_s[2],
                "tier12_gross": t12_s[3],
                "tier12_returned": t12_s[4],
                "tier12_net": t12_s[5],
                "tier12_share_of_all_corp_net_pct": round(100.0 * t12_s[5] / all_n, 4) if all_n else 0.0,
                "tier3_candidates": t3_s[0],
                "tier3_corps": t3_s[1],
                "tier3_rows": t3_s[2],
                "tier3_gross": t3_s[3],
                "tier3_returned": t3_s[4],
                "tier3_net": t3_s[5],
            }
        )
    df_el_sum = pd.DataFrame(el_rows)
    df_el_sum.to_csv(os.path.join(OUT_DIR, "04_election_summary.csv"), index=False, encoding="utf-8-sig")

    # Company summary
    comp_rows = []
    for tid, grp in df_matched.groupby("tax_id"):
        m_row = df_master[df_master["tax_id"] == tid].iloc[0]
        rec_list = []
        for (el, area, cand), cgrp in grp.groupby(["election", "area", "candidate"], dropna=False):
            area_s = f"{area}" if area else "全國"
            cn = cgrp["net_amount"].sum()
            cg = cgrp["gross_amount"].sum()
            cr = cgrp["returned_amount"].sum()
            if cr > 0:
                rec_list.append((cn, f"{el}|{area_s}|{cand}:毛額{int(cg):,}/返還{int(cr):,}/淨額{int(cn):,}"))
            else:
                rec_list.append((cn, f"{el}|{area_s}|{cand}:{int(cn):,}"))
        rec_list.sort(key=lambda x: -x[0])
        comp_rows.append(
            {
                "tier": m_row["tier"],
                "tax_id": tid,
                "gcis_name": m_row["gcis_name"],
                "rep_name": m_row["rep_name"],
                "associations": m_row["associations"],
                "official_lists": m_row["official_lists"],
                "core_codes": m_row["core_codes"],
                "aux_codes": m_row["aux_codes"],
                "classification_reason": m_row["classification_reason"],
                "gross_amount": grp["gross_amount"].sum(),
                "returned_amount": grp["returned_amount"].sum(),
                "net_amount": grp["net_amount"].sum(),
                "donation_count": len(grp),
                "candidate_count": grp[["election", "area", "candidate"]].drop_duplicates().shape[0],
                "elections": " | ".join(sorted(grp["election"].unique())),
                "recipients_detail": " ; ".join(x[1] for x in rec_list),
            }
        )
    df_comp = pd.DataFrame(comp_rows).sort_values(["tier", "net_amount", "gross_amount"], ascending=[True, False, False])
    df_comp.to_csv(os.path.join(OUT_DIR, "04_company_summary.csv"), index=False, encoding="utf-8-sig")

    # Dual-source reconciliation against OpenFun incomes.csv
    tid_to_tier = dict(zip(df_master["tax_id"], df_master["tier"]))
    of_agg = defaultdict(lambda: {"rows": 0, "gross": 0.0, "returned": 0.0, "net": 0.0})
    with open(OPENFUN_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            el = norm_text(row.get("選舉名稱", ""))
            if el not in ELECTIONS:
                continue
            if "營利事業" not in norm_text(row.get("收支科目", "")):
                continue
            tid_raw = norm_text(row.get("身分證／統一編號", ""))
            tid = tid_raw if re.match(r"^\d{8}$", tid_raw) else (tid_raw.zfill(8) if re.match(r"^\d{7}$", tid_raw) else tid_raw)
            tier = tid_to_tier.get(tid)
            if not tier:
                continue
            amt = parse_amount(row.get("收入金額", "0"))
            ret_flag = norm_text(row.get("返還/繳庫", ""))
            ret_amt = amt if ret_flag else 0.0
            net_amt = amt - ret_amt
            for ekey in (el, "合計"):
                st = of_agg[(ekey, tier)]
                st["rows"] += 1
                st["gross"] += amt
                st["returned"] += ret_amt
                st["net"] += net_amt

    rec_rows = []
    for el in ELECTIONS + ["合計"]:
        sub_m = df_matched if el == "合計" else df_matched[df_matched["election"] == el]
        for tier in ("Tier 1", "Tier 2", "Tier 3"):
            km = sub_m[sub_m["tier"] == tier]
            k_rows = len(km)
            k_gross = float(km["gross_amount"].sum())
            k_ret = float(km["returned_amount"].sum())
            k_net = float(km["net_amount"].sum())
            os_ = of_agg[(el, tier)]
            rec_rows.append(
                {
                    "election": el,
                    "tier": tier,
                    "kiang_rows": k_rows,
                    "openfun_rows": os_["rows"],
                    "diff_rows": k_rows - os_["rows"],
                    "kiang_gross": k_gross,
                    "openfun_gross": os_["gross"],
                    "diff_gross": k_gross - os_["gross"],
                    "kiang_returned": k_ret,
                    "openfun_returned": os_["returned"],
                    "diff_returned": k_ret - os_["returned"],
                    "kiang_net": k_net,
                    "openfun_net": os_["net"],
                    "diff_net": k_net - os_["net"],
                }
            )
    df_rec = pd.DataFrame(rec_rows)
    df_rec.to_csv(os.path.join(OUT_DIR, "04_dual_source_solar_reconciliation.csv"), index=False, encoding="utf-8-sig")

    print("=== 04_election_summary.csv ===")
    print(df_el_sum[["election", "all_corp_net", "tier1_candidates", "tier1_corps", "tier1_gross", "tier1_net", "tier12_candidates", "tier12_corps", "tier12_gross", "tier12_net"]].to_string(index=False))
    print("\n=== 04_dual_source_solar_reconciliation.csv (non-zero diffs only) ===")
    nz = df_rec[(df_rec["diff_rows"] != 0) | (df_rec["diff_gross"].abs() > 0.01) | (df_rec["diff_net"].abs() > 0.01)]
    if nz.empty:
        print("ZERO DIFFERENCES ACROSS ALL ELECTIONS AND TIERS between Kiang and OpenFun!")
    else:
        print(nz.to_string(index=False))


if __name__ == "__main__":
    main()
