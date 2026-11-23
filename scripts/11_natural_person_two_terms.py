#!/usr/bin/env python3
"""
步驟十一（跨兩屆自然人董監事四級比對 ＋ 零捐款／高 PCC 對照彙總）：
1. 自兩屆 Tier 1+2 光電企業、20 家水庫／台南爭議大廠（含剛補齊之 18 家董監事 JSON）與七大公協會幹部，建立自然人名冊 -> output/11_natural_person_roster_two_terms.csv
2. 掃描 raw/openfun/incomes.csv 全部 12 類選舉個人捐贈收入，依嚴格四級防誤判規則分級 L1/L2/L3/X（補齊 2018-2024 中選會政黨） -> output/11_natural_person_donations_two_terms.csv
3. 產出跨兩屆（111/113 本屆、107/109 前屆、兩屆合計）× 雙口徑（全部光電 T1+T2、僅 PCC 政府得標企業）合併彙總 -> output/11_combined_corp_and_person_two_terms.csv
4. 整理高 PCC 得標與零直接候選人捐款光電大廠之「候選人企業／政黨專戶／集團穿透／L1 自然人／L2 待複核」對照表 -> output/11_zero_donation_and_high_pcc_summary.csv
"""

from __future__ import annotations

import importlib.util
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "output"
RAW_DIR = BASE_DIR / "raw"
INCOMES_CSV = RAW_DIR / "openfun" / "incomes.csv"


