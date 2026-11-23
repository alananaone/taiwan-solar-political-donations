#!/usr/bin/env python3
"""
步驟六：串聯中選會（CEC）官方政黨資料、政府電子採購網（PCC API）得標紀錄，
並針對水庫光電與台南光電案指標企業進行全量政治獻金核查。

輸出：
- output/06_candidates_with_cec_party.csv
- output/06_party_summary_tier1_tier2.csv
- output/06_solar_companies_pcc_tenders.csv
- output/06_controversy_entities_audit.csv
"""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "output"
RAW_DIR = BASE_DIR / "raw"
CEC_DIR = RAW_DIR / "cec"
PCC_DIR = RAW_DIR / "pcc_cache"
PCC_DETAIL_DIR = RAW_DIR / "pcc_tender_detail"

DETAILS_CSV = OUT_DIR / "04_donation_details_matched.csv"
COMPANY_CSV = OUT_DIR / "04_company_summary.csv"
ALL_CORP_CSV = OUT_DIR / "01_all_corporate_donations.csv"

CEC_SOURCES = {
    "2022_mayor_mun.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/data/2022/%E7%9B%B4%E8%BD%84%E5%B8%82%E9%95%B7.csv",
    "2022_mayor_cnt.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/data/2022/%E7%B8%A3%E5%B8%82%E9%95%B7.csv",
    "2022_council_mun.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/data/2022/%E7%9B%B4%E8%BD%84%E5%B8%82%E8%AD%B0%E5%93%A1.csv",
    "2022_council_cnt.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/data/2022/%E7%B8%A3%E5%B8%82%E8%AD%B0%E5%93%A1.csv",
    "2022_chiayi_cand.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/voteData/2022%E5%B9%B4_%E5%98%89%E7%BE%A9%E5%B8%82%E9%95%B7%E9%87%8D%E8%A1%8C%E9%81%B8%E8%88%89/cand.csv",
    "2024_pres_elcand.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/voteData/2024%E7%B8%BD%E7%B5%B1%E7%AB%8B%E5%A7%94/%E7%B8%BD%E7%B5%B1/elcand.csv",
    "2024_pres_elpaty.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/voteData/2024%E7%B8%BD%E7%B5%B1%E7%AB%8B%E5%A7%94/%E7%B8%BD%E7%B5%B1/elpaty.csv",
    "2024_elbase.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/voteData/2024%E7%B8%BD%E7%B5%B1%E7%AB%8B%E5%A7%94/%E7%B8%BD%E7%B5%B1/elbase.csv",
    "2024_ly_dist_elcand.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/voteData/2024%E7%B8%BD%E7%B5%B1%E7%AB%8B%E5%A7%94/%E5%8D%80%E5%9F%9F%E7%AB%8B%E5%A7%94/elcand.csv",
    "2024_ly_dist_elpaty.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/voteData/2024%E7%B8%BD%E7%B5%B1%E7%AB%8B%E5%A7%94/%E5%8D%80%E5%9F%9F%E7%AB%8B%E5%A7%94/elpaty.csv",
    "2024_ly_mtn_elcand.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/voteData/2024%E7%B8%BD%E7%B5%B1%E7%AB%8B%E5%A7%94/%E5%B1%B1%E5%9C%B0%E7%AB%8B%E5%A7%94/elcand.csv",
    "2024_ly_mtn_elpaty.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/voteData/2024%E7%B8%BD%E7%B5%B1%E7%AB%8B%E5%A7%94/%E5%B1%B1%E5%9C%B0%E7%AB%8B%E5%A7%94/elpaty.csv",
    "2024_ly_pln_elcand.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/voteData/2024%E7%B8%BD%E7%B5%B1%E7%AB%8B%E5%A7%94/%E5%B9%B3%E5%9C%B0%E7%AB%8B%E5%A7%94/elcand.csv",
    "2024_ly_pln_elpaty.csv": "https://raw.githubusercontent.com/kiang/db.cec.gov.tw/master/voteData/2024%E7%B8%BD%E7%B5%B1%E7%AB%8B%E5%A7%94/%E5%B9%B3%E5%9C%B0%E7%AB%8B%E5%A7%94/elpaty.csv",
}

