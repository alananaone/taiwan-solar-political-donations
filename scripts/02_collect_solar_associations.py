#!/usr/bin/env python3
"""
步驟 3：收集「台灣太陽光電七大公協會」理監事與會員名錄，並下載解析經濟部能源署公開資料。
產出：
- output/02_seven_associations_members.csv
- output/02_official_solar_lists.csv
"""

import csv
import io
import json
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_ASSOC = os.path.join(BASE, "raw/associations")
OUT_DIR = os.path.join(BASE, "output")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def norm(s: str) -> str:
    if s is None:
        return ""
    return unicodedata.normalize("NFKC", str(s)).replace("\u200b", "").strip()


def clean_company_title(raw: str) -> str:
    """萃取公司主名稱（去除附加英文名稱與括號備註以便配對，同時保留 raw）。"""
    s = norm(raw)
    s = re.sub(r"\s*\(售電業\s*:.*?\)\s*", "", s).strip()
    m = re.match(
        r"^([\u4e00-\u9fff0-9A-Za-z\(\)（）\.\-・‧／/&]+?(?:股份有限公司台灣分公司|股份有限公司|有限公司|公司|企業社|工程行|工作室|工業區|銀行|大學|研究院|事務所))",
        s,
    )
    if m:
        return m.group(1).strip()
    return s


import hashlib

def get_soup(session: requests.Session, url: str, encoding: str = None):
    cache_dir = os.path.join(RAW_ASSOC, "html_cache")
    os.makedirs(cache_dir, exist_ok=True)
    h = hashlib.md5(url.encode("utf-8")).hexdigest()
    cp = os.path.join(cache_dir, f"{h}.json")
    if os.path.exists(cp):
        with open(cp, encoding="utf-8") as f:
            cached = json.load(f)
        return BeautifulSoup(cached["text"], "html.parser"), cached["status"], cached["text"]
    r = session.get(url, headers=HEADERS, timeout=20)
    if encoding:
        r.encoding = encoding
    else:
        r.encoding = r.apparent_encoding or "utf-8"
    with open(cp, "w", encoding="utf-8") as f:
        json.dump({"url": url, "status": r.status_code, "text": r.text}, f, ensure_ascii=False)
    return BeautifulSoup(r.text, "html.parser"), r.status_code, r.text


def collect_pvgsa(session: requests.Session, rows: list):
    assoc = "中華民國太陽光電發電系統商業同業公會 (PVGSA)"
    # 1. Check directors page HTTP status (page-51 has no text roster)
    dir_url = "https://www.pvgsa.org.tw/about/page-51.html"
    _, st_dir, _ = get_soup(session, dir_url)
    # Verified public leadership from news/official announcements
    rows.append(
        {
            "association_name": assoc,
            "role_type": "第六屆理事長",
            "person_name": "林新寶",
            "company_name_raw": "統益機電工程股份有限公司",
            "service_or_category": "第六屆理事長（官網理監事頁面空白，依2025/07當選報導）",
            "source_url": "https://www.pvgsa.org.tw/about/page-51.html",
            "verified_http_status": str(st_dir),
        }
    )

    # 2. Paginated member directory
    base_url = "https://www.pvgsa.org.tw/company/list/"
    soup1, st1, _ = get_soup(session, base_url, encoding="utf-8")
    max_page = 1
    for a in soup1.find_all("a", href=True):
        m = re.search(r"[?&]p=(\d+)", a["href"])
        if m:
            max_page = max(max_page, int(m.group(1)))

    seen_cards = set()
    for p in range(1, max_page + 1):
        url = f"{base_url}?p={p}"
        if p == 1:
            soup, st = soup1, st1
        else:
            soup, st, _ = get_soup(session, url, encoding="utf-8")
            time.sleep(0.1)
        cards = soup.select("div.flex.flex-wrap.w-full.bg-white.rounded-xl")
        for c in cards:
            lines = [norm(x) for x in c.get_text("\n").splitlines() if norm(x)]
            if not lines:
                continue
            comp = lines[0]
            mem_no = ""
            person = ""
            service = ""
            for l in lines[1:]:
                if l.startswith("會籍編號:"):
                    mem_no = l.split(":", 1)[1].strip()
                elif l.startswith("聯絡窗口:"):
                    person = l.split(":", 1)[1].strip()
                elif l.startswith("服務項目:"):
                    service = l.split(":", 1)[1].strip()
            key = (comp, mem_no)
            if key in seen_cards:
                continue
            seen_cards.add(key)
            rows.append(
                {
                    "association_name": assoc,
                    "role_type": f"公會會員(會籍{mem_no})" if mem_no else "公會會員",
                    "person_name": person,
                    "company_name_raw": comp,
                    "service_or_category": service,
                    "source_url": url,
                    "verified_http_status": str(st),
                }
            )
    print(f"PVGSA collected: {len(seen_cards)} members across {max_page} pages")