def load_mod(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, BASE_DIR / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


step06 = load_mod("step06", "06_enrich_party_and_tenders.py")
step08 = load_mod("step08", "08_natural_person_cross_check.py")
step09 = load_mod("step09", "09_expand_two_terms_107_109.py")


# 經查證之 L1/L2 自然人受贈退選／無中選會名冊紀錄補充對照表（查核後擴增）
EXTRA_WITHDRAWN_NATURAL_TWO_TERMS: dict[tuple[str, str, str], tuple[str, str, str]] = {
    ("107年縣(市)議員選舉", "屏東縣", "王志豐"): (
        "中國國民黨",
        "未當選／喪失資格",
        "107年屏東縣議員第3選區國民黨參選人，因另案判刑定讞喪失資格（elections.olc.tw 與公開新聞核實）",
    ),
    ("113年立法委員選舉", "臺北市", "楊永明"): (
        "中國國民黨",
        "初選未提名",
        "參與113年臺北市第6選區國民黨立委初選未獲提名（公開新聞核實）",
    ),
}


def build_two_term_roster() -> tuple[pd.DataFrame, list[str]]:
    master_df = pd.read_csv(OUT_DIR / "09_solar_entities_master_two_terms.csv", dtype={"tax_id": str})
    t12_df = master_df[master_df["tier"].isin(["Tier 1", "Tier 2"])].copy()

    name_to_comp = {}
    for _, r in master_df.iterrows():
        name_to_comp[str(r["gcis_name"]).strip()] = (str(r["tax_id"]).strip(), str(r["tier"]).strip())

    roster_rows = []
    rejected = []

    # 1. All two-term Tier 1+2 GCIS boards (using local cache + newly fetched gcis_extra)
    for _, r in t12_df.iterrows():
        tid = str(r["tax_id"]).strip()
        cname = str(r["gcis_name"]).strip()
        tier = str(r["tier"]).strip()
        assoc = str(r["associations"]) if pd.notna(r["associations"]) else ""
        g = step08.load_local_gcis(tid)
        city = step08.extract_city(
            g.get("公司所在地") or g.get("地址") or (g.get("財政部") or {}).get("營業地址") or g.get("登記機關") or ""
        )
        cands = []
        if g.get("代表人姓名"):
            cands.append((g.get("代表人姓名"), "代表人"))
        if g.get("負責人姓名"):
            cands.append((g.get("負責人姓名"), "負責人"))
        for b in g.get("董監事名單") or []:
            if isinstance(b, dict) and b.get("姓名"):
                title = str(b.get("職稱") or "董監事").strip()
                corp_rep = b.get("所代表法人")
                if isinstance(corp_rep, list) and len(corp_rep) >= 2:
                    title = f"{title}（代表：{corp_rep[1]}）"
                elif corp_rep:
                    title = f"{title}（代表：{corp_rep}）"
                cands.append((b.get("姓名"), title))
        for m in g.get("經理人名單") or []:
            if isinstance(m, dict) and m.get("姓名"):
                cands.append((m.get("姓名"), str(m.get("職稱") or "經理人").strip()))

        seen_pt = {}
        for raw_nm, role in cands:
            ok, nm = step08.is_valid_natural_person(raw_nm)
            if not ok:
                if raw_nm and str(raw_nm).strip() not in ("(缺額)", "缺額"):
                    rejected.append(f"[GCIS] {str(raw_nm).strip()}")
                continue
            seen_pt.setdefault(nm, [])
            if role not in seen_pt[nm]:
                seen_pt[nm].append(role)

        for nm, roles in seen_pt.items():
            roster_rows.append({
                "person_name": nm,
                "person_name_norm": nm,
                "source_category": tier,
                "company_name": cname,
                "tax_id": tid,
                "role_title": "；".join(roles),
                "company_city": city,
                "association_or_note": assoc,
            })

    # 2. Seven Associations officers
    assoc_df = pd.read_csv(OUT_DIR / "02_seven_associations_members.csv", dtype=str)
    non_mem = assoc_df[~assoc_df["role_type"].astype(str).str.contains("會員", na=False)]
    for _, r in non_mem.iterrows():
        raw_nm = r.get("person_name", "")
        ok, nm = step08.is_valid_natural_person(raw_nm)
        if not ok:
            continue
        c1, c2 = r.get("company_name_clean"), r.get("company_name_raw")
        comp_nm = str(c1 if pd.notna(c1) and str(c1).strip() else (c2 if pd.notna(c2) else "")).strip()
        tid, _ = name_to_comp.get(comp_nm, ("", ""))
        city = ""
        if tid:
            g = step08.load_local_gcis(tid)
            city = step08.extract_city(g.get("公司所在地") or g.get("地址") or (g.get("財政部") or {}).get("營業地址") or "")
        roster_rows.append({
            "person_name": nm,
            "person_name_norm": nm,
            "source_category": "公協會",
            "company_name": comp_nm,
            "tax_id": tid,
            "role_title": str(r.get("role_type") if pd.notna(r.get("role_type")) else "").strip(),
            "company_city": city,
            "association_or_note": str(r.get("association_name") if pd.notna(r.get("association_name")) else "").strip(),
        })

    # 3. All 20 controversy / major zero-donation solar firms + ALL newly cached gcis_extra board members
    known_controversy_city = {
        "86685142": "臺北市", "83189970": "臺南市", "97282032": "臺北市", "28997300": "新竹縣",
        "54782662": "高雄市", "55891060": "臺南市", "82874121": "臺南市", "85117591": "臺南市",
        "82874142": "臺南市", "83527640": "臺南市", "83560725": "臺南市", "64868610": "臺南市",
        "45142567": "臺南市", "61800150": "臺南市", "53084598": "嘉義縣", "28653781": "新北市",
        "82921412": "新北市", "50791838": "屏東縣", "27763753": "新竹市", "16452612": "臺南市",
    }
    for cat, role_desc, tid, cname, rep_field in step06.CONTROVERSY_ENTITIES:
        g = step08.load_local_gcis(tid)
        city = step08.extract_city(g.get("公司所在地") or g.get("地址") or "") or known_controversy_city.get(tid, "")
        # A. From GCIS board / managers / rep (18 newly cached!)
        board_cands = []
        if g.get("代表人姓名"):
            board_cands.append((g.get("代表人姓名"), "代表人"))
        for b in g.get("董監事名單") or []:
            if isinstance(b, dict) and b.get("姓名"):
                title = str(b.get("職稱") or "董監事").strip()
                corp_rep = b.get("所代表法人")
                if isinstance(corp_rep, list) and len(corp_rep) >= 2:
                    title = f"{title}（代表：{corp_rep[1]}）"
                board_cands.append((b.get("姓名"), title))
        for m in g.get("經理人名單") or []:
            if isinstance(m, dict) and m.get("姓名"):
                board_cands.append((m.get("姓名"), str(m.get("職稱") or "經理人").strip()))

        seen_pt = {}
        for raw_nm, rtitle in board_cands:
            ok, nm = step08.is_valid_natural_person(raw_nm)
            if ok:
                seen_pt.setdefault(nm, [])
                if rtitle not in seen_pt[nm]:
                    seen_pt[nm].append(rtitle)

        # B. Also extract explicit bracketed key persons (e.g. 古盛煇, 陳啟昱)
        for part in re.split(r"[（(：:）)、；;]", rep_field):
            ok, nm = step08.is_valid_natural_person(part)
            if not ok:
                continue
            rnote = "爭議指標負責人／關鍵人"
            if "總裁" in rep_field and part in rep_field.split("總裁")[-1]:
                rnote = "集團總裁（關鍵人物）"
            elif "前董事長" in rep_field and part in rep_field.split("前董事長")[-1]:
                rnote = "前董事長（關鍵人物）"
            seen_pt.setdefault(nm, [])
            if rnote not in seen_pt[nm]:
                seen_pt[nm].append(rnote)

        for nm, roles in seen_pt.items():
            roster_rows.append({
                "person_name": nm,
                "person_name_norm": nm,
                "source_category": "水庫與台南爭議指標",
                "company_name": cname,
                "tax_id": tid,
                "role_title": "；".join(roles),
                "company_city": city,
                "association_or_note": f"{cat}｜{role_desc}",
            })

    roster_df = pd.DataFrame(roster_rows).drop_duplicates(
        subset=["person_name_norm", "source_category", "company_name", "tax_id", "role_title"]
    )
    return roster_df, sorted(set(rejected))


def main():
    print("1. 建立跨兩屆＋爭議大廠完整董監事自然人名冊……")
    roster_df, rejected = build_two_term_roster()
    roster_df.to_csv(OUT_DIR / "11_natural_person_roster_two_terms.csv", index=False, encoding="utf-8-sig")
    uniq_names = set(roster_df["person_name_norm"])
    print(f"   名冊共計 {len(roster_df)} 筆關聯紀錄、{len(uniq_names)} 位不重複自然人（較本屆擴增自完整兩屆＋18 家爭議廠董監事）。")
    print("   各來源人數：", roster_df.groupby("source_category")["person_name_norm"].nunique().to_dict())

    person_profile = defaultdict(lambda: {
        "companies": [], "tax_ids": set(), "categories": set(), "cities": set(), "roles": []
    })
    for _, r in roster_df.iterrows():
        nm = r["person_name_norm"]
        p = person_profile[nm]
        if r["company_name"] and r["company_name"] not in p["companies"]:
            p["companies"].append(r["company_name"])
        if r["tax_id"]:
            p["tax_ids"].add(r["tax_id"])
        p["categories"].add(r["source_category"])
        if r["company_city"]:
            p["cities"].add(r["company_city"])
        rs = f"{r['company_name']}（{r['role_title']}）" if r["company_name"] else f"{r['association_or_note']}（{r['role_title']}）"
        if rs not in p["roles"]:
            p["roles"].append(rs)

    # Load 12-election Tier 1+2 corporate donations & PCC status
    corp_det = pd.read_csv(OUT_DIR / "09_donation_details_two_terms.csv", dtype={"tax_id": str})
    corp_det["area"] = corp_det["area"].fillna("")
    corp_det = corp_det[corp_det["tier"].isin(["Tier 1", "Tier 2"])].copy()
    corp_det["cand_key"] = corp_det["election"] + "|" + corp_det["area"] + "|" + corp_det["candidate"]
    corp_det["cand_norm"] = corp_det["candidate"].map(step06.norm_text)

    pcc_df = pd.read_csv(OUT_DIR / "09_solar_companies_pcc_two_terms.csv", dtype={"tax_id": str})
    pcc_awarded_tids = set(pcc_df[pcc_df["pcc_has_award"] == "Y"]["tax_id"])
    # Also add controversy companies with PCC awards so L1 natural persons linked to PCC-awarded controversy firms are tracked!
    aud06 = pd.read_csv(OUT_DIR / "06_controversy_entities_audit.csv", dtype={"tax_id": str})
    pcc_awarded_tids.update(aud06[aud06["pcc_awarded_count"] > 0]["tax_id"].astype(str))

    corp_cand_dates = defaultdict(list)
    solar_cand_keys = set(corp_det["cand_key"])
    for _, r in corp_det.iterrows():
        corp_cand_dates[(r["tax_id"], r["election"], r["cand_norm"])].append(step08.parse_roc_date(r["tx_date"]))

    cec_idx = step09.load_cec_two_terms()
    step06.WITHDRAWN_VERIFIED_PARTIES.update(EXTRA_WITHDRAWN_NATURAL_TWO_TERMS)

    print("2. 掃描本機 raw/openfun/incomes.csv 全部 12 類選舉個人捐贈收入……")
    cols = [
        "選舉名稱", "縣市", "擬參選人／政黨", "交易日期", "收支科目",
        "捐贈者／支出對象", "身分證／統一編號", "收入金額", "返還/繳庫", "地址", "聯絡電話",
    ]
    all_target_els = set(step09.ALL_ELECTIONS)
    matched_chunks = []
    tot_pers_12 = 0
    for chunk in pd.read_csv(INCOMES_CSV, usecols=cols, dtype=str, chunksize=150000):
        el_m = chunk["選舉名稱"].isin(all_target_els)
        sub_m = chunk["收支科目"].astype(str).str.strip() == "個人捐贈收入"
        sub = chunk[el_m & sub_m].copy()
        tot_pers_12 += len(sub)
        sub["donor_norm"] = sub["捐贈者／支出對象"].map(step08.norm_p_name)
        hits = sub[sub["donor_norm"].isin(uniq_names)]
        if len(hits):
            matched_chunks.append(hits)

    hits_df = pd.concat(matched_chunks, ignore_index=True) if matched_chunks else pd.DataFrame(columns=cols + ["donor_norm"])
    print(f"   12 類選舉個人捐贈總筆數：{tot_pers_12:,}；純姓名命中筆數：{len(hits_df)}（{hits_df['donor_norm'].nunique()} 人）。")

    hits_df["area_clean"] = hits_df["縣市"].fillna("").astype(str).str.strip()
    hits_df.loc[hits_df["選舉名稱"].isin(["113年總統、副總統選舉", "109年總統、副總統選舉"]), "area_clean"] = ""
    hits_df["candidate"] = hits_df["擬參選人／政黨"].fillna("").astype(str).str.strip()
    hits_df["cand_norm"] = hits_df["candidate"].map(step06.norm_text)
    hits_df["cand_key"] = hits_df["選舉名稱"] + "|" + hits_df["area_clean"] + "|" + hits_df["candidate"]
    hits_df["term"] = hits_df["選舉名稱"].map(step09.TERM_MAP)

    hits_df["gross_amount"] = pd.to_numeric(hits_df["收入金額"], errors="coerce").fillna(0).astype(int)
    hits_df["ret_flag"] = hits_df["返還/繳庫"].fillna("").astype(str).str.strip()
    hits_df["returned_amount"] = hits_df.apply(lambda r: r["gross_amount"] if r["ret_flag"] else 0, axis=1)
    hits_df["net_amount"] = hits_df["gross_amount"] - hits_df["returned_amount"]

    def ex_id3(s):
        m = re.match(r"^([A-Z][12]\d)", str(s or "").strip().upper())
        return m.group(1) if m else ""

    def ex_ph4(s):
        d = re.sub(r"\D", "", str(s or ""))
        return d[:4] if len(d) >= 4 else ""

    hits_df["id_prefix3"] = hits_df["身分證／統一編號"].map(ex_id3)
    hits_df["id_gender"] = hits_df["id_prefix3"].map(lambda x: "男" if len(x) >= 2 and x[1] == "1" else ("女" if len(x) >= 2 and x[1] == "2" else ""))
    hits_df["addr_city"] = hits_df["地址"].map(step08.extract_city)
    hits_df["phone_prefix4"] = hits_df["聯絡電話"].map(ex_ph4)
    hits_df["tx_dt"] = hits_df["交易日期"].map(step08.parse_roc_date)

    # Match CEC parties
    cand_party_cache = {}
    for ck in hits_df["cand_key"].unique():
        el, ar, cn = ck.split("|", 2)
        cand_party_cache[ck] = step06.match_candidate_party(cec_idx, el, ar, cn)
    hits_df["party"] = hits_df["cand_key"].map(lambda k: cand_party_cache[k][0])
    hits_df["is_victor"] = hits_df["cand_key"].map(lambda k: cand_party_cache[k][1])
    hits_df["party_source"] = hits_df["cand_key"].map(lambda k: cand_party_cache[k][2])

    # Precompute diversity & co-director clusters across 12 elections
    name_id_sets = defaultdict(set)
    name_city_sets = defaultdict(set)
    id_solar_cands = defaultdict(set)
    for _, r in hits_df.iterrows():
        nm, id3, ct = r["donor_norm"], r["id_prefix3"], r["addr_city"]
        if id3:
            name_id_sets[nm].add(id3)
            if r["cand_key"] in solar_cand_keys:
                id_solar_cands[(nm, id3)].add(r["cand_key"])
        if ct:
            name_city_sets[nm].add(ct)

    PRES_ELS = {"113年總統、副總統選舉", "109年總統、副總統選舉"}

    co_director_hits = set()
    e2_rows = []
    for _, r in hits_df.iterrows():
        nm, id3, amt = r["donor_norm"], r["id_prefix3"], int(r["gross_amount"])
        if not id3 or amt < 20000:
            continue
        prof = person_profile[nm]
        ct = r["addr_city"]
        city_ex = bool(ct and ct in prof["cities"])
        city_me = bool(ct and any(frozenset((ct, cc)) in step08.METRO_COMPAT for cc in prof["cities"]))
        city_mis = bool(ct and prof["cities"] and not city_ex and not city_me)
        is_hom = len(name_id_sets[nm]) >= 2 and len(name_city_sets[nm]) >= 2
        if city_mis and is_hom:
            continue
        if r["選舉名稱"] in PRES_ELS and (amt < 50000 or is_hom):
            continue
        for tid in prof["tax_ids"]:
            e2_rows.append({"tax_id": tid, "donor_norm": nm, "cand_key": r["cand_key"], "el": r["選舉名稱"], "cn": r["cand_norm"]})

    if e2_rows:
        for _, grp in pd.DataFrame(e2_rows).groupby(["tax_id", "el", "cn"]):
            if grp["donor_norm"].nunique() >= 2:
                for _, gr in grp.iterrows():
                    co_director_hits.add((gr["donor_norm"], gr["cand_key"]))

    confirmed_id3_by_name = defaultdict(set)
    for _, r in hits_df.iterrows():
        nm, prof, id3, amt = r["donor_norm"], person_profile[r["donor_norm"]], r["id_prefix3"], int(r["gross_amount"])
        if not id3:
            continue
        is_hom = len(name_id_sets[nm]) >= 2 and len(name_city_sets[nm]) >= 2
        ct = r["addr_city"]
        city_ok = bool(ct and (ct in prof["cities"] or any(frozenset((ct, cc)) in step08.METRO_COMPAT for cc in prof["cities"])))
        e1_ok = False
        for tid in prof["tax_ids"]:
            dts = corp_cand_dates.get((tid, r["選舉名稱"], r["cand_norm"]), [])
            if dts:
                min_d = min((abs((cdt - r["tx_dt"]).days) for cdt in dts if cdt and r["tx_dt"]), default=999)
                if r["選舉名稱"] in PRES_ELS:
                    if amt >= 50000 and not is_hom and city_ok:
                        e1_ok = True
                elif (amt >= 20000 and not (not city_ok and is_hom)) or (amt >= 10000 and min_d <= 30):
                    e1_ok = True
        if e1_ok or (nm, r["cand_key"]) in co_director_hits:
            confirmed_id3_by_name[nm].add(id3)

    conf_list, ev_list, hom_list, note_list = [], [], [], []
    for _, r in hits_df.iterrows():
        nm, prof = r["donor_norm"], person_profile[r["donor_norm"]]
        id3, ct, amt = r["id_prefix3"], r["addr_city"], int(r["gross_amount"])
        evs = []
        city_exact = bool(ct and ct in prof["cities"])
        city_metro = bool(ct and any(frozenset((ct, cc)) in step08.METRO_COMPAT for cc in prof["cities"]))
        city_mismatch = bool(ct and prof["cities"] and not city_exact and not city_metro)

        d_ids, d_cts = name_id_sets[nm], name_city_sets[nm]
        is_multi_id = len(d_ids) >= 2
        is_homonym = is_multi_id and len(d_cts) >= 2
        is_pres = r["選舉名稱"] in PRES_ELS

        e1_valid = False
        e1_min_days = None
        for tid in prof["tax_ids"]:
            dts = corp_cand_dates.get((tid, r["選舉名稱"], r["cand_norm"]), [])
            if dts:
                d_vals = [abs((cdt - r["tx_dt"]).days) for cdt in dts if cdt and r["tx_dt"]]
                md = min(d_vals) if d_vals else None
                e1_min_days = md if e1_min_days is None else (md if md is not None and md < e1_min_days else e1_min_days)
                if id3:
                    if is_pres:
                        if amt >= 50000 and not is_homonym and (city_exact or city_metro):
                            e1_valid = True
                    elif (amt >= 20000 and not (city_mismatch and is_homonym)) or (amt >= 10000 and md is not None and md <= 30):
                        e1_valid = True
        if e1_min_days is not None or any((tid, r["選舉名稱"], r["cand_norm"]) in corp_cand_dates for tid in prof["tax_ids"]):
            evs.append(f"E1_SAME_CAND_AS_CORP(Δ{e1_min_days}日)" if e1_min_days is not None else "E1_SAME_CAND_AS_CORP")

        has_e2 = (nm, r["cand_key"]) in co_director_hits
        if has_e2:
            evs.append("E2_CO_DIRECTOR_CLUSTER")
        if len(d_ids) == 1 and id3 in d_ids and (city_exact or city_metro):
            evs.append("E3_UNIQUE_IDENTITY_CITY_MATCH" if city_exact else "E3_UNIQUE_IDENTITY_METRO_MATCH")
        if id3 and amt >= 10000 and len(id_solar_cands[(nm, id3)]) >= 2:
            evs.append(f"E4_REPEAT_SOLAR_CANDS({len(id_solar_cands[(nm, id3)])}人)")
        if amt >= 50000:
            evs.append(f"E5_HIGH_AMT({amt // 10000}萬)")

        other_conf = confirmed_id3_by_name.get(nm, set())
        id3_conflict = bool(other_conf and id3 and id3 not in other_conf)
        has_e3_exact = "E3_UNIQUE_IDENTITY_CITY_MATCH" in evs
        has_e4 = any(x.startswith("E4_") for x in evs)
        has_e5 = amt >= 50000

        if id3_conflict:
            conf = "X"
            note = f"同姓名已由企業共現確認他組證號（{','.join(sorted(other_conf))}），本筆 {id3} 屬不同自然人"
        elif e1_valid:
            conf = "L1"
            note = "高信心：任職企業亦於同屆選舉捐贈同一候選人（含金額／地區／時點檢核）"
        elif has_e2 and not (city_mismatch and is_homonym):
            conf = "L1"
            note = "高信心：同企業多名負責人／董監事（單筆 ≥ 2 萬具證號）共同捐贈同一候選人"
        elif has_e3_exact and (has_e4 or has_e5) and (not is_pres or has_e4):
            conf = "L1"
            note = "高信心：全庫僅單一證號前3碼且地址與公司登記縣市完全相符，並具高額或跨光電候選人重複捐贈"
        elif has_e4 and (city_exact or city_metro) and not is_multi_id and amt >= 20000:
            conf = "L1"
            note = "高信心：同一證號前3碼跨捐多位光電候選人且生活圈與公司登記地一致"
        elif has_e5 and not city_mismatch and (any(x.startswith("E1_") for x in evs) or not is_homonym or city_exact or city_metro):
            conf = "L2"
            note = "高度疑似・待人工複核：金額達 5 萬元以上且地區無矛盾，尚缺足夠唯一強閉環證據"
        elif is_homonym:
            conf = "L3"
            note = f"同名衝突：全庫對應 {len(d_ids)} 組證號前3碼及 {len(d_cts)} 個縣市，缺乏行為共現"
        else:
            conf = "X"
            note = f"排除：{'地址與公司登記地不符' if city_mismatch else '金額未達 5 萬元且無行為共現或單一強身分閉環'}"

        conf_list.append(conf)
        ev_list.append("；".join(evs) if evs else "無強證據")
        hom_list.append("HOMONYM_CONFLICT" if is_homonym else ("MULTI_ID" if is_multi_id else "UNIQUE_ID"))
        note_list.append(note)

    hits_df["match_confidence"] = conf_list
    hits_df["evidence_codes"] = ev_list
    hits_df["homonym_flag"] = hom_list
    hits_df["classification_note"] = note_list
    hits_df["linked_tax_ids"] = hits_df["donor_norm"].map(lambda n: "；".join(sorted(person_profile[n]["tax_ids"])))
    hits_df["linked_companies"] = hits_df["donor_norm"].map(lambda n: "；".join(person_profile[n]["companies"]))
    hits_df["linked_roles"] = hits_df["donor_norm"].map(lambda n: "；".join(person_profile[n]["roles"][:5]))
    hits_df["linked_source_categories"] = hits_df["donor_norm"].map(lambda n: "；".join(sorted(person_profile[n]["categories"])))
    hits_df["linked_company_cities"] = hits_df["donor_norm"].map(lambda n: "；".join(sorted(person_profile[n]["cities"])))
    hits_df["linked_pcc_awarded"] = hits_df["donor_norm"].map(lambda n: "Y" if (person_profile[n]["tax_ids"] & pcc_awarded_tids) else "N")

    out_cols = [
        "match_confidence", "homonym_flag", "evidence_codes", "classification_note",
        "term", "選舉名稱", "area_clean", "candidate", "party", "is_victor", "party_source",
        "交易日期", "donor_norm", "身分證／統一編號", "id_prefix3", "id_gender",
        "addr_city", "地址", "phone_prefix4",
        "gross_amount", "returned_amount", "net_amount",
        "linked_pcc_awarded", "linked_tax_ids", "linked_source_categories", "linked_companies", "linked_company_cities", "linked_roles",
    ]
    out_matched = hits_df[out_cols].rename(columns={
        "選舉名稱": "election",
        "area_clean": "area",
        "交易日期": "tx_date",
        "donor_norm": "person_name",
        "身分證／統一編號": "id_masked",
        "地址": "address_masked",
    }).sort_values(["match_confidence", "net_amount", "gross_amount"], ascending=[True, False, False])

    l12_unm = out_matched[out_matched["match_confidence"].isin(["L1", "L2"]) & (out_matched["party"] == "UNMATCHED")]
    print(f"   L1/L2 中選會政黨未命中筆數：{len(l12_unm)}")
    if len(l12_unm):
        print(l12_unm[["match_confidence", "election", "area", "candidate", "person_name", "net_amount"]].drop_duplicates().to_string(index=False))

    out_matched.to_csv(OUT_DIR / "11_natural_person_donations_two_terms.csv", index=False, encoding="utf-8-sig")

    print("\n=== 兩屆合計自然人四級比對統計 ===")
    for lvl in ("L1", "L2", "L3", "X"):
        sub = out_matched[out_matched["match_confidence"] == lvl]
        t_prev = int(sub[sub["term"] == "107/109 前屆"]["net_amount"].sum())
        t_curr = int(sub[sub["term"] == "111/113 本屆"]["net_amount"].sum())
        print(f"  {lvl}: {len(sub)} 筆 · {sub['person_name'].nunique()} 人 · 合計實捐淨額 {int(sub['net_amount'].sum()):,} 元（本屆 {t_curr:,} ／ 前屆 {t_prev:,}）")

    print("\n=== 兩屆 L1 高信心確認全量明細（依屆別檢核防同名誤判）===")
    l1 = out_matched[out_matched["match_confidence"] == "L1"]
    print(l1[["term", "person_name", "id_prefix3", "addr_city", "linked_company_cities", "candidate", "party", "net_amount", "linked_companies", "evidence_codes"]].to_string(index=False))

    # 3. Build 11_combined_corp_and_person_two_terms.csv (Term x Scope x Party)
    cands_cec = pd.read_csv(OUT_DIR / "09_candidates_two_terms_with_cec.csv")
    cand_party_map = cands_cec.set_index("cand_key")["party"].to_dict()
    corp_det["party"] = corp_det["cand_key"].map(cand_party_map)
    corp_det["term"] = corp_det["election"].map(step09.TERM_MAP)
    corp_det["is_pcc"] = corp_det["tax_id"].isin(pcc_awarded_tids)

    l1_df = out_matched[out_matched["match_confidence"] == "L1"].copy()
    l1_df["cand_key"] = l1_df["election"] + "|" + l1_df["area"].fillna("") + "|" + l1_df["candidate"]
    l2_df = out_matched[out_matched["match_confidence"] == "L2"].copy()
    l2_df["cand_key"] = l2_df["election"] + "|" + l2_df["area"].fillna("") + "|" + l2_df["candidate"]

    comb_rows = []
    for term_lbl in ("111/113 本屆", "107/109 前屆", "兩屆合計"):
        cd_t = corp_det if term_lbl == "兩屆合計" else corp_det[corp_det["term"] == term_lbl]
        l1_t = l1_df if term_lbl == "兩屆合計" else l1_df[l1_df["term"] == term_lbl]
        l2_t = l2_df if term_lbl == "兩屆合計" else l2_df[l2_df["term"] == term_lbl]

        for scope_lbl, only_pcc in [("全部光電 T1+T2", False), ("僅 PCC 政府得標企業", True)]:
            cd_s = cd_t[cd_t["is_pcc"]] if only_pcc else cd_t
            l1_s = l1_t[l1_t["linked_pcc_awarded"] == "Y"] if only_pcc else l1_t
            l2_s = l2_t[l2_t["linked_pcc_awarded"] == "Y"] if only_pcc else l2_t

            tot_comb = int(cd_s["net_amount"].sum()) + int(l1_s["net_amount"].sum())
            parties = sorted(set(cd_s["party"].dropna()) | set(l1_s["party"].dropna()) | set(l2_s["party"].dropna()))
            for party in parties:
                sc = cd_s[cd_s["party"] == party]
                sl1 = l1_s[l1_s["party"] == party]
                sl2 = l2_s[l2_s["party"] == party]
                c_net = int(sc["net_amount"].sum())
                l1_net = int(sl1["net_amount"].sum())
                cb_net = c_net + l1_net
                comb_cands = set(sc["cand_key"]) | set(sl1["cand_key"])
                comb_rows.append({
                    "term": term_lbl,
                    "scope": scope_lbl,
                    "party": party,
                    "corp_net": c_net,
                    "l1_net": l1_net,
                    "combined_net": cb_net,
                    "combined_share_pct": round(cb_net / tot_comb * 100, 2) if tot_comb > 0 else 0.0,
                    "corp_cands": int(sc["cand_key"].nunique()),
                    "l1_donors": int(sl1["person_name"].nunique()),
                    "l1_cands": int(sl1["cand_key"].nunique()),
                    "combined_cands": len(comb_cands),
                    "l2_excluded_net": int(sl2["net_amount"].sum()),
                    "l2_excluded_tx": int(len(sl2)),
                })

    comb_out = pd.DataFrame(comb_rows).sort_values(["term", "scope", "combined_net"], ascending=[True, True, False])
    comb_out.to_csv(OUT_DIR / "11_combined_corp_and_person_two_terms.csv", index=False, encoding="utf-8-sig")

    # 4. Build 11_zero_donation_and_high_pcc_summary.csv
    party_ann = pd.read_csv(OUT_DIR / "10_party_annual_solar_donations.csv", dtype={"donor_tax_id": str})
    group_pen = pd.read_csv(OUT_DIR / "10_group_penetration_donations.csv", dtype={"donating_tax_id": str})
    all_corp12 = pd.read_csv(OUT_DIR / "09_all_corporate_donations_12elections.csv", dtype={"tax_id_raw": str, "tax_id_8": str})
    all_corp12["tid_key"] = all_corp12["tax_id_8"].fillna("").astype(str).str.strip()

    # Select union of: 20 controversy entities + zero-net PCC solar firms + top 15 PCC awarded solar firms + 泓德能源
    pcc_zero = pcc_df[(pcc_df["pcc_awarded_count"] > 0) & (pcc_df["total_net"] == 0)]
    pcc_top = pcc_df[pcc_df["pcc_awarded_count"] > 0].sort_values(["pcc_awarded_count", "total_net"], ascending=[False, False]).head(18)

    target_tids = []
    target_meta = {}
    for cat, role_desc, tid, cname, rep in step06.CONTROVERSY_ENTITIES:
        target_tids.append(tid)
        target_meta[tid] = (cat, cname, rep)
    for _, r in pd.concat([pcc_zero, pcc_top]).iterrows():
        tid = str(r["tax_id"]).strip()
        if tid not in target_meta:
            target_tids.append(tid)
            target_meta[tid] = (r["tier"], r["gcis_name"], r["rep_name"])
    # Also ensure key solar firms found in Party Annual Accounts (e.g. 寶島陽光／永鑫／泓德等 if zero direct or large party donation)
    for _, r in pcc_df[pcc_df["tax_id"].isin(["45877096", "53911029"])].iterrows():
        tid = str(r["tax_id"]).strip()
        if tid not in target_meta:
            target_tids.append(tid)
            target_meta[tid] = (r["tier"], r["gcis_name"], r["rep_name"])

    summary_rows = []
    for tid in dict.fromkeys(target_tids):
        cat_or_tier, cname, rep = target_meta[tid]
        # PCC info
        pr = pcc_df[pcc_df["tax_id"] == tid]
        ar = aud06[aud06["tax_id"] == tid]
        if len(pr):
            pcc_aw, pcc_sol, pcc_ag = int(pr.iloc[0]["pcc_awarded_count"]), int(pr.iloc[0]["pcc_solar_awarded_count"]), str(pr.iloc[0]["pcc_agencies"] or "")
        elif len(ar):
            pcc_aw, pcc_sol, pcc_ag = int(ar.iloc[0]["pcc_awarded_count"]), int(ar.iloc[0]["pcc_solar_awarded_count"]), str(ar.iloc[0]["pcc_agencies"] or "")
        else:
            pcc_aw, pcc_sol, pcc_ag = 0, 0, ""

        # Two-term direct corporate donations
        sub_c = all_corp12[all_corp12["tid_key"] == tid]
        cand_net = int(sub_c["net_amount"].sum())
        cand_ret = int(sub_c["returned_amount"].sum())

        # Party annual accounts (both direct tid & linked seed name)
        pa_sub = party_ann[(party_ann["donor_tax_id"] == tid) | (party_ann["linked_solar_entity"].astype(str).str.contains(cname[:4], na=False))]
        pa_net = int(pa_sub["net_amount"].sum()) if len(pa_sub) else 0
        pa_parties = "；".join(sorted({f"{r['party']}({int(r['net_amount']):,}元)" for _, r in pa_sub[pa_sub["net_amount"] > 0].iterrows()})) if len(pa_sub) else ""

        # Group penetration linked to this seed firm
        gp_sub = group_pen[group_pen["linked_solar_seeds"].astype(str).str.contains(cname[:4], na=False)]
        gp_net = int(gp_sub["net_amount"].sum()) if len(gp_sub) else 0
        gp_corps = "；".join(sorted(set(gp_sub["donating_company"]))) if len(gp_sub) else ""

        # Natural persons linked to this tid
        l1_sub = l1_df[l1_df["linked_tax_ids"].astype(str).str.contains(tid, na=False)]
        l1_net = int(l1_sub["net_amount"].sum()) if len(l1_sub) else 0
        l1_who = "；".join(sorted({f"{r['person_name']}→{r['candidate']}({int(r['net_amount']):,})" for _, r in l1_sub.iterrows()})) if len(l1_sub) else ""

        l2_sub = l2_df[l2_df["linked_tax_ids"].astype(str).str.contains(tid, na=False)]
        l2_net = int(l2_sub["net_amount"].sum()) if len(l2_sub) else 0

        channels = []
        if cand_net > 0:
            channels.append(f"候選人企業實捐 {cand_net:,}元")
        elif cand_ret > 0:
            channels.append(f"候選人申報全數返還(淨0)")
        if pa_net > 0:
            channels.append(f"政黨專戶 {pa_net:,}元({pa_parties})")
        if gp_net > 0:
            channels.append(f"集團穿透 {gp_net:,}元({gp_corps[:40]})")
        if l1_net > 0:
            channels.append(f"L1自然人 {l1_net:,}元")
        if l2_net > 0:
            channels.append(f"L2待複核 {l2_net:,}元")

        summary_rows.append({
            "tax_id": tid,
            "company_name": cname,
            "category_or_tier": cat_or_tier,
            "rep_or_key_person": rep,
            "pcc_awarded_count": pcc_aw,
            "pcc_solar_count": pcc_sol,
            "pcc_agencies": pcc_ag,
            "cand_corp_net_two_terms": cand_net,
            "cand_corp_returned_two_terms": cand_ret,
            "party_annual_net_107_114": pa_net,
            "group_penetration_net_two_terms": gp_net,
            "l1_person_net_two_terms": l1_net,
            "l2_person_excluded_net": l2_net,
            "l1_detail": l1_who,
            "channel_summary": " ｜ ".join(channels) if channels else "四路徑兩屆均無捐贈紀錄",
        })

    zero_pcc_df = pd.DataFrame(summary_rows).sort_values(["pcc_awarded_count", "cand_corp_net_two_terms", "l1_person_net_two_terms"], ascending=[False, False, False])
    zero_pcc_df.to_csv(OUT_DIR / "11_zero_donation_and_high_pcc_summary.csv", index=False, encoding="utf-8-sig")
    print(f"\n   高 PCC 與爭議企業四路徑對照清冊已寫入（{len(zero_pcc_df)} 家）。")


if __name__ == "__main__":
    main()