# 退選／初選或未完成中選會正式登記之政治獻金擬參選人（每筆須經公開提名與媒體紀錄人工核對）
# 格式：(election, area, candidate) -> (party, is_victor_status, verification_note)
WITHDRAWN_VERIFIED_PARTIES: dict[tuple[str, str, str], tuple[str, str, str]] = {
    ("113年立法委員選舉", "高雄市", "趙天麟"): (
        "民主進步黨",
        "退選",
        "獲民主進步黨提名高雄市第6選區連任，2023年10月宣布退選（公開新聞與中選會名冊更替核對）",
    ),
}

SOLAR_TENDER_KEYWORDS = (
    "太陽", "光電", "綠能", "發電", "儲能", "能源", "微電網", "屋頂", "水庫", "併網", "電力", "變電", "電力工程"
)
SOLAR_AGENCY_KEYWORDS = (
    "電力", "台電", "台灣自來水", "台糖", "台灣糖業", "水利署", "農田水利", "能源署", "能源局"
)

# 已知重大水庫光電及台南光電司法案件指標企業（皆先透過經濟部商工登記驗證統編與代表人）
CONTROVERSY_ENTITIES = [
    # (類別, 角色說明, 統一編號, 公司名稱, 代表人或相關人物)
    ("水庫水面型光電", "烏山頭水庫光電得標母公司（與公股台電合資背景）", "86685142", "台灣汽電共生股份有限公司", "王振勇"),
    ("水庫水面型光電", "烏山頭水庫光電專案經營子公司（台汽電 100% 轉投資）", "83189970", "星曄綠能股份有限公司", "鄭鉉"),
    ("水庫水面型光電", "烏山頭及台電五水庫水面型光電統包工程執行廠", "97282032", "星能股份有限公司", "郭芳楠"),
    ("水庫水面型光電", "烏山頭等光電案場主要太陽能模組供應商", "28997300", "元晶太陽能科技股份有限公司", "廖國榮（法人代表：偉任投資）"),
    ("水庫水面型光電", "高雄阿公店水庫水面型光電第一、二期得標開發廠", "54782662", "辰亞能源股份有限公司", "柏谷秀信"),
    ("台南光電司法案件", "台南小二甲光電關說案起訴核心集團（2024 年 4 月南檢起訴）", "55891060", "力暘能源股份有限公司", "黃志文（總裁：古盛煇）"),
    ("台南光電司法案件", "力暘集團「五天公司」之一（小二甲涉案專案公司）", "82874121", "天英能源股份有限公司", "陳鳳龍"),
    ("台南光電司法案件", "力暘集團「五天公司」之一（小二甲涉案專案公司）", "85117591", "天心智慧綠能股份有限公司", "陳鳳龍"),
    ("台南光電司法案件", "力暘集團「五天公司」之一（小二甲涉案專案公司）", "82874142", "天柱能源股份有限公司", "陳鳳龍"),
    ("台南光電司法案件", "力暘集團「五天公司」之一（小二甲涉案專案公司）", "83527640", "天任能源股份有限公司", "陳鳳龍"),
    ("台南光電司法案件", "力暘集團「五天公司」之一（小二甲涉案專案公司）", "83560725", "天芮能源股份有限公司", "陳鳳龍"),
    ("台南光電司法案件", "台鹽綠能特別背信與掏空案標的企業（公股轉投資）", "64868610", "臺鹽綠能股份有限公司", "李杰翰（前董事長：陳啟昱）"),
    ("台南光電司法案件", "台鹽綠能案起訴涉案民股合作開發廠商", "45142567", "鴻暉國際科技股份有限公司", "蘇俊仁"),
    ("台南光電司法案件", "台鹽綠能案涉案民股合作開發廠商（注：與桃園晁暘投資 54536352 簡士善無涉）", "61800150", "晁暘開發股份有限公司", "戴妤倩"),
    ("大型綠能／指標對照", "台南嘉義七股漁電共生指標企業（政治獻金申報 30 萬後全額返還）", "53084598", "向陽優能電力股份有限公司", "陳貴光"),
    ("大型綠能／指標對照", "大型綠能上市集團（正崴／永崴集團旗下再生能源主力）", "28653781", "森崴能源股份有限公司", "郭台強"),
    ("大型綠能／指標對照", "森崴能源子公司（綠電交易／售電業）", "82921412", "富威電力股份有限公司", "郝遐鵬"),
    ("大型綠能／指標對照", "南部重要地面及屋頂型太陽能開發集團（蔡佳晋）", "50791838", "寶晶能源股份有限公司", "蔡佳晋"),
    ("大型綠能／指標對照", "太陽能電池與模組上市廠", "27763753", "聯合再生能源股份有限公司", "洪傳獻"),
    ("大型綠能／指標對照", "大型太陽光電 EPC 系統工程廠", "16452612", "聚恆科技股份有限公司", "周恒豪"),
]


