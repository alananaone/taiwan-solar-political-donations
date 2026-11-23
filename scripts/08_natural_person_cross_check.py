#!/usr/bin/env python3
"""
步驟八（僅使用本機既有快取與產出檔案，不發外部網路請求）：
1. 建立「光電企業負責人／董監事／公協會理監事／水庫及台南爭議人物」自然人名冊 -> output/08_natural_person_roster.csv
2. 比對 raw/openfun/incomes.csv 111年及113年六大選舉「個人捐贈收入」，並依四級防誤判規則標記 L1/L2/L3/X -> output/08_natural_person_donations_matched.csv
3. 產出企業法人與 L1 自然人關係人合併彙總（L2 單獨獨立列出，不計入確定總額） -> output/08_combined_corp_and_person_summary.csv
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "output"
RAW_DIR = BASE_DIR / "raw"
GCIS_MAIN_DIR = RAW_DIR / "kiang_ardata" / "gcis.nat.g0v.tw"
GCIS_EXTRA_DIR = RAW_DIR / "gcis_extra"
INCOMES_CSV = RAW_DIR / "openfun" / "incomes.csv"
CEC_DIR = RAW_DIR / "cec"

COMPANY_CSV = OUT_DIR / "04_company_summary.csv"
CORP_DETAILS_CSV = OUT_DIR / "04_donation_details_matched.csv"
ASSOC_CSV = OUT_DIR / "02_seven_associations_members.csv"
CONTROVERSY_CSV = OUT_DIR / "06_controversy_entities_audit.csv"
CAND_PARTY_CSV = OUT_DIR / "06_candidates_with_cec_party.csv"
PARTY_SUM_CSV = OUT_DIR / "06_party_summary_tier1_tier2.csv"

OUT_ROSTER = OUT_DIR / "08_natural_person_roster.csv"
OUT_MATCHED = OUT_DIR / "08_natural_person_donations_matched.csv"
OUT_COMBINED = OUT_DIR / "08_combined_corp_and_person_summary.csv"

TARGET_ELECTIONS = {
    "111年直轄市市長選舉",
    "111年縣(市)長選舉",
    "111年直轄市議員選舉",
    "111年縣(市)議員選舉",
    "113年立法委員選舉",
    "113年總統、副總統選舉",
}

NON_PERSON_KEYWORDS = (
    "公司", "銀行", "投資", "控股", "開發", "科技", "能源", "電力", "實業",
    "事業", "集團", "商業", "事務所", "中心", "基金會", "協會", "公會", "聯盟",
    "委員會", "醫院", "大學", "政府", "管理處", "股份", "有限", "缺額", "無",
    "法人", "信託", "企管", "工程", "建設", "營造", "光電", "貿易", "顧問",
    "行銷", "工業", "機械", "國際", "社團", "財團", "合夥", "工作室", "企業社",
    "ltd", "inc", "corp", "co.",
)

TW_CITIES = (
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市",
    "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣",
    "南投縣", "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣",
    "臺東縣", "澎湖縣", "金門縣", "連江縣",
)

# 已知台北／新北共同生活與商業登記圈（僅作輔助地區相容判斷，不單獨構成 L1）
METRO_COMPAT = {
    frozenset(("臺北市", "新北市")),
    frozenset(("高雄市", "屏東縣")),
    frozenset(("臺南市", "高雄市")),
    frozenset(("新竹市", "新竹縣")),
    frozenset(("嘉義市", "嘉義縣")),
}

# 引用步驟六已核對之 CEC 邏輯
sys.path.insert(0, str(BASE_DIR / "scripts"))
import importlib.util
_spec = importlib.util.spec_from_file_location("step06", BASE_DIR / "scripts" / "06_enrich_party_and_tenders.py")
step06 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(step06)

# 補入步驟八中若出現退選／初選未正式登記之政治獻金擬參選人（必須經查證後方可填入）
EXTRA_WITHDRAWN_PARTIES: dict[tuple[str, str, str], tuple[str, str, str]] = {
    ("113年立法委員選舉", "高雄市", "趙天麟"): ("民主進步黨", "退選", "113年高雄市第6選區退選擬參選人（步驟六已核實）"),
}


def norm_p_name(s: str) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    t = str(s).strip()
    t = re.sub(r"[（(][^）)]*[）)]", "", t)
    t = t.replace("\u3000", "").replace(" ", "").replace("‧", "").replace("・", "").replace(".", "")
    return t.strip()


def is_valid_natural_person(raw_name: str) -> tuple[bool, str]:
    nm = norm_p_name(raw_name)
    if not nm or len(nm) < 2 or len(nm) > 5:
        return False, ""
    low = nm.lower()
    if any(k in low for k in NON_PERSON_KEYWORDS):
        return False, ""
    if re.search(r"[0-9A-Za-z_/*@#$%&]", nm):
        return False, ""
    return True, nm


def extract_city(text: str) -> str:
    if not text:
        return ""
    t = str(text).strip().replace("台", "臺").replace("\u3000", "").replace(" ", "")
    for c in TW_CITIES:
        if c in t:
            return c
    # Special patterns like 桃園縣 -> 桃園市, 台南縣 -> 臺南市
    legacy = {"桃園縣": "桃園市", "臺北縣": "新北市", "臺中縣": "臺中市", "臺南縣": "臺南市", "高雄縣": "高雄市"}
    for k, v in legacy.items():
        if k in t:
            return v
    return ""


def parse_roc_date(dt_str: str):
    s = re.sub(r"\D", "", str(dt_str or ""))
    if len(s) == 7:
        try:
            y = int(s[:3]) + 1911
            m = int(s[3:5])
            d = int(s[5:7])
            return datetime(y, m, d)
        except ValueError:
            return None
    return None


def load_local_gcis(tid: str) -> dict:
    for d in (GCIS_MAIN_DIR, GCIS_EXTRA_DIR):
        p = d / f"{tid}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")).get("data", {}) or {}
            except Exception:
                return {}
    return {}


def build_roster() -> tuple[pd.DataFrame, list[str]]:
    comp_df = pd.read_csv(COMPANY_CSV, dtype={"tax_id": str})
    t12_df = comp_df[comp_df["tier"].isin(["Tier 1", "Tier 2"])].copy()
    name_to_comp = {}
    for _, r in comp_df.iterrows():
        nm = str(r["gcis_name"]).strip()
        name_to_comp[nm] = (str(r["tax_id"]).strip(), str(r["tier"]).strip())

    roster_rows = []
    rejected_samples = []

    # Source 1: 139 Tier 1+2 GCIS cached JSON
    for _, r in t12_df.iterrows():
        tid = str(r["tax_id"]).strip()
        cname = str(r["gcis_name"]).strip()
        tier = str(r["tier"]).strip()
        assoc = str(r["associations"]) if pd.notna(r["associations"]) else ""
        g = load_local_gcis(tid)
        city = extract_city(
            g.get("公司所在地")
            or g.get("地址")
            or (g.get("財政部") or {}).get("營業地址")
            or g.get("登記機關")
            or ""
        )

        candidates = []
        if g.get("代表人姓名"):
            candidates.append((g.get("代表人姓名"), "代表人"))
        if g.get("負責人姓名"):
            candidates.append((g.get("負責人姓名"), "負責人"))
        for b in g.get("董監事名單") or []:
            if isinstance(b, dict) and b.get("姓名"):
                # 若所代表法人欄位有值，姓名仍可能是被指派的自然人代表；仍需通過人名檢核
                title = str(b.get("職稱") or "董監事").strip()
                corp_rep = str(b.get("所代表法人") or "").strip()
                if corp_rep:
                    title = f"{title}（代表：{corp_rep}）"
                candidates.append((b.get("姓名"), title))
        for m in g.get("經理人名單") or []:
            if isinstance(m, dict) and m.get("姓名"):
                title = str(m.get("職稱") or "經理人").strip()
                candidates.append((m.get("姓名"), title))

        # Deduplicate roles per (person, tid)
        seen_pt = {}
        for raw_nm, role in candidates:
            ok, nm = is_valid_natural_person(raw_nm)
            if not ok:
                if raw_nm and str(raw_nm).strip() not in ("(缺額)", "缺額"):
                    rejected_samples.append(f"[GCIS] {str(raw_nm).strip()}")
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

    # Source 2: Seven Associations non-member officers
    assoc_df = pd.read_csv(ASSOC_CSV, dtype=str)
    non_mem = assoc_df[~assoc_df["role_type"].astype(str).str.contains("會員", na=False)]
    for _, r in non_mem.iterrows():
        raw_nm = r.get("person_name", "")
        ok, nm = is_valid_natural_person(raw_nm)
        if not ok:
            if pd.notna(raw_nm) and str(raw_nm).strip():
                rejected_samples.append(f"[公協會] {str(raw_nm).strip()}")
            continue
        c1 = r.get("company_name_clean")
        c2 = r.get("company_name_raw")
        comp_nm = str(c1 if pd.notna(c1) and str(c1).strip() else (c2 if pd.notna(c2) else "")).strip()
        tid, _ = name_to_comp.get(comp_nm, ("", ""))
        city = ""
        if tid:
            g = load_local_gcis(tid)
            city = extract_city(g.get("公司所在地") or g.get("地址") or (g.get("財政部") or {}).get("營業地址") or "")
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

    # Source 3: 20 reservoir / Tainan controversy entities
    aud_df = pd.read_csv(CONTROVERSY_CSV, dtype={"tax_id": str})
    # Known verified cities for key controversy entities where local GCIS cache is absent
    known_controversy_city = {
        "86685142": "臺北市",  # 台灣汽電共生（內湖）
        "83189970": "臺南市",  # 星曄綠能（烏山頭／台北設籍台南案場）
        "97282032": "臺北市",  # 星能
        "28997300": "新竹縣",  # 元晶太陽能（湖口）
        "54782662": "高雄市",  # 辰亞能源（阿公店）
        "55891060": "臺南市",  # 力暘能源
        "82874121": "臺南市",
        "85117591": "臺南市",
        "82874142": "臺南市",
        "83527640": "臺南市",
        "83560725": "臺南市",
        "64868610": "臺南市",  # 臺鹽綠能
        "45142567": "臺南市",  # 鴻暉國際
        "61800150": "臺南市",  # 晁暘開發
        "53084598": "嘉義縣",  # 向陽優能電力
        "28653781": "新北市",  # 森崴能源（土城）
        "82921412": "新北市",  # 富威電力
        "50791838": "屏東縣",  # 寶晶能源
        "27763753": "新竹市",  # 聯合再生能源
        "16452612": "臺南市",  # 聚恆科技（永康）
    }
    for _, r in aud_df.iterrows():
        tid = str(r["tax_id"]).strip()
        cname = str(r["company_name"]).strip()
        cat = str(r["category"]).strip()
        rep_field = str(r["rep_or_key_person"]).strip()
        g = load_local_gcis(tid)
        city = extract_city(g.get("公司所在地") or g.get("地址") or "") or known_controversy_city.get(tid, "")
        # Extract main name and bracketed names (e.g. "黃志文（總裁：古盛煇）")
        parts = re.split(r"[（(：:）)、；;]", rep_field)
        for p in parts:
            ok, nm = is_valid_natural_person(p)
            if not ok:
                continue
            role_note = "爭議指標負責人／關鍵人" if p in rep_field else "爭議指標人物"
            if "總裁" in rep_field and p in rep_field.split("總裁")[-1]:
                role_note = "集團總裁（關鍵人物）"
            elif "前董事長" in rep_field and p in rep_field.split("前董事長")[-1]:
                role_note = "前董事長（關鍵人物）"
            roster_rows.append({
                "person_name": nm,
                "person_name_norm": nm,
                "source_category": "水庫與台南爭議指標",
                "company_name": cname,
                "tax_id": tid,
                "role_title": role_note,
                "company_city": city,
                "association_or_note": f"{cat}｜{r['role']}",
            })

    roster_df = pd.DataFrame(roster_rows).drop_duplicates(
        subset=["person_name_norm", "source_category", "company_name", "tax_id", "role_title"]
    )
    return roster_df, sorted(set(rejected_samples))


def load_cec_from_local():
    # Only read from disk raw/cec cache
    step06.WITHDRAWN_VERIFIED_PARTIES.update(EXTRA_WITHDRAWN_PARTIES)
    return step06.load_cec_indexes()


def main():
    print("1. 從本機既有快取與產出表萃取自然人名冊……")
    roster_df, rejected = build_roster()
    roster_df.to_csv(OUT_ROSTER, index=False, encoding="utf-8-sig")
    uniq_names = set(roster_df["person_name_norm"])
    print(f"   名冊共計 {len(roster_df)} 筆關聯紀錄、{len(uniq_names)} 位不重複自然人（已自動排除非人名樣本數：{len(rejected)}）。")
    print("   各來源分布：", roster_df.groupby("source_category")["person_name_norm"].nunique().to_dict())

    # Build lookup structures per person_name_norm
    person_profile = defaultdict(lambda: {
        "companies": [],
        "tax_ids": set(),
        "categories": set(),
        "cities": set(),
        "roles": [],
        "raw_links": [],
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
        role_s = f"{r['company_name']}（{r['role_title']}）" if r["company_name"] else f"{r['association_or_note']}（{r['role_title']}）"
        if role_s not in p["roles"]:
            p["roles"].append(role_s)

    # Load corporate donations (Tier 1+2) for E1 co-occurrence check
    corp_det = pd.read_csv(CORP_DETAILS_CSV, dtype={"tax_id": str})
    corp_det["area"] = corp_det["area"].fillna("")
    corp_det = corp_det[corp_det["tier"].isin(["Tier 1", "Tier 2"])].copy()
    corp_det["cand_key"] = corp_det["election"] + "|" + corp_det["area"] + "|" + corp_det["candidate"]
    corp_det["cand_norm"] = corp_det["candidate"].map(step06.norm_text)

    # Map (tax_id, election, cand_norm) -> list of tx_dates, and global solar cand set
    corp_cand_dates = defaultdict(list)
    solar_cand_keys = set(corp_det["cand_key"])
    for _, r in corp_det.iterrows():
        dt = parse_roc_date(r["tx_date"])
        corp_cand_dates[(r["tax_id"], r["election"], r["cand_norm"])].append(dt)

    # Load CEC local indexes
    cec_idx = load_cec_from_local()

    print("2. 掃描本機 raw/openfun/incomes.csv（嚴格限定 111／113 六大選舉個人捐贈收入）……")
    cols = [
        "選舉名稱", "縣市", "擬參選人／政黨", "交易日期", "收支科目",
        "捐贈者／支出對象", "身分證／統一編號", "收入金額", "返還/繳庫", "地址", "聯絡電話",
    ]
    matched_rows = []
    total_pers_6el = 0
    for chunk in pd.read_csv(INCOMES_CSV, usecols=cols, dtype=str, chunksize=150000):
        el_mask = chunk["選舉名稱"].isin(TARGET_ELECTIONS)
        sub_mask = chunk["收支科目"].astype(str).str.strip() == "個人捐贈收入"
        sub = chunk[el_mask & sub_mask].copy()
        total_pers_6el += len(sub)
        sub["donor_norm"] = sub["捐贈者／支出對象"].map(norm_p_name)
        hits = sub[sub["donor_norm"].isin(uniq_names)]
        if len(hits):
            matched_rows.append(hits)

    hits_df = pd.concat(matched_rows, ignore_index=True) if matched_rows else pd.DataFrame(columns=cols + ["donor_norm"])
    print(f"   六大選舉個人捐贈收入總筆數：{total_pers_6el:,}；純姓名命中自然人名冊筆數：{len(hits_df)}（{hits_df['donor_norm'].nunique()} 位姓名）。")

    # Normalize fields on hits_df
    hits_df["area_clean"] = hits_df["縣市"].fillna("").astype(str).str.strip()
    hits_df.loc[hits_df["選舉名稱"] == "113年總統、副總統選舉", "area_clean"] = ""
    hits_df["candidate"] = hits_df["擬參選人／政黨"].fillna("").astype(str).str.strip()
    hits_df["cand_norm"] = hits_df["candidate"].map(step06.norm_text)
    hits_df["cand_key"] = hits_df["選舉名稱"] + "|" + hits_df["area_clean"] + "|" + hits_df["candidate"]

    hits_df["gross_amount"] = pd.to_numeric(hits_df["收入金額"], errors="coerce").fillna(0).astype(int)
    hits_df["ret_flag"] = hits_df["返還/繳庫"].fillna("").astype(str).str.strip()
    hits_df["returned_amount"] = hits_df.apply(lambda r: r["gross_amount"] if r["ret_flag"] else 0, axis=1)
    hits_df["net_amount"] = hits_df["gross_amount"] - hits_df["returned_amount"]

    def extract_id3(raw_id: str) -> str:
        s = str(raw_id or "").strip().upper()
        m = re.match(r"^([A-Z][12]\d)", s)
        return m.group(1) if m else ""

    def extract_phone4(raw_ph: str) -> str:
        s = re.sub(r"\D", "", str(raw_ph or ""))
        return s[:4] if len(s) >= 4 else ""

    hits_df["id_prefix3"] = hits_df["身分證／統一編號"].map(extract_id3)
    hits_df["id_gender"] = hits_df["id_prefix3"].map(lambda x: "男" if len(x) >= 2 and x[1] == "1" else ("女" if len(x) >= 2 and x[1] == "2" else ""))
    hits_df["addr_city"] = hits_df["地址"].map(extract_city)
    hits_df["phone_prefix4"] = hits_df["聯絡電話"].map(extract_phone4)
    hits_df["tx_dt"] = hits_df["交易日期"].map(parse_roc_date)

    # Match CEC parties for all unique recipients in hits_df
    cand_party_cache = {}
    unmatched_cands = []
    for ck in hits_df["cand_key"].unique():
        el, ar, cn = ck.split("|", 2)
        p, vic, psrc = step06.match_candidate_party(cec_idx, el, ar, cn)
        cand_party_cache[ck] = (p, vic, psrc)
        if p in ("UNMATCHED", "待人工複核（同縣市同名異黨）"):
            unmatched_cands.append((el, ar, cn, int(hits_df[hits_df["cand_key"] == ck]["net_amount"].sum())))

    hits_df["party"] = hits_df["cand_key"].map(lambda k: cand_party_cache[k][0])
    hits_df["is_victor"] = hits_df["cand_key"].map(lambda k: cand_party_cache[k][1])
    hits_df["party_source"] = hits_df["cand_key"].map(lambda k: cand_party_cache[k][2])

    # Precompute per-name identity diversity + E2 co-director clusters + E4 repeat solar cands
    name_id_sets = defaultdict(set)
    name_city_sets = defaultdict(set)
    name_cluster_sets = defaultdict(set)
    id_solar_cands = defaultdict(set)  # (donor_norm, id_prefix3) -> set of solar cand_keys
    id_all_cands = defaultdict(set)
    id_phone_counts = defaultdict(set)

    for _, r in hits_df.iterrows():
        nm = r["donor_norm"]
        id3 = r["id_prefix3"]
        ct = r["addr_city"]
        ph4 = r["phone_prefix4"]
        if id3:
            name_id_sets[nm].add(id3)
            id_all_cands[(nm, id3)].add(r["cand_key"])
            if r["cand_key"] in solar_cand_keys:
                id_solar_cands[(nm, id3)].add(r["cand_key"])
            if ph4:
                id_phone_counts[(nm, id3)].add(ph4)
        if ct:
            name_city_sets[nm].add(ct)
        if id3 or ct:
            name_cluster_sets[nm].add((id3, ct))

    # Detect E2 co-director clusters: same tax_id having >=2 distinct roster people donating >= 20,000 with masked ID to same (election, cand_norm)
    co_director_hits = set()  # set of (donor_norm, cand_key)
    e2_rows = []
    for idx, r in hits_df.iterrows():
        nm = r["donor_norm"]
        id3 = r["id_prefix3"]
        amt = int(r["gross_amount"])
        if not id3 or amt < 20000:
            continue
        prof = person_profile[nm]
        ct = r["addr_city"]
        city_ex = bool(ct and ct in prof["cities"])
        city_me = bool(ct and any(frozenset((ct, cc)) in METRO_COMPAT for cc in prof["cities"]))
        city_mis = bool(ct and prof["cities"] and not city_ex and not city_me)
        is_hom = len(name_id_sets[nm]) >= 2 and len(name_city_sets[nm]) >= 2
        if city_mis and is_hom:
            continue
        if r["選舉名稱"] == "113年總統、副總統選舉" and (amt < 50000 or is_hom):
            continue
        for tid in (person_profile[nm]["tax_ids"] or set()):
            e2_rows.append({
                "tax_id": tid, "donor_norm": nm, "cand_key": r["cand_key"],
                "el": r["選舉名稱"], "cn": r["cand_norm"], "tx_dt": r["tx_dt"], "amt": amt,
            })

    if e2_rows:
        for tid_cand, grp in pd.DataFrame(e2_rows).groupby(["tax_id", "el", "cn"]):
            if grp["donor_norm"].nunique() >= 2:
                for _, gr in grp.iterrows():
                    co_director_hits.add((gr["donor_norm"], gr["cand_key"]))

    # Also evaluate per-person primary L1 id3 if strict E1/E2 reveals an unambiguous identity
    confirmed_id3_by_name = defaultdict(set)
    for _, r in hits_df.iterrows():
        nm = r["donor_norm"]
        prof = person_profile[nm]
        id3 = r["id_prefix3"]
        amt = int(r["gross_amount"])
        if not id3:
            continue
        is_hom = len(name_id_sets[nm]) >= 2 and len(name_city_sets[nm]) >= 2
        ct = r["addr_city"]
        city_ok = bool(ct and (ct in prof["cities"] or any(frozenset((ct, cc)) in METRO_COMPAT for cc in prof["cities"])))
        e1_ok = False
        for tid in prof["tax_ids"]:
            dts = corp_cand_dates.get((tid, r["選舉名稱"], r["cand_norm"]), [])
            if dts:
                min_d = min((abs((cdt - r["tx_dt"]).days) for cdt in dts if cdt and r["tx_dt"]), default=999)
                if r["選舉名稱"] == "113年總統、副總統選舉":
                    if amt >= 50000 and not is_hom and city_ok:
                        e1_ok = True
                elif (amt >= 20000 and not (not city_ok and is_hom)) or (amt >= 10000 and min_d <= 30):
                    e1_ok = True
        has_e2 = (nm, r["cand_key"]) in co_director_hits
        if e1_ok or has_e2:
            confirmed_id3_by_name[nm].add(id3)

    # Score every matched donation row under L1 / L2 / L3 / X
    conf_list, ev_list, hom_list, note_list = [], [], [], []
    for _, r in hits_df.iterrows():
        nm = r["donor_norm"]
        prof = person_profile[nm]
        id3 = r["id_prefix3"]
        ct = r["addr_city"]
        amt = int(r["gross_amount"])
        evs = []

        # City consistency check against company registered cities
        city_exact = bool(ct and ct in prof["cities"])
        city_metro = bool(ct and any(frozenset((ct, cc)) in METRO_COMPAT for cc in prof["cities"]))
        city_mismatch = bool(ct and prof["cities"] and not city_exact and not city_metro)

        distinct_ids = name_id_sets[nm]
        distinct_cities = name_city_sets[nm]
        is_multi_id = len(distinct_ids) >= 2
        is_multi_city = len(distinct_cities) >= 2
        is_homonym_conflict = is_multi_id and is_multi_city
        is_pres = (r["選舉名稱"] == "113年總統、副總統選舉")

        # E1: Same candidate as linked corporation (strict amount & timing guardrails)
        e1_valid = False
        e1_min_days = None
        for tid in prof["tax_ids"]:
            dts = corp_cand_dates.get((tid, r["選舉名稱"], r["cand_norm"]), [])
            if dts:
                d_vals = [abs((cdt - r["tx_dt"]).days) for cdt in dts if cdt and r["tx_dt"]]
                min_d = min(d_vals) if d_vals else None
                e1_min_days = min_d if e1_min_days is None else min(e1_min_days, min_d)
                if id3:
                    if is_pres:
                        if amt >= 50000 and not is_homonym_conflict and (city_exact or city_metro):
                            e1_valid = True
                    elif (amt >= 20000 and not (city_mismatch and is_homonym_conflict)) or (amt >= 10000 and min_d is not None and min_d <= 30):
                        e1_valid = True
        if e1_min_days is not None or any((tid, r["選舉名稱"], r["cand_norm"]) in corp_cand_dates for tid in prof["tax_ids"]):
            evs.append(f"E1_SAME_CAND_AS_CORP(Δ{e1_min_days}日)" if e1_min_days is not None else "E1_SAME_CAND_AS_CORP")

        # E2: Same company/group co-director cluster on same candidate
        has_e2 = (nm, r["cand_key"]) in co_director_hits
        if has_e2:
            evs.append("E2_CO_DIRECTOR_CLUSTER")

        # E3: Unique identity in full 6-election personal DB + exact/metro city match
        if len(distinct_ids) == 1 and id3 in distinct_ids and (city_exact or city_metro):
            evs.append("E3_UNIQUE_IDENTITY_CITY_MATCH" if city_exact else "E3_UNIQUE_IDENTITY_METRO_MATCH")

        # E4: Same (name, id3) donates >= 10,000 to >=2 solar-linked candidates
        if id3 and amt >= 10000 and len(id_solar_cands[(nm, id3)]) >= 2:
            evs.append(f"E4_REPEAT_SOLAR_CANDS({len(id_solar_cands[(nm, id3)])}人)")

        # E5: Significant amount >= 50,000
        if amt >= 50000:
            evs.append(f"E5_HIGH_AMT({amt // 10000}萬)")

        other_confirmed = confirmed_id3_by_name.get(nm, set())
        id3_conflict_with_l1 = bool(other_confirmed and id3 and id3 not in other_confirmed)

        has_e3_exact = "E3_UNIQUE_IDENTITY_CITY_MATCH" in evs
        has_e4 = any(x.startswith("E4_") for x in evs)
        has_e5 = amt >= 50000

        if id3_conflict_with_l1:
            conf = "X"
            note = f"同姓名已由企業共現確認他組證號（{','.join(sorted(other_confirmed))}），本筆證號 {id3} 屬不同自然人"
        elif e1_valid:
            conf = "L1"
            note = "高信心：任職企業亦於同屆選舉捐贈同一候選人（含金額／地區／時點檢核）"
        elif has_e2 and not (city_mismatch and is_homonym_conflict):
            conf = "L1"
            note = "高信心：同企業多名負責人／董監事（單筆 ≥ 2 萬具證號）共同捐贈同一候選人"
        elif has_e3_exact and (has_e4 or has_e5) and (not is_pres or has_e4):
            conf = "L1"
            note = "高信心：全庫僅單一證號前3碼且地址與公司登記縣市完全相符，並具高額或跨光電候選人重複捐贈"
        elif has_e4 and (city_exact or city_metro) and not is_multi_id and amt >= 20000:
            conf = "L1"
            note = "高信心：同一證號前3碼跨捐多位光電候選人且生活圈與公司登記地一致"
        elif has_e5 and not city_mismatch and (any(x.startswith("E1_") for x in evs) or not is_homonym_conflict or city_exact or city_metro):
            conf = "L2"
            note = "高度疑似・待人工複核：金額達 5 萬元以上且地區無矛盾，尚缺足夠唯一強閉環證據"
        elif is_homonym_conflict:
            conf = "L3"
            note = f"同名衝突：全庫對應 {len(distinct_ids)} 組證號前3碼（{','.join(sorted(distinct_ids)[:4])}）及 {len(distinct_cities)} 個縣市，缺乏行為共現"
        else:
            conf = "X"
            if city_mismatch:
                note = f"排除：捐贈地址縣市（{ct}）與名冊公司登記地（{','.join(sorted(prof['cities']))}）不符"
            else:
                note = "排除：金額未達 5 萬元門檻且無行為共現或單一強身分閉環"

        conf_list.append(conf)
        ev_list.append("；".join(evs) if evs else "無強證據")
        hom_list.append("HOMONYM_CONFLICT" if is_homonym_conflict else ("MULTI_ID" if is_multi_id else "UNIQUE_ID"))
        note_list.append(note)

    hits_df["match_confidence"] = conf_list
    hits_df["evidence_codes"] = ev_list
    hits_df["homonym_flag"] = hom_list
    hits_df["classification_note"] = note_list
    hits_df["linked_companies"] = hits_df["donor_norm"].map(lambda n: "；".join(person_profile[n]["companies"]))
    hits_df["linked_roles"] = hits_df["donor_norm"].map(lambda n: "；".join(person_profile[n]["roles"][:5]))
    hits_df["linked_source_categories"] = hits_df["donor_norm"].map(lambda n: "；".join(sorted(person_profile[n]["categories"])))
    hits_df["linked_company_cities"] = hits_df["donor_norm"].map(lambda n: "；".join(sorted(person_profile[n]["cities"])))

    out_cols = [
        "match_confidence", "homonym_flag", "evidence_codes", "classification_note",
        "選舉名稱", "area_clean", "candidate", "party", "is_victor", "party_source",
        "交易日期", "donor_norm", "身分證／統一編號", "id_prefix3", "id_gender",
        "addr_city", "地址", "phone_prefix4",
        "gross_amount", "returned_amount", "net_amount",
        "linked_source_categories", "linked_companies", "linked_company_cities", "linked_roles",
    ]
    out_matched = hits_df[out_cols].rename(columns={
        "選舉名稱": "election",
        "area_clean": "area",
        "交易日期": "tx_date",
        "donor_norm": "person_name",
        "身分證／統一編號": "id_masked",
        "地址": "address_masked",
    }).sort_values(["match_confidence", "net_amount", "gross_amount"], ascending=[True, False, False])

    # Check if any L1 or L2 recipient has UNMATCHED CEC party
    l12_unmatched = out_matched[out_matched["match_confidence"].isin(["L1", "L2"]) & (out_matched["party"] == "UNMATCHED")]
    print(f"\n   L1/L2 中選會政黨未命中筆數：{len(l12_unmatched)}")
    if len(l12_unmatched):
        print(l12_unmatched[["match_confidence", "election", "area", "candidate", "person_name", "net_amount"]].drop_duplicates().to_string(index=False))

    out_matched.to_csv(OUT_MATCHED, index=False, encoding="utf-8-sig")

    # Print full summary by confidence level
    print("\n=== 四級防誤判比對分布統計 ===")
    for lvl in ("L1", "L2", "L3", "X"):
        sub = out_matched[out_matched["match_confidence"] == lvl]
        print(f"  {lvl}: {len(sub)} 筆 · {sub['person_name'].nunique()} 人 · {sub['candidate'].nunique()} 位候選人 · 實捐淨額 NT${int(sub['net_amount'].sum()):,}（總申報 NT${int(sub['gross_amount'].sum()):,}）")

    print("\n=== 全部 L1 高信心確認明細 ===")
    l1 = out_matched[out_matched["match_confidence"] == "L1"]
    print(l1[["person_name", "id_prefix3", "addr_city", "linked_company_cities", "candidate", "party", "net_amount", "linked_companies", "evidence_codes"]].to_string(index=False))

    print("\n=== 前 25 筆 L2 高度疑似・待人工複核明細（不計入確定總額） ===")
    l2 = out_matched[out_matched["match_confidence"] == "L2"]
    print(l2[["person_name", "id_prefix3", "addr_city", "linked_company_cities", "candidate", "party", "net_amount", "linked_companies"]].head(25).to_string(index=False))

    # Build 08_combined_corp_and_person_summary.csv (by party across Corp, L1, Combined, plus L2 reference)
    corp_cands = pd.read_csv(CAND_PARTY_CSV)
    party_sum_prev = pd.read_csv(PARTY_SUM_CSV)
    corp_all_p = party_sum_prev[party_sum_prev["scope"] == "Tier 1+2 合計"].copy()

    # Build L1 party summary and Combined party summary
    l1_only = out_matched[out_matched["match_confidence"] == "L1"].copy()
    l1_only["cand_key"] = l1_only["election"] + "|" + l1_only["area"].fillna("") + "|" + l1_only["candidate"]
    l2_only = out_matched[out_matched["match_confidence"] == "L2"].copy()
    l2_only["cand_key"] = l2_only["election"] + "|" + l2_only["area"].fillna("") + "|" + l2_only["candidate"]

    corp_det["cand_key"] = corp_det["election"] + "|" + corp_det["area"] + "|" + corp_det["candidate"]
    corp_cand_party = corp_cands.set_index("cand_key")["party"].to_dict()
    corp_det["party"] = corp_det["cand_key"].map(corp_cand_party)

    all_parties = sorted(set(corp_all_p["party"]) | set(l1_only["party"]) | set(l2_only["party"]))
    comb_rows = []
    tot_corp_net = int(corp_det["net_amount"].sum())
    tot_l1_net = int(l1_only["net_amount"].sum())
    tot_comb_net = tot_corp_net + tot_l1_net

    for party in all_parties:
        sc = corp_det[corp_det["party"] == party]
        sl1 = l1_only[l1_only["party"] == party]
        sl2 = l2_only[l2_only["party"] == party]
        c_net = int(sc["net_amount"].sum())
        l1_net = int(sl1["net_amount"].sum())
        cb_net = c_net + l1_net
        comb_cands = set(sc["cand_key"]) | set(sl1["cand_key"])
        comb_rows.append({
            "party": party,
            "corp_net_amount": c_net,
            "corp_share_pct": round(c_net / tot_corp_net * 100, 2) if tot_corp_net else 0.0,
            "corp_candidate_count": int(sc["cand_key"].nunique()),
            "l1_person_net_amount": l1_net,
            "l1_person_share_pct": round(l1_net / tot_l1_net * 100, 2) if tot_l1_net else 0.0,
            "l1_person_donor_count": int(sl1["person_name"].nunique()),
            "l1_person_candidate_count": int(sl1["cand_key"].nunique()),
            "combined_net_amount": cb_net,
            "combined_share_pct": round(cb_net / tot_comb_net * 100, 2) if tot_comb_net else 0.0,
            "combined_candidate_count": len(comb_cands),
            "l2_suspect_net_excluded": int(sl2["net_amount"].sum()),
            "l2_suspect_tx_count_excluded": int(len(sl2)),
        })

    comb_df = pd.DataFrame(comb_rows).sort_values("combined_net_amount", ascending=False)
    comb_df.to_csv(OUT_COMBINED, index=False, encoding="utf-8-sig")
    print("\n=== 企業法人 vs. L1 自然人 vs. 合併口徑（與獨立 L2 待複核）政黨彙總 ===")
    print(comb_df.to_string(index=False))


if __name__ == "__main__":
    main()