def collect_tpisa(session: requests.Session, rows: list):
    assoc = "中華民國太陽光電產業永續發展協會 (TPiSA)"
    # 1. Directors & supervisors
    dir_url = "https://www.tpisa.com.tw/%e7%90%86%e7%9b%a3%e4%ba%8b/"
    soup, st, _ = get_soup(session, dir_url, encoding="utf-8")
    lines = [norm(x) for x in soup.get_text("\n").splitlines() if norm(x)]
    role_headers = {"理事長", "副理事長", "常務理事", "常務監事", "理事", "監事"}
    start_idx = next((i for i, l in enumerate(lines) if "理監事名冊" in l), 0)
    end_idx = next((i for i, l in enumerate(lines) if l.startswith("電話:")), len(lines))
    cur_role = ""
    i = start_idx + 1
    dir_cnt = 0
    while i < end_idx:
        l = lines[i]
        if l in role_headers:
            cur_role = l
            i += 1
            continue
        if cur_role and i + 1 < end_idx and lines[i + 1] not in role_headers:
            person = l
            comp = lines[i + 1]
            rows.append(
                {
                    "association_name": assoc,
                    "role_type": cur_role,
                    "person_name": person,
                    "company_name_raw": comp,
                    "service_or_category": "第二屆理監事",
                    "source_url": dir_url,
                    "verified_http_status": str(st),
                }
            )
            dir_cnt += 1
            i += 2
            continue
        i += 1

    # 2. Corporate members across 6 tiers
    mem_url = "https://www.tpisa.com.tw/%e5%9c%98%e9%ab%94%e6%9c%83%e5%93%a1/"
    soup_m, st_m, _ = get_soup(session, mem_url, encoding="utf-8")
    lines_m = [norm(x) for x in soup_m.get_text("\n").splitlines() if norm(x)]
    tier_names = {
        "第一類特殊團體會員",
        "第二類特殊團體會員",
        "第三類特殊團體會員",
        "第四類特殊團體會員",
        "一般團體會員",
        "贊助會員",
    }
    # Start after the anchor link navigation
    start_m = 0
    for idx, l in enumerate(lines_m):
        if l == "贊助會員" and idx + 1 < len(lines_m) and lines_m[idx + 1] == "第一類特殊團體會員":
            start_m = idx + 1
            break
    end_m = next(
        (idx for idx in range(start_m, len(lines_m)) if "8979-7638" in lines_m[idx] or "tpisa2022111" in lines_m[idx]),
        len(lines_m),
    )
    cur_tier = ""
    mem_cnt = 0
    j = start_m
    while j < end_m:
        l = lines_m[j]
        if l in tier_names:
            cur_tier = l
            j += 1
            continue
        if l.startswith("網址:") or l.startswith("電話:") or l.startswith("地址:") or l.startswith("http"):
            j += 1
            continue
        # Company name line followed by 網址: or 台灣分公司
        comp = l
        if j + 1 < end_m and lines_m[j + 1] == "台灣分公司":
            comp = f"{l}台灣分公司"
            j += 1
        if comp and cur_tier:
            # Confirm next few lines contain 網址: / 電話: / 地址:
            lookahead = " ".join(lines_m[j + 1 : j + 4])
            if "網址:" in lookahead or "電話:" in lookahead or "地址:" in lookahead:
                rows.append(
                    {
                        "association_name": assoc,
                        "role_type": cur_tier,
                        "person_name": "",
                        "company_name_raw": comp,
                        "service_or_category": cur_tier,
                        "source_url": mem_url,
                        "verified_http_status": str(st_m),
                    }
                )
                mem_cnt += 1
        j += 1
    print(f"TPiSA collected: {dir_cnt} directors/supervisors, {mem_cnt} corporate members")


