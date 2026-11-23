#!/usr/bin/env python3
"""
步驟十：深入探尋「在個別候選人名單上沒有捐錢（或淨額為 0）的光電公司」（全採本機優先）
1. 僅補查缺檔之高指標／爭議光電大廠（嚴格 <= 20 家）之經濟部商工董監事 JSON 至 raw/gcis_extra/。
2. 路徑一（政黨年度專戶 107～114 年）：掃描 raw/kiang_ardata/data/parties/account/ 全政黨最高版本年度專戶，
   整理直接光電機構、爭議大廠、公協會／能源署名單及母公司之政黨專戶捐款明細（嚴格獨立列示，不併入候選人總額）。
3. 路徑二（集團穿透）：運用本機 GCIS 商工 JSON（董監事所代表法人／母子公司、同代表人、專屬同址）追蹤非 Tier 1/2 關聯企業對兩屆候選人之捐贈，
   並嚴格剔除共用商辦／商務中心鄰居與高頻姓名代表人（嚴格獨立列示，不併入確定總額）。
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import re
import time
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

csv.field_size_limit(10_000_000)

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw"
OUT_DIR = BASE_DIR / "output"
PARTY_ROOT = RAW_DIR / "kiang_ardata" / "data" / "parties" / "account"
GCIS_MAIN_DIR = RAW_DIR / "kiang_ardata" / "gcis.nat.g0v.tw"
GCIS_EXTRA_DIR = RAW_DIR / "gcis_extra"


def load_mod(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, BASE_DIR / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


step03 = load_mod("step03", "03_build_solar_entity_master.py")
step06 = load_mod("step06", "06_enrich_party_and_tenders.py")
step09 = load_mod("step09", "09_expand_two_terms_107_109.py")

# 嚴格限定最多補查 19 家（<= 20 家上限）：18 家缺檔爭議／大型光電指標廠 ＋ 泓德能源科技
MISSING_HIGH_PROFILE_SOLAR_TIDS = [tid for _, _, tid, _, _ in step06.CONTROVERSY_ENTITIES] + ["45877096"]

ALL_EXCLUSIONS = {**step03.EXPLICIT_EXCLUSIONS, **step09.EXPLICIT_EXCLUSIONS_107_109}

NON_SOLAR_INSTITUTIONAL_SHAREHOLDERS = {
    # 公股機構、金控銀行或純財務／外部法人股東排除清單（視需要於稽核後補充，避免誤將台電或大型財團一般投資列為光電集團）
    "03795904",  # 台灣電力股份有限公司
    "03707901",  # 台灣中油股份有限公司
    "03796507",  # 行政院國發基金等若無捐贈本體不影響
}


def fetch_limited_gcis() -> int:
    """嚴格限制外部補查 <= 20 家本機缺檔之高指標光電大廠。"""
    GCIS_EXTRA_DIR.mkdir(parents=True, exist_ok=True)
    fetched = 0
    for tid in MISSING_HIGH_PROFILE_SOLAR_TIDS:
        p_main = GCIS_MAIN_DIR / f"{tid}.json"
        p_extra = GCIS_EXTRA_DIR / f"{tid}.json"
        if p_main.exists() or p_extra.exists():
            continue
        if fetched >= 20:
            raise RuntimeError("Exceeded strict 20-company GCIS query cap!")
        url = f"https://company.g0v.ronny.tw/api/show/{tid}"
        req = urllib.request.Request(url, headers={"User-Agent": "solar-research/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                txt = resp.read().decode("utf-8")
            p_extra.write_text(txt, encoding="utf-8")
            fetched += 1
            time.sleep(0.35)
        except Exception as e:
            print(f"   [WARN] GCIS 補查失敗 {tid}: {e}")
    return fetched


def load_gcis_data(tid: str) -> dict:
    for d in (GCIS_MAIN_DIR, GCIS_EXTRA_DIR):
        p = d / f"{tid}.json"
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                data = raw.get("data", {})
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
    return {}


def extract_board_corps(gcis_data: dict) -> list[tuple[str, str, str]]:
    """從董監事名單抽出 (corp_tax_id_or_empty, corp_name, relation_title)。"""
    res = []
    for b in gcis_data.get("董監事名單") or []:
        if not isinstance(b, dict):
            continue
        title = step03.norm(b.get("職稱") or "董監事")
        rep_corp = b.get("所代表法人")
        if isinstance(rep_corp, list) and len(rep_corp) >= 2:
            rtid = step03.norm(rep_corp[0])
            rname = step03.norm(rep_corp[1])
            if rname:
                res.append((rtid if re.match(r"^\d{8}$", rtid) else "", rname, f"{title}所代表法人"))
        elif isinstance(rep_corp, str) and rep_corp.strip():
            res.append(("", step03.norm(rep_corp), f"{title}所代表法人"))
        nm = step03.norm(b.get("姓名") or "")
        if nm and any(k in nm for k in ("公司", "銀行", "投資", "控股", "基金會", "社團", "合作社")):
            res.append(("", nm, f"法人{title}"))
    return res


def main():
    print("1. 補查高指標／爭議零捐款光電大廠缺檔之商工董監事 JSON（嚴格上限 <= 20 家）……")
    n_fetched = fetch_limited_gcis()
    print(f"   實際外部補查家數：{n_fetched} 家（上限 20 家）。")

    # Load 12-election corporate donations baseline & two-term solar master
    df_all12 = pd.read_csv(OUT_DIR / "09_all_corporate_donations_12elections.csv", dtype={"tax_id_raw": str, "tax_id_8": str})
    df_all12["area"] = df_all12["area"].fillna("")
    df_all12["tid_key"] = df_all12.apply(
        lambda r: r["tax_id_8"] if pd.notna(r["tax_id_8"]) and str(r["tax_id_8"]).strip() else f"RAW:{r['tax_id_raw']}:{r['donor_name']}",
        axis=1,
    )
    cand_net_by_tid = df_all12.groupby("tid_key")["net_amount"].sum().to_dict()
    cand_gross_by_tid = df_all12.groupby("tid_key")["gross_amount"].sum().to_dict()

    master_df = pd.read_csv(OUT_DIR / "09_solar_entities_master_two_terms.csv", dtype={"tax_id": str})
    t12_df = master_df[master_df["tier"].isin(["Tier 1", "Tier 2"])].copy()
    t12_map = t12_df.set_index("tax_id").to_dict("index")
    t3_tids = set(master_df[master_df["tier"] == "Tier 3"]["tax_id"])

    controversy_map = {tid: (cat, role, cname, rep) for cat, role, tid, cname, rep in step06.CONTROVERSY_ENTITIES}

    # Seed universe for Path 1 & Path 2: Tier 1+2 firms + 20 controversy/major firms
    seed_firms: dict[str, dict] = {}
    for tid, info in t12_map.items():
        seed_firms[tid] = {
            "tax_id": tid,
            "name": info["gcis_name"],
            "seed_type": info["tier"],
            "cand_net": float(cand_net_by_tid.get(tid, 0.0)),
            "cand_gross": float(cand_gross_by_tid.get(tid, 0.0)),
        }
    for tid, (cat, role, cname, rep) in controversy_map.items():
        if tid in seed_firms:
            seed_firms[tid]["seed_type"] += f"｜{cat}"
        else:
            seed_firms[tid] = {
                "tax_id": tid,
                "name": cname,
                "seed_type": cat,
                "cand_net": float(cand_net_by_tid.get(tid, 0.0)),
                "cand_gross": float(cand_gross_by_tid.get(tid, 0.0)),
            }

    # Pre-index corporate shareholders of seed firms AND local all-donors name->tid map
    corp_name_to_tids = defaultdict(set)
    for tid, grp in df_all12.groupby("tid_key"):
        if re.match(r"^\d{8}$", tid):
            for nm in grp["donor_name"].dropna().unique():
                corp_name_to_tids[step03.norm_name_key(nm)].add(tid)
            g = load_gcis_data(tid)
            gnm = step03.norm(g.get("公司名稱") or "")
            if gnm:
                corp_name_to_tids[step03.norm_name_key(gnm)].add(tid)

    # Map parent_tid / parent_name -> set of child solar seed names & tids
    shareholder_tid_to_seeds = defaultdict(list)
    shareholder_name_to_seeds = defaultdict(list)
    for stid, sinfo in seed_firms.items():
        g = load_gcis_data(stid)
        for sh_tid, sh_name, sh_role in extract_board_corps(g):
            if sh_tid in NON_SOLAR_INSTITUTIONAL_SHAREHOLDERS or sh_tid == stid:
                continue
            if sh_tid:
                shareholder_tid_to_seeds[sh_tid].append((stid, sinfo["name"], sh_role))
            nk = step03.norm_name_key(sh_name)
            if nk and len(nk) >= 4:
                shareholder_name_to_seeds[nk].append((stid, sinfo["name"], sh_role))

    # Load 7-assoc & MOEAEA names for catching zero-cand solar companies directly in Party Annual Accounts
    assoc_names = set()
    df_assoc = pd.read_csv(OUT_DIR / "02_seven_associations_members.csv", dtype=str).fillna("")
    for _, r in df_assoc.iterrows():
        for c in ("company_name_clean", "company_name_raw"):
            v = step03.norm_name_key(r.get(c, ""))
            if len(v) >= 3:
                assoc_names.add(v)
    off_names = set()
    df_off = pd.read_csv(OUT_DIR / "02_official_solar_lists.csv", dtype=str).fillna("")
    for _, r in df_off.iterrows():
        if r["category"] not in ("水力發電業", "地熱發電業"):
            v = step03.norm_name_key(r.get("company_name", ""))
            if len(v) >= 3:
                off_names.add(v)

    # =========================================================================
    # PATH 1: Party Annual Accounts (107～114 年, deduplicated highest version)
    # =========================================================================
    print("2. 掃描本機 107～114 年全政黨年度政治獻金專戶（最高版本去重）……")
    dedup_party_zips = {}
    for pdir in sorted(PARTY_ROOT.iterdir()):
        if not pdir.is_dir():
            continue
        for zp in pdir.rglob("*.zip"):
            m = re.match(r"^(\d+)(?:_v(\d+))?\.zip$", zp.name)
            if not m:
                continue
            yr, ver = int(m.group(1)), int(m.group(2) or 1)
            if not (107 <= yr <= 114):
                continue
            key = (pdir.name, yr)
            if key not in dedup_party_zips or ver > dedup_party_zips[key][0]:
                dedup_party_zips[key] = (ver, zp)

    party_solar_rows = []
    solar_name_kws = ("太陽", "光電", "綠能", "綠電", "光儲", "能源", "電力", "發電", "儲能")
    for (party_name, yr), (ver, zp) in sorted(dedup_party_zips.items()):
        with zipfile.ZipFile(zp) as zf:
            if "incomes.csv" not in zf.namelist():
                continue
            with zf.open("incomes.csv") as f:
                for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
                    subj = step09.norm_text(r.get("收支科目", ""))
                    if "營利事業" not in subj:
                        continue
                    tid_raw = step09.norm_text(r.get("身分證／統一編號", ""))
                    tid = tid_raw if re.match(r"^\d{8}$", tid_raw) else (tid_raw.zfill(8) if re.match(r"^\d{7}$", tid_raw) else tid_raw)
                    donor = step09.norm_text(r.get("捐贈者／支出對象", ""))
                    if tid in ALL_EXCLUSIONS or (tid in t3_tids and tid not in seed_firms) or tid in NON_SOLAR_INSTITUTIONAL_SHAREHOLDERS:
                        continue

                    amt = step09.parse_amount(r.get("收入金額", "0"))
                    ret_flag = step09.norm_text(r.get("返還/繳庫", ""))
                    ret_amt = amt if ret_flag else 0.0
                    net_amt = amt - ret_amt

                    nk = step03.norm_name_key(donor)
                    match_role = ""
                    linked_seed = ""
                    seed_cand_net = cand_net_by_tid.get(tid, 0.0)

                    if tid in seed_firms:
                        match_role = f"主清冊／爭議指標本體（{seed_firms[tid]['seed_type']}）"
                        linked_seed = seed_firms[tid]["name"]
                    elif tid in shareholder_tid_to_seeds or nk in shareholder_name_to_seeds:
                        hits = shareholder_tid_to_seeds.get(tid, []) or shareholder_name_to_seeds.get(nk, [])
                        # Keep only if shareholder links to a solar firm (not unrelated generic)
                        match_role = "光電／爭議指標企業之法人股東／母公司"
                        linked_seed = "；".join(sorted({f"{nm}（{rl}）" for _, nm, rl in hits})[:5])
                        seed_cand_net = min(seed_firms[stid]["cand_net"] for stid, _, _ in hits)
                    else:
                        # Check 7-assoc / official lists / local GCIS CORE_SOLAR_CODES
                        in_a = nk in assoc_names
                        in_o = nk in off_names
                        g = load_gcis_data(tid) if re.match(r"^\d{8}$", tid) else {}
                        gnm = step03.norm(g.get("公司名稱") or donor)
                        codes = set()
                        for it in g.get("所營事業資料") or []:
                            if isinstance(it, list) and len(it) >= 1:
                                c = step03.norm(it[0])
                                if re.match(r"^[A-Z]{1,2}\d{5,6}$", c):
                                    codes.add(c)
                        has_core = bool(codes & step03.CORE_SOLAR_CODES)
                        has_kw = any(k in gnm for k in solar_name_kws)
                        if (in_a or in_o) and (has_kw or has_core or "IG03010" in codes or "E601010" in codes):
                            match_role = "七大公協會／能源署名單企業（候選人名單無紀錄）" if not cand_gross_by_tid.get(tid) else "七大公協會／能源署名單企業"
                            linked_seed = gnm
                        elif has_kw and has_core and not (gnm.endswith("行") or gnm.endswith("社")):
                            match_role = "商工登記光電發電本業企業（未見於候選人 Tier1+2）"
                            linked_seed = gnm

                    if match_role:
                        party_solar_rows.append({
                            "party": party_name,
                            "roc_year": yr,
                            "zip_file": zp.name,
                            "tx_date": step09.norm_text(r.get("交易日期", "")),
                            "donor_tax_id": tid,
                            "donor_name": donor,
                            "gross_amount": int(amt),
                            "returned_amount": int(ret_amt),
                            "net_amount": int(net_amt),
                            "returned_flag": ret_flag,
                            "match_role": match_role,
                            "linked_solar_entity": linked_seed,
                            "donor_cand_net_two_terms": int(cand_net_by_tid.get(tid, 0.0)),
                            "seed_cand_net_two_terms": int(seed_cand_net),
                            "is_zero_cand_donor": "Y" if int(seed_cand_net) == 0 else "N",
                        })

    party_df = pd.DataFrame(party_solar_rows).sort_values(["net_amount", "roc_year"], ascending=[False, False]) if party_solar_rows else pd.DataFrame()
    party_df.to_csv(OUT_DIR / "10_party_annual_solar_donations.csv", index=False, encoding="utf-8-sig")
    print(f"   政黨年度專戶（107～114 年）共掃描 {len(dedup_party_zips)} 份政黨年報，命中 {len(party_df)} 筆光電／關聯母公司捐贈。")
    if len(party_df):
        print("   政黨專戶各黨合計（實收淨額）：")
        print(party_df.groupby(["party", "is_zero_cand_donor"])[["gross_amount", "net_amount"]].agg(["count", "sum"]).to_string())
        print("\n   [前 20 筆] 候選人名單為 0 元（或返還至 0）、卻捐贈政黨年度專戶之企業：")
        zonly = party_df[party_df["is_zero_cand_donor"] == "Y"]
        print(zonly[["roc_year", "party", "donor_tax_id", "donor_name", "net_amount", "match_role", "linked_solar_entity"]].head(20).to_string(index=False))

    # =========================================================================
    # PATH 2: Group Penetration (母公司／法人股東／同代表人／專屬同址)
    # =========================================================================
    print("\n3. 執行集團穿透追蹤（母公司／法人股東／同代表人＋地區或共董佐證／專屬同址）……")
    TW_CITIES = (
        "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市",
        "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣",
        "南投縣", "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣",
        "臺東縣", "澎湖縣", "金門縣", "連江縣",
    )
    METRO_PAIRS = {
        frozenset(("臺北市", "新北市")),
        frozenset(("高雄市", "屏東縣")),
        frozenset(("臺南市", "高雄市")),
        frozenset(("新竹市", "新竹縣")),
        frozenset(("嘉義市", "嘉義縣")),
    }

    def city_of(addr_str: str) -> str:
        t = str(addr_str or "").replace("台", "臺").replace(" ", "")
        for ct in TW_CITIES:
            if ct in t:
                return ct
        return ""

    def is_sole_prop(name_str: str) -> bool:
        nm = str(name_str or "").strip()
        return nm.endswith(("行", "社", "銀樓", "工作室", "商行"))

    def extract_board_people(gcis_data: dict) -> set[str]:
        ppl = set()
        for b in gcis_data.get("董監事名單") or []:
            if isinstance(b, dict) and b.get("姓名"):
                nm = step03.norm(b["姓名"])
                if nm and nm != "缺額" and not any(k in nm for k in ("公司", "銀行", "投資", "控股", "基金會")):
                    ppl.add(nm)
        return ppl

    # Build GCIS profiles for all unique 8-digit tax_ids in 12-election corporate donations
    valid_donor_tids = sorted({t for t in df_all12["tid_key"].unique() if re.match(r"^\d{8}$", t)})
    donor_gcis = {}
    addr_counter = Counter()
    rep_counter = Counter()
    for tid in valid_donor_tids:
        g = load_gcis_data(tid)
        if not g:
            continue
        rep = step03.norm(g.get("代表人姓名") or g.get("負責人姓名") or "")
        addr = step03.norm(g.get("公司所在地") or g.get("地址") or "")
        addr_n = step03.norm_name_key(addr)
        gnm = step03.norm(g.get("公司名稱") or g.get("商業名稱") or "")
        donor_gcis[tid] = {
            "name": gnm, "rep": rep, "addr": addr, "addr_norm": addr_n,
            "city": city_of(addr), "board": extract_board_corps(g), "board_people": extract_board_people(g),
        }
        if addr_n:
            addr_counter[addr_n] += 1
        if rep and not is_sole_prop(gnm):
            rep_counter[rep] += 1

    # Seed profiles (including 19 newly fetched zero-donation / high-profile companies)
    seed_rep_map = defaultdict(list)
    seed_addr_map = defaultdict(list)
    for stid, sinfo in seed_firms.items():
        g = load_gcis_data(stid)
        if not g:
            continue
        rep = step03.norm(g.get("代表人姓名") or g.get("負責人姓名") or "")
        addr = step03.norm(g.get("公司所在地") or g.get("地址") or "")
        addr_n = step03.norm_name_key(addr)
        sct = city_of(addr)
        sb_ppl = extract_board_people(g)
        if rep and not is_sole_prop(sinfo["name"]):
            if rep_counter[rep] <= 7:
                seed_rep_map[rep].append((stid, sinfo["name"], sinfo["cand_net"], sct, sb_ppl))
        # Strict anti-coworking/shared-building guard: must contain 號 & (樓 or >=12 chars), NOT 商務, and <= 4 donating firms share exact address
        if addr_n and not is_sole_prop(sinfo["name"]) and "號" in addr_n and ("樓" in addr_n or len(addr_n) >= 12) and "商務" not in addr_n and "共同工作" not in addr_n:
            if addr_counter[addr_n] <= 4:
                seed_addr_map[addr_n].append((stid, sinfo["name"], sinfo["cand_net"]))

    # Cross-city rep pair explicitly verified via corporate registry/media (蔡易達：大力省電照明 & 易晶綠能系統)
    VERIFIED_CROSS_CITY_REP_PAIRS = {("53510262", "24576623")}

    # Scan non-Tier1/2 corporate donors in 12 elections
    excluded_from_pen = set(t12_map.keys()) | set(ALL_EXCLUSIONS.keys()) | NON_SOLAR_INSTITUTIONAL_SHAREHOLDERS
    pen_links = {}
    for tid in valid_donor_tids:
        if tid in excluded_from_pen:
            continue
        dg = donor_gcis.get(tid)
        if not dg:
            continue
        dnk = step03.norm_name_key(dg["name"])
        links = []
        linked_seeds = []
        seed_nets = []

        # Link A: Donating firm is corporate shareholder/parent of a seed solar firm
        if tid in shareholder_tid_to_seeds or dnk in shareholder_name_to_seeds:
            hits = shareholder_tid_to_seeds.get(tid, []) or shareholder_name_to_seeds.get(dnk, [])
            for stid, snm, srole in hits:
                links.append("母公司／法人股東")
                linked_seeds.append(f"{snm}（本體淨額{int(seed_firms[stid]['cand_net']):,}元，{srole}）")
                seed_nets.append(seed_firms[stid]["cand_net"])

        # Link B: Seed solar firm is corporate shareholder on the donating firm's board
        seed_name_map = {step03.norm_name_key(v["name"]): k for k, v in seed_firms.items()}
        for bt, bn, br in dg["board"]:
            bnk = step03.norm_name_key(bn)
            if bt in seed_firms and bt != tid:
                links.append("子公司／轉投資企業")
                linked_seeds.append(f"{seed_firms[bt]['name']}（本體淨額{int(seed_firms[bt]['cand_net']):,}元，出任{br}）")
                seed_nets.append(seed_firms[bt]["cand_net"])
            elif bnk in seed_name_map:
                stid = seed_name_map[bnk]
                if stid != tid:
                    links.append("子公司／轉投資企業")
                    linked_seeds.append(f"{seed_firms[stid]['name']}（本體淨額{int(seed_firms[stid]['cand_net']):,}元，出任{br}）")
                    seed_nets.append(seed_firms[stid]["cand_net"])

        # Link C: Same Rep (exclude sole-props + require same county/metro OR shared co-director OR same brand prefix)
        rep = dg["rep"]
        if rep and not is_sole_prop(dg["name"]) and rep in seed_rep_map:
            for stid, snm, snet, sct, sb_ppl in seed_rep_map[rep]:
                if stid == tid:
                    continue
                city_ok = bool(dg["city"] and sct and (dg["city"] == sct or frozenset((dg["city"], sct)) in METRO_PAIRS))
                co_dir_ok = len((dg["board_people"] & sb_ppl) - {rep}) >= 1
                brand_ok = len(dg["name"]) >= 2 and len(snm) >= 2 and dg["name"][:2] == snm[:2]
                explicit_ok = (tid, stid) in VERIFIED_CROSS_CITY_REP_PAIRS
                if city_ok or co_dir_ok or brand_ok or explicit_ok:
                    links.append("同代表人關聯公司")
                    linked_seeds.append(f"{snm}（代表人：{rep}，本體淨額{int(snet):,}元）")
                    seed_nets.append(snet)

        # Link D: Exclusive same exact address (shared office buildings & sole-props excluded)
        an = dg["addr_norm"]
        if an and not is_sole_prop(dg["name"]) and an in seed_addr_map:
            for stid, snm, snet in seed_addr_map[an]:
                if stid != tid:
                    links.append("專屬同址關聯公司")
                    linked_seeds.append(f"{snm}（同址：{dg['addr']}，本體淨額{int(snet):,}元）")
                    seed_nets.append(snet)

        if links:
            pen_links[tid] = {
                "link_types": "；".join(sorted(set(links))),
                "linked_seeds": "；".join(sorted(set(linked_seeds))[:5]),
                "min_seed_cand_net": min(seed_nets) if seed_nets else 0,
                "has_zero_cand_seed": "Y" if any(int(x) == 0 for x in seed_nets) else "N",
                "is_tier3": "Y" if tid in t3_tids else "N",
            }

    # Build transaction-level output joined with CEC parties if available
    cands_cec_df = pd.read_csv(OUT_DIR / "09_candidates_two_terms_with_cec.csv") if (OUT_DIR / "09_candidates_two_terms_with_cec.csv").exists() else pd.DataFrame()
    cec_idx = step09.load_cec_two_terms()

    pen_df_raw = df_all12[df_all12["tid_key"].isin(pen_links)].copy()
    pen_rows = []
    party_cache = {}
    for _, r in pen_df_raw.iterrows():
        tid = r["tid_key"]
        meta = pen_links[tid]
        ck = (r["election"], r["area"], r["candidate"])
        if ck not in party_cache:
            party_cache[ck] = step06.match_candidate_party(cec_idx, r["election"], r["area"], r["candidate"])
        pty, vic, _ = party_cache[ck]
        pen_rows.append({
            "term": r["term"],
            "election": r["election"],
            "area": r["area"],
            "candidate": r["candidate"],
            "party": pty,
            "is_victor": vic,
            "tx_date": r["tx_date"],
            "donating_tax_id": tid,
            "donating_company": donor_gcis[tid]["name"] or r["donor_name"],
            "donating_rep": donor_gcis[tid]["rep"],
            "is_also_tier3": meta["is_tier3"],
            "link_types": meta["link_types"],
            "linked_solar_seeds": meta["linked_seeds"],
            "has_zero_cand_seed": meta["has_zero_cand_seed"],
            "gross_amount": int(r["gross_amount"]),
            "returned_amount": int(r["returned_amount"]),
            "net_amount": int(r["net_amount"]),
        })

    pen_out = pd.DataFrame(pen_rows).sort_values(["net_amount", "donating_company"], ascending=[False, True]) if pen_rows else pd.DataFrame()
    pen_out.to_csv(OUT_DIR / "10_group_penetration_donations.csv", index=False, encoding="utf-8-sig")
    print(f"   集團穿透共命中 {pen_out['donating_tax_id'].nunique() if len(pen_out) else 0} 家非 Tier 1/2 企業、{len(pen_out)} 筆捐贈，合計實捐淨額 {int(pen_out['net_amount'].sum()) if len(pen_out) else 0:,} 元。")
    if len(pen_out):
        print("\n   [集團穿透各關聯企業前 25 家彙總，供人工覆核防誤判]")
        grp_sum = pen_out.groupby(["donating_tax_id", "donating_company", "donating_rep", "link_types", "has_zero_cand_seed"], as_index=False).agg(
            tx_count=("net_amount", "count"),
            net_sum=("net_amount", "sum"),
            linked=("linked_solar_seeds", "first"),
        ).sort_values("net_sum", ascending=False)
        print(grp_sum.head(25).to_string(index=False))


if __name__ == "__main__":
    main()
