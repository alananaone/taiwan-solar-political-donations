#!/usr/bin/env python3
"""
步驟 4：整合經濟部商工登記 (GCIS)、七大光電公協會名單、經濟部能源署公開名單，
進行同代表人/同地址集團關聯比對與嚴格誤判排除，建立三級「光電機構清冊」。

產出：
- output/03_solar_entities_master.csv
- output/03_excluded_false_positives.csv
"""

import csv
import json
import os
import re
import unicodedata
from collections import defaultdict

import pandas as pd
import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GCIS_CACHE_DIR = os.path.join(BASE, "raw/kiang_ardata/gcis.nat.g0v.tw")
GCIS_EXTRA_DIR = os.path.join(BASE, "raw/gcis_extra")
OUT_DIR = os.path.join(BASE, "output")

CORE_SOLAR_CODES = {"D101060", "D101011", "D101040", "D101070"}
AUX_ENERGY_CODES = {"IG03010", "E601010", "D101010"}
FOSSIL_CODES = {"D201040", "F112040", "F212050"}

# Explicitly verified false-positive or non-solar exclusions (documented with reason)
EXPLICIT_EXCLUSIONS = {
    "69651695": "離岸風電製造業(世紀離岸風電設備，非太陽光電)",
    "23556563": "鉛酸蓄電池製造業(廣隆光電科技，非太陽光電)",
    "86880449": "寬頻通訊與光電傳輸設備(達運光電，非太陽光電)",
    "28718932": "電信與保全系統服務(新光電通，非太陽光電)",
    "25073514": "精密化學/機械電子(台灣飛特光電，無太陽光電/能源業務)",
    "80601856": "光學監控設備(銳視光電，無能源發電代碼)",
    "28575511": "電子材料批發(威富光電，非太陽光電發電業)",
    "69670383": "電池與汽機車運輸零組件(明創能源，非太陽光電)",
    "29050730": "生物科技/奈米產品設計(綠能奈米科技，非太陽光電)",
    "53304087": "一般光學電子零組件(沅皜光電科技，非太陽光電)",
    "16561174": "光學儀器/照明燈具(瑩隆光電，非太陽光電)",
    "80011253": "表面處理電著塗裝(鴻光電著塗裝，誤中光電字樣)",
    "23274467": "表面處理電著塗裝(平光電著塗裝，誤中光電字樣)",
    "49114402": "一般電氣行(宏光電氣行，誤中光電字樣)",
    "86753611": "一般電器行(嶸光電器，誤中光電字樣)",
    "54608854": "補教事業(志光教育科技，誤中志光關鍵字)",
    "85594480": "綜合五金百貨(金三地綜合五金百貨，誤中三地關鍵字)",
    "23678159": "汽車買賣維修(向陽車業，誤中向陽關鍵字)",
    "28679781": "不動產建設開發(向陽開發建設，誤中向陽關鍵字)",
    "82831469": "農業科技(振富通農業科技，誤中富通關鍵字)",
    "13108659": "環保工程(友達環保科技，非友達光電)",
    "23251632": "環保清運(大亞環保，非大亞綠能)",
    "28584650": "製酒業(東太陽製酒，誤中太陽關鍵字)",
    "17899295": "教育用品零售(小太陽教育用品社，誤中太陽關鍵字)",
    "80251020": "液化石油氣與石油製品(三燕兄弟能源，非再生能源)",
    "80551906": "液化石油氣與石油製品(銘欣能源，非再生能源)",
    "25173627": "生技農業肥料業(台灣生技綠能，非太陽光電)",
    "53988434": "顧問與廣告業(昱崴帝一生技能源，非太陽光電)",
    "89310387": "建築清潔與病媒防治(正環綠能科技，非太陽光電)",
    "90898955": "木業合板與金屬加工(蔚來國際綠能，非太陽光電)",
    "80012823": "一般商品批發(太陽國際企業，非太陽光電)",
    "80736616": "金屬加工(元太金屬，誤中元太關鍵字)",
    "53473983": "電子材料與回收物料批發(台灣綠能材料，無發電或光電工程代碼)",
    "28095344": "一般電子零組件零售(頂尖光電，無光電發電代碼)",
    "53154849": "家具與五金批發(陸山光電，無能源代碼)",
    "53422373": "五金日常用品批發(順合光電，無能源代碼)",
    "28099735": "消防器材批發(岳森光電科技，無光電發電代碼)",
    "53502214": "一般商品零售/電器批發(汎美強光電，無光電發電代碼)",
    "24519476": "照明燈具(極亮鎂節能光電，非太陽光電)",
    "59058105": "電子/機械零件(中華精工光電，無光電發電代碼)",
    "28933756": "一般電子照明(環宇光電，無能源發電代碼)",
    "86988265": "一般電子/機械(岳華展光電，無光電發電代碼)",
    "54798952": "一般光電/電子(名馳光電科技，無發電代碼)",
    "54079165": "一般光學電子(璟元光電，無發電代碼)",
    "80457254": "一般電子/LED(佑冠光電科技，無發電代碼)",
    "53346431": "化學塑膠電子材料(友晁能源材料，無再生能源發電代碼)",
    "29075079": "微電子零組件(裕豐微電子科技，誤中微電關鍵字)",
    "27697641": "機械電器批發(興楠電業，無發電業代碼)",
    "82897807": "電機製造(順興電業，無發電業代碼)",
    "78709944": "電器承裝業行號(旭鵬電業行，非發電業)",
    "76821132": "電器零售業行號(宏亮電業行，非發電業)",
    "90681626": "家具五金與電器承裝(一六八電力科技，非再生能源發電業)",
    "59210621": "再生鋁合金鑄造與金屬回收(勁展綠能，非太陽光電)",
    "27453928": "醫療器材血糖機製造(訊映光電，非太陽光電)",
    "12959391": "室內裝潢與花卉園藝(景光電子科技，非太陽光電)",
    "54002693": "文教樂器與電器批發(昇運光電科技，非太陽光電)",
    "24724737": "五金日常用品批發(西北光電，非太陽光電)",
    "33856815": "電線電纜與視聽電子(裕光電業，非太陽光電)",
    "42771211": "疏濬與沙石工程(全通電業工程，非太陽光電)",
    "03317410": "通信器材與視聽電子(信裕電業，非太陽光電)",
    "22223413": "水管空調與消防工程(聯邦電力工程，非太陽光電)",
    "53280698": "一般配管與電器承裝(雲鼎電業工程，非太陽光電)",
    "82923684": "五金機械自控批發(力菱能源科技，無再生能源發電或IG03010代碼)",
    "83580200": "機械電焊與五金建材(宜信能源，無再生能源發電或IG03010代碼)",
    "54269860": "五金建材與電器批發零售(瞬展綠能，無再生能源發電或IG03010代碼)",
    "16297817": "五金電池與資訊器材批發(微欣能源科技，無再生能源發電或IG03010代碼)",
    "28155757": "廢棄物清除與廢木材回收再利用(協昇能源科技，非太陽光電)",
    "83582946": "薪炭木製品與熱能供應業(詮盛能源科技，非太陽光電)",
    "50914249": "住宅開發與廣告餐飲多角業(土盒子綠能行銷國際，非太陽光電)",
    "24210420": "室內裝潢與建材工程(真昌能源，非太陽光電)",
}

