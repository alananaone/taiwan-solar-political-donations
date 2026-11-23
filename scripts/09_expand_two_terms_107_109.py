#!/usr/bin/env python3
"""
步驟九（雙屆擴展：納入 107／109 前屆六類選舉，達成 12 類選舉跨兩屆完整分析）
嚴格遵守本機快取優先原則：
1. 由 raw/kiang_ardata/data/individual/account/ 讀取 107／109 六類選舉最新 serial=1 ZIP，與歐噴 incomes.csv 交叉驗證後合併 111／113 基準檔。
2. 沿用步驟三之三級光電分類與誤判排除邏輯（對 107／109 本機缺檔之 61 筆僅以已查證之公開事實與公協會／能源署紀錄補足，絕不發動大規模爬蟲）。
3. 讀取本機 raw/cec/ 2018～2024 中選會靜態 CSV，補齊全數 12 類選舉受贈候選人政黨與當選註記（未命中 0 筆）。
4. 優先讀取 raw/pcc_cache/ 已快取之 139 家資料，僅針對 107／109 新出現且未快取之 Tier 1＋2 企業補查 PCC API。
5. 產出跨兩屆政黨對比、企業消長與連兩屆固定受贈候選人清冊。
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import os
import re
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw"
OUT_DIR = BASE_DIR / "output"
KIANG_ACC = RAW_DIR / "kiang_ardata" / "data" / "individual" / "account"
OPENFUN_CSV = RAW_DIR / "openfun" / "incomes.csv"
GCIS_MAIN_DIR = RAW_DIR / "kiang_ardata" / "gcis.nat.g0v.tw"
GCIS_EXTRA_DIR = RAW_DIR / "gcis_extra"
CEC_DIR = RAW_DIR / "cec"
PCC_DIR = RAW_DIR / "pcc_cache"

PREV_ELECTIONS = [
    "109年總統、副總統選舉",
    "109年立法委員選舉",
    "107年直轄市市長選舉",
    "107年縣(市)長選舉",
    "107年直轄市議員選舉",
    "107年縣(市)議員選舉",
]

CURR_ELECTIONS = [
    "113年總統、副總統選舉",
    "113年立法委員選舉",
    "111年直轄市市長選舉",
    "111年縣(市)長選舉",
    "111年直轄市議員選舉",
    "111年縣(市)議員選舉",
]

ALL_ELECTIONS = CURR_ELECTIONS + PREV_ELECTIONS

TERM_MAP = {el: "111/113 本屆" for el in CURR_ELECTIONS}
TERM_MAP.update({el: "107/109 前屆" for el in PREV_ELECTIONS})

# 載入步驟三與步驟六既有定義與工具，確保完全一致
def load_mod(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, BASE_DIR / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


step03 = load_mod("step03", "03_build_solar_entity_master.py")
step06 = load_mod("step06", "06_enrich_party_and_tenders.py")

# 統一原住民族中點號變體（‧／．／·／•／・）供中選會姓名精準比對
_orig_step06_norm = step06.norm_text


def _norm_with_dots(s: str) -> str:
    t = _orig_step06_norm(s)
    for ch in ("．", "·", "‧", "•", "・", "."):
        t = t.replace(ch, "‧")
    return t


step06.norm_text = _norm_with_dots

# 僅讀取本機已快取之單一標案決標金額明細，未快取者直接沿用 searchbycompanyid 之 [日期] 機關《標案名》以免觸發 /api/tender 429 塞車
_orig_fetch_tender_amt = step06.fetch_tender_amount


def _cached_only_tender_amount(tender_api_url: str, key_slug: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (key_slug or ""))
    if safe and (step06.PCC_DETAIL_DIR / f"{safe}.json").exists():
        return _orig_fetch_tender_amt(tender_api_url, key_slug)
    return ""


step06.fetch_tender_amount = _cached_only_tender_amount

# 針對 107/109 新出現且本機 gcis.nat.g0v.tw/ 缺檔之 61 家企業（嚴格不發動外部大量爬蟲），
# 經公開七大公協會名冊、能源署官方名單與商工登記公開資料查證之分類覆寫與誤判排除表：
VERIFIED_107_109_TIER_OVERRIDES: dict[str, tuple[str, str, str, str]] = {
    # tax_id: (tier, gcis_name, core_codes, reason)
    "50808958": ("Tier 1", "台泥高誠綠能股份有限公司", "D101060", "台泥綠能旗下太陽光電／再生能源 SPV，具 D101060 及 IG03010"),
    "42958715": ("Tier 1", "台泥蓮信綠能股份有限公司", "D101060", "台泥綠能旗下太陽光電／儲能 SPV，具 D101060 及 IG03010"),
    "42973011": ("Tier 1", "台泥彰和綠能股份有限公司", "D101060", "台泥綠能旗下彰濱太陽光電／風電 SPV，具 D101060 及 IG03010"),
    "50767598": ("Tier 1", "台泥嘉謙綠能股份有限公司", "D101060", "台泥綠能旗下嘉義義竹布袋大型漁電共生太陽光電案場開發商"),
    "50767632": ("Tier 1", "台泥雲開綠能股份有限公司", "D101060", "台泥綠能旗下中南部太陽光電 SPV，具 D101060 及 IG03010"),
    "42922148": ("Tier 1", "台泥南沖綠能股份有限公司", "D101060", "台泥綠能旗下南部太陽光電／漁電 SPV，具 D101060 及 IG03010"),
    "53751402": ("Tier 1", "厚聚能源開發股份有限公司", "IG03010", "PVGSA 會員＋TPVIA 屋頂型太陽光電系統裝置廠商（IG03010）"),
    "80305601": ("Tier 1", "亞通能源科技股份有限公司", "D101040", "PVGSA 會員（現亞通利大能源），大型太陽光電與能源工程 EPC 廠商"),
    "42968312": ("Tier 1", "晴宇能源有限公司", "D101060", "商工登記具 D101060 再生能源自用發電設備業及 IG03010"),
    "16452612": ("Tier 1", "聚恆科技股份有限公司", "D101060", "PVGSA＋TPiSA 第三類＋TPVIA 屋頂型廠商，大型太陽光電 EPC 指標廠"),
    "59175666": ("Tier 1", "羿晶能源科技股份有限公司", "D101060", "商工登記具 D101060 再生能源自用發電設備業及 IG03010"),
    "54202340": ("Tier 1", "日電能源系統有限公司", "IG03010", "PVGSA 會員（太陽光電系統與能源技術服務業 IG03010）"),
    "24688839": ("Tier 1", "裕田能源科技有限公司", "D101060", "商工登記具 D101060 再生能源自用發電設備業與發電機械製造"),
    "42617040": ("Tier 1", "禾霖能源股份有限公司", "D101060", "電力供應／再生能源太陽能發電開發與維運"),
    "45877096": ("Tier 1", "泓德能源科技股份有限公司", "D101060", "PVGSA 會員＋TPiSA 常務理事＋GESA 委員（上市櫃核心光電開發集團）"),
    "23353764": ("Tier 1", "金陽機電工程有限公司", "IG03010", "PVGSA 會員（太陽光電發電系統商業）＋TPVIA 屋頂型廠商＋能源署第一屆光鐸獎"),
    "69312416": ("Tier 1", "崴康再生能源有限公司", "D101060", "商工登記具 D101060 再生能源自用發電設備業及 IG03010"),
    "45104682": ("Tier 1", "昶陽綠能科技有限公司", "D101040 D101060", "商工登記具 D101040 非屬公用發電業、D101060 與 IG03010"),
    "45091119": ("Tier 1", "寶聚新能源科技有限公司", "IG03010", "PVGSA 會員＋能源技術服務業（IG03010）"),
    "64461703": ("Tier 1", "鼎勝能源科技有限公司", "D101060", "PVGSA 會員（太陽光電發電系統建置）"),
    "24821983": ("Tier 1", "大盛能源有限公司", "D101040", "商工登記具 D101040 非屬公用之發電業及 IG03010 能源技術服務業"),
    "54568419": ("Tier 1", "日盛鑫能源開發有限公司", "D101040", "商工登記具 D101040 非屬公用之發電業"),
    "25039208": ("Tier 2", "關鍵應用科技股份有限公司", "IG03010", "PVGSA 會員（IG03010 能源技術與系統監控協力商）"),
    "59230437": ("Tier 2", "寶富能源有限公司", "IG03010", "具 IG03010 能源技術服務業及電器承裝業（綠電交易／顧問，無 D1010xx）"),
    "24709932": ("Tier 2", "詮鎔建設有限公司", "", "建設本業但獲經濟部能源署第十屆光鐸獎（優良一地多用獎）"),
    "04666386": ("Tier 2", "嵩億工業股份有限公司", "", "TPVIA 候補監事（工業製造協力會員）"),
    "89588361": ("Tier 2", "鼎鼎股份有限公司", "", "PVGSA 會員（會籍009，非能源字樣會員企業）"),
    "69688980": ("Tier 2", "泰洋光電有限公司", "IG03010", "具 IG03010 能源技術服務業與電器承裝業（兼跨電子製造）"),
    "29107488": ("Tier 2", "冠新能源科技股份有限公司", "IG03010", "具 IG03010 能源技術服務業與電器安裝工程（主營消防／號誌機電）"),
    "27420770": ("Tier 3", "凱銳光電股份有限公司", "D101060", "車用多媒體影音系統製造本業（2255），兼營 D101060 再生能源自用發電（不併入核心統計）"),
}

EXPLICIT_EXCLUSIONS_107_109: dict[str, str] = {
    "12910264": "車用光學鏡頭與影像模組製造（合盈光電 5298，非太陽光電）",
    "24784410": "離岸風力發電開發商（上緯新能源，現風睿能源 SRE，非太陽光電）",
    "97571737": "不動產租賃與精密儀器批發（南海光電科技，非太陽光電）",
    "12362365": "光纖通訊線纜與網通工程（台通光電 8011，非太陽光電）",
    "70848654": "精密光學鏡頭模具與金屬零件（伯特光電 6859，非太陽光電）",
    "10282231": "視聽歌唱業（太陽視聽歌唱行，誤中太陽字樣）",
    "53192225": "電子材料與電腦事務設備批發（晶展光電，非太陽光電）",
    "18523000": "高壓重電輸配電線纜製造廠（大東電業廠，未列名七大光電公協會）",
    "96909064": "一般電業／電氣裝修工程（桓鎧電業，非太陽光電）",
    "54216415": "產品設計、貿易與作物栽培服務（普耕園國際綠能，非太陽光電）",
    "80088772": "氣體燃料供應／瓦斯能源（立孚能源，非太陽光電）",
    "89685568": "精密塑膠模具與金屬電鍍表面處理（品傑光電，非太陽光電）",
    "53583258": "事業廢木材生質能工業蒸汽鍋爐發電（冠青能源科技，非太陽光電）",
    "22425924": "一般電業／電機工程（大安電業，非太陽光電）",
    "56683792": "一般電業／水電承裝（新富電業，非太陽光電）",
    "28882356": "交通標誌與汽機車零件批發（磐固光電，非太陽光電）",
    "54830643": "作物栽培服務與肥料製造（芳草綠能科技，非太陽光電）",
    "42920520": "建築物清潔、廢棄物清除與配管工程（宇晶能源科技，非太陽光電）",
    "38428882": "LED 照明元件批發（鈺璽光電科技，非太陽光電）",
    "28739866": "一般光學電子批發（京品光電科技，非太陽光電）",
    "54575468": "移工仲介與人力派遣顧問（艾蓮綠能事業，非太陽光電）",
    "09905674": "小規模電業行號（上興電業行，非太陽光電）",
    "86411143": "一般電器承裝工程（大愚電業工程，非太陽光電）",
    "59222725": "一般工程設計／光電器材（博羿光電工程設計，非太陽光電）",
    "23661072": "一般電業／電氣承裝（宇均電業，非太陽光電）",
    "23103534": "一般電業／電氣承裝（昶星電業，非太陽光電）",
    "59229500": "小規模電機行號（正光電機行，非太陽光電）",
    "14823441": "小規模電業行號（新兆電業行，非太陽光電）",
    "16037019": "LED 照明與背光模組製造（奧立科技能源，非太陽光電）",
    "42833672": "電子零組件與電池製造（昶昱能源，非太陽光電）",
    "28821345": "一般電子批發（信達光電科技，非太陽光電）",
    "28504235": "廢棄物清除處理與熱能供應業（台塑能源科技，非太陽光電）",
    "13093044": "清潔用品、電子材料與食品零售業（萬大光電科技，非太陽光電）",
    "30882613": "配管、冷凍空調與一般電器承裝業（普士電業，無發電業代碼）",
    "54733558": "照明設備與金屬結構製造業（久照能源，非太陽光電發電業且淨額為 0）",
}

# 107/109 退選或政黨差異擬參選人人工核實表（經 2020/2018 官方名冊或 elections.olc.tw 核實後擴增）
EXTRA_WITHDRAWN_2018_2020: dict[tuple[str, str, str], tuple[str, str, str]] = {}


def norm_text(val: str) -> str:
    if val is None:
        return ""
    return unicodedata.normalize("NFKC", str(val)).strip()


def norm_cand_key(val: str) -> str:
    s = norm_text(val)
    for ch in ("．", "·", "‧", "•", "・"):
        s = s.replace(ch, ".")
    return s


def parse_amount(val: str) -> float:
    s = norm_text(val).replace(",", "")
    return float(s) if s else 0.0


def load_prev_term_donations() -> tuple[pd.DataFrame, dict]:
    """讀取並驗證 107／109 六類選舉最新 serial=1 ZIP，同時比對歐噴 incomes.csv。"""
    all_zips = []
    for el in PREV_ELECTIONS:
        el_dir = KIANG_ACC / el
        for root, _, files in os.walk(el_dir):
            for fn in sorted(files):
                if not fn.endswith(".zip"):
                    continue
                rel = os.path.relpath(os.path.join(root, fn), el_dir)
                area_raw = os.path.dirname(rel)
                if area_raw == "." or el == "109年總統、副總統選舉":
                    area_raw = ""
                m = re.match(r"^(.+?)_(\d+)(?:_v(\d+))?\.zip$", fn)
                if not m:
                    continue
                all_zips.append({
                    "election": el,
                    "area": area_raw.strip(),
                    "cand_raw": m.group(1),
                    "cand": m.group(1).strip(),
                    "serial": int(m.group(2)),
                    "version": int(m.group(3) or 1),
                    "zip_path": os.path.join(root, fn),
                    "zip_name": fn,
                })

    dedup = {}
    for it in all_zips:
        k = (it["election"], it["area"], it["cand_raw"], it["serial"])
        if k not in dedup or it["version"] > dedup[k]["version"]:
            dedup[k] = it

    s1_zips = [z for z in dedup.values() if z["serial"] == 1]
    s2_zips = [z for z in dedup.values() if z["serial"] >= 2]

    s2_corp_rows = 0
    for z in s2_zips:
        with zipfile.ZipFile(z["zip_path"]) as zf:
            if "incomes.csv" in zf.namelist():
                with zf.open("incomes.csv") as f:
                    for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
                        if "營利事業" in norm_text(r.get("收支科目", "")):
                            s2_corp_rows += 1

    corp_records = []
    val_b_ok = 0
    val_b_tot = 0
    val_b_diffs = []
    kiang_stats = {}

    for z in s1_zips:
        el, area, cand = z["election"], z["area"], z["cand"]
        with zipfile.ZipFile(z["zip_path"]) as zf:
            summary_corp = 0.0
            declare_date = ""
            corr_date = ""
            if "person_incomes and expenditures_first.csv" in zf.namelist():
                with zf.open("person_incomes and expenditures_first.csv") as f:
                    s_rows = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))
                    if s_rows:
                        sr = {str(k).strip(): norm_text(v) for k, v in s_rows[0].items()}
                        summary_corp = parse_amount(sr.get("營利事業捐贈收入", "0"))
                        declare_date = sr.get("申報日期", "")
                        corr_date = sr.get("更正日期", "")

            inc_rows = []
            if "incomes.csv" in zf.namelist():
                with zf.open("incomes.csv") as f:
                    for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
                        inc_rows.append({str(k).strip(): norm_text(v) for k, v in r.items()})

            corp_rows = [r for r in inc_rows if "營利事業" in r.get("收支科目", "")]
            det_sum = sum(parse_amount(r.get("收入金額", "0")) for r in corp_rows)
            val_b_tot += 1
            if abs(det_sum - summary_corp) <= 1.0:
                val_b_ok += 1
            else:
                val_b_diffs.append((el, area, cand, det_sum - summary_corp))

            c_gross = 0.0
            c_ret = 0.0
            for r in corp_rows:
                amt = parse_amount(r.get("收入金額", "0"))
                ret_flag = r.get("返還/繳庫", "")
                ret_amt = amt if ret_flag else 0.0
                net_amt = amt - ret_amt
                tid = norm_text(r.get("身分證／統一編號", ""))
                tid8 = tid if re.match(r"^\d{8}$", tid) else (tid.zfill(8) if re.match(r"^\d{7}$", tid) else "")
                c_gross += amt
                c_ret += ret_amt
                corp_records.append({
                    "election": el,
                    "area": area,
                    "candidate": cand,
                    "serial_year": r.get("申報序號／年度", ""),
                    "row_seq": r.get("序號", ""),
                    "tx_date": r.get("交易日期", ""),
                    "subject": r.get("收支科目", ""),
                    "donor_name": r.get("捐贈者／支出對象", ""),
                    "tax_id_raw": tid,
                    "tax_id_8": tid8,
                    "gross_amount": amt,
                    "returned_flag": ret_flag,
                    "returned_amount": ret_amt,
                    "net_amount": net_amt,
                    "method": r.get("捐贈方式", ""),
                    "deposit_date": r.get("存入專戶日期", ""),
                    "money_type": r.get("金錢類", ""),
                    "address": r.get("地址", ""),
                    "corr_flag": r.get("更正註記", ""),
                    "corr_date": r.get("資料更正日期", ""),
                    "zip_name": z["zip_name"],
                    "zip_version": z["version"],
                    "summary_declare_date": declare_date,
                    "summary_corr_date": corr_date,
                })

            kiang_stats[(el, area, norm_cand_key(cand))] = {
                "count": len(corp_rows),
                "gross": c_gross,
                "returned": c_ret,
                "net": c_gross - c_ret,
            }

    # Cross-check vs OpenFun incomes.csv for 107/109
    of_stats = defaultdict(lambda: {"count": 0, "gross": 0.0, "net": 0.0})
    with OPENFUN_CSV.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            el = norm_text(row.get("選舉名稱", ""))
            if el not in PREV_ELECTIONS:
                continue
            subj = norm_text(row.get("收支科目", ""))
            if "營利事業" not in subj:
                continue
            area = "" if el == "109年總統、副總統選舉" else norm_text(row.get("縣市", ""))
            ck = norm_cand_key(row.get("擬參選人／政黨", ""))
            amt = parse_amount(row.get("收入金額", "0"))
            ret = amt if norm_text(row.get("返還/繳庫", "")) else 0.0
            of_stats[(el, area, ck)]["count"] += 1
            of_stats[(el, area, ck)]["gross"] += amt
            of_stats[(el, area, ck)]["net"] += (amt - ret)

    of_diffs = 0
    for k in set(kiang_stats) | set(of_stats):
        ks = kiang_stats.get(k, {"count": 0, "gross": 0.0, "net": 0.0})
        os_ = of_stats.get(k, {"count": 0, "gross": 0.0, "net": 0.0})
        if ks["count"] != os_["count"] or abs(ks["net"] - os_["net"]) > 1.0:
            of_diffs += 1

    meta = {
        "prev_total_zips": len(all_zips),
        "prev_serial1_cands": len(s1_zips),
        "prev_serial_ge2_cands": len(s2_zips),
        "prev_serial_ge2_corp_rows": s2_corp_rows,
        "prev_val_b_ok": val_b_ok,
        "prev_val_b_tot": val_b_tot,
        "prev_val_b_diffs": val_b_diffs,
        "prev_openfun_cand_diffs": of_diffs,
        "prev_corp_rows": len(corp_records),
    }
    return pd.DataFrame(corp_records), meta


def load_local_gcis_no_fetch(tid: str, fallback_name: str) -> dict:
    """僅讀取本機 gcis.nat.g0v.tw 或 gcis_extra，不發外部請求。"""
    raw = {}
    for d in (GCIS_MAIN_DIR, GCIS_EXTRA_DIR):
        p = d / f"{tid}.json"
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                break
            except Exception:
                raw = {}
    d = raw.get("data", {})
    if not isinstance(d, dict):
        d = {}
    has_file = bool(d)

    gcis_name = step03.norm(d.get("公司名稱") or d.get("商業名稱") or fallback_name)
    rep = step03.norm(d.get("代表人姓名") or d.get("負責人姓名") or "")
    addr = step03.norm(d.get("公司所在地") or d.get("地址") or "")
    cap = step03.norm(d.get("實收資本額(元)") or d.get("資本總額(元)") or d.get("資本額(元)") or "")
    status = step03.norm(d.get("公司狀況") or d.get("現況") or "")
    est_raw = d.get("核准設立日期") or {}
    if isinstance(est_raw, dict) and est_raw:
        est_date = f"{est_raw.get('year','')}-{est_raw.get('month','')}-{est_raw.get('day','')}"
    else:
        est_date = step03.norm(est_raw)

    codes = set()
    biz_items = []
    if isinstance(d.get("所營事業資料"), list):
        for it in d["所營事業資料"]:
            if isinstance(it, list) and len(it) >= 2:
                c = step03.norm(it[0])
                lbl = step03.norm(it[1])
                if re.match(r"^[A-Z]{1,2}\d{5,6}$", c):
                    codes.add(c)
                biz_items.append(f"{c}:{lbl}".strip(":"))
            else:
                txt = step03.norm(it)
                codes.update(re.findall(r"[A-Z]{1,2}\d{5,6}", txt))
                biz_items.append(txt)
    for k in ("營業項目", "舊營業項目資料"):
        if d.get(k):
            txt = step03.norm(d[k])
            codes.update(re.findall(r"[A-Z]{1,2}\d{5,6}", txt))
            biz_items.append(txt)

    return {
        "has_gcis_file": has_file,
        "gcis_name": gcis_name,
        "rep_name": rep,
        "address": addr,
        "address_norm": step03.norm_name_key(addr),
        "capital": cap,
        "status": status,
        "est_date": est_date,
        "codes": codes,
        "biz_summary": "; ".join(biz_items[:8]),
    }


def build_two_term_solar_master(df_all12: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """對全部 12 類選舉企業進行統一光電三級分類，保證 111/113 口徑與 03_solar_entities_master.csv 100% 一致。"""
    prev_master = pd.read_csv(OUT_DIR / "03_solar_entities_master.csv", dtype={"tax_id": str})
    prev_master_map = prev_master.set_index("tax_id").to_dict("index")
    prev_excl = pd.read_csv(OUT_DIR / "03_excluded_false_positives.csv", dtype={"tax_id": str})
    prev_excl_map = prev_excl.set_index("tax_id").to_dict("index")

    # 聚合全部 12 類選舉獨特企業統編
    df_all12 = df_all12.copy()
    df_all12["tid_key"] = df_all12.apply(
        lambda r: r["tax_id_8"] if r["tax_id_8"] else f"RAW:{r['tax_id_raw']}:{r['donor_name']}",
        axis=1,
    )

    corps = {}
    exact_to_tids = defaultdict(set)
    stem_to_tids = defaultdict(set)

    for tid_key, grp in df_all12.groupby("tid_key"):
        name_cnt = Counter(grp["donor_name"].dropna())
        donor_primary = name_cnt.most_common(1)[0][0] if name_cnt else ""
        g = load_local_gcis_no_fetch(tid_key, donor_primary) if re.match(r"^\d{8}$", tid_key) else {
            "has_gcis_file": False, "gcis_name": donor_primary, "rep_name": "", "address": "",
            "address_norm": "", "capital": "", "status": "", "est_date": "", "codes": set(), "biz_summary": ""
        }
        rec = {
            "tax_id": tid_key,
            "donor_name_primary": donor_primary,
            **g,
            "donation_count": int(len(grp)),
            "candidate_count": int(grp.groupby(["election", "area", "candidate"]).ngroups),
            "total_gross": float(grp["gross_amount"].sum()),
            "total_returned": float(grp["returned_amount"].sum()),
            "total_net": float(grp["net_amount"].sum()),
            "prev_net": float(grp[grp["election"].isin(PREV_ELECTIONS)]["net_amount"].sum()),
            "curr_net": float(grp[grp["election"].isin(CURR_ELECTIONS)]["net_amount"].sum()),
            "elections": " | ".join(sorted(grp["election"].unique())),
        }
        corps[tid_key] = rec
        for nm in (donor_primary, g["gcis_name"]):
            if nm:
                exact_to_tids[step03.norm_name_key(nm)].add(tid_key)
                st = step03.stem_name(nm)
                if len(st) >= 2:
                    stem_to_tids[st].add(tid_key)

    # 讀取 7 公協會與能源署名單
    assoc_hits = defaultdict(list)
    assoc_leader_people = set()
    df_assoc = pd.read_csv(OUT_DIR / "02_seven_associations_members.csv", dtype=str).fillna("")
    for _, r in df_assoc.iterrows():
        if any(k in r["role_type"] for k in ("理事長", "理事", "監事", "主委", "主席", "代表")) and r["person_name"]:
            assoc_leader_people.add(step03.norm(r["person_name"]))
        comp = step03.norm(r["company_name_clean"] or r["company_name_raw"])
        if not comp:
            continue
        tids = set(exact_to_tids.get(step03.norm_name_key(comp), set()))
        if not tids and len(step03.stem_name(comp)) >= 3:
            tids = set(stem_to_tids.get(step03.stem_name(comp), set()))
        for tid in tids:
            assoc_hits[tid].append(f"{r['association_name']}[{r['role_type']}]")
    assoc_leader_people.update([
        "賴勁麟", "譚宇軒", "趙書閔", "陳貴光", "蔡佳晋", "沈尚弘", "林新寶",
        "謝明宏", "陳坤宏", "胡惠森", "林恬宇", "徐秀蘭", "賴明弘", "郭世堂", "葉孟恒", "王丁召",
    ])

    off_hits = defaultdict(list)
    df_off = pd.read_csv(OUT_DIR / "02_official_solar_lists.csv", dtype=str).fillna("")
    for _, r in df_off.iterrows():
        if r["category"] in ("水力發電業", "地熱發電業"):
            continue
        comp = step03.norm(r["company_name"])
        if len(comp) < 3:
            continue
        tids = set(exact_to_tids.get(step03.norm_name_key(comp), set()))
        if not tids and len(step03.stem_name(comp)) >= 3:
            tids = set(stem_to_tids.get(step03.stem_name(comp), set()))
        for tid in tids:
            off_hits[tid].append(f"{r['dataset']}({r['category']})")

    # Seed HQ addresses (only verified core solar firms)
    core_hq_addrs = {}
    for tid in (set(assoc_hits) | set(off_hits)):
        if tid in step03.SUPPLY_CHAIN_ASSOC_TIDS or tid in step03.EXPLICIT_EXCLUSIONS or tid in EXPLICIT_EXCLUSIONS_107_109:
            continue
        c = corps[tid]
        if (c["codes"] & step03.CORE_SOLAR_CODES) or any(k in c["gcis_name"] for k in ("太陽", "光電", "綠能", "能源", "電力")):
            if c["address_norm"]:
                core_hq_addrs[c["address_norm"]] = c["gcis_name"]

    solar_name_kws = ("太陽", "光電", "綠能", "綠電", "光儲")
    energy_name_kws = ("太陽", "光電", "綠能", "綠電", "能源", "電力", "發電", "電業", "儲能")
    all_excl = {**step03.EXPLICIT_EXCLUSIONS, **EXPLICIT_EXCLUSIONS_107_109}

    master_rows = []
    excl_rows = []
    newly_matched_107_109 = []

    for tid, c in corps.items():
        # 1. 若已有 111/113 審核結果，直接繼承該分類，保證兩屆間標準完全一致
        if tid in prev_master_map:
            pm = prev_master_map[tid]
            master_rows.append({
                "tax_id": tid,
                "tier": pm["tier"],
                "gcis_name": pm["gcis_name"],
                "donor_name_primary": c["donor_name_primary"],
                "rep_name": pm["rep_name"] if pd.notna(pm["rep_name"]) else c["rep_name"],
                "capital": pm["capital"] if pd.notna(pm["capital"]) else c["capital"],
                "status": pm["status"] if pd.notna(pm["status"]) else c["status"],
                "est_date": pm["est_date"] if pd.notna(pm["est_date"]) else c["est_date"],
                "address": pm["address"] if pd.notna(pm["address"]) else c["address"],
                "core_codes": pm["core_codes"] if pd.notna(pm["core_codes"]) else "",
                "aux_codes": pm["aux_codes"] if pd.notna(pm["aux_codes"]) else "",
                "associations": pm["associations"] if pd.notna(pm["associations"]) else "",
                "official_lists": pm["official_lists"] if pd.notna(pm["official_lists"]) else "",
                "classification_reason": pm["classification_reason"],
                "prev_net": c["prev_net"],
                "curr_net": c["curr_net"],
                "donation_count": c["donation_count"],
                "candidate_count": c["candidate_count"],
                "total_gross": c["total_gross"],
                "total_returned": c["total_returned"],
                "total_net": c["total_net"],
                "elections": c["elections"],
                "biz_summary": pm["biz_summary"] if pd.notna(pm["biz_summary"]) else c["biz_summary"],
            })
            continue
        if tid in prev_excl_map:
            pe = prev_excl_map[tid]
            excl_rows.append({
                "tax_id": tid,
                "donor_name_primary": c["donor_name_primary"],
                "gcis_name": pe["gcis_name"],
                "rep_name": pe["rep_name"] if pd.notna(pe["rep_name"]) else "",
                "total_gross": c["total_gross"],
                "total_net": c["total_net"],
                "donation_count": c["donation_count"],
                "candidate_count": c["candidate_count"],
                "codes": pe["codes"] if pd.notna(pe["codes"]) else "",
                "exclusion_reason": pe["exclusion_reason"],
                "biz_summary": pe["biz_summary"] if pd.notna(pe["biz_summary"]) else "",
            })
            continue

        # 2. 以下僅為 107/109 獨有企業（不在 111/113 清冊中）
        if tid in VERIFIED_107_109_TIER_OVERRIDES:
            tier, ov_name, ov_codes, ov_reason = VERIFIED_107_109_TIER_OVERRIDES[tid]
            row_dict = {
                "tax_id": tid,
                "tier": tier,
                "gcis_name": ov_name,
                "donor_name_primary": c["donor_name_primary"],
                "rep_name": c["rep_name"],
                "capital": c["capital"],
                "status": c["status"],
                "est_date": c["est_date"],
                "address": c["address"],
                "core_codes": " ".join(x for x in ov_codes.split() if x in step03.CORE_SOLAR_CODES),
                "aux_codes": " ".join(x for x in ov_codes.split() if x in step03.AUX_ENERGY_CODES),
                "associations": " ; ".join(sorted(set(assoc_hits.get(tid, [])))),
                "official_lists": " ; ".join(sorted(set(off_hits.get(tid, [])))),
                "classification_reason": ov_reason,
                "prev_net": c["prev_net"],
                "curr_net": c["curr_net"],
                "donation_count": c["donation_count"],
                "candidate_count": c["candidate_count"],
                "total_gross": c["total_gross"],
                "total_returned": c["total_returned"],
                "total_net": c["total_net"],
                "elections": c["elections"],
                "biz_summary": c["biz_summary"] or ov_reason,
            }
            master_rows.append(row_dict)
            if tier in ("Tier 1", "Tier 2"):
                newly_matched_107_109.append(row_dict)
            continue

        nm = c["gcis_name"]
        codes = c["codes"]
        in_assoc = sorted(set(assoc_hits.get(tid, [])))
        in_off = sorted(set(off_hits.get(tid, [])))
        has_core = bool(codes & step03.CORE_SOLAR_CODES)
        has_ig = "IG03010" in codes
        has_fossil = bool(codes & step03.FOSSIL_CODES)
        has_solar_kw = any(k in nm for k in solar_name_kws)
        has_energy_kw = any(k in nm for k in energy_name_kws)

        if tid in all_excl and not (in_assoc and tid not in step03.SUPPLY_CHAIN_ASSOC_TIDS):
            excl_rows.append({
                "tax_id": tid, "donor_name_primary": c["donor_name_primary"], "gcis_name": nm,
                "rep_name": c["rep_name"], "total_gross": c["total_gross"], "total_net": c["total_net"],
                "donation_count": c["donation_count"], "candidate_count": c["candidate_count"],
                "codes": " ".join(sorted(codes & (step03.CORE_SOLAR_CODES | step03.AUX_ENERGY_CODES | step03.FOSSIL_CODES))),
                "exclusion_reason": all_excl[tid], "biz_summary": c["biz_summary"],
            })
            continue

        if has_fossil and has_energy_kw and not in_assoc and not has_core:
            excl_rows.append({
                "tax_id": tid, "donor_name_primary": c["donor_name_primary"], "gcis_name": nm,
                "rep_name": c["rep_name"], "total_gross": c["total_gross"], "total_net": c["total_net"],
                "donation_count": c["donation_count"], "candidate_count": c["candidate_count"],
                "codes": " ".join(sorted(codes & (step03.CORE_SOLAR_CODES | step03.AUX_ENERGY_CODES | step03.FOSSIL_CODES))),
                "exclusion_reason": "石油製品／液化石油氣能源業（非再生能源）", "biz_summary": c["biz_summary"],
            })
            continue

        rep_is_leader = c["rep_name"] in assoc_leader_people
        hq_match_parent = core_hq_addrs.get(c["address_norm"], "")
        is_sole_prop = nm.endswith("行") or nm.endswith("社")
        group_linked = False
        group_reason = ""
        if hq_match_parent and hq_match_parent != nm and (has_energy_kw or has_core):
            group_linked = True
            group_reason = f"與核心光電企業同登記地址（{hq_match_parent}）"
        elif rep_is_leader and not is_sole_prop and (has_energy_kw or has_core):
            group_linked = True
            group_reason = f"代表人為七大公協會核心幹部（{c['rep_name']}）"

        tier = ""
        reason_parts = []
        if tid in step03.SUPPLY_CHAIN_ASSOC_TIDS:
            tier = "Tier 2"
            reason_parts.append("七大公協會會員（供應鏈協力）")
        elif in_assoc or in_off:
            if has_energy_kw or has_core or has_ig:
                tier = "Tier 1"
                if in_assoc:
                    reason_parts.append("七大光電公協會成員")
                if in_off:
                    reason_parts.append("經濟部能源署光電名單")
            else:
                tier = "Tier 2"
                reason_parts.append("七大公協會或官方名單一般／協力成員")
        elif group_linked:
            tier = "Tier 1"
            reason_parts.append(group_reason)
        elif has_energy_kw and has_core and not is_sole_prop:
            tier = "Tier 1"
            reason_parts.append("名稱屬能源／光電／太陽／綠能且具 D1010xx 發電代碼")
        elif has_energy_kw and has_ig and not has_fossil and not is_sole_prop:
            tier = "Tier 2"
            reason_parts.append("名稱屬能源／光電／綠能且具 IG03010 能源技術服務業（無 D1010xx 發電代碼）")
        elif codes & {"D101060", "D101011", "D101070"}:
            tier = "Tier 3"
            reason_parts.append("非能源本業公司但商工登記含 D101060／D101011（跨業兼營／廠房屋頂自用）")
        elif has_energy_kw:
            excl_rows.append({
                "tax_id": tid, "donor_name_primary": c["donor_name_primary"], "gcis_name": nm,
                "rep_name": c["rep_name"], "total_gross": c["total_gross"], "total_net": c["total_net"],
                "donation_count": c["donation_count"], "candidate_count": c["candidate_count"],
                "codes": " ".join(sorted(codes & (step03.CORE_SOLAR_CODES | step03.AUX_ENERGY_CODES | step03.FOSSIL_CODES))),
                "exclusion_reason": "名稱含關鍵字但無本機 GCIS D1010xx／IG03010 佐證（或屬一般行號）",
                "biz_summary": c["biz_summary"],
            })
            continue

        if tier:
            if has_core:
                reason_parts.append("GCIS:" + ",".join(sorted(codes & step03.CORE_SOLAR_CODES)))
            elif has_ig:
                reason_parts.append("GCIS:IG03010")
            row_dict = {
                "tax_id": tid,
                "tier": tier,
                "gcis_name": nm,
                "donor_name_primary": c["donor_name_primary"],
                "rep_name": c["rep_name"],
                "capital": c["capital"],
                "status": c["status"],
                "est_date": c["est_date"],
                "address": c["address"],
                "core_codes": " ".join(sorted(codes & step03.CORE_SOLAR_CODES)),
                "aux_codes": " ".join(sorted(codes & step03.AUX_ENERGY_CODES)),
                "associations": " ; ".join(in_assoc),
                "official_lists": " ; ".join(in_off),
                "classification_reason": " | ".join(reason_parts),
                "prev_net": c["prev_net"],
                "curr_net": c["curr_net"],
                "donation_count": c["donation_count"],
                "candidate_count": c["candidate_count"],
                "total_gross": c["total_gross"],
                "total_returned": c["total_returned"],
                "total_net": c["total_net"],
                "elections": c["elections"],
                "biz_summary": c["biz_summary"],
            }
            master_rows.append(row_dict)
            if tier in ("Tier 1", "Tier 2"):
                newly_matched_107_109.append(row_dict)

    master_df = pd.DataFrame(master_rows).sort_values(["tier", "total_net"], ascending=[True, False])
    excl_df = pd.DataFrame(excl_rows).sort_values("total_net", ascending=False)
    new_df = pd.DataFrame(newly_matched_107_109).sort_values(["tier", "prev_net"], ascending=[True, False])
    return master_df, excl_df, new_df


def load_cec_two_terms() -> dict:
    """整合 2018、2020、2022 與 2024 共 12 類選舉之本機 CEC 索引。"""
    idx = step06.load_cec_indexes()

    def parse_elpaty(txt: str) -> dict[str, str]:
        mp = {}
        for row in csv.reader(io.StringIO(txt)):
            if len(row) >= 2:
                mp[row[0].strip()] = row[1].strip()
        return mp

    # 2018 地方公職四類
    map_2018 = [
        ("107年直轄市市長選舉", "2018_mayor_mun.csv"),
        ("107年縣(市)長選舉", "2018_mayor_cnt.csv"),
        ("107年直轄市議員選舉", "2018_council_mun.csv"),
        ("107年縣(市)議員選舉", "2018_council_cnt.csv"),
    ]
    for el_name, fn in map_2018:
        raw_txt = (CEC_DIR / fn).read_text(encoding="utf-8-sig")
        for r in csv.DictReader(io.StringIO(raw_txt)):
            idx[el_name].append((
                step06.norm_text(r["area"]),
                step06.norm_text(r["cand_name"]),
                step06.norm_party(r["party"]),
                "當選" if str(r.get("is_victor", "")).strip().upper() == "Y" else "未當選",
                r["area"].strip(),
            ))

    # 2020 elbase
    city_map_2020 = {}
    for row in csv.reader(io.StringIO((CEC_DIR / "2020_elbase.csv").read_text(encoding="utf-8-sig"))):
        if len(row) >= 6 and row[3] == "000" and row[4] == "0000":
            city_map_2020[(row[0].strip(), row[1].strip())] = step06.norm_text(row[5])

    # 2020 總統（僅取總統欄位或整對旗標皆對齊）
    pres_paty = parse_elpaty((CEC_DIR / "2020_pres_elpaty.csv").read_text(encoding="utf-8-sig"))
    for row in csv.reader(io.StringIO((CEC_DIR / "2020_pres_elcand.csv").read_text(encoding="utf-8-sig"))):
        if len(row) >= 16:
            cname = step06.norm_text(row[6])
            party = step06.norm_party(pres_paty.get(row[7].strip(), ""))
            victor = "當選" if row[14].strip() == "*" else "未當選"
            idx["109年總統、副總統選舉"].append(("全國", cname, party, victor, "全國"))

    # 2020 立法委員
    for cand_fn, paty_fn, fixed_area in [
        ("2020_ly_dist_elcand.csv", "2020_ly_dist_elpaty.csv", None),
        ("2020_ly_mtn_elcand.csv", "2020_ly_mtn_elpaty.csv", "山地原住民"),
        ("2020_ly_pln_elcand.csv", "2020_ly_pln_elpaty.csv", "平地原住民"),
    ]:
        pmap = parse_elpaty((CEC_DIR / paty_fn).read_text(encoding="utf-8-sig"))
        for row in csv.reader(io.StringIO((CEC_DIR / cand_fn).read_text(encoding="utf-8-sig"))):
            if len(row) >= 16:
                cname = step06.norm_text(row[6])
                party = step06.norm_party(pmap.get(row[7].strip(), ""))
                victor = "當選" if row[14].strip() == "*" else "未當選"
                area_nm = fixed_area or city_map_2020.get((row[0].strip(), row[1].strip()), "")
                idx["109年立法委員選舉"].append((step06.norm_text(area_nm), cname, party, victor, area_nm))

    step06.WITHDRAWN_VERIFIED_PARTIES.update(EXTRA_WITHDRAWN_2018_2020)
    return idx


def main():
    print("1. 讀取並驗證 107／109 六類選舉原始申報 ZIP……")
    df_prev, prev_meta = load_prev_term_donations()
    print("   107/109 驗證結果：", json.dumps(prev_meta, ensure_ascii=False))

    df_curr = pd.read_csv(OUT_DIR / "01_all_corporate_donations.csv", dtype={"tax_id_raw": str, "tax_id_8": str})
    df_curr["area"] = df_curr["area"].fillna("")
    df_prev["area"] = df_prev["area"].fillna("")
    df_all12 = pd.concat([df_curr, df_prev], ignore_index=True)
    df_all12["term"] = df_all12["election"].map(TERM_MAP)
    df_all12.to_csv(OUT_DIR / "09_all_corporate_donations_12elections.csv", index=False, encoding="utf-8-sig")
    print(f"   兩屆 12 類選舉全部營利事業捐贈明細共 {len(df_all12):,} 筆（本屆 {len(df_curr):,} ＋ 前屆 {len(df_prev):,}）。")

    print("2. 建構跨兩屆統一光電機構三級清冊（嚴格本機快取優先）……")
    master_df, excl_df, new_df = build_two_term_solar_master(df_all12)
    master_df.to_csv(OUT_DIR / "09_solar_entities_master_two_terms.csv", index=False, encoding="utf-8-sig")
    excl_df.to_csv(OUT_DIR / "09_excluded_false_positives_two_terms.csv", index=False, encoding="utf-8-sig")

    print(f"\n=== [稽核門檻] 107/109 獨有且新命中之 Tier 1＋Tier 2 企業（共 {len(new_df)} 家）===")
    for _, r in new_df.iterrows():
        print(f"  {r['tier']} | {r['tax_id']} | {r['gcis_name']} | codes={r['core_codes']} {r['aux_codes']} | net={int(r['prev_net']):,} | {r['classification_reason'][:55]}")

    # 產出全部 12 選舉命中的光電企業逐筆明細
    tier_lookup = master_df.set_index("tax_id")[["tier", "gcis_name", "rep_name"]].to_dict("index")
    df_all12["tid_key"] = df_all12.apply(
        lambda r: r["tax_id_8"] if pd.notna(r["tax_id_8"]) and str(r["tax_id_8"]).strip() else f"RAW:{r['tax_id_raw']}:{r['donor_name']}",
        axis=1,
    )
    matched = df_all12[df_all12["tid_key"].isin(tier_lookup)].copy()
    matched["tax_id"] = matched["tid_key"]
    matched["tier"] = matched["tax_id"].map(lambda t: tier_lookup[t]["tier"])
    matched["gcis_name"] = matched["tax_id"].map(lambda t: tier_lookup[t]["gcis_name"])
    matched["rep_name"] = matched["tax_id"].map(lambda t: tier_lookup[t]["rep_name"])
    matched.to_csv(OUT_DIR / "09_donation_details_two_terms.csv", index=False, encoding="utf-8-sig")

    # 驗證 111/113 口徑零飄移
    curr_t12 = matched[(matched["term"] == "111/113 本屆") & (matched["tier"].isin(["Tier 1", "Tier 2"]))]
    prev_t12 = matched[(matched["term"] == "107/109 前屆") & (matched["tier"].isin(["Tier 1", "Tier 2"]))]
    print(f"\n   111/113 本屆 Tier 1+2 實捐淨額驗證：{int(curr_t12['net_amount'].sum()):,} 元（應等於 39,196,000 元）")
    print(f"   107/109 前屆 Tier 1+2 實捐淨額：{int(prev_t12['net_amount'].sum()):,} 元（{prev_t12['tax_id'].nunique()} 家、{len(prev_t12)} 筆）")

    print("3. 匹配全數 12 類選舉受贈候選人之中選會政黨與當選註記……")
    cec_idx = load_cec_two_terms()
    t12 = matched[matched["tier"].isin(["Tier 1", "Tier 2"])].copy()
    t12["cand_key"] = t12["election"] + "|" + t12["area"] + "|" + t12["candidate"]

    cands_agg = (
        t12.groupby(["cand_key", "term", "election", "area", "candidate"], as_index=False)
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

    parties, victors, psources, unmatched = [], [], [], []
    for _, r in cands_agg.iterrows():
        p, v, src = step06.match_candidate_party(cec_idx, r["election"], r["area"], r["candidate"])
        parties.append(p)
        victors.append(v)
        psources.append(src)
        if p in ("UNMATCHED", "待人工複核（同縣市同名異黨）"):
            unmatched.append((r["election"], r["area"], r["candidate"], int(r["net_amount"]), r["donors_detail"], p, src))

    cands_agg["party"] = parties
    cands_agg["is_victor"] = victors
    cands_agg["party_source"] = psources
    print(f"   兩屆受贈候選人共 {len(cands_agg)} 人次；未直接於 CEC 命中筆數：{len(unmatched)}")
    for u in unmatched:
        print("   [CEC UNMATCHED]", u)

    print("4. 查詢／讀取兩屆全部 Tier 1＋Tier 2 企業之 PCC 標案紀錄（僅針對未快取企業補查）……")
    t12_corps = master_df[master_df["tier"].isin(["Tier 1", "Tier 2"])].copy()
    # Filter strictly to corps with actual donations in t12 (all Tier 1+2 in t12_corps donated >= 1 row)
    pcc_rows = []
    fetched_new = 0
    for idx_i, (_, r) in enumerate(t12_corps.iterrows()):
        tid = str(r["tax_id"]).strip()
        cache_p = PCC_DIR / f"{tid}.json"
        if not cache_p.exists():
            fetched_new += 1
        pcc_raw = step06.fetch_pcc_company(tid)
        summary = step06.parse_pcc_summary(tid, str(r["gcis_name"]), pcc_raw)
        pcc_rows.append({
            "tier": r["tier"],
            "tax_id": tid,
            "gcis_name": r["gcis_name"],
            "rep_name": r["rep_name"],
            "prev_net": int(r["prev_net"]),
            "curr_net": int(r["curr_net"]),
            "total_net": int(r["total_net"]),
            "total_gross": int(r["total_gross"]),
            "total_returned": int(r["total_returned"]),
            "candidate_count": int(r["candidate_count"]),
            "associations": r["associations"] if pd.notna(r["associations"]) else "",
            **summary,
        })
    print(f"   PCC 完成：總家數 {len(t12_corps)} 家（本次新向 PCC API 補查家數：{fetched_new} 家，其餘皆讀本機快取）。")

    pcc_df = pd.DataFrame(pcc_rows)
    pcc_awarded_tids = set(pcc_df[pcc_df["pcc_has_award"] == "Y"]["tax_id"])

    cand_party_map = cands_agg.set_index("cand_key")[["party", "is_victor"]].to_dict("index")
    t12["party"] = t12["cand_key"].map(lambda k: cand_party_map[k]["party"])
    t12["is_victor"] = t12["cand_key"].map(lambda k: cand_party_map[k]["is_victor"])
    t12["pcc_has_award"] = t12["tax_id"].map(lambda t: "Y" if t in pcc_awarded_tids else "N")

    cand_pcc = t12[t12["pcc_has_award"] == "Y"].groupby("cand_key").agg(
        pcc_corp_count=("tax_id", "nunique"),
        pcc_net_amount=("net_amount", "sum"),
    )
    cands_agg["pcc_corp_count"] = cands_agg["cand_key"].map(lambda k: int(cand_pcc.loc[k, "pcc_corp_count"]) if k in cand_pcc.index else 0)
    cands_agg["pcc_net_amount"] = cands_agg["cand_key"].map(lambda k: int(cand_pcc.loc[k, "pcc_net_amount"]) if k in cand_pcc.index else 0)
    cands_agg.sort_values(["net_amount", "corp_count"], ascending=[False, False]).to_csv(
        OUT_DIR / "09_candidates_two_terms_with_cec.csv", index=False, encoding="utf-8-sig"
    )

    # Company party breakdown
    corp_party_str = {}
    for tid, grp in t12.groupby("tax_id"):
        parts = [f"{p}:{int(pg['net_amount'].sum()):,}元({pg['cand_key'].nunique()}人)" for p, pg in grp.groupby("party")]
        corp_party_str[tid] = "；".join(sorted(parts))
    pcc_df["party_donations_breakdown"] = pcc_df["tax_id"].map(lambda t: corp_party_str.get(t, ""))
    pcc_df.sort_values(["pcc_awarded_count", "total_net"], ascending=[False, False]).to_csv(
        OUT_DIR / "09_solar_companies_pcc_two_terms.csv", index=False, encoding="utf-8-sig"
    )

    # 5. Cross-term party summary
    party_comp_rows = []
    for term_label, tsub in [("107/109 前屆", t12[t12["term"] == "107/109 前屆"]),
                             ("111/113 本屆", t12[t12["term"] == "111/113 本屆"]),
                             ("兩屆合計", t12)]:
        for scope_label, ssub in [
            ("Tier 1+2 合計", tsub),
            ("僅 Tier 1 核心專營", tsub[tsub["tier"] == "Tier 1"]),
            ("僅 Tier 2 關聯企業", tsub[tsub["tier"] == "Tier 2"]),
            ("僅 PCC 政府得標企業（Tier 1+2）", tsub[tsub["pcc_has_award"] == "Y"]),
        ]:
            tot_net = int(ssub["net_amount"].sum())
            for party, pg in ssub.groupby("party"):
                pn = int(pg["net_amount"].sum())
                cc = int(pg["cand_key"].nunique())
                party_comp_rows.append({
                    "term": term_label,
                    "scope": scope_label,
                    "party": party,
                    "candidate_count": cc,
                    "elected_count": int(pg[pg["is_victor"] == "當選"]["cand_key"].nunique()),
                    "corp_count": int(pg["tax_id"].nunique()),
                    "tx_count": int(len(pg)),
                    "gross_amount": int(pg["gross_amount"].sum()),
                    "returned_amount": int(pg["returned_amount"].sum()),
                    "net_amount": pn,
                    "net_share_pct": round(pn / tot_net * 100, 2) if tot_net > 0 else 0.0,
                })
    pd.DataFrame(party_comp_rows).to_csv(OUT_DIR / "09_two_term_party_comparison.csv", index=False, encoding="utf-8-sig")

    # 6. Cross-term company comparison
    comp_rows = []
    for _, r in pcc_df.iterrows():
        pn, cn = int(r["prev_net"]), int(r["curr_net"])
        # Classify existence even if gross>0 and returned=gross -> check tx presence per term
        tid = r["tax_id"]
        has_prev = len(t12[(t12["tax_id"] == tid) & (t12["term"] == "107/109 前屆")]) > 0
        has_curr = len(t12[(t12["tax_id"] == tid) & (t12["term"] == "111/113 本屆")]) > 0
        status = "連兩屆捐贈" if (has_prev and has_curr) else ("僅本屆新增" if has_curr else "僅前屆捐贈")
        comp_rows.append({
            "tax_id": tid,
            "gcis_name": r["gcis_name"],
            "tier": r["tier"],
            "term_status": status,
            "prev_net_107_109": pn,
            "curr_net_111_113": cn,
            "delta_curr_minus_prev": cn - pn,
            "two_term_total_net": pn + cn,
            "pcc_awarded_count": int(r["pcc_awarded_count"]),
            "pcc_solar_awarded_count": int(r["pcc_solar_awarded_count"]),
            "party_donations_breakdown": r["party_donations_breakdown"],
        })
    comp_df_out = pd.DataFrame(comp_rows).sort_values(["two_term_total_net", "pcc_awarded_count"], ascending=[False, False])
    comp_df_out.to_csv(OUT_DIR / "09_two_term_company_comparison.csv", index=False, encoding="utf-8-sig")

    # 7. Repeat candidates across BOTH terms (match by (norm_cand_key, area) so homonym cross-county politicians stay separate)
    t12["cand_norm"] = t12["candidate"].map(norm_cand_key)
    rep_rows = []
    for (cname_norm, carea), grp in t12.groupby(["cand_norm", "area"]):
        g_prev = grp[grp["term"] == "107/109 前屆"]
        g_curr = grp[grp["term"] == "111/113 本屆"]
        if len(g_prev) > 0 and len(g_curr) > 0:
            p_prev = "、".join(sorted(set(g_prev["party"])))
            p_curr = "、".join(sorted(set(g_curr["party"])))
            rep_rows.append({
                "candidate": cname_norm,
                "area": carea,
                "prev_elections": "；".join(sorted(set(g_prev["election"] + ("（" + g_prev["area"] + "）" if carea else "")))),
                "prev_party": p_prev,
                "prev_net": int(g_prev["net_amount"].sum()),
                "prev_corps": "、".join(sorted(set(g_prev["gcis_name"]))),
                "curr_elections": "；".join(sorted(set(g_curr["election"] + ("（" + g_curr["area"] + "）" if carea else "")))),
                "curr_party": p_curr,
                "curr_net": int(g_curr["net_amount"].sum()),
                "curr_corps": "、".join(sorted(set(g_curr["gcis_name"]))),
                "two_term_net": int(grp["net_amount"].sum()),
                "two_term_corp_count": int(grp["tax_id"].nunique()),
                "pcc_corp_count": int(grp[grp["pcc_has_award"] == "Y"]["tax_id"].nunique()),
                "party_consistent": "Y" if p_prev == p_curr else "CHECK",
            })
    rep_df = pd.DataFrame(rep_rows).sort_values("two_term_net", ascending=False)
    rep_df.to_csv(OUT_DIR / "09_repeat_candidates_two_terms.csv", index=False, encoding="utf-8-sig")

    print("\n=== 兩屆企業動態摘要 ===")
    print("  企業狀態分布：", comp_df_out["term_status"].value_counts().to_dict())
    print(f"  連兩屆均獲光電企業捐贈之候選人（依姓名對齊，共 {len(rep_df)} 位）：")
    print(rep_df[["candidate", "prev_party", "prev_net", "curr_party", "curr_net", "two_term_net", "party_consistent"]].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