def norm_text(s: str) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    return (
        str(s)
        .strip()
        .replace("台", "臺")
        .replace("姗", "姍")
        .replace("釆", "采")
        .replace("\ue018", "聰")
        .replace("\u3000", "")
        .replace(" ", "")
    )


def norm_party(p: str) -> str:
    p = str(p or "").strip()
    if not p or p in ("無", "無黨籍及未經政黨推薦", "無黨籍及未經政黨推薦 ", "連署", "nan"):
        return "無黨籍"
    if p == "臺灣民眾黨":
        return "台灣民眾黨"
    return p


def fetch_or_cache(url: str, local_path: Path) -> bytes:
    if local_path.exists() and local_path.stat().st_size > 0:
        return local_path.read_bytes()
    local_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read()
    local_path.write_bytes(data)
    return data


def load_cec_indexes() -> dict:
    CEC_DIR.mkdir(parents=True, exist_ok=True)
    raw_files = {}
    for fname, url in CEC_SOURCES.items():
        raw_files[fname] = fetch_or_cache(url, CEC_DIR / fname).decode("utf-8-sig")

    # Build base lookup for 2024 (prv_code, city_code) -> city_name
    city_map = {}
    for row in csv.reader(io.StringIO(raw_files["2024_elbase.csv"])):
        if len(row) >= 6 and row[3] == "000" and row[4] == "0000":
            city_map[(row[0], row[1])] = norm_text(row[5])

    def parse_elpaty(csv_txt: str) -> dict[str, str]:
        mp = {}
        for row in csv.reader(io.StringIO(csv_txt)):
            if len(row) >= 2:
                mp[row[0].strip()] = row[1].strip()
        return mp

    # Index: election_label -> list of (area_norm, cand_norm, party, is_victor, raw_area)
    idx: dict[str, list[tuple[str, str, str, str, str]]] = defaultdict(list)

    # 2022 CSVs (with headers)
    mapping_2022 = [
        ("111年直轄市市長選舉", "2022_mayor_mun.csv"),
        ("111年縣(市)長選舉", "2022_mayor_cnt.csv"),
        ("111年直轄市議員選舉", "2022_council_mun.csv"),
        ("111年縣(市)議員選舉", "2022_council_cnt.csv"),
    ]
    for el_name, fname in mapping_2022:
        reader = csv.DictReader(io.StringIO(raw_files[fname]))
        for r in reader:
            idx[el_name].append(
                (
                    norm_text(r["area"]),
                    norm_text(r["cand_name"]),
                    norm_party(r["party"]),
                    "當選" if str(r.get("is_victor", "")).strip().upper() == "Y" else "未當選",
                    r["area"].strip(),
                )
            )

    # Supplement 2022 Chiayi City Mayor re-election (黃敏惠 was elected)
    chiayi_reader = csv.DictReader(io.StringIO(raw_files["2022_chiayi_cand.csv"]))
    for r in chiayi_reader:
        nm = norm_text(r["名字"])
        idx["111年縣(市)長選舉"].append(
            (
                "嘉義市",
                nm,
                norm_party(r["政黨名稱"]),
                "當選" if r["號次"].strip() == "1" else "未當選",
                "嘉義市",
            )
        )

    # 2024 President (cand_no=2 賴清德當選)
    pres_paty = parse_elpaty(raw_files["2024_pres_elpaty.csv"])
    for row in csv.reader(io.StringIO(raw_files["2024_pres_elcand.csv"])):
        if len(row) >= 16:
            # Keep only presidential candidates (col[8] == '1') or match both
            cname = norm_text(row[6])
            party = norm_party(pres_paty.get(row[7].strip(), ""))
            victor = "當選" if row[14].strip() == "*" else "未當選"
            idx["113年總統、副總統選舉"].append(("全國", cname, party, victor, "全國"))

    # 2024 Legislators (district, mountain indigenous, plain indigenous)
    ly_sets = [
        ("2024_ly_dist_elcand.csv", "2024_ly_dist_elpaty.csv", None),
        ("2024_ly_mtn_elcand.csv", "2024_ly_mtn_elpaty.csv", "山地原住民"),
        ("2024_ly_pln_elcand.csv", "2024_ly_pln_elpaty.csv", "平地原住民"),
    ]
    for cand_fn, paty_fn, fixed_area in ly_sets:
        pmap = parse_elpaty(raw_files[paty_fn])
        for row in csv.reader(io.StringIO(raw_files[cand_fn])):
            if len(row) >= 16:
                cname = norm_text(row[6])
                party = norm_party(pmap.get(row[7].strip(), ""))
                victor = "當選" if row[14].strip() == "*" else "未當選"
                area_nm = fixed_area or city_map.get((row[0].strip(), row[1].strip()), "")
                idx["113年立法委員選舉"].append((norm_text(area_nm), cname, party, victor, area_nm))

    return idx