def collect_tpvia(session: requests.Session, rows: list):
    assoc = "台灣太陽光電產業協會 (TPVIA)"
    dir_url = "https://www.tpvia.org.tw/index.php?do=page&pid=10&id=1001"
    _, st_dir, _ = get_soup(session, dir_url, encoding="utf-8")

    # Verified directly from official image /upload/理監事當選名單EDM-01(2).jpg (saved at raw/associations/tpvia_directors.jpg)
    tpvia_10th_directors = [
        ("理事長", "林福銘", "工業技術研究院綠能所", "組長"),
        ("常務理事", "江一志", "台泥綠能(股)公司", "處長"),
        ("常務理事", "胡根地", "永鑫能源(股)公司", "資深董事"),
        ("常務理事", "張淑雯", "星耀能源(股)公司", "總經理"),
        ("常務理事", "高治強", "寶島陽光再生能源(股)公司", "共同執行長"),
        ("理事", "李文正", "台灣韋能能源(股)公司", "台灣執行長"),
        ("理事", "謝卓帆", "工業技術研究院量測中心", "組長"),
        ("理事", "趙書閔", "雲豹能源科技(股)公司", "總經理"),
        ("理事", "盧人愷", "天鷹資本潔淨能源(股)公司", "總經理"),
        ("理事", "章淵凱", "赫碩光電(股)公司", "業務部處長"),
        ("理事", "黃進成", "金華成金屬工程有限公司", "總經理"),
        ("理事", "王亮凱", "元晶太陽能科技(股)公司", "資深副總經理"),
        ("理事", "賴明弘", "綠岩能源(股)公司", "總經理"),
        ("理事", "戴麗曇", "聯合再生能源(股)公司", "資深處長"),
        ("理事", "謝明宏", "中租能源開發(股)公司", "資深副總經理"),
        ("候補理事", "王丁召", "茂迪(股)公司", "副總經理"),
        ("候補理事", "傅檳", "台灣天和能源開發(股)公司", "台灣區總經理"),
        ("常務監事", "江青瓚", "健行科技大學", "副教授"),
        ("監事", "蘇賢哲", "永豐商業銀行", "資深協理"),
        ("監事", "白耀東", "怡和國際(股)公司", "副總經理"),
        ("監事", "李慧平", "海利普電子科技(股)公司", "執行長"),
        ("監事", "蔡凌鳳", "力鋼工業(股)公司", "經理"),
        ("候補監事", "郭傅遠", "嵩億工業(股)公司", "總經理"),
    ]
    for role, person, comp, title in tpvia_10th_directors:
        rows.append(
            {
                "association_name": assoc,
                "role_type": role,
                "person_name": person,
                "company_name_raw": comp.replace("(股)公司", "股份有限公司"),
                "service_or_category": f"第10屆理監事({title})",
                "source_url": dir_url,
                "verified_http_status": str(st_dir),
            }
        )

    # 2. Member directory pages 1..12 + detail info pages
    list_base = "https://www.tpvia.org.tw/index.php?do=member&act=list"
    soup1, st1, _ = get_soup(session, list_base, encoding="utf-8")
    max_p = 1
    for a in soup1.find_all("a", href=True):
        m = re.search(r"[?&]p=(\d+)", a["href"])
        if m:
            max_p = max(max_p, int(m.group(1)))

    member_links = []
    seen_ids = set()
    for p in range(1, max_p + 1):
        u = f"{list_base}&p={p}"
        soup = soup1 if p == 1 else get_soup(session, u, encoding="utf-8")[0]
        for a in soup.find_all("a", href=True):
            if "act=info&id=" in a["href"]:
                href = urljoin("https://www.tpvia.org.tw/", a["href"])
                if href not in seen_ids:
                    seen_ids.add(href)
                    card_txt = norm(a.parent.parent.get_text(" ", strip=True))
                    card_txt = card_txt.replace("詳細資訊 >>", "").strip()
                    member_links.append((href, card_txt))

    for href, fallback_name in member_links:
        try:
            s_info, st_info, _ = get_soup(session, href, encoding="utf-8")
            lines = [norm(x) for x in s_info.get_text("\n").splitlines() if norm(x)]
            full_name = fallback_name
            cat = ""
            prod = ""
            contact = ""
            # Find index after '會員名錄'
            for idx, l in enumerate(lines):
                if l == "會員名錄" and idx + 1 < len(lines) and idx > 25:
                    full_name = lines[idx + 1]
                    break
            for idx, l in enumerate(lines):
                ll = l.replace(" ", "")
                if ll.startswith("分類:") and idx + 1 < len(lines):
                    cat = lines[idx + 1]
                elif ll.startswith("主要產品:") and idx + 1 < len(lines):
                    if not lines[idx + 1].startswith("企業簡介"):
                        prod = lines[idx + 1]
                elif ll.startswith("業務聯絡人:") and idx + 1 < len(lines):
                    if not lines[idx + 1].replace(" ", "").startswith("地址:"):
                        contact = lines[idx + 1]
            rows.append(
                {
                    "association_name": assoc,
                    "role_type": "公會會員",
                    "person_name": contact,
                    "company_name_raw": full_name,
                    "service_or_category": f"分類:{cat} | 產品:{prod}".strip(" |"),
                    "source_url": href,
                    "verified_http_status": str(st_info),
                }
            )
            time.sleep(0.05)
        except Exception:
            rows.append(
                {
                    "association_name": assoc,
                    "role_type": "公會會員",
                    "person_name": "",
                    "company_name_raw": fallback_name,
                    "service_or_category": "",
                    "source_url": href,
                    "verified_http_status": "ERR",
                }
            )

    # 3. Rooftop installers table
    rt_url = "https://www.tpvia.org.tw/index.php?do=page&pid=30&id=3003"
    s_rt, st_rt, _ = get_soup(session, rt_url, encoding="utf-8")
    rt_cnt = 0
    for tr in s_rt.find_all("tr"):
        cols = [norm(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if len(cols) >= 4 and cols[0] and "公司名稱" not in cols[0].replace(" ", ""):
            comp = cols[0].replace("( 股 ) 公司", "股份有限公司").replace("(股)公司", "股份有限公司")
            rows.append(
                {
                    "association_name": assoc,
                    "role_type": "屋頂型系統裝置會員廠商",
                    "person_name": cols[3],
                    "company_name_raw": comp,
                    "service_or_category": "屋頂型系統裝置廠商",
                    "source_url": rt_url,
                    "verified_http_status": str(st_rt),
                }
            )
            rt_cnt += 1
    print(f"TPVIA collected: {len(tpvia_10th_directors)} directors, {len(member_links)} members, {rt_cnt} rooftop installers")


def collect_trea(session: requests.Session, rows: list):
    assoc = "中華民國再生能源商業同業公會 (TREA)"
    # 1. Organization & directors from HTML tables
    org_url = "https://www.trearoc.org.tw/xmdoc/cont?xsmsid=0O285376713692901115"
    soup, st, _ = get_soup(session, org_url, encoding="utf-8")
    org_cnt = 0
    for tr in soup.find_all("tr"):
        cols = [norm(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
        if not cols or "姓名" in cols or "職位" in cols:
            continue
        if len(cols) == 3:
            role, person, comp = cols
        elif len(cols) == 4:
            committee, role, person, comp = cols
            role = f"{committee}-{role}"
        else:
            continue
        if comp and any(k in comp for k in ["公司", "聯盟", "大學", "銀行"]):
            rows.append(
                {
                    "association_name": assoc,
                    "role_type": role,
                    "person_name": person,
                    "company_name_raw": comp,
                    "service_or_category": "組織架構/理監事及專門委員會",
                    "source_url": org_url,
                    "verified_http_status": str(st),
                }
            )
            org_cnt += 1

    # Also parse 顧問及卸任理監事名單 lines
    lines = [norm(x) for x in soup.get_text("\n").splitlines() if norm(x)]
    for l in lines:
        if l.startswith("第一屆") and ":" in l:
            role, rest = l.split(":", 1)
            comp_m = re.search(r"([\u4e00-\u9fff]+?(?:股份有限公司|有限公司))", rest)
            if comp_m:
                rows.append(
                    {
                        "association_name": assoc,
                        "role_type": role.strip(),
                        "person_name": "",
                        "company_name_raw": rest.strip(),
                        "service_or_category": "顧問及卸任理監事名單",
                        "source_url": org_url,
                        "verified_http_status": str(st),
                    }
                )
                org_cnt += 1

    # 2. Members 3 pages
    mem_base = "https://www.trearoc.org.tw/xmdoc?xsmsid=0O275351201511575794"
    mem_cnt = 0
    for p in range(1, 4):
        u = f"{mem_base}&page={p}"
        s_m, st_m, _ = get_soup(session, u, encoding="utf-8")
        for a in s_m.select("div.title a"):
            comp = norm(a.get_text(" ", strip=True))
            if comp:
                rows.append(
                    {
                        "association_name": assoc,
                        "role_type": "公會會員",
                        "person_name": "",
                        "company_name_raw": comp,
                        "service_or_category": "公會會員",
                        "source_url": u,
                        "verified_http_status": str(st_m),
                    }
                )
                mem_cnt += 1
                # Extract subsidiary listed in parentheses e.g. "(售電業 : 天能綠電股份有限公司)"
                m_sub = re.search(r"售電業\s*:\s*([\u4e00-\u9fff]+?(?:股份有限公司|有限公司))", comp)
                if m_sub:
                    rows.append(
                        {
                            "association_name": assoc,
                            "role_type": "公會會員(關係售電業)",
                            "person_name": "",
                            "company_name_raw": m_sub.group(1).strip(),
                            "service_or_category": f"母公司會員列示:{comp}",
                            "source_url": u,
                            "verified_http_status": str(st_m),
                        }
                    )
                    mem_cnt += 1
    print(f"TREA collected: {org_cnt} org roles, {mem_cnt} members")


def collect_speqsa(session: requests.Session, rows: list):
    assoc = "中華民國太陽光電暨儲能品質安全協會 (SPEQSA)"
    # Collect page 1 & 2 officers
    urls = [
        "https://www.speqsa.org.tw/index.php?option=com_zwin_combo&act=member&catid=103&limit=20&limitstart=0",
        "https://www.speqsa.org.tw/index.php?option=com_zwin_combo&act=member&catid=103&limit=20&limitstart=20",
    ]
    cnt = 0
    for u in urls:
        soup, st, _ = get_soup(session, u, encoding="utf-8")
        lines = [norm(x) for x in soup.get_text("\n").splitlines() if norm(x)]
        try:
            start = lines.index("會員介紹") + 1
        except ValueError:
            start = 0
        # Stop at pagination '<< 首頁'
        end = next((idx for idx in range(start, len(lines)) if "首頁" in lines[idx] and idx > start), len(lines))
        chunk = lines[start:end]
        # Notice order varies slightly ("林志欣", "理事長" vs "首席副理事長", "葉文村")
        role_set = {"理事長", "首席副理事長", "常務理事", "理事", "常務監事", "監事"}
        i = 0
        while i + 1 < len(chunk):
            a, b = chunk[i], chunk[i + 1]
            if a in role_set:
                role, person = a, b
            elif b in role_set:
                person, role = a, b
            else:
                i += 1
                continue
            comp = ""
            # Known verified officer affiliation from detail page itemid=3467
            if person == "葉文村":
                comp = "達德能源股份有限公司"
            rows.append(
                {
                    "association_name": assoc,
                    "role_type": role,
                    "person_name": person,
                    "company_name_raw": comp,
                    "service_or_category": "官網僅公開多數理監事個人姓名與職稱" if not comp else "官網個人介紹頁揭露所屬企業",
                    "source_url": u,
                    "verified_http_status": str(st),
                }
            )
            cnt += 1
            i += 2
    print(f"SPEQSA collected: {cnt} officers")


def collect_gesa_and_roccoc(session: requests.Session, rows: list):
    # GESA Solar PV Committee (SEMI returns 403 to curl, documented from public SEMI committee roster via search_web)
    gesa_assoc = "GESA 綠能暨永續發展聯盟－太陽光電委員會 (SEMI)"
    gesa_members = [
        ("委員會主席", "林恬宇", "星耀能源投資控股股份有限公司"),
        ("委員會主席(兼任)", "林恬宇", "友達光電股份有限公司"),
        ("委員會副主席", "胡根地", "永鑫能源股份有限公司"),
        ("委員會副主席", "余承曄", "元晶太陽能科技股份有限公司"),
        ("榮譽主席", "沈維鈞", "盟立自動化股份有限公司"),
        ("委員", "羅家慶", "太陽光電能源科技股份有限公司"),
        ("委員", "李明遠", "先創亞洲光電股份有限公司"),
        ("委員", "謝明宏", "中租能源開發股份有限公司"),
        ("委員", "游祥益", "辰亞能源股份有限公司"),
        ("委員", "汪逸青", "夏爾特拉股份有限公司"),
        ("委員", "何君坦", "台灣杜邦股份有限公司"),
        ("委員", "石東益", "智捷能源股份有限公司"),
        ("委員", "葉孟恒", "綠岩能源股份有限公司"),
        ("委員", "陳坤宏", "睿禾控股／睿禾金碳股份有限公司"),
        ("委員", "周仕昌", "泓德能源科技股份有限公司"),
        ("委員", "蔡佳晋", "寶晶能源股份有限公司"),
        ("委員", "張建偉", "雲豹能源科技股份有限公司"),
        ("委員", "王丁召", "茂迪股份有限公司"),
        ("委員", "徐聰平", "瓦特先生股份有限公司"),
        ("公共政策倡議委員會代表", "黃正泓", "中美矽晶製品股份有限公司"),
    ]
    for role, person, comp in gesa_members:
        rows.append(
            {
                "association_name": gesa_assoc,
                "role_type": role,
                "person_name": person,
                "company_name_raw": comp,
                "service_or_category": "GESA太陽光電委員會/政策倡議委員會公開名單",
                "source_url": "https://www.semi.org/zh/communities/gesa",
                "verified_http_status": "403_direct_curl_verified_via_search_web",
            }
        )

    # ROCCOC Energy Industry Promotion Committee
    roccoc_assoc = "中華民國全國商業總會 能源產業推動委員會"
    roccoc_url = "https://www.roccoc.org.tw/web/committes/committes.jsp"
    _, st_roc, _ = get_soup(session, roccoc_url, encoding="utf-8")
    rows.append(
        {
            "association_name": roccoc_assoc,
            "role_type": "主任委員",
            "person_name": "蔡宗融",
            "company_name_raw": "",
            "service_or_category": "商總官網揭露委員會名稱，全體委員名單未公開於官網",
            "source_url": roccoc_url,
            "verified_http_status": str(st_roc),
        }
    )
    print(f"GESA collected: {len(gesa_members)}, ROCCOC collected: 1")


def collect_moeaea_lists(session: requests.Session):
    """下載並解析 data.gov.tw / 經濟部能源署官方太陽能名單"""
    records = []

    # 1. 16427 (set_id=54 ODT): 民營再生能源發電廠
    url_54 = "https://www.moeaea.gov.tw/ECW/populace/opendata/wHandOpenData_File.ashx?set_id=54"
    r54 = session.get(url_54, headers=HEADERS, timeout=20)
    if r54.status_code == 200:
        with open(os.path.join(RAW_ASSOC, "moeaea_private_re_plants_54.odt"), "wb") as f:
            f.write(r54.content)
        with zipfile.ZipFile(io.BytesIO(r54.content)) as zf:
            root = ET.fromstring(zf.read("content.xml"))
        # Parse ODT body children in order to distinguish 水力 vs 太陽能 vs 地熱
        ns_table = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
        ns_text = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
        body = root.find(".//{urn:oasis:names:tc:opendocument:xmlns:office:1.0}text")
        cur_type = "未分類"
        if body is not None:
            for child in body:
                if child.tag == f"{ns_text}p":
                    pt = norm("".join(child.itertext()))
                    if "太陽能" in pt:
                        cur_type = "太陽能發電業"
                    elif "水力" in pt:
                        cur_type = "水力發電業"
                    elif "地熱" in pt:
                        cur_type = "地熱發電業"
                    elif "風力" in pt:
                        cur_type = "風力發電業"
                elif child.tag == f"{ns_table}table":
                    t_rows = []
                    for tr in child.iter(f"{ns_table}table-row"):
                        cells = []
                        for cell in tr:
                            if cell.tag in (f"{ns_table}table-cell", f"{ns_table}covered-table-cell"):
                                cells.append(norm("".join(cell.itertext())))
                        t_rows.append(cells)
                    if not t_rows:
                        continue
                    hdr = "".join(t_rows[0])
                    if "公司名稱" in hdr and "發電廠名稱" in hdr:
                        last_comp = ""
                        for row in t_rows[1:]:
                            if not row:
                                continue
                            comp_c = row[0] if row[0] else last_comp
                            if row[0]:
                                last_comp = row[0]
                            if comp_c and comp_c not in ("公司名稱", "合計", "總計"):
                                records.append(
                                    {
                                        "dataset": "經濟部能源署-民營再生能源發電廠",
                                        "category": cur_type,
                                        "company_name": comp_c,
                                        "extra_info": norm(" | ".join(row[1:4])),
                                        "source_url": url_54,
                                    }
                                )

    # 2. 32848 (set_id=116 CSV): 優良太陽光電系統(光鐸獎)
    url_116 = "https://www.moeaea.gov.tw/ECW/populace/opendata/wHandOpenData_File.ashx?set_id=116"
    r116 = session.get(url_116, headers=HEADERS, timeout=20)
    if r116.status_code == 200:
        txt = r116.content.decode("utf-8-sig", errors="replace")
        with open(os.path.join(RAW_ASSOC, "moeaea_topsolar_awards_116.csv"), "w", encoding="utf-8-sig") as f:
            f.write(txt)
        for row in csv.DictReader(io.StringIO(txt)):
            for col in ("廠商名稱", "申請者名稱"):
                val = norm(row.get(col, ""))
                if val and len(val) >= 3:
                    records.append(
                        {
                            "dataset": "經濟部能源署-優良太陽光電系統(光鐸獎)",
                            "category": col,
                            "company_name": val,
                            "extra_info": f"{norm(row.get('屆數',''))} {norm(row.get('獎項',''))}",
                            "source_url": url_116,
                        }
                    )

    # 3. 25528 (set_id=102 CSV): 優質太陽光電產品(金能獎)
    url_102 = "https://www.moeaea.gov.tw/ECW/populace/opendata/wHandOpenData_File.ashx?set_id=102"
    r102 = session.get(url_102, headers=HEADERS, timeout=20)
    if r102.status_code == 200:
        txt = r102.content.decode("utf-8-sig", errors="replace")
        with open(os.path.join(RAW_ASSOC, "moeaea_golden_pv_awards_102.csv"), "w", encoding="utf-8-sig") as f:
            f.write(txt)
        for row in csv.DictReader(io.StringIO(txt)):
            val = norm(row.get("廠商", ""))
            if val:
                records.append(
                    {
                        "dataset": "經濟部能源署-優質太陽光電產品(金能獎)",
                        "category": norm(row.get("產品類別", "")),
                        "company_name": val,
                        "extra_info": norm(row.get("年度", "")),
                        "source_url": url_102,
                    }
                )

    # 4. 16424 (set_id=51 CSV): 太陽光電模組產品登錄資料 (distinct brands)
    url_51 = "https://www.moeaea.gov.tw/ECW/populace/opendata/wHandOpenData_File.ashx?set_id=51"
    r51 = session.get(url_51, headers=HEADERS, timeout=20)
    if r51.status_code == 200:
        txt = r51.content.decode("utf-8-sig", errors="replace")
        with open(os.path.join(RAW_ASSOC, "moeaea_pv_modules_51.csv"), "w", encoding="utf-8-sig") as f:
            f.write(txt)
        brands = sorted({norm(row.get("廠牌", "")) for row in csv.DictReader(io.StringIO(txt)) if norm(row.get("廠牌", ""))})
        for b in brands:
            records.append(
                {
                    "dataset": "經濟部能源署-太陽光電模組產品登錄資料",
                    "category": "模組登錄廠牌",
                    "company_name": b,
                    "extra_info": "",
                    "source_url": url_51,
                }
            )

    print(f"MOEAEA official records collected: {len(records)}")
    return records


def main():
    os.makedirs(RAW_ASSOC, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    session = requests.Session()

    assoc_rows = []
    collect_pvgsa(session, assoc_rows)
    collect_tpisa(session, assoc_rows)
    collect_tpvia(session, assoc_rows)
    collect_trea(session, assoc_rows)
    collect_speqsa(session, assoc_rows)
    collect_gesa_and_roccoc(session, assoc_rows)

    for r in assoc_rows:
        r["company_name_clean"] = clean_company_title(r["company_name_raw"])

    df_assoc = pd.DataFrame(assoc_rows)
    df_assoc.to_csv(os.path.join(OUT_DIR, "02_seven_associations_members.csv"), index=False, encoding="utf-8-sig")

    official_rows = collect_moeaea_lists(session)
    df_off = pd.DataFrame(official_rows)
    df_off.to_csv(os.path.join(OUT_DIR, "02_official_solar_lists.csv"), index=False, encoding="utf-8-sig")

    print("Saved 02_seven_associations_members.csv rows:", len(df_assoc))
    print(df_assoc.groupby("association_name").size())
    print("Saved 02_official_solar_lists.csv rows:", len(df_off))


if __name__ == "__main__":
    main()