# Association members whose core business is steel/cables/construction/consulting/optical/cleaning (Tier 2 supply chain)
SUPPLY_CHAIN_ASSOC_TIDS = {
    "35836625",  # 新光鋼鐵 (鋼材結構，PVGSA會員)
    "42703170",  # 錦德鋼鐵 (鋼鐵建材，PVGSA會員)
    "31235657",  # 力鋼工業 (鋼結構，TPiSA 4類/TPVIA監事)
    "70712100",  # 立城鋼鐵 (鋼鐵，PVGSA會員)
    "54929624",  # 宇軒鋼鐵工程 (鋼鐵工程，PVGSA會員)
    "03064800",  # 太平洋電線電纜 (電纜，TPiSA 4類會員)
    "24991001",  # 億興企業 (五金建材，PVGSA會員)
    "16454554",  # 久鋒國際企業 (門窗玻璃鋼材，PVGSA會員)
    "13068740",  # 同順立 (鋼材門窗裝潢，PVGSA會員)
    "70798937",  # 集合成環保科技 (廢棄物清除處理與回收，PVGSA會員)
    "12998177",  # 萬世盛工程顧問 (工程技術顧問，PVGSA會員)
    "28963358",  # 創價心工程顧問 (工程技術顧問，TPiSA會員)
    "23746488",  # 達威光電 (機械/光學儀器/熱能，PVGSA會員)
    "59209167",  # 加雲聯網 (資通訊/電信與儲能系統整合，PVGSA會員)
    "97413007",  # 金氏科訊 (資訊/電子工程，PVGSA會員)
    "28650715",  # 諾亞聯合科技 (電子零組件/化工批發，PVGSA會員)
    "28601623",  # 芃柏科技 (資訊軟體/照明/電池，PVGSA會員)
    "54259027",  # 山月科技 (電器批發/太陽熱能與光電板清洗，PVGSA/TPiSA會員)
    "82102244",  # 凌積應用科技 (PVGSA會員)
    "24230381",  # 明軒科技 (PVGSA會員)
    "27289146",  # 士能科技 (電信機械批發，PVGSA會員)
    "83138699",  # 弘昌泰 (電器承裝/太陽熱能安裝，TREA會員)
    "24334816",  # 台灣達亨能源科技 (電信射頻/電子材料批發，PVGSA會員)
    "50941858",  # 樂泉享受 (人力派遣/管顧/能源服務，PVGSA會員)
}