def match_candidate_party(idx: dict, election: str, area: str, candidate: str) -> tuple[str, str, str]:
    key = (election, area, candidate)
    if key in WITHDRAWN_VERIFIED_PARTIES:
        p, vic, note = WITHDRAWN_VERIFIED_PARTIES[key]
        return norm_party(p), vic, f"未登記或退選（{note}）"

    c_norm = norm_text(candidate)
    a_norm = norm_text(area)
    pool = idx.get(election, [])

    # Exact area prefix + candidate name (including indigenous Romanized suffix) match
    def name_matches(pc: str) -> bool:
        return pc == c_norm or (pc.startswith(c_norm) and len(pc) > len(c_norm) and pc[len(c_norm)].isascii())

    hits = []
    for pa, pc, pp, pv, raw_a in pool:
        if not name_matches(pc):
            continue
        if not a_norm:
            hits.append((pp, pv, raw_a))
        elif pa.startswith(a_norm) or a_norm in pa:
            hits.append((pp, pv, raw_a))

    if len(hits) == 1:
        return hits[0][0], hits[0][1], "中選會官方候選人名冊"
    if len(hits) > 1:
        parties = {h[0] for h in hits}
        vics = {h[1] for h in hits}
        if len(parties) == 1:
            return hits[0][0], ("當選" if "當選" in vics else hits[0][1]), f"中選會官方候選人名冊（同名多區一致性比對：{len(hits)} 筆）"
        return "待人工複核（同縣市同名異黨）", "待複核", str(hits)

    # Fallback: same election exact candidate name only if globally unique in that election
    name_hits = [(pp, pv, raw_a) for pa, pc, pp, pv, raw_a in pool if name_matches(pc)]
    if len(name_hits) == 1:
        return name_hits[0][0], name_hits[0][1], f"中選會官方候選人名冊（選區：{name_hits[0][2]}）"

    return "UNMATCHED", "UNMATCHED", ""


def fetch_json_with_backoff(url: str) -> dict:
    delays = [5, 12, 25, 45]
    for attempt in range(len(delays) + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "solar-research/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < len(delays):
                wait_s = delays[attempt]
                print(f"   [HTTP {e.code}] 等待 {wait_s} 秒後重試：{url}")
                time.sleep(wait_s)
                continue
            raise
    return {}


def fetch_pcc_company(tax_id: str) -> dict:
    PCC_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = PCC_DIR / f"{tax_id}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    all_records = []
    page = 1
    total_records = 0
    total_pages = 1
    while page <= total_pages and page <= 10:
        url = f"https://pcc-api.openfun.app/api/searchbycompanyid?query={urllib.parse.quote(tax_id)}&page={page}"
        d = fetch_json_with_backoff(url)
        time.sleep(0.7)
        if page == 1:
            total_records = int(d.get("total_records", 0) or 0)
            total_pages = int(d.get("total_pages", 1) or 1)
        all_records.extend(d.get("records", []))
        if page >= total_pages:
            break
        page += 1

    out = {"tax_id": tax_id, "total_records": total_records, "records": all_records}
    cache_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def fetch_tender_amount(tender_api_url: str, key_slug: str) -> str:
    if not tender_api_url:
        return ""
    PCC_DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in key_slug)
    cpath = PCC_DETAIL_DIR / f"{safe}.json"
    if cpath.exists():
        d = json.loads(cpath.read_text(encoding="utf-8"))
    else:
        url = tender_api_url.replace("http://", "https://")
        try:
            d = fetch_json_with_backoff(url)
            cpath.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            time.sleep(0.6)
        except Exception:
            return ""
    for rec in d.get("records", []):
        det = rec.get("detail", {})
        amt = det.get("決標資料:總決標金額") or det.get("採購資料:預算金額")
        if amt:
            return str(amt).strip()
    return ""


def parse_pcc_summary(tax_id: str, gcis_name: str, pcc_data: dict) -> dict:
    records = pcc_data.get("records", [])
    total_records = int(pcc_data.get("total_records", 0))
    awarded = []
    bid_only = 0
    seen_jobs = set()

    for rec in records:
        brief = rec.get("brief", {}) or {}
        btype = str(brief.get("type", ""))
        title = str(brief.get("title", ""))
        companies = brief.get("companies", {}) or {}
        name_key = companies.get("name_key", {}) or {}
        id_key = companies.get("id_key", {}) or {}

        # Check if THIS company is marked as 得標廠商 (and NOT purely 未得標廠商)
        is_awarded = False
        for k in id_key.get(tax_id, []):
            if "得標廠商" in k and "未得標" not in k:
                is_awarded = True
        if not is_awarded:
            # Also inspect name_key keys belonging to matching company names
            for nm, ks in name_key.items():
                if tax_id in nm or gcis_name[:4] in nm:
                    for k in ks:
                        if "得標廠商" in k and "未得標" not in k:
                            is_awarded = True

        # Only count as procurement bid if decision notice or similar
        job_key = (str(rec.get("unit_id", "")), str(rec.get("job_number", "")), title)
        if is_awarded:
            if job_key not in seen_jobs:
                seen_jobs.add(job_key)
                awarded.append(rec)
        else:
            if "未得標" in json.dumps(name_key, ensure_ascii=False):
                bid_only += 1

    solar_awarded = []
    agencies = []
    for rec in awarded:
        brief = rec.get("brief", {}) or {}
        title = str(brief.get("title", ""))
        unit = str(rec.get("unit_name", "") or "").strip()
        if unit and unit not in agencies:
            agencies.append(unit)
        if any(k in title for k in SOLAR_TENDER_KEYWORDS) or any(k in unit for k in SOLAR_AGENCY_KEYWORDS):
            solar_awarded.append(rec)

    # Fetch exact awarded amount for up to 3 top solar/recent awarded tenders per company if awarded
    sample_strs = []
    for rec in (solar_awarded + [r for r in awarded if r not in solar_awarded])[:4]:
        brief = rec.get("brief", {}) or {}
        dt = str(rec.get("date", ""))
        unit = str(rec.get("unit_name", "") or "")
        title = str(brief.get("title", ""))
        amt = fetch_tender_amount(rec.get("tender_api_url", ""), f"{tax_id}_{rec.get('filename','')}")
        amt_txt = f"｜決標金額：{amt}" if amt else ""
        sample_strs.append(f"[{dt}] {unit}《{title}》{amt_txt}")

    return {
        "pcc_total_records": total_records,
        "pcc_awarded_count": len(awarded),
        "pcc_solar_awarded_count": len(solar_awarded),
        "pcc_bid_unsuccessful_mentions": bid_only,
        "pcc_has_award": "Y" if len(awarded) > 0 else "N",
        "pcc_has_solar_award": "Y" if len(solar_awarded) > 0 else "N",
        "pcc_agencies": "；".join(agencies[:8]),
        "pcc_sample_tenders": " || ".join(sample_strs),
    }