def first_str(v) -> str:
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v or "")


def norm(s) -> str:
    return unicodedata.normalize("NFKC", first_str(s)).strip()


def norm_name_key(s: str) -> str:
    return norm(s).replace("臺", "台").replace(" ", "").replace("　", "")


def stem_name(s: str) -> str:
    k = norm_name_key(s)
    for suf in ("股份有限公司台灣分公司", "股份有限公司", "有限公司", "(股)公司", "公司"):
        if k.endswith(suf):
            k = k[: -len(suf)]
            break
    return k


def load_gcis(tid: str, fallback_name: str):
    p = os.path.join(GCIS_CACHE_DIR, f"{tid}.json")
    if not os.path.exists(p):
        os.makedirs(GCIS_EXTRA_DIR, exist_ok=True)
        ep = os.path.join(GCIS_EXTRA_DIR, f"{tid}.json")
        if not os.path.exists(ep):
            try:
                r = requests.get(f"https://company.g0v.ronny.tw/api/show/{tid}", timeout=10)
                with open(ep, "w", encoding="utf-8") as f:
                    f.write(r.text)
            except Exception:
                with open(ep, "w", encoding="utf-8") as f:
                    json.dump({"data": {}}, f)
        p = ep

    with open(p, encoding="utf-8") as f:
        raw = json.load(f)
    d = raw.get("data", {})
    if not isinstance(d, dict):
        d = {}

    gcis_name = norm(d.get("公司名稱") or d.get("商業名稱") or fallback_name)
    rep = norm(d.get("代表人姓名") or d.get("負責人姓名") or "")
    addr = norm(d.get("公司所在地") or d.get("地址") or "")
    cap = norm(d.get("實收資本額(元)") or d.get("資本總額(元)") or d.get("資本額(元)") or "")
    status = norm(d.get("公司狀況") or d.get("現況") or "")
    est_date_raw = d.get("核准設立日期") or {}
    if isinstance(est_date_raw, dict) and est_date_raw:
        est_date = f"{est_date_raw.get('year','')}-{est_date_raw.get('month','')}-{est_date_raw.get('day','')}"
    else:
        est_date = norm(est_date_raw)

    codes = set()
    biz_items = []
    if isinstance(d.get("所營事業資料"), list):
        for it in d["所營事業資料"]:
            if isinstance(it, list) and len(it) >= 2:
                c = norm(it[0])
                lbl = norm(it[1])
                if re.match(r"^[A-Z]{1,2}\d{5,6}$", c):
                    codes.add(c)
                biz_items.append(f"{c}:{lbl}".strip(":"))
            else:
                txt = norm(it)
                codes.update(re.findall(r"[A-Z]{1,2}\d{5,6}", txt))
                biz_items.append(txt)
    if d.get("營業項目"):
        txt = norm(d["營業項目"])
        codes.update(re.findall(r"[A-Z]{1,2}\d{5,6}", txt))
        biz_items.append(txt)
    if d.get("舊營業項目資料"):
        txt = norm(d["舊營業項目資料"])
        codes.update(re.findall(r"[A-Z]{1,2}\d{5,6}", txt))
        biz_items.append(txt)

    return {
        "gcis_name": gcis_name,
        "rep_name": rep,
        "address": addr,
        "address_norm": norm_name_key(addr),
        "capital": cap,
        "status": status,
        "est_date": est_date,
        "codes": codes,
        "biz_summary": "; ".join(biz_items[:8]),
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    df_corps = pd.read_csv(os.path.join(OUT_DIR, "01_unique_donating_corps.csv"), dtype={"tax_id": str}, encoding="utf-8-sig")

    corps = {}
    exact_to_tids = defaultdict(set)
    stem_to_tids = defaultdict(set)

    for _, row in df_corps.iterrows():
        tid = str(row["tax_id"]).strip()
        donor_name = norm(row["donor_name_primary"])
        g = load_gcis(tid, donor_name)
        rec = {
            "tax_id": tid,
            "donor_name_primary": donor_name,
            "gcis_name": g["gcis_name"],
            "rep_name": g["rep_name"],
            "address": g["address"],
            "address_norm": g["address_norm"],
            "capital": g["capital"],
            "status": g["status"],
            "est_date": g["est_date"],
            "codes": g["codes"],
            "biz_summary": g["biz_summary"],
            "donation_count": int(row["donation_count"]),
            "candidate_count": int(row["candidate_count"]),
            "total_gross": float(row["total_gross"]),
            "total_returned": float(row["total_returned"]),
            "total_net": float(row["total_net"]),
            "elections": row["elections"],
        }
        corps[tid] = rec
        for nm in (donor_name, g["gcis_name"]):
            if nm:
                exact_to_tids[norm_name_key(nm)].add(tid)
                st = stem_name(nm)
                if len(st) >= 2:
                    stem_to_tids[st].add(tid)

    # 1. Match 7 associations
    assoc_hits = defaultdict(list)
    assoc_leader_people = set()
    df_assoc = pd.read_csv(os.path.join(OUT_DIR, "02_seven_associations_members.csv"), dtype=str, encoding="utf-8-sig").fillna("")
    for _, r in df_assoc.iterrows():
        if any(k in r["role_type"] for k in ("理事長", "理事", "監事", "主委", "主席", "代表")) and r["person_name"]:
            assoc_leader_people.add(norm(r["person_name"]))
        comp = norm(r["company_name_clean"] or r["company_name_raw"])
        if not comp:
            continue
        tids = set(exact_to_tids.get(norm_name_key(comp), set()))
        if not tids and len(stem_name(comp)) >= 3:
            tids = set(stem_to_tids.get(stem_name(comp), set()))
        for tid in tids:
            assoc_hits[tid].append(f"{r['association_name']}[{r['role_type']}]")

    # Add well-known solar leadership names directly linked to 7-association member firms
    assoc_leader_people.update(["賴勁麟", "譚宇軒", "趙書閔", "陳貴光", "蔡佳晋", "沈尚弘", "林新寶", "謝明宏", "陳坤宏", "胡惠森", "林恬宇", "徐秀蘭", "賴明弘", "郭世堂", "葉孟恒", "王丁召"])

    # 2. Match MOEAEA official lists (exclude Hydro / Geothermal plants)
    off_hits = defaultdict(list)
    df_off = pd.read_csv(os.path.join(OUT_DIR, "02_official_solar_lists.csv"), dtype=str, encoding="utf-8-sig").fillna("")
    for _, r in df_off.iterrows():
        if r["category"] in ("水力發電業", "地熱發電業"):
            continue
        comp = norm(r["company_name"])
        if len(comp) < 3:
            continue
        tids = set(exact_to_tids.get(norm_name_key(comp), set()))
        if not tids and len(stem_name(comp)) >= 3:
            tids = set(stem_to_tids.get(stem_name(comp), set()))
        for tid in tids:
            off_hits[tid].append(f"{r['dataset']}({r['category']})")

    # 3. Identify core solar HQ addresses for verified group/SPV linking
    core_hq_addrs = {}
    seed_tids = set(assoc_hits.keys()) | set(off_hits.keys())
    for tid in seed_tids:
        if tid in SUPPLY_CHAIN_ASSOC_TIDS or tid in EXPLICIT_EXCLUSIONS:
            continue
        c = corps[tid]
        if (c["codes"] & CORE_SOLAR_CODES) or any(k in c["gcis_name"] for k in ("太陽", "光電", "綠能", "能源", "電力")):
            if c["address_norm"]:
                core_hq_addrs[c["address_norm"]] = c["gcis_name"]

    # Classify each entity
    master_rows = []
    excluded_rows = []

    solar_name_kws = ("太陽", "光電", "綠能", "綠電", "光儲")
    energy_name_kws = ("太陽", "光電", "綠能", "綠電", "能源", "電力", "發電", "電業", "儲能")

    for tid, c in corps.items():
        nm = c["gcis_name"]
        codes = c["codes"]
        in_assoc = sorted(set(assoc_hits.get(tid, [])))
        in_off = sorted(set(off_hits.get(tid, [])))
        has_core_code = bool(codes & CORE_SOLAR_CODES)
        has_ig = "IG03010" in codes
        has_fossil = bool(codes & FOSSIL_CODES)

        rep_is_leader = c["rep_name"] in assoc_leader_people
        hq_match_parent = core_hq_addrs.get(c["address_norm"], "")

        has_solar_kw = any(k in nm for k in solar_name_kws)
        has_energy_kw = any(k in nm for k in energy_name_kws)

        # Group SPV link: same HQ address as core solar firm + energy keyword/code, OR rep is 7-assoc leader + (energy keyword or core code)
        # Note: exclude small sole-proprietorships (工程行/企業行) from rep-name matching to avoid common-name false positives
        is_sole_prop = nm.endswith("行") or nm.endswith("社")
        group_linked = False
        group_reason = ""
        if hq_match_parent and hq_match_parent != nm and (has_energy_kw or has_core_code):
            group_linked = True
            group_reason = f"與核心光電企業同登記地址({hq_match_parent})"
        elif rep_is_leader and not is_sole_prop and (has_energy_kw or has_core_code):
            group_linked = True
            group_reason = f"代表人為七大公協會核心幹部({c['rep_name']})"

        # Check explicit exclusion or fossil fuel exclusion first
        if tid in EXPLICIT_EXCLUSIONS and not (in_assoc and tid not in SUPPLY_CHAIN_ASSOC_TIDS):
            excluded_rows.append(
                {
                    **{k: c[k] for k in ("tax_id", "donor_name_primary", "gcis_name", "rep_name", "total_gross", "total_net", "donation_count", "candidate_count")},
                    "codes": " ".join(sorted(codes & (CORE_SOLAR_CODES | AUX_ENERGY_CODES | FOSSIL_CODES))),
                    "exclusion_reason": EXPLICIT_EXCLUSIONS[tid],
                    "biz_summary": c["biz_summary"],
                }
            )
            continue

        if has_fossil and has_energy_kw and not in_assoc and not has_core_code:
            excluded_rows.append(
                {
                    **{k: c[k] for k in ("tax_id", "donor_name_primary", "gcis_name", "rep_name", "total_gross", "total_net", "donation_count", "candidate_count")},
                    "codes": " ".join(sorted(codes & (CORE_SOLAR_CODES | AUX_ENERGY_CODES | FOSSIL_CODES))),
                    "exclusion_reason": "石油製品/液化石油氣能源業(非再生能源)",
                    "biz_summary": c["biz_summary"],
                }
            )
            continue

        # Exclude North-Base (北基國際 23218091) or Tier 2 vs Tier 1 carefully:
        # Let's assign Tier 1 / Tier 2 / Tier 3
        tier = ""
        reason_parts = []

        if tid in SUPPLY_CHAIN_ASSOC_TIDS:
            tier = "Tier 2"
            reason_parts.append("七大公協會會員(供應鏈/鋼鐵/電纜/工程顧問/設備協力)")
        elif in_assoc or in_off:
            # Pure/dedicated solar in association or official solar award list
            if tid == "86375580":  # 威昇開發 (向陽董事長陳貴光 + 光鐸獎 + D101060)
                tier = "Tier 1"
                reason_parts.append("能源署光鐸獎得主＋與向陽優能同代表人同地址＋D101060")
            elif has_energy_kw or has_core_code or has_ig:
                tier = "Tier 1"
                if in_assoc:
                    reason_parts.append("七大光電公協會成員")
                if in_off:
                    reason_parts.append("經濟部能源署光電名單")
            else:
                tier = "Tier 2"
                reason_parts.append("七大公協會或官方名單一般/協力成員")
        elif tid == "52476913":  # 太登太陽能 (rep=謝源一, board=周仕昌, 泓德能源集團)
            tier = "Tier 1"
            reason_parts.append("太陽能集團關聯企業(代表人謝源一/董事周仕昌為泓德能源與公協會核心幹部)")
        elif tid == "23218091":  # 北基國際 (rep=鍾嘉村, 三地能源集團母公司, 具D101060)
            tier = "Tier 2"
            reason_parts.append("光電集團母公司/跨業能源集團(三地能源母公司，代表人鍾嘉村，具D101060)")
        elif group_linked:
            tier = "Tier 1"
            reason_parts.append(group_reason)
        elif has_energy_kw and has_core_code:
            tier = "Tier 1"
            reason_parts.append("名稱屬能源/光電/太陽/綠能且具D1010xx發電代碼")
        elif (has_energy_kw and has_ig and not has_fossil) or tid == "16845146":
            # Energy/solar/green name + IG03010 (energy tech service), plus 16845146 中石化綠能科技
            tier = "Tier 2"
            if has_ig:
                reason_parts.append("名稱屬能源/光電/綠能且具IG03010能源技術服務業(無D1010xx發電代碼)")
            else:
                reason_parts.append("泛綠能工程企業(中石化綠能科技，具E601010電器承裝業)")
        elif tid == "50890149":  # 華洋電業開發 D101011
            tier = "Tier 2"
            reason_parts.append("具D101011發電業代碼之電業開發公司")
        elif codes & {"D101060", "D101011", "D101070"}:
            # Non-energy companies that happen to have D101060 (e.g. factory rooftop self-gen)
            tier = "Tier 3"
            reason_parts.append("非能源本業公司但商工登記含D101060/D101011代碼(跨業兼營/廠房屋頂自用)")
        elif has_energy_kw:
            excluded_rows.append(
                {
                    **{k: c[k] for k in ("tax_id", "donor_name_primary", "gcis_name", "rep_name", "total_gross", "total_net", "donation_count", "candidate_count")},
                    "codes": " ".join(sorted(codes & (CORE_SOLAR_CODES | AUX_ENERGY_CODES | FOSSIL_CODES))),
                    "exclusion_reason": "名稱含關鍵字但無D1010xx發電或IG03010能源技術服務代碼",
                    "biz_summary": c["biz_summary"],
                }
            )
            continue

        if tier:
            if has_core_code:
                reason_parts.append("GCIS:" + ",".join(sorted(codes & CORE_SOLAR_CODES)))
            elif has_ig:
                reason_parts.append("GCIS:IG03010")
            master_rows.append(
                {
                    "tax_id": tid,
                    "tier": tier,
                    "gcis_name": c["gcis_name"],
                    "donor_name_primary": c["donor_name_primary"],
                    "rep_name": c["rep_name"],
                    "capital": c["capital"],
                    "status": c["status"],
                    "est_date": c["est_date"],
                    "address": c["address"],
                    "core_codes": " ".join(sorted(codes & CORE_SOLAR_CODES)),
                    "aux_codes": " ".join(sorted(codes & AUX_ENERGY_CODES)),
                    "associations": " ; ".join(in_assoc),
                    "official_lists": " ; ".join(in_off),
                    "classification_reason": " | ".join(reason_parts),
                    "donation_count": c["donation_count"],
                    "candidate_count": c["candidate_count"],
                    "total_gross": c["total_gross"],
                    "total_returned": c["total_returned"],
                    "total_net": c["total_net"],
                    "elections": c["elections"],
                    "biz_summary": c["biz_summary"],
                }
            )

    df_master = pd.DataFrame(master_rows).sort_values(["tier", "total_gross"], ascending=[True, False])
    df_excl = pd.DataFrame(excluded_rows).sort_values("total_gross", ascending=False)

    df_master.to_csv(os.path.join(OUT_DIR, "03_solar_entities_master.csv"), index=False, encoding="utf-8-sig")
    df_excl.to_csv(os.path.join(OUT_DIR, "03_excluded_false_positives.csv"), index=False, encoding="utf-8-sig")

    print("=== Summary of 03_solar_entities_master.csv ===")
    print(df_master.groupby("tier")[["tax_id", "total_gross", "total_net"]].agg({"tax_id": "count", "total_gross": "sum", "total_net": "sum"}))
    print("\n=== ALL Tier 1 Companies ===")
    for _, r in df_master[df_master["tier"] == "Tier 1"].iterrows():
        print(f"  {r['total_gross']:10,.0f} | {r['tax_id']} | {r['gcis_name']} | codes={r['core_codes']} | {r['classification_reason'][:80]}")
    print("\n=== Top 50 Tier 2 Companies ===")
    for _, r in df_master[df_master["tier"] == "Tier 2"].head(50).iterrows():
        print(f"  {r['total_gross']:10,.0f} | {r['tax_id']} | {r['gcis_name']} | codes={r['core_codes']} {r['aux_codes']} | {r['classification_reason'][:70]}")
    print("\n=== Excluded False Positives (count =", len(df_excl), ") ===")
    for _, r in df_excl.head(25).iterrows():
        print(f"  {r['total_gross']:10,.0f} | {r['tax_id']} | {r['gcis_name']} | {r['exclusion_reason']}")


if __name__ == "__main__":
    main()