def main():
    print("1. 載入中選會（CEC）111 年與 113 年候選人名冊……")
    cec_idx = load_cec_indexes()

    df = pd.read_csv(DETAILS_CSV, dtype={"tax_id": str})
    df["area"] = df["area"].fillna("")
    t12 = df[df["tier"].isin(["Tier 1", "Tier 2"])].copy()
    t12["cand_key"] = t12["election"] + "|" + t12["area"] + "|" + t12["candidate"]

    # Match CEC parties for all 200 unique (election, area, candidate)
    cands_agg = (
        t12.groupby(["cand_key", "election", "area", "candidate"], as_index=False)
        .agg(
            gross_amount=("gross_amount", "sum"),
            returned_amount=("returned_amount", "sum"),
            net_amount=("net_amount", "sum"),
            tx_count=("tx_date", "count"),
            corp_count=("tax_id", "nunique"),
            t1_net=("net_amount", lambda s: int(s[t12.loc[s.index, "tier"] == "Tier 1"].sum())),
            t2_net=("net_amount", lambda s: int(s[t12.loc[s.index, "tier"] == "Tier 2"].sum())),
            donors_detail=("gcis_name", lambda s: "、".join(sorted(set(s)))),
        )
    )

    parties, victors, psources = [], [], []
    unmatched = []
    for _, r in cands_agg.iterrows():
        p, v, src = match_candidate_party(cec_idx, r["election"], r["area"], r["candidate"])
        parties.append(p)
        victors.append(v)
        psources.append(src)
        if p in ("UNMATCHED", "待人工複核（同縣市同名異黨）"):
            unmatched.append((r["election"], r["area"], r["candidate"], int(r["net_amount"]), r["donors_detail"], p, src))

    cands_agg["party"] = parties
    cands_agg["is_victor"] = victors
    cands_agg["party_source"] = psources

    print(f"   共計 {len(cands_agg)} 人次候選人；未直接於 CEC 名冊命中筆數：{len(unmatched)}")
    for u in unmatched:
        print("   [UNMATCHED]", u)

    # 2. Query PCC API for all 139 Tier 1 + Tier 2 companies
    comp_df = pd.read_csv(COMPANY_CSV, dtype={"tax_id": str})
    comp_df = comp_df[comp_df["tier"].isin(["Tier 1", "Tier 2"])].reset_index(drop=True)
    print(f"2. 查詢政府電子採購網（PCC API）全部 {len(comp_df)} 家 Tier 1＋Tier 2 光電企業標案紀錄……")
    pcc_rows = []
    for idx_i, r in comp_df.iterrows():
        tid = str(r["tax_id"]).strip()
        pcc_raw = fetch_pcc_company(tid)
        summary = parse_pcc_summary(tid, str(r["gcis_name"]), pcc_raw)
        pcc_rows.append({
            "tier": r["tier"],
            "tax_id": tid,
            "gcis_name": r["gcis_name"],
            "rep_name": r["rep_name"],
            "gross_amount": int(r["gross_amount"]),
            "returned_amount": int(r["returned_amount"]),
            "net_amount": int(r["net_amount"]),
            "candidate_count": int(r["candidate_count"]),
            "associations": r["associations"] if pd.notna(r["associations"]) else "",
            **summary,
        })
        if (idx_i + 1) % 30 == 0 or idx_i + 1 == len(comp_df):
            print(f"   進度 {idx_i + 1}/{len(comp_df)}")

    pcc_df = pd.DataFrame(pcc_rows)
    pcc_awarded_tids = set(pcc_df[pcc_df["pcc_has_award"] == "Y"]["tax_id"])
    print(f"   PCC 總查詢完成：共有 {len(pcc_awarded_tids)} 家曾為政府採購得標廠商，其中 {(pcc_df['pcc_solar_awarded_count'] > 0).sum()} 家有明確光電／電力／能源得標紀錄。")

    # Enrich candidate party mapping onto t12 to compute exact party summary across tiers + PCC
    cand_party_map = cands_agg.set_index("cand_key")[["party", "is_victor", "party_source"]].to_dict("index")
    t12["party"] = t12["cand_key"].map(lambda k: cand_party_map[k]["party"])
    t12["is_victor"] = t12["cand_key"].map(lambda k: cand_party_map[k]["is_victor"])
    t12["pcc_has_award"] = t12["tax_id"].map(lambda t: "Y" if t in pcc_awarded_tids else "N")

    # Also add PCC awarded corp breakdown per candidate
    cand_pcc_corps = (
        t12[t12["pcc_has_award"] == "Y"]
        .groupby("cand_key")
        .agg(pcc_corp_count=("tax_id", "nunique"), pcc_net=("net_amount", "sum"))
    )
    cands_agg["pcc_corp_count"] = cands_agg["cand_key"].map(lambda k: int(cand_pcc_corps.loc[k, "pcc_corp_count"]) if k in cand_pcc_corps.index else 0)
    cands_agg["pcc_net_amount"] = cands_agg["cand_key"].map(lambda k: int(cand_pcc_corps.loc[k, "pcc_net"]) if k in cand_pcc_corps.index else 0)

    # Save candidate table
    cands_out = cands_agg.sort_values(["net_amount", "corp_count"], ascending=[False, False])
    cands_out.to_csv(OUT_DIR / "06_candidates_with_cec_party.csv", index=False, encoding="utf-8-sig")

    # Build party summary across 4 scopes
    summary_rows = []
    scopes = [
        ("Tier 1+2 合計", t12),
        ("僅 Tier 1 核心專營", t12[t12["tier"] == "Tier 1"]),
        ("僅 Tier 2 關聯企業", t12[t12["tier"] == "Tier 2"]),
        ("僅具 PCC 政府採購得標紀錄之企業（Tier 1+2）", t12[t12["pcc_has_award"] == "Y"]),
    ]
    for scope_name, sub in scopes:
        tot_net = int(sub["net_amount"].sum())
        for party, pgrp in sub.groupby("party"):
            p_net = int(pgrp["net_amount"].sum())
            c_cnt = int(pgrp["cand_key"].nunique())
            summary_rows.append({
                "scope": scope_name,
                "party": party,
                "candidate_count": c_cnt,
                "elected_count": int(pgrp[pgrp["is_victor"] == "當選"]["cand_key"].nunique()),
                "corp_count": int(pgrp["tax_id"].nunique()),
                "tx_count": int(len(pgrp)),
                "gross_amount": int(pgrp["gross_amount"].sum()),
                "returned_amount": int(pgrp["returned_amount"].sum()),
                "net_amount": p_net,
                "net_share_pct": round(p_net / tot_net * 100, 2) if tot_net > 0 else 0.0,
                "avg_net_per_candidate": int(round(p_net / c_cnt)) if c_cnt > 0 else 0,
            })

    party_sum_df = pd.DataFrame(summary_rows).sort_values(["scope", "net_amount"], ascending=[True, False])
    party_sum_df.to_csv(OUT_DIR / "06_party_summary_tier1_tier2.csv", index=False, encoding="utf-8-sig")

    # Add party breakdown string to PCC companies table
    corp_party_str = {}
    for tid, grp in t12.groupby("tax_id"):
        parts = []
        for party, pg in grp.groupby("party"):
            parts.append(f"{party}:{int(pg['net_amount'].sum()):,}元({pg['cand_key'].nunique()}人)")
        corp_party_str[tid] = "；".join(sorted(parts))
    pcc_df["party_donations_breakdown"] = pcc_df["tax_id"].map(lambda t: corp_party_str.get(t, ""))
    pcc_df = pcc_df.sort_values(["pcc_awarded_count", "net_amount"], ascending=[False, False])
    pcc_df.to_csv(OUT_DIR / "06_solar_companies_pcc_tenders.csv", index=False, encoding="utf-8-sig")

    # 3. Audit reservoir & Tainan controversy companies against FULL 01_all_corporate_donations.csv
    all_corps = pd.read_csv(ALL_CORP_CSV, dtype={"tax_id_8": str})
    all_corps["gross_amount"] = pd.to_numeric(all_corps["gross_amount"], errors="coerce").fillna(0)
    all_corps["returned_amount"] = pd.to_numeric(all_corps["returned_amount"], errors="coerce").fillna(0)
    all_corps["net_amount"] = pd.to_numeric(all_corps["net_amount"], errors="coerce").fillna(0)

    audit_rows = []
    for cat, role, tid, cname, rep in CONTROVERSY_ENTITIES:
        sub = all_corps[all_corps["tax_id_8"] == tid]
        pcc_d = fetch_pcc_company(tid)
        pcc_s = parse_pcc_summary(tid, cname, pcc_d)
        detail = ""
        if len(sub) > 0:
            detail = "；".join(
                f"{r['election']}·{r['candidate']}({int(r['net_amount']):,}元,返還{int(r['returned_amount']):,}元)"
                for _, r in sub.iterrows()
            )
        audit_rows.append({
            "category": cat,
            "role": role,
            "tax_id": tid,
            "company_name": cname,
            "rep_or_key_person": rep,
            "donation_rows_in_6_elections": int(len(sub)),
            "gross_amount": int(sub["gross_amount"].sum()),
            "returned_amount": int(sub["returned_amount"].sum()),
            "net_amount": int(sub["net_amount"].sum()),
            "donation_detail": detail or "六大選舉企業捐贈紀錄為 0 筆",
            "pcc_total_records": pcc_s["pcc_total_records"],
            "pcc_awarded_count": pcc_s["pcc_awarded_count"],
            "pcc_solar_awarded_count": pcc_s["pcc_solar_awarded_count"],
            "pcc_agencies": pcc_s["pcc_agencies"],
        })
    audit_df = pd.DataFrame(audit_rows)
    audit_df.to_csv(OUT_DIR / "06_controversy_entities_audit.csv", index=False, encoding="utf-8-sig")
    print("3. 全部步驟六輸出檔產製完畢。")


if __name__ == "__main__":
    main()
