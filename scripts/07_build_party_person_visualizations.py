#!/usr/bin/env python3
"""
產出單一桌面版 Lieflat 編輯室紙墨風格互動儀表板（107～113 年兩屆 12 類選舉）：
1. output/光電政治獻金_政黨與個人流向總覽.html
2. output/index.html（寫入完全相同之桌面儀表板，使本機首頁直達主圖表）

功能設計：
- 回歸原始 Lieflat 紙墨美學（#F0EFEB 暖紙底、#F6F5F1 紙面卡、#1C1C1A 深墨、B3 深色三段桑基絲線圖、L16 單色墨階熱力矩陣、F5 垂直刻度條、L2 暖紙膠囊稽核列）。
- 不再生成二分關係網絡圖與手機預覽入口頁；聚焦寬敞桌面雙欄／全幅閱覽體驗。
- 頂部配備 6 枚即時圖層開關＋動態數字脈動控制台（動畫計數器＋全尺寸基準比例條＋邊際增減預覽），撥動開關時所有數字、比例條、深色桑基絲線圖、熱力矩陣、刻度條與 L2 清單即時長大或縮小。
- 嚴守零 Emoji、全形標點與括號（）、零單向 CSS 邊框（禁用 border-left/right/top/bottom）及 WCAG AAA 高對比配色。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "output"

ELECTION_SHORT = {
    "113年總統、副總統選舉": "113 總統副總統",
    "113年立法委員選舉": "113 立委",
    "111年直轄市市長選舉": "111 直轄市長",
    "111年直轄市長選舉": "111 直轄市長",
    "111年縣(市)長選舉": "111 縣市長",
    "111年直轄市議員選舉": "111 直轄市議員",
    "111年縣(市)議員選舉": "111 縣市議員",
    "109年總統、副總統選舉": "109 總統副總統",
    "109年立法委員選舉": "109 立委",
    "107年直轄市市長選舉": "107 直轄市長",
    "107年直轄市長選舉": "107 直轄市長",
    "107年縣(市)長選舉": "107 縣市長",
    "107年直轄市議員選舉": "107 直轄市議員",
    "107年縣(市)議員選舉": "107 縣市議員",
}

PARTY_STYLES = {
    "民主進步黨": {"short": "民進黨", "color": "#1B9A4B", "pill_bg": "#E4F2E9", "pill_text": "#0F5E2D"},
    "中國國民黨": {"short": "國民黨", "color": "#000095", "pill_bg": "#E7E8F8", "pill_text": "#000080"},
    "台灣民眾黨": {"short": "民眾黨", "color": "#28C8C8", "pill_bg": "#E1F5F5", "pill_text": "#0D5D5D"},
    "無黨籍": {"short": "無黨籍", "color": "#64748B", "pill_bg": "#ECEEF2", "pill_text": "#2D3748"},
    "親民黨": {"short": "親民黨", "color": "#D96B27", "pill_bg": "#FAEDE3", "pill_text": "#8C3D0E"},
    "無黨團結聯盟": {"short": "無盟", "color": "#8E24AA", "pill_bg": "#F3E8F7", "pill_text": "#5E1573"},
    "中華統一促進黨": {"short": "統促黨", "color": "#991B1B", "pill_bg": "#F8E8E8", "pill_text": "#781212"},
    "安定力量": {"short": "安定力量", "color": "#475569", "pill_bg": "#ECEFF3", "pill_text": "#1E293B"},
    "新黨": {"short": "新黨", "color": "#D4A017", "pill_bg": "#FCF4D6", "pill_text": "#5A4500"},
    "時代力量": {"short": "時代力量", "color": "#E09100", "pill_bg": "#FDF1D4", "pill_text": "#5C3A00"},
    "台灣團結聯盟": {"short": "台聯", "color": "#8B5A2B", "pill_bg": "#F4EBE1", "pill_text": "#5E3A17"},
    "台灣基進": {"short": "台灣基進", "color": "#9E2A2B", "pill_bg": "#FAE8E8", "pill_text": "#6B1919"},
}

PARTY_ORDER = [
    "民主進步黨", "中國國民黨", "無黨籍", "台灣民眾黨",
    "親民黨", "無黨團結聯盟", "中華統一促進黨", "安定力量",
    "新黨", "時代力量", "台灣團結聯盟", "台灣基進",
]


def clean_str(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def to_int(v: Any) -> int:
    s = clean_str(v)
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def fw_text(v: Any) -> str:
    s = clean_str(v)
    return s.replace("(", "（").replace(")", "）") if s else ""


def short_corp_name(name: str) -> str:
    s = fw_text(name)
    for suf in ("股份有限公司", "有限公司", "企業社", "實業社", "工程行"):
        if s.endswith(suf) and len(s) > len(suf) + 1:
            return s[: -len(suf)]
    return s


def short_election(el: str) -> str:
    s = clean_str(el)
    return ELECTION_SHORT.get(s, fw_text(s))


def build_payload() -> dict[str, Any]:
    d09 = pd.read_csv(OUT_DIR / "09_donation_details_two_terms.csv", dtype=str).fillna("")
    d09 = d09[d09["tier"].isin(["Tier 1", "Tier 2"])].copy()
    for col in ("gross_amount", "returned_amount", "net_amount"):
        d09[col] = pd.to_numeric(d09[col], errors="coerce").fillna(0).astype(int)

    c09 = pd.read_csv(OUT_DIR / "09_candidates_two_terms_with_cec.csv", dtype=str).fillna("")
    pcc09 = pd.read_csv(OUT_DIR / "09_solar_companies_pcc_two_terms.csv", dtype=str).fillna("")
    comp_cmp = pd.read_csv(OUT_DIR / "09_two_term_company_comparison.csv", dtype=str).fillna("")
    repeat_df = pd.read_csv(OUT_DIR / "09_repeat_candidates_two_terms.csv", dtype=str).fillna("")

    party_ann = pd.read_csv(OUT_DIR / "10_party_annual_solar_donations.csv", dtype=str).fillna("")
    group_pen = pd.read_csv(OUT_DIR / "10_group_penetration_donations.csv", dtype=str).fillna("")

    nat_all = pd.read_csv(OUT_DIR / "11_natural_person_donations_two_terms.csv", dtype=str).fillna("")
    for col in ("gross_amount", "returned_amount", "net_amount"):
        nat_all[col] = pd.to_numeric(nat_all[col], errors="coerce").fillna(0).astype(int)
    zero_pcc = pd.read_csv(OUT_DIR / "11_zero_donation_and_high_pcc_summary.csv", dtype=str).fillna("")

    cand_map: dict[tuple[str, str, str], int] = {}
    cands_list: list[dict[str, Any]] = []

    def register_cand(term_s: str, el: str, area: str, cname: str, party: str, victor: str) -> int:
        key = (clean_str(el), clean_str(area), clean_str(cname))
        if key in cand_map:
            return cand_map[key]
        idx = len(cands_list)
        cand_map[key] = idx
        cands_list.append({
            "id": idx,
            "t": "c" if "111/113" in term_s else "p",
            "el": short_election(el),
            "area": fw_text(area) or "全國／不分區",
            "name": clean_str(cname),
            "party": clean_str(party) or "未明",
            "vic": 1 if clean_str(victor) == "當選" else 0,
            "vic_lbl": fw_text(victor) or "未當選",
        })
        return idx

    for _, r in c09.iterrows():
        register_cand(r["term"], r["election"], r["area"], r["candidate"], r["party"], r["is_victor"])

    l1_df = nat_all[nat_all["match_confidence"] == "L1"].copy()
    l2_df = nat_all[nat_all["match_confidence"] == "L2"].copy()
    for _, r in l1_df.iterrows():
        register_cand(r["term"], r["election"], r["area"], r["candidate"], r["party"], r["is_victor"])

    firms_meta: dict[str, dict[str, Any]] = {}
    for _, r in pcc09.iterrows():
        tid = clean_str(r["tax_id"])
        firms_meta[tid] = {
            "tid": tid,
            "name": fw_text(r["gcis_name"]),
            "short": short_corp_name(r["gcis_name"]),
            "tier": clean_str(r["tier"]),
            "t_num": 1 if clean_str(r["tier"]) == "Tier 1" else 2,
            "rep": clean_str(r["rep_name"]),
            "assoc": fw_text(r["associations"]),
            "pcc": to_int(r["pcc_awarded_count"]),
            "pcc_solar": to_int(r["pcc_solar_awarded_count"]),
            "agencies": fw_text(r["pcc_agencies"]),
        }

    corp_agg: dict[tuple[str, str, int], list[int]] = {}
    for _, r in d09.iterrows():
        t_flag = "c" if "111/113" in r["term"] else "p"
        tid = clean_str(r["tax_id"])
        cid = cand_map[(clean_str(r["election"]), clean_str(r["area"]), clean_str(r["candidate"]))]
        k = (t_flag, tid, cid)
        if k not in corp_agg:
            corp_agg[k] = [0, 0, 0, 0]
        corp_agg[k][0] += int(r["gross_amount"])
        corp_agg[k][1] += int(r["returned_amount"])
        corp_agg[k][2] += int(r["net_amount"])
        corp_agg[k][3] += 1

    corp_edges = [
        {"t": k[0], "tid": k[1], "c": k[2], "g": v[0], "r": v[1], "n": v[2], "tx": v[3]}
        for k, v in corp_agg.items()
    ]

    person_meta: dict[str, dict[str, Any]] = {}
    l1_agg: dict[tuple[str, str, int], dict[str, Any]] = {}
    for _, r in l1_df.iterrows():
        pname = clean_str(r["person_name"])
        id3 = clean_str(r["id_prefix3"])
        pkey = f"{pname}｜{id3}"
        if pkey not in person_meta:
            comps_raw = [short_corp_name(x) for x in clean_str(r["linked_companies"]).split("；") if x.strip()]
            person_meta[pkey] = {
                "id": pkey,
                "name": pname,
                "id3": id3,
                "city": clean_str(r["addr_city"]) or "未填",
                "comp": comps_raw[0] if comps_raw else "光電關聯企業",
                "comps": "、".join(comps_raw[:3]),
                "roles": fw_text(r["linked_roles"]),
                "pcc": 1 if clean_str(r["linked_pcc_awarded"]) == "Y" else 0,
            }
        t_flag = "c" if "111/113" in r["term"] else "p"
        cid = cand_map[(clean_str(r["election"]), clean_str(r["area"]), clean_str(r["candidate"]))]
        k = (t_flag, pkey, cid)
        if k not in l1_agg:
            l1_agg[k] = {
                "t": t_flag, "p": pkey, "c": cid,
                "g": 0, "r": 0, "n": 0, "tx": 0,
                "pcc": 1 if clean_str(r["linked_pcc_awarded"]) == "Y" else 0,
            }
        l1_agg[k]["g"] += int(r["gross_amount"])
        l1_agg[k]["r"] += int(r["returned_amount"])
        l1_agg[k]["n"] += int(r["net_amount"])
        l1_agg[k]["tx"] += 1

    l1_edges = list(l1_agg.values())

    l2_items = []
    for _, r in l2_df.sort_values(["net_amount", "gross_amount"], ascending=[False, False]).iterrows():
        l2_items.append({
            "t": "c" if "111/113" in r["term"] else "p",
            "t_lbl": fw_text(r["term"]),
            "person": clean_str(r["person_name"]),
            "id3": clean_str(r["id_prefix3"]),
            "city": clean_str(r["addr_city"]) or "未填地址",
            "cand": clean_str(r["candidate"]),
            "party": clean_str(r["party"]),
            "el": short_election(r["election"]),
            "vic": fw_text(r["is_victor"]),
            "net": int(r["net_amount"]),
            "gross": int(r["gross_amount"]),
            "pcc": 1 if clean_str(r["linked_pcc_awarded"]) == "Y" else 0,
            "comp": fw_text(r["linked_companies"]) or "公協會理監事（無特定公司名）",
            "roles": fw_text(r["linked_roles"]),
            "note": fw_text(r["classification_note"]),
        })

    comp_movers = []
    for _, r in comp_cmp.iterrows():
        comp_movers.append({
            "tid": clean_str(r["tax_id"]),
            "name": fw_text(r["gcis_name"]),
            "short": short_corp_name(r["gcis_name"]),
            "tier": clean_str(r["tier"]),
            "status": fw_text(r["term_status"]),
            "prev": to_int(r["prev_net_107_109"]),
            "curr": to_int(r["curr_net_111_113"]),
            "delta": to_int(r["delta_curr_minus_prev"]),
            "tot": to_int(r["two_term_total_net"]),
            "pcc": to_int(r["pcc_awarded_count"]),
            "parties": fw_text(r["party_donations_breakdown"]),
        })

    repeat_cands = []
    for _, r in repeat_df.iterrows():
        repeat_cands.append({
            "cand": clean_str(r["candidate"]),
            "area": fw_text(r["area"]) or "全國／不分區",
            "prev_el": "、".join(short_election(x.strip()) for x in clean_str(r["prev_elections"]).split("；") if x.strip()),
            "prev_party": clean_str(r["prev_party"]),
            "prev_net": to_int(r["prev_net"]),
            "prev_corps": fw_text(r["prev_corps"]),
            "curr_el": "、".join(short_election(x.strip()) for x in clean_str(r["curr_elections"]).split("；") if x.strip()),
            "curr_party": clean_str(r["curr_party"]),
            "curr_net": to_int(r["curr_net"]),
            "curr_corps": fw_text(r["curr_corps"]),
            "tot_net": to_int(r["two_term_net"]),
            "corps_cnt": to_int(r["two_term_corp_count"]),
            "pcc_cnt": to_int(r["pcc_corp_count"]),
            "consistent": clean_str(r["party_consistent"]) == "Y",
        })

    party_ann_rows = []
    for _, r in party_ann.iterrows():
        party_ann_rows.append({
            "party": clean_str(r["party"]),
            "year": to_int(r["roc_year"]),
            "date": clean_str(r["tx_date"]),
            "tid": clean_str(r["donor_tax_id"]),
            "donor": fw_text(r["donor_name"]),
            "gross": to_int(r["gross_amount"]),
            "ret": to_int(r["returned_amount"]),
            "net": to_int(r["net_amount"]),
            "role": fw_text(r["match_role"]),
            "linked": fw_text(r["linked_solar_entity"]),
            "cand_net": to_int(r["donor_cand_net_two_terms"]),
            "seed_net": to_int(r["seed_cand_net_two_terms"]),
            "zero": clean_str(r["is_zero_cand_donor"]) == "Y",
        })

    grp_by_firm: dict[str, dict[str, Any]] = {}
    grp_party_totals: dict[str, int] = {}
    for _, r in group_pen.iterrows():
        tid = clean_str(r["donating_tax_id"])
        net_v = to_int(r["net_amount"])
        party = clean_str(r["party"])
        grp_party_totals[party] = grp_party_totals.get(party, 0) + net_v
        if tid not in grp_by_firm:
            grp_by_firm[tid] = {
                "tid": tid,
                "name": fw_text(r["donating_company"]),
                "rep": clean_str(r["donating_rep"]),
                "links": fw_text(r["link_types"]),
                "seeds": fw_text(r["linked_solar_seeds"]),
                "has_zero_seed": clean_str(r["has_zero_cand_seed"]) == "Y",
                "tx": 0,
                "net": 0,
                "party_map": {},
                "samples": [],
            }
        g = grp_by_firm[tid]
        g["tx"] += 1
        g["net"] += net_v
        if net_v > 0:
            g["party_map"][party] = g["party_map"].get(party, 0) + net_v
            if len(g["samples"]) < 4:
                amt_txt = f"{net_v // 10000} 萬" if net_v >= 10000 and net_v % 10000 == 0 else (f"{net_v / 10000:.1f} 萬" if net_v >= 10000 else f"{net_v} 元")
                g["samples"].append(f"{r['candidate']}（{PARTY_STYLES.get(party, {}).get('short', party)} {amt_txt}）")

    group_firms = sorted(grp_by_firm.values(), key=lambda x: (-x["net"], -x["tx"]))
    for g in group_firms:
        pm = sorted(g.pop("party_map").items(), key=lambda kv: -kv[1])
        g["parties"] = "、".join(
            f"{p} {v // 10000 if v % 10000 == 0 else round(v / 10000, 1)} 萬" if v >= 10000 else f"{p} {v} 元"
            for p, v in pm
        )
        g["sample_txt"] = "、".join(g.pop("samples"))

    zero_pcc_rows = []
    for _, r in zero_pcc.iterrows():
        zero_pcc_rows.append({
            "tid": clean_str(r["tax_id"]),
            "name": fw_text(r["company_name"]),
            "cat": fw_text(r["category_or_tier"]),
            "rep": clean_str(r["rep_or_key_person"]),
            "pcc": to_int(r["pcc_awarded_count"]),
            "agencies": fw_text(r["pcc_agencies"]),
            "cand_net": to_int(r["cand_corp_net_two_terms"]),
            "party_net": to_int(r["party_annual_net_107_114"]),
            "grp_net": to_int(r["group_penetration_net_two_terms"]),
            "l1_net": to_int(r["l1_person_net_two_terms"]),
            "l2_net": to_int(r["l2_person_excluded_net"]),
            "summary": fw_text(r["channel_summary"]),
            "is_controversy": any(k in r["category_or_tier"] for k in ("爭議", "案件", "光電案", "水庫")),
        })

    return {
        "party_styles": PARTY_STYLES,
        "party_order": PARTY_ORDER,
        "firms": firms_meta,
        "persons": person_meta,
        "cands": cands_list,
        "corp_edges": corp_edges,
        "l1_edges": l1_edges,
        "l2_items": l2_items,
        "comp_movers": comp_movers,
        "repeat_cands": repeat_cands,
        "party_ann": party_ann_rows,
        "group_firms": group_firms,
        "group_party_totals": [{"party": p, "net": v} for p, v in sorted(grp_party_totals.items(), key=lambda kv: -kv[1])],
        "zero_pcc": zero_pcc_rows,
    }


SVG_PARTY_ICON_JS = """
const PARTY_META = __PARTY_META__;
const PARTY_ORDER = __PARTY_ORDER__;
const SVG_NS = 'http://www.w3.org/2000/svg';

function el(p, t, a){
  const n = document.createElementNS(SVG_NS, t);
  for(const k in a) n.setAttribute(k, a[k]);
  p.appendChild(n);
  return n;
}
function txt(p, a, s){
  const n = el(p, 'text', a);
  n.textContent = s;
  return n;
}
function partyColor(p){ return (PARTY_META[p] && PARTY_META[p].color) || '#64748B'; }
function partyShort(p){ return (PARTY_META[p] && PARTY_META[p].short) || p || '其他'; }
function partyPillStyle(p){
  const m = PARTY_META[p] || {pill_bg:'#ECEEF2', pill_text:'#1F2526', color:'#64748B'};
  return `background:${m.pill_bg};color:${m.pill_text};border:1px solid ${m.color};`;
}
function renderPartySvg(party, size=18){
  const s = size;
  switch(party){
    case '民主進步黨':
      return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0"><circle cx="12" cy="12" r="10.5" fill="#1B9A4B"/><path d="M12 4.5 C8.5 7.5 6.8 10.8 7.5 14.5 C9.2 15.8 11.4 17 12 19.5 C12.6 17 14.8 15.8 16.5 14.5 C17.2 10.8 15.5 7.5 12 4.5 Z" fill="#FFFFFF"/><circle cx="12" cy="11.5" r="2" fill="#1B9A4B"/></svg>`;
    case '中國國民黨':
      return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0"><circle cx="12" cy="12" r="10.5" fill="#000095"/><polygon points="12,3.5 13.7,8.4 18.8,6.8 15.4,11 19.8,14 14.5,14.3 15.5,19.4 12,15.5 8.5,19.4 9.5,14.3 4.2,14 8.6,11 5.2,6.8 10.3,8.4" fill="#FFFFFF"/><circle cx="12" cy="12" r="3.6" fill="#000095"/><circle cx="12" cy="12" r="2.6" fill="#FFFFFF"/></svg>`;
    case '台灣民眾黨':
      return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0"><circle cx="12" cy="12" r="10.5" fill="#28C8C8"/><text x="12" y="15.8" text-anchor="middle" font-size="11.5" font-weight="800" fill="#1F2526" font-family="sans-serif">眾</text></svg>`;
    case '無黨籍':
      return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0"><circle cx="12" cy="12" r="10.5" fill="#ECEEF2" stroke="#64748B" stroke-width="2"/><text x="12" y="15.5" text-anchor="middle" font-size="10.5" font-weight="700" fill="#2D3748" font-family="sans-serif">無</text></svg>`;
    case '親民黨':
      return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0"><circle cx="12" cy="12" r="10.5" fill="#D96B27"/><text x="12" y="15.8" text-anchor="middle" font-size="11" font-weight="800" fill="#FFFFFF" font-family="sans-serif">親</text></svg>`;
    case '無黨團結聯盟':
      return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0"><rect x="2" y="2" width="20" height="20" rx="5" fill="#8E24AA"/><text x="12" y="15.5" text-anchor="middle" font-size="10" font-weight="800" fill="#FFFFFF" font-family="sans-serif">盟</text></svg>`;
    case '中華統一促進黨':
      return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0"><rect x="2" y="2" width="20" height="20" rx="5" fill="#991B1B"/><text x="12" y="15.5" text-anchor="middle" font-size="10" font-weight="800" fill="#FFFFFF" font-family="sans-serif">統</text></svg>`;
    case '新黨':
      return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0"><circle cx="12" cy="12" r="10.5" fill="#EAB308" stroke="#9A7100" stroke-width="1.2"/><text x="12" y="15.5" text-anchor="middle" font-size="11" font-weight="800" fill="#1F2526" font-family="sans-serif">新</text></svg>`;
    case '時代力量':
      return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0"><circle cx="12" cy="12" r="10.5" fill="#F59E0B" stroke="#9A6000" stroke-width="1.2"/><text x="12" y="15.5" text-anchor="middle" font-size="11" font-weight="800" fill="#1F2526" font-family="sans-serif">時</text></svg>`;
    case '安定力量':
      return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0"><circle cx="12" cy="12" r="10.5" fill="#475569"/><text x="12" y="15.5" text-anchor="middle" font-size="10.5" font-weight="800" fill="#FFFFFF" font-family="sans-serif">安</text></svg>`;
    case '台灣團結聯盟':
      return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0"><circle cx="12" cy="12" r="10.5" fill="#8B5A2B"/><text x="12" y="15.5" text-anchor="middle" font-size="10.5" font-weight="800" fill="#FFFFFF" font-family="sans-serif">台</text></svg>`;
    case '台灣基進':
      return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0"><circle cx="12" cy="12" r="10.5" fill="#9E2A2B"/><text x="12" y="15.5" text-anchor="middle" font-size="10.5" font-weight="800" fill="#FFFFFF" font-family="sans-serif">基</text></svg>`;
    default:
      return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0"><circle cx="12" cy="12" r="10" fill="#64748B"/></svg>`;
  }
}
function drawPartyDotSvg(parent, party, cx, cy, r=6){
  const col = partyColor(party);
  const g = el(parent, 'g', {});
  el(g, 'circle', {cx, cy, r, fill: col, stroke: '#FFFFFF', 'stroke-width': 0.9});
  if(party === '中國國民黨'){
    el(g, 'circle', {cx, cy, r: r * 0.42, fill: '#FFFFFF'});
  } else if(party === '民主進步黨'){
    el(g, 'circle', {cx, cy, r: r * 0.34, fill: '#FFFFFF'});
  }
  return g;
}
"""


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=1280" />
<title>台灣光電政治獻金政黨歸屬、桑基流向與三路徑追查總覽（107～113 年兩屆 12 類選舉）</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Sans+TC:wght@400;500;700;800&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#F0EFEB;
  --card:#F6F5F1;
  --row:#EEECE6;
  --dark:#1C1C1A;
  --ink:#1C1C1A;
  --muted:#6A6963;
  --faint:#8F8E88;
  --grid:#DEDDD6;
  --aaa:#1F2526;
  --gold-bg:#F8E4A0;
  --gold-border:#B6891B;
  --l1-color:#C57B27;
}
*{margin:0;padding:0;box-sizing:border-box;}
[hidden]{display:none !important;}
body{
  background:var(--bg);
  color:var(--ink);
  font-family:'Inter','Noto Sans TC','PingFang TC','Microsoft JhengHei',sans-serif;
  padding:32px 34px 56px;
  line-height:1.55;
  -webkit-font-smoothing:antialiased;
}
.pagehead{
  max-width:1360px;
  margin:0 auto 20px;
  display:flex;
  justify-content:space-between;
  align-items:flex-end;
  gap:20px;
}
.pagehead h1{
  font-size:23px;
  font-weight:800;
  letter-spacing:-0.02em;
  margin-bottom:6px;
}
.pagehead p{
  font-size:12.5px;
  color:var(--muted);
  max-width:960px;
}
.grid2{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:22px;
  max-width:1360px;
  margin:0 auto;
}
.card{
  background:var(--card);
  border:1px solid #E3E2DB;
  border-radius:24px;
  padding:26px 26px 20px;
  position:relative;
}
.card.dark{
  background:var(--dark);
  border:1px solid var(--dark);
  color:#F0EFEB;
}
.card.dark .sub{color:#A3A198;}
.card.dark .src{color:#78776F;}
.card.wide{grid-column:1/-1;}
.cardhead{
  display:flex;
  justify-content:space-between;
  align-items:flex-start;
  gap:16px;
  margin-bottom:10px;
}
h2{font-size:16.5px;font-weight:800;letter-spacing:-0.015em;margin-bottom:3px;}
.sub{font-size:12px;color:var(--muted);line-height:1.55;}
.src{font-size:9.5px;color:var(--faint);margin-top:14px;letter-spacing:0.06em;font-weight:600;}
.pills{
  display:inline-flex;
  background:#DEDDD6;
  padding:3px;
  border-radius:999px;
  gap:3px;
  flex-shrink:0;
}
.pill{
  border:none;
  background:transparent;
  color:var(--aaa);
  font-family:inherit;
  font-size:11.5px;
  font-weight:700;
  padding:6px 13px;
  border-radius:999px;
  cursor:pointer;
  white-space:nowrap;
}
.pill.active{background:var(--dark);color:#F0EFEB;}
.card.dark .pills{background:#2A2925;}
.card.dark .pill{color:#C8C6BC;}
.card.dark .pill.active{background:#F0EFEB;color:var(--aaa);}
.btn-outline{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding:8px 15px;
  border-radius:999px;
  background:var(--card);
  border:1px solid #C8C6BD;
  color:var(--aaa);
  font-family:inherit;
  font-size:12px;
  font-weight:700;
  cursor:pointer;
  white-space:nowrap;
}
.btn-outline:hover{background:#EAE8E1;}
.btn-outline.active{background:var(--dark);color:#F0EFEB;border-color:var(--dark);}

/* 名詞白話對照表抽屜 */
.glossary-panel{
  max-width:1360px;
  margin:0 auto 20px;
  background:var(--card);
  border:1px solid #C8C6BD;
  border-radius:20px;
  padding:20px 24px;
}
.glossary-grid{
  display:grid;
  grid-template-columns:repeat(4,minmax(0,1fr));
  gap:10px;
  margin-top:12px;
}
.g-box{
  background:var(--row);
  border:1px solid #DEDDD6;
  border-radius:14px;
  padding:11px 13px;
  font-size:12px;
}
.g-head{
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:6px;
  margin-bottom:4px;
  font-weight:800;
}

/* 即時圖層開關控制台 */
.console-top{
  display:grid;
  grid-template-columns:1.15fr 1fr;
  gap:24px;
  align-items:center;
  padding-bottom:18px;
}
.ledger-row{
  display:flex;
  align-items:baseline;
  gap:12px;
  flex-wrap:wrap;
}
.ledger-big{
  font-size:38px;
  font-weight:800;
  letter-spacing:-0.03em;
  font-variant-numeric:tabular-nums;
  line-height:1.1;
}
.delta-chip{
  display:inline-flex;
  align-items:center;
  padding:4px 11px;
  border-radius:999px;
  font-size:12px;
  font-weight:800;
  font-variant-numeric:tabular-nums;
  background:#E4ECE6;
  color:#1F2526;
  border:1px solid #8CB39A;
}
.delta-chip.neg{background:#FAD5CD;color:#1F2526;border-color:#C97A6A;}
.delta-chip.neu{background:#ECEAE3;color:#4B4A45;border-color:#C8C6BD;}
.scale-wrap{margin-top:12px;}
.scale-meta{
  display:flex;
  justify-content:space-between;
  font-size:11.5px;
  color:var(--muted);
  margin-bottom:5px;
}
.scale-track{
  height:14px;
  border-radius:999px;
  background:#E3E1DA;
  border:1px solid #D2CFC6;
  overflow:hidden;
  display:flex;
}
.scale-seg{height:100%;transition:width 360ms cubic-bezier(.22,1,.36,1);}
.scale-seg.t1{background:#1C1C1A;}
.scale-seg.t2{background:#6A6963;}
.scale-seg.l1{background:#C57B27;}
.scale-legend{
  display:flex;
  gap:14px;
  margin-top:6px;
  font-size:11.5px;
  color:var(--muted);
}
.dot-sq{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:middle;}
.mini-stats{
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:10px;
}
.mini-stat{
  background:var(--row);
  border:1px solid #DEDDD6;
  border-radius:14px;
  padding:11px 14px;
}
.mini-stat.gold{background:#FBF2D2;border:1px solid var(--gold-border);}
.mini-k{font-size:11.5px;color:var(--muted);font-weight:600;}
.mini-v{font-size:20px;font-weight:800;font-variant-numeric:tabular-nums;margin-top:2px;color:var(--ink);}

/* 6 枚真實滑動開關 */
.switches-bar{
  display:grid;
  grid-template-columns:repeat(6,minmax(0,1fr));
  gap:10px;
  margin-top:4px;
}
.sw-card{
  display:flex;
  flex-direction:column;
  justify-content:space-between;
  gap:8px;
  background:#ECEAE3;
  border:1px solid #D4D2C9;
  border-radius:16px;
  padding:11px 12px;
  cursor:pointer;
  text-align:left;
  font-family:inherit;
  transition:background .16s,border-color .16s;
}
.sw-card.on{
  background:#FFFFFF;
  border:1.5px solid #1C1C1A;
}
.sw-card.pcc{
  background:#FBF2D2;
  border:1px solid var(--gold-border);
}
.sw-card.pcc.on{
  background:var(--gold-bg);
  border:2px solid #8A6208;
}
.sw-head{display:flex;justify-content:space-between;align-items:center;gap:6px;}
.sw-title{font-size:12.5px;font-weight:800;color:var(--aaa);line-height:1.3;}
.sw-track{
  width:38px;height:22px;border-radius:999px;background:#B7B5AC;position:relative;flex-shrink:0;transition:background .18s;
}
.sw-card.on .sw-track{background:#1C1C1A;}
.sw-card.pcc.on .sw-track{background:#8A6208;}
.sw-knob{
  width:16px;height:16px;border-radius:50%;background:#FFFFFF;position:absolute;top:3px;left:3px;transition:transform .18s cubic-bezier(.22,1,.36,1);
}
.sw-card.on .sw-knob{transform:translateX(16px);}
.sw-delta{font-size:11px;font-weight:700;color:var(--muted);font-variant-numeric:tabular-nums;}
.sw-card.on .sw-delta{color:var(--aaa);}

/* 徽章（高明度背景配 #1F2526 達 WCAG AAA） */
.badge-pcc{display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;background:var(--gold-bg);color:var(--aaa);border:1px solid var(--gold-border);font-size:11px;font-weight:800;white-space:nowrap;}
.badge-tier{display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;background:#ECEAE3;color:var(--aaa);border:1px solid #C8C6BD;font-size:11px;font-weight:700;white-space:nowrap;}
.badge-l1{display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;background:#FDEBD3;color:var(--aaa);border:1px solid #C57B27;font-size:11px;font-weight:700;white-space:nowrap;}
.badge-ok{display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;background:#D6E5DC;color:var(--aaa);border:1px solid #59876E;font-size:11px;font-weight:700;white-space:nowrap;}
.badge-warn{display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;background:#FAD5CD;color:var(--aaa);border:1px solid #B85D4E;font-size:11px;font-weight:700;white-space:nowrap;}

/* Card 1 政黨列 */
.party-rows{display:flex;flex-direction:column;gap:8px;}
.party-row{
  display:grid;
  grid-template-columns:170px 1fr 165px 115px 95px 85px 100px;
  align-items:center;
  gap:14px;
  background:var(--row);
  border:1px solid #E3E1DA;
  border-radius:14px;
  padding:11px 16px;
}
.party-row.head{
  background:transparent;
  border:none;
  padding:4px 16px;
  font-size:11.5px;
  font-weight:700;
  color:var(--muted);
}
.p-bar-bg{height:10px;border-radius:999px;background:#E0DFD8;overflow:hidden;}
.p-bar-fill{height:100%;border-radius:999px;transition:width 360ms cubic-bezier(.22,1,.36,1);}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;}

/* Card 2 深色三段桑基圖 */
.thread{transition:opacity .16s ease,stroke-width .16s ease;}
.thread.hot{opacity:.95 !important;}
svg.focused .thread:not(.hot){opacity:.045 !important;}
.nodelab{cursor:pointer;transition:opacity .16s ease;}
svg.focused .nodelab:not(.hot){opacity:.22;}
.hit{cursor:pointer;}
#statusBar{
  background:#262522;
  border:1px solid #3A3934;
  border-radius:12px;
  padding:11px 16px;
  margin-top:10px;
  font-size:12.5px;
  color:#C4C2B8;
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:12px;
}
#statusBar b{color:#F0EFEB;font-weight:700;}
#spinNote{font-size:11px;color:#9C9A91;font-weight:700;}

/* SVG tooltips */
#thrSvg,#matSvg,#tickSvg{width:100%;display:block;margin:0 auto;}
svg text{font-family:'Inter','Noto Sans TC',sans-serif;user-select:none;}
.pop{transform-box:fill-box;transform-origin:center;animation:pop .36s cubic-bezier(.2,.7,.3,1.2) both;}
@keyframes pop{from{transform:scale(0.2);opacity:0}to{transform:none;opacity:1}}
.fade{animation:fade .45s ease both;}
@keyframes fade{from{opacity:0}}
#hoverTip{
  position:fixed;pointer-events:none;z-index:999;
  background:var(--dark);color:#F0EFEB;
  border:1px solid #4A4944;border-radius:12px;
  padding:10px 14px;font-size:12px;line-height:1.55;max-width:360px;display:none;
}

/* Table cards (Card 5, 6, 7) */
.search-input{
  padding:7px 14px;border-radius:999px;border:1px solid #C8C6BD;background:#FFFFFF;color:var(--aaa);font-family:inherit;font-size:12.5px;min-width:230px;
}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
.subbox{background:var(--row);border:1px solid #DEDDD6;border-radius:16px;padding:16px;}
table.lf-tbl{width:100%;border-collapse:separate;border-spacing:0 6px;font-size:12.5px;}
table.lf-tbl th{text-align:left;padding:8px 11px;font-size:11.5px;font-weight:800;color:var(--muted);background:#EAE8E1;border:1px solid #DCDAD1;border-radius:10px;white-space:nowrap;}
table.lf-tbl td{padding:10px 11px;background:var(--row);border:1px solid #E3E1DA;vertical-align:top;}
table.lf-tbl td:first-child{border-radius:12px 0 0 12px;}
table.lf-tbl td:last-child{border-radius:0 12px 12px 0;}
.notice-pill{
  padding:11px 15px;border-radius:14px;background:#FBF2D2;border:1px solid var(--gold-border);color:var(--aaa);font-size:12.5px;margin-bottom:14px;
}
.l2-rows{display:flex;flex-direction:column;gap:7px;}
.l2-row{
  display:grid;
  grid-template-columns:105px 210px 210px 1fr 115px 220px;
  align-items:center;
  gap:12px;
  background:var(--row);
  border:1px solid #E3E1DA;
  border-radius:14px;
  padding:10px 14px;
  font-size:12px;
}
</style>
</head>
<body>

<header class="pagehead">
  <div>
    <h1>台灣太陽光電政治獻金政黨歸屬、桑基流向與三路徑追查總覽（107～113 年兩屆 12 類選舉）</h1>
    <p>彙總監察院 107／109 前屆與 111／113 本屆 12 類選舉原始會計報告書、中選會政黨與當選名冊、政府電子採購網（PCC）決標紀錄及董監事自然人四級查核；無直接候選人捐款企業另於第六區獨立追蹤，L2 疑似項目嚴格隔離列示，絕不混入確定總額。</p>
  </div>
  <button class="btn-outline" id="toggleGlossaryBtn" type="button">名詞與分級白話對照表</button>
</header>

<section class="glossary-panel" id="glossaryPanel" hidden>
  <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
    <div>
      <strong style="font-size:15px;">名詞與分級白話對照表（一眼看懂哪些計入確定總額、哪些獨立隔離）</strong>
      <div style="font-size:12px;color:var(--muted);">下方六枚圖層開關僅操作具備確定證據之「核心光電 T1」、「供應鏈 T2」與「高信心自然人 L1」；其餘待查或間接管道皆隔離顯示。</div>
    </div>
    <button class="btn-outline" id="closeGlossaryBtn" type="button">收合說明</button>
  </div>
  <div class="glossary-grid">
    <div class="g-box"><div class="g-head"><span>核心光電企業（Tier 1）</span><span class="badge-ok">計入確定總額</span></div>主營太陽光電發電、案場開發（SPV）、售電業或列名七大公協會與能源署太陽能名單之業者。</div>
    <div class="g-box"><div class="g-head"><span>供應鏈與母公司（Tier 2）</span><span class="badge-ok">計入確定總額</span></div>光電公協會會員內之鋼鐵支架、電纜工程協力廠，或跨業太陽能母公司（如北基國際）。</div>
    <div class="g-box"><div class="g-head"><span>屋頂自發電跨業（Tier 3）</span><span class="badge-warn">不併入確定總額</span></div>本業為製造、化工、食品或營建等傳統企業，僅廠房屋頂自發電兼列 D101060 代碼。</div>
    <div class="g-box"><div class="g-head"><span>高信心自然人（L1）</span><span class="badge-l1">可開關併入</span></div>光電董監事／核心幹部以個人名義捐款，且通過同案共現、群聚共捐或戶籍縣市單一特徵驗證者。</div>
    <div class="g-box"><div class="g-head"><span>高度疑似自然人（L2）</span><span class="badge-warn">獨立清單・不併入</span></div>姓名命中且多為 5 萬至 10 萬元大額、性別與縣市相符，但缺共現證據；隔離於第七區待複核。</div>
    <div class="g-box"><div class="g-head"><span>同名衝突（L3）／排除（X）</span><span class="badge-warn">完全排除</span></div>全庫對應多組不同「證號前 3 碼＋不同縣市」（L3）或性別地緣矛盾（X），全數排除。</div>
    <div class="g-box"><div class="g-head"><span>PCC 政府得標機構</span><span class="badge-pcc">暖金開關聚焦</span></div>曾在政府電子採購網（PCC）取得政府標案決標之光電企業；開啟「僅限 PCC」開關可看流向如何集中收斂。</div>
    <div class="g-box"><div class="g-head"><span>政黨年度專戶與集團穿透</span><span class="badge-warn">獨立追蹤・不併入</span></div>追查對候選人 0 元或低額之業者是否改捐 107～114 年政黨專戶，或由母公司／法人股東／專屬同址公司出資。</div>
  </div>
</section>

<!-- 即時圖層開關控制台 -->
<section class="grid2" style="margin-bottom:22px;">
  <div class="card wide">
    <div class="cardhead" style="margin-bottom:14px;">
      <div>
        <h2>即時圖層開關控制台（撥動任一開關，即時觀看總額長大與縮小、各圖重繪）</h2>
        <div class="sub">以兩屆完整確定上限 76,247,050 元為滿尺基準；每個開關下緣即時顯示在當前狀態下「開啟／關閉」對總淨額的精準增減影響。</div>
      </div>
      <button class="btn-outline" id="resetSwitchesBtn" type="button">重設為預設全開</button>
    </div>

    <div class="console-top">
      <div>
        <div class="ledger-row">
          <div class="ledger-big" id="ledgerTotal">76,247,050 元</div>
          <span class="delta-chip neu" id="ledgerDelta">初始基準全開（雙屆＋企業 T1／T2＋自然人 L1）</span>
        </div>
        <div class="scale-wrap">
          <div class="scale-meta">
            <span id="scaleRatioTxt">占雙屆滿額口徑比例：100.00%</span>
            <span>滿格基準：76,247,050 元</span>
          </div>
          <div class="scale-track">
            <div class="scale-seg t1" id="barSegT1" style="width:60.2%;"></div>
            <div class="scale-seg t2" id="barSegT2" style="width:27.1%;"></div>
            <div class="scale-seg l1" id="barSegL1" style="width:12.6%;"></div>
          </div>
          <div class="scale-legend">
            <span><i class="dot-sq" style="background:#1C1C1A;"></i>核心光電（Tier 1）：<strong id="legT1Txt">45,928,050 元</strong></span>
            <span><i class="dot-sq" style="background:#6A6963;"></i>供應鏈與母公司（Tier 2）：<strong id="legT2Txt">20,679,000 元</strong></span>
            <span><i class="dot-sq" style="background:#C57B27;"></i>高信心自然人（L1）：<strong id="legL1Txt">9,640,000 元</strong></span>
          </div>
        </div>
      </div>

      <div class="mini-stats">
        <div class="mini-stat">
          <div class="mini-k">企業法人實捐淨額（Tier 1＋2）</div>
          <div class="mini-v" id="miniCorpNet">66,607,050 元</div>
        </div>
        <div class="mini-stat">
          <div class="mini-k">高信心自然人（L1）實捐淨額</div>
          <div class="mini-v" id="miniL1Net">9,640,000 元</div>
        </div>
        <div class="mini-stat">
          <div class="mini-k">受贈候選專戶總計（已扣除返還）</div>
          <div class="mini-v" id="miniCandCnt">330 人次</div>
        </div>
        <div class="mini-stat gold">
          <div class="mini-k">含 PCC 政府得標企業實捐</div>
          <div class="mini-v" id="miniPccFirms">38 家 ／ 19,675,600 元</div>
        </div>
      </div>
    </div>

    <div class="switches-bar" id="switchesBar"></div>
  </div>
</section>

<div class="grid2">
  <!-- 卡片一：資金流入哪一個政黨 -->
  <section class="card wide">
    <div class="cardhead">
      <div>
        <h2>一、資金流入哪一個政黨：各政黨實捐淨額、受贈人次與當選席次占比</h2>
        <div class="sub" id="partySub">依中選會官方候選人推薦政黨與當選名冊歸屬統計（未命中 0 筆），比例條與右欄數字隨上方開關即時長大與縮小。</div>
      </div>
      <span class="badge-pcc" id="partyPccStateBadge" hidden>目前僅計 PCC 政府得標機構</span>
    </div>
    <div class="party-rows" id="partyRows"></div>
    <div class="src">PARTY ATTRIBUTION SUMMARY · 監察院原始會計報告書 × 中選會政黨名冊 × 政府電子採購網（PCC）</div>
  </section>

  <!-- 卡片二：三段流向桑基絲線圖（B3 原始深墨設計） -->
  <section class="card dark wide">
    <div class="cardhead">
      <div>
        <h2>二、三段流向桑基絲線圖：光電企業／自然人（L1） → 中選會政黨 → 個人候選人</h2>
        <div class="sub">左欄＝光電企業（標示 T1／T2 與 PCC 得標件數）或高信心自然人〔自然人〕 · 中欄＝中選會政黨樞紐 · 右欄＝受贈候選人 · 懸停絲線或節點抽出整束路徑，點擊釘住，點空白處釋放</div>
      </div>
      <div class="pills" id="sankeyDensityPills">
        <button class="pill active" data-sd="compact" type="button">主幹焦點（前 48 來源 → 前 30 候選人）</button>
        <button class="pill" data-sd="wide" type="button">展開視野（前 68 來源 → 前 42 候選人）</button>
      </div>
    </div>
    <svg id="thrSvg" viewBox="0 0 1280 860"></svg>
    <div id="statusBar">
      <span id="stText">懸停任一條絲線或標籤，即可抽出單筆或整束資金流動路徑與明細</span>
      <span id="spinNote"></span>
    </div>
    <div class="src">THREAD TRIPTYCH · LIEFLAT B3 · SANKEY FLOW · CORPORATES（T1／T2）＋ L1 NATURAL PERSONS → PARTY → CANDIDATE</div>
  </section>

  <!-- 卡片三：L16 熱力矩陣 -->
  <section class="card wide">
    <div class="cardhead">
      <div>
        <h2>三、交叉分布密度：前 20 大捐贈機構／自然人 × 各政黨實捐淨額熱力矩陣</h2>
        <div class="sub">單格色階＝該機構捐贈該政黨實捐淨額分級 · 括號為該政黨下受贈候選人次 · 懸停方格檢視個別候選人明細</div>
      </div>
      <div class="pills" id="matSortPills">
        <button class="pill active" data-ms="net" type="button">依實捐淨額排序</button>
        <button class="pill" data-ms="deg" type="button">依跨候選人數排序</button>
      </div>
    </div>
    <svg id="matSvg" viewBox="0 0 1240 620"></svg>
    <div class="src">MATRIX HEAT · LIEFLAT L16 · 每格可懸停查閱詳細候選人名單</div>
  </section>

  <!-- 卡片四：F5 垂直刻度條 -->
  <section class="card wide">
    <div class="cardhead">
      <div>
        <h2>四、流向個人金額排行：前 28 位實收光電獻金最高候選人（企業＋高信心自然人 L1）</h2>
        <div class="sub">左側為中選會政黨圖示與候選人（選舉・當選狀態），每根垂直刻度＝10 萬元實捐淨額（每 5 根加寬間距＝50 萬元）；政黨色刻度＝企業法人實捐，暖琥珀色刻度＝自然人（L1）實捐</div>
      </div>
    </div>
    <svg id="tickSvg" viewBox="0 0 1240 860"></svg>
    <div class="src">TICK ROWS · LIEFLAT F5 · ONE TICK = 100,000 NTD NET DONATION TO INDIVIDUAL CANDIDATE</div>
  </section>

  <!-- 卡片五：跨兩屆對比與 35 位連兩屆受贈候選人 -->
  <section class="card wide">
    <div class="cardhead">
      <div>
        <h2>五、跨兩屆對比（107／109 前屆 vs. 111／113 本屆）與 35 位連兩屆受贈固定候選人</h2>
        <div class="sub">左半為前屆與本屆政黨分配對照（隨上方 T1／T2／L1／PCC 開關同步重算）；右下方完整列示 191 家企業跨屆消長與 35 位連兩屆重複受贈候選人（同名「許淑華」已依選區嚴格分列）。</div>
      </div>
    </div>
    <div class="two-col" id="twoTermCmpGrid"></div>

    <div style="margin-top:20px;">
      <div class="cardhead" style="margin-bottom:8px;">
        <div>
          <h3 style="font-size:14.5px;font-weight:800;">企業跨屆消長明細（共 191 家：僅本屆新增 115 家 · 僅前屆捐贈 52 家 · 連兩屆皆捐 24 家）</h3>
          <div class="sub">焦點包含台泥集團 6 家綠能子公司（前屆合計 990 萬 → 本屆 0）與永鑫能源（前屆 210 萬 → 本屆 0）。</div>
        </div>
        <div class="pills" id="moverPills">
          <button class="pill active" data-mf="key" type="button">消長金額前 18 家</button>
          <button class="pill" data-mf="only_prev" type="button">僅前屆捐贈（52 家）</button>
          <button class="pill" data-mf="both" type="button">連兩屆皆捐（24 家）</button>
        </div>
      </div>
      <div id="moverTableWrap"></div>
    </div>

    <div style="margin-top:22px;">
      <div class="cardhead" style="margin-bottom:8px;">
        <div>
          <h3 style="font-size:14.5px;font-weight:800;">連兩屆皆收受光電企業政治獻金之固定候選人（共 35 位）</h3>
          <div class="sub">嚴格以「候選人姓名 × 選區」識別同一人；臺北市民進黨許淑華與南投縣國民黨許淑華分別列示。</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
          <input class="search-input" id="repeatSearch" type="search" placeholder="搜尋候選人姓名、選區或捐贈企業…">
          <button class="btn-outline" id="repeatPccToggle" type="button">僅顯示含 PCC 得標企業捐贈</button>
        </div>
      </div>
      <div id="repeatTableWrap"></div>
    </div>
    <div class="src">CROSS-TERM COMPARISON · 107／109 前屆 vs. 111／113 本屆 · 含 35 位連兩屆固定受贈候選人</div>
  </section>

  <!-- 卡片六：無直接候選人捐款三路徑獨立追蹤 -->
  <section class="card wide">
    <div class="cardhead">
      <div>
        <h2>六、無直接候選人捐款光電企業三路徑獨立追蹤（絕不併入確定總額）</h2>
        <div class="sub">針對個別候選人名單為 0 元（或全額返還）之光電大廠與水庫／台南爭議指標企業，獨立追蹤政黨年度專戶、GCIS 集團穿透與四路徑總對照。</div>
      </div>
      <div class="pills" id="zeroPathPills">
        <button class="pill active" data-zp="party_ann" type="button">路徑一：政黨年度專戶（42 筆）</button>
        <button class="pill" data-zp="group" type="button">路徑二：集團穿透企業（38 家）</button>
        <button class="pill" data-zp="matrix41" type="button">路徑三：高 PCC 與爭議對照（41 家）</button>
      </div>
    </div>
    <div class="notice-pill">
      口徑隔離聲明：本區所呈現之「107～114 年政黨年度專戶（實收 1,034.5 萬元）」與「GCIS 集團穿透非 Tier 1／2 企業（實捐 3,201 萬元）」均獨立列管，<strong>絕不混入上方候選人直接確定總額</strong>。
    </div>
    <div id="zeroPathBody"></div>
    <div class="src">THREE-PATHWAY AUDIT · 107～114 政黨專戶 × GCIS 股權代表人同址穿透 × 41 家指標清冊</div>
  </section>

  <!-- 卡片七：L2 高度疑似自然人獨立人工複核清單 -->
  <section class="card wide">
    <div class="cardhead">
      <div>
        <h2>七、L2 高度疑似自然人待人工查核清單（嚴格隔離・絕不併入確定總額）</h2>
        <div class="sub" id="l2Sub">共列出隨上方屆別與 PCC 開關過濾之 L2 疑似紀錄；雖與光電董事同名且多為 5 萬至 10 萬元大額，但缺同公司共現證據，僅供人工查證參考。</div>
      </div>
      <input class="search-input" id="l2Search" type="search" placeholder="搜尋自然人姓名、關聯公司或候選人…">
    </div>
    <div class="l2-rows" id="l2RowsWrap"></div>
    <div class="src">INDEPENDENT AUDIT QUEUE · L2 HIGH-AMOUNT SUSPECTS EXCLUDED FROM CONFIRMED TOTALS</div>
  </section>
</div>

<div id="hoverTip"></div>

<script>
const DATA = __DATA_JSON__;
__SVG_PARTY_ICON_JS__

const SW_STATE = {
  curr: true,
  prev: true,
  t1: true,
  t2: true,
  l1: true,
  pcc: false,
};

const UI_STATE = {
  sankeyDensity: 'compact',
  matSort: 'net',
  moverFilter: 'key',
  repeatSearch: '',
  repeatPccOnly: false,
  zeroPath: 'party_ann',
  zeroOnlyLowCand: false,
  matrix41Mode: 'all',
  l2Search: '',
};

let lastTotalRendered = 0;
let animFrameId = null;

function esc(s){
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function fmtN(n){ return Number(n || 0).toLocaleString('zh-TW'); }
function fmtW(n){
  const v = Number(n || 0);
  if(v === 0) return '0 元';
  if(Math.abs(v) >= 10000){
    const w = v / 10000;
    return (v % 10000 === 0 ? fmtN(w) : w.toFixed(1).replace(/\\.0$/,'')) + ' 萬';
  }
  return fmtN(v) + ' 元';
}

const tipBox = document.getElementById('hoverTip');
function bindTip(node, htmlFn){
  node.style.cursor = 'pointer';
  node.addEventListener('mouseenter', e => {
    tipBox.innerHTML = htmlFn();
    tipBox.style.display = 'block';
    moveTip(e);
  });
  node.addEventListener('mousemove', moveTip);
  node.addEventListener('mouseleave', () => { tipBox.style.display = 'none'; });
}
function moveTip(e){
  const pad = 14;
  let x = e.clientX + pad, y = e.clientY + pad;
  if(x + 360 > window.innerWidth) x = e.clientX - 370;
  if(y + 180 > window.innerHeight) y = e.clientY - 150;
  tipBox.style.left = Math.max(8, x) + 'px';
  tipBox.style.top = Math.max(8, y) + 'px';
}

function evalState(st){
  const ce = DATA.corp_edges.filter(e => {
    const tOk = (st.curr && e.t === 'c') || (st.prev && e.t === 'p');
    if(!tOk) return false;
    const f = DATA.firms[e.tid];
    if(!f) return false;
    const tierOk = (f.t_num === 1 && st.t1) || (f.t_num === 2 && st.t2);
    if(!tierOk) return false;
    if(st.pcc && f.pcc <= 0) return false;
    return true;
  });
  const le = !st.l1 ? [] : DATA.l1_edges.filter(e => {
    const tOk = (st.curr && e.t === 'c') || (st.prev && e.t === 'p');
    if(!tOk) return false;
    if(st.pcc && e.pcc !== 1) return false;
    return true;
  });
  let t1Net = 0, t2Net = 0, l1Net = 0;
  const candSet = new Set();
  const pccFirmSet = new Set();
  let pccCorpNet = 0;
  for(const e of ce){
    const f = DATA.firms[e.tid];
    if(f.t_num === 1) t1Net += e.n; else t2Net += e.n;
    candSet.add(e.c);
    if(e.n > 0 && f.pcc > 0){
      pccFirmSet.add(e.tid);
      pccCorpNet += e.n;
    }
  }
  for(const e of le){
    l1Net += e.n;
    candSet.add(e.c);
  }
  return {
    ce, le,
    t1Net, t2Net,
    corpNet: t1Net + t2Net,
    l1Net,
    totalNet: t1Net + t2Net + l1Net,
    candCount: candSet.size,
    pccFirms: pccFirmSet.size,
    pccCorpNet,
  };
}

const FULL_MAX_TOTAL = evalState({curr:true, prev:true, t1:true, t2:true, l1:true, pcc:false}).totalNet || 1;

function animateNumber(elDom, fromVal, toVal, suffix){
  const t0 = performance.now();
  const dur = 320;
  function step(now){
    const p = Math.min(1, (now - t0) / dur);
    const eased = 1 - Math.pow(1 - p, 3);
    const cur = Math.round(fromVal + (toVal - fromVal) * eased);
    elDom.textContent = fmtN(cur) + suffix;
    if(p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

const SWITCH_DEFS = [
  {key:'curr', title:'111／113 本屆選舉', pcc:false},
  {key:'prev', title:'107／109 前屆選舉', pcc:false},
  {key:'t1', title:'核心光電企業（T1）', pcc:false},
  {key:'t2', title:'供應鏈與母公司（T2）', pcc:false},
  {key:'l1', title:'高信心自然人（L1）', pcc:false},
  {key:'pcc', title:'僅限 PCC 政府得標機構', pcc:true},
];

function renderSwitchesAndLedger(res, prevTotal, isInitial){
  const ledgerEl = document.getElementById('ledgerTotal');
  if(isInitial){
    ledgerEl.textContent = fmtN(res.totalNet) + ' 元';
  } else {
    animateNumber(ledgerEl, prevTotal, res.totalNet, ' 元');
  }
  lastTotalRendered = res.totalNet;

  const deltaEl = document.getElementById('ledgerDelta');
  if(isInitial){
    deltaEl.className = 'delta-chip neu';
    deltaEl.textContent = '基準全開口徑（雙屆 12 類選舉＋企業 T1／T2＋自然人 L1）';
  } else {
    const diff = res.totalNet - prevTotal;
    if(diff > 0){
      deltaEl.className = 'delta-chip';
      deltaEl.textContent = `較前一狀態增加 +${fmtN(diff)} 元`;
    } else if(diff < 0){
      deltaEl.className = 'delta-chip neg';
      deltaEl.textContent = `較前一狀態縮小 ${fmtN(diff)} 元`;
    } else {
      deltaEl.className = 'delta-chip neu';
      deltaEl.textContent = '數額維持不變';
    }
  }

  document.getElementById('scaleRatioTxt').textContent = `占雙屆滿額口徑比例：${(res.totalNet / FULL_MAX_TOTAL * 100).toFixed(2)}%`;
  document.getElementById('barSegT1').style.width = (res.t1Net / FULL_MAX_TOTAL * 100).toFixed(2) + '%';
  document.getElementById('barSegT2').style.width = (res.t2Net / FULL_MAX_TOTAL * 100).toFixed(2) + '%';
  document.getElementById('barSegL1').style.width = (res.l1Net / FULL_MAX_TOTAL * 100).toFixed(2) + '%';

  document.getElementById('legT1Txt').textContent = fmtN(res.t1Net) + ' 元';
  document.getElementById('legT2Txt').textContent = fmtN(res.t2Net) + ' 元';
  document.getElementById('legL1Txt').textContent = fmtN(res.l1Net) + ' 元';

  document.getElementById('miniCorpNet').textContent = fmtN(res.corpNet) + ' 元';
  document.getElementById('miniL1Net').textContent = fmtN(res.l1Net) + ' 元';
  document.getElementById('miniCandCnt').textContent = fmtN(res.candCount) + ' 人次';
  document.getElementById('miniPccFirms').textContent = `${res.pccFirms} 家 ／ ${fmtN(res.pccCorpNet)} 元`;

  document.getElementById('partyPccStateBadge').hidden = !SW_STATE.pcc;

  // 計算 6 枚開關各自在當前狀態下的邊際增減
  document.getElementById('switchesBar').innerHTML = SWITCH_DEFS.map(def => {
    const isOn = SW_STATE[def.key];
    const flipped = {...SW_STATE, [def.key]: !isOn};
    const flipRes = evalState(flipped);
    const diff = flipRes.totalNet - res.totalNet; // 若撥動此開關將產生之變化
    let hint = '';
    if(def.key === 'pcc'){
      hint = isOn ? `取消篩選將放寬 +${fmtW(diff)}` : `開啟後將聚焦為 ${fmtW(flipRes.totalNet)}`;
    } else {
      hint = isOn ? `已計入 ${fmtW(-diff)}（點此關閉）` : `已關閉（開啟可加 +${fmtW(diff)}）`;
    }
    return `
      <button class="sw-card ${def.pcc ? 'pcc' : ''} ${isOn ? 'on' : ''}" data-sw="${def.key}" type="button" aria-pressed="${isOn}">
        <div class="sw-head">
          <span class="sw-title">${esc(def.title)}</span>
          <span class="sw-track"><span class="sw-knob"></span></span>
        </div>
        <div class="sw-delta">${esc(hint)}</div>
      </button>
    `;
  }).join('');

  document.querySelectorAll('#switchesBar .sw-card').forEach(btn => {
    btn.addEventListener('click', () => {
      const k = btn.dataset.sw;
      const oldTotal = lastTotalRendered;
      SW_STATE[k] = !SW_STATE[k];
      renderDashboard(false, oldTotal);
    });
  });
}

function renderPartyCard(res){
  const agg = {};
  const ensure = p => {
    if(!agg[p]) agg[p] = {party:p, net:0, corp:0, l1:0, cands:new Set(), vicCands:new Set(), firms:new Set(), l1Donors:new Set()};
    return agg[p];
  };
  for(const e of res.ce){
    const c = DATA.cands[e.c];
    const r = ensure(c.party);
    r.net += e.n; r.corp += e.n;
    r.cands.add(c.id);
    if(c.vic) r.vicCands.add(c.id);
    if(e.n > 0) r.firms.add(e.tid);
  }
  for(const e of res.le){
    const c = DATA.cands[e.c];
    const r = ensure(c.party);
    r.net += e.n; r.l1 += e.n;
    r.cands.add(c.id);
    if(c.vic) r.vicCands.add(c.id);
    if(e.n > 0) r.l1Donors.add(e.p);
  }
  const rows = Object.values(agg).filter(r => r.net > 0 || r.cands.size > 0).sort((a,b) => b.net - a.net || b.cands.size - a.cands.size);
  const grand = rows.reduce((a,r)=>a+r.net, 0) || 1;

  const headHtml = `
    <div class="party-row head">
      <div>中選會推薦政黨</div>
      <div>實捐淨額比例條（目前共 ${fmtN(res.totalNet)} 元）</div>
      <div class="num">實捐淨額（占比）</div>
      <div class="num">受贈人次（當選）</div>
      <div class="num">捐贈企業</div>
      <div class="num">L1 自然人</div>
      <div class="num">人均受贈</div>
    </div>
  `;
  const bodyHtml = rows.length ? rows.map(r => {
    const pct = (r.net / grand * 100).toFixed(2);
    const avg = r.cands.size ? Math.round(r.net / r.cands.size) : 0;
    return `
      <div class="party-row">
        <div style="display:flex;align-items:center;gap:8px;font-weight:800;font-size:13.5px;">${renderPartySvg(r.party, 20)}<span>${esc(r.party)}</span></div>
        <div class="p-bar-bg"><div class="p-bar-fill" style="width:${Math.max(Number(pct), 1.5)}%;background:${partyColor(r.party)};"></div></div>
        <div class="num" style="font-weight:800;">${fmtW(r.net)}（${pct}%）</div>
        <div class="num">${r.cands.size} 人（${r.vicCands.size} 席）</div>
        <div class="num">${r.firms.size} 家</div>
        <div class="num">${r.l1Donors.size} 人</div>
        <div class="num">${fmtW(avg)}</div>
      </div>
    `;
  }).join('') : '<div class="notice-pill">目前開關已全部關閉或無符合交易紀錄。</div>';
  document.getElementById('partyRows').innerHTML = headHtml + bodyHtml;
}

function renderSankey(res){
  const svg = document.getElementById('thrSvg');
  svg.innerHTML = '';
  svg.classList.remove('focused');
  const stText = document.getElementById('stText');
  const spinNote = document.getElementById('spinNote');
  stText.textContent = '懸停任一條絲線或標籤，即可抽出單筆或整束資金流動路徑與明細';
  spinNote.textContent = '';

  const maxSrc = UI_STATE.sankeyDensity === 'wide' ? 68 : 48;
  const maxDst = UI_STATE.sankeyDensity === 'wide' ? 42 : 30;

  // 建構來源（企業或 L1 自然人）與候選人總額，取主要流向確保版面精準可讀
  const srcMap = {};
  const dstMap = {};
  const rawLinks = [];

  for(const e of res.ce){
    if(e.n <= 0) continue;
    const f = DATA.firms[e.tid];
    const sid = 'F_' + e.tid;
    if(!srcMap[sid]){
      const tag = f.pcc > 0 ? `${f.t_num === 1 ? 'T1' : 'T2'}・PCC ${f.pcc}件` : (f.t_num === 1 ? 'T1' : 'T2');
      srcMap[sid] = {id: sid, label: `${f.short}〔${tag}〕`, full: f.name, tier: f.tier, pcc: f.pcc, kind:'corp', net:0};
    }
    srcMap[sid].net += e.n;
    const c = DATA.cands[e.c];
    const did = 'C_' + c.id;
    if(!dstMap[did]){
      dstMap[did] = {id: did, cand: c, label: `${c.name}（${c.el}・${c.vic_lbl}）`, net:0};
    }
    dstMap[did].net += e.n;
    rawLinks.push({sid, party: c.party, did, n: e.n});
  }
  for(const e of res.le){
    if(e.n <= 0) continue;
    const p = DATA.persons[e.p];
    const sid = 'P_' + e.p;
    if(!srcMap[sid]){
      const pTag = p.pcc ? `自然人・${p.comp}・PCC` : `自然人・${p.comp}`;
      srcMap[sid] = {id: sid, label: `${p.name}〔${pTag}〕`, full: `${p.name}（${p.comps}）`, tier: 'L1', pcc: p.pcc, kind:'l1', net:0};
    }
    srcMap[sid].net += e.n;
    const c = DATA.cands[e.c];
    const did = 'C_' + c.id;
    if(!dstMap[did]){
      dstMap[did] = {id: did, cand: c, label: `${c.name}（${c.el}・${c.vic_lbl}）`, net:0};
    }
    dstMap[did].net += e.n;
    rawLinks.push({sid, party: c.party, did, n: e.n});
  }

  const topDst = Object.values(dstMap).sort((a,b)=>b.net-a.net).slice(0, maxDst);
  const topDstSet = new Set(topDst.map(x=>x.id));
  const linksToTopDst = rawLinks.filter(l => topDstSet.has(l.did));

  // 依匯入焦點候選人之金額排序挑選左欄來源，確保右欄受贈者具備完整進線
  const srcFlowToDst = {};
  for(const l of linksToTopDst){
    srcFlowToDst[l.sid] = (srcFlowToDst[l.sid] || 0) + l.n;
  }
  const topSrc = Object.keys(srcFlowToDst)
    .sort((a,b) => srcFlowToDst[b] - srcFlowToDst[a] || srcMap[b].net - srcMap[a].net)
    .slice(0, maxSrc)
    .map(id => srcMap[id]);
  const topSrcSet = new Set(topSrc.map(x=>x.id));

  const keptLinks = linksToTopDst.filter(l => topSrcSet.has(l.sid));
  const usedSrcSet = new Set(keptLinks.map(l=>l.sid));
  const usedDstSet = new Set(keptLinks.map(l=>l.did));
  const srcList = topSrc.filter(s => usedSrcSet.has(s.id));
  const dstList = topDst.filter(d => usedDstSet.has(d.id));

  const partyNetMap = {};
  for(const l of keptLinks){ partyNetMap[l.party] = (partyNetMap[l.party] || 0) + l.n; }
  const midList = PARTY_ORDER.filter(p => partyNetMap[p] > 0).map(p => ({id: p, net: partyNetMap[p]}));

  if(!keptLinks.length){
    svg.setAttribute('viewBox', '0 0 1280 260');
    txt(svg, {x:640, y:130, 'text-anchor':'middle', 'font-size':14, fill:'#B3B0A4'}, '目前開關組合下尚無正淨額捐款連線，請撥開左側任一圖層開關。');
    return;
  }

  const rowMax = Math.max(srcList.length, dstList.length, 10);
  const H = Math.max(780, rowMax * 20 + 115);
  svg.setAttribute('viewBox', `0 0 1280 ${H}`);

  const X1 = 278, X2 = 640, X3 = 975;
  const H_TOP = 54, H_BOT = H - 36;
  const span = (n, idx) => n <= 1 ? (H_TOP + H_BOT) / 2 : H_TOP + idx * ((H_BOT - H_TOP) / (n - 1));

  const srcIdx = Object.fromEntries(srcList.map((s,i)=>[s.id, i]));
  const midIdx = Object.fromEntries(midList.map((m,i)=>[m.id, i]));
  const dstIdx = Object.fromEntries(dstList.map((d,i)=>[d.id, i]));

  const sy = i => span(srcList.length, i);
  const my = i => midList.length <= 1 ? (H_TOP + H_BOT) / 2 : 120 + i * ((H - 220) / (midList.length - 1));
  const dy = i => span(dstList.length, i);

  [[X1 - 80, '① 光電企業／高信心自然人（L1）'], [X2, '② 中選會政黨'], [X3 + 95, '③ 受贈個人候選人（實收淨額）']].forEach(([x,t]) => {
    txt(svg, {x, y:24, 'font-size':11, 'font-weight':800, fill:'#F0EFEB', 'letter-spacing':'0.1em', 'text-anchor':'middle'}, t);
  });

  // 合併相同 (sid, party, did) 邊
  const mergedMap = {};
  for(const l of keptLinks){
    const mk = `${l.sid}|${l.party}|${l.did}`;
    if(!mergedMap[mk]) mergedMap[mk] = {s: srcIdx[l.sid], m: midIdx[l.party], d: dstIdx[l.did], net: 0, sid: l.sid, party: l.party, did: l.did};
    mergedMap[mk].net += l.n;
  }
  const routes = Object.values(mergedMap);
  const pathD = r =>
    `M${X1 + 6} ${sy(r.s)} C${(X1 + X2)/2} ${sy(r.s)} ${(X1 + X2)/2} ${my(r.m)} ${X2} ${my(r.m)} C${(X2 + X3)/2} ${my(r.m)} ${(X2 + X3)/2} ${dy(r.d)} ${X3 - 6} ${dy(r.d)}`;

  const gThreads = el(svg, 'g', {});
  const routeObjs = routes.map((r, ri) => {
    const w = Math.max(0.85, Math.min(5.2, 0.7 + Math.sqrt(r.net / 10000) * 0.42));
    const col = partyColor(r.party);
    const pEl = el(gThreads, 'path', {
      d: pathD(r), fill: 'none', stroke: col, 'stroke-width': w,
      class: 'thread', opacity: 0.22 + Math.min(0.28, r.net / 1500000), 'stroke-linecap': 'round'
    });
    const hit = el(gThreads, 'path', {
      d: pathD(r), fill: 'none', stroke: '#000', 'stroke-opacity': 0, 'stroke-width': 10, class: 'hit'
    });
    hit.dataset.route = ri;
    return {...r, el: pEl, hit};
  });

  // 左欄來源節點
  srcList.forEach((s, i) => {
    const y = sy(i);
    const g = el(svg, 'g', {class:'nodelab'});
    g.dataset.kind = 's'; g.dataset.idx = i;
    const dotCol = s.pcc > 0 ? '#F8E4A0' : (s.kind === 'l1' ? '#D9822B' : '#DCDAD2');
    el(g, 'rect', {x: X1 - 4, y: y - 2, width: 7, height: 4, rx: 1, fill: dotCol});
    txt(g, {
      x: X1 - 10, y: y + 3.5, 'font-size': srcList.length > 42 ? 9.2 : 10, 'font-weight': 600,
      fill: s.pcc > 0 ? '#F8E4A0' : (s.kind === 'l1' ? '#F3B469' : '#DCDAD2'), 'text-anchor': 'end'
    }, s.label);
    el(g, 'rect', {x: X1 - 268, y: y - 7, width: 274, height: 14, fill: '#000', 'fill-opacity': 0, class: 'hit'});
  });

  // 中欄政黨膠囊
  midList.forEach((m, i) => {
    const y = my(i);
    const g = el(svg, 'g', {class:'nodelab'});
    g.dataset.kind = 'm'; g.dataset.idx = i;
    el(g, 'rect', {x: X2 - 74, y: y - 14, width: 148, height: 28, rx: 14, fill: '#2B2A26', stroke: partyColor(m.id), 'stroke-width': 1.5});
    drawPartyDotSvg(g, m.id, X2 - 56, y, 6);
    txt(g, {x: X2 + 8, y: y + 4, 'font-size': 11, 'font-weight': 700, fill: '#F0EFEB', 'text-anchor': 'middle'}, `${m.id}（${fmtW(m.net)}）`);
    el(g, 'rect', {x: X2 - 76, y: y - 15, width: 152, height: 30, fill: '#000', 'fill-opacity': 0, class: 'hit'});
  });

  // 右欄候選人節點
  dstList.forEach((d, i) => {
    const y = dy(i);
    const g = el(svg, 'g', {class:'nodelab'});
    g.dataset.kind = 'd'; g.dataset.idx = i;
    drawPartyDotSvg(g, d.cand.party, X3 + 4, y, 4.5);
    txt(g, {
      x: X3 + 14, y: y + 3.5, 'font-size': dstList.length > 32 ? 9.5 : 10.5, 'font-weight': 600,
      fill: '#DCDAD2', 'text-anchor': 'start'
    }, `${d.label}・${fmtW(d.net)}`);
    el(g, 'rect', {x: X3 - 4, y: y - 7, width: 295, height: 14, fill: '#000', 'fill-opacity': 0, class: 'hit'});
  });

  let pinnedFn = null;
  const nodeLabs = [...svg.querySelectorAll('.nodelab')];
  const clear = () => {
    svg.classList.remove('focused');
    routeObjs.forEach(r => r.el.classList.remove('hot'));
    nodeLabs.forEach(n => n.classList.remove('hot'));
    stText.textContent = '懸停任一條絲線或標籤，即可抽出單筆或整束資金流動路徑與明細';
    spinNote.textContent = '';
  };
  const focusRoutes = (rs, label) => {
    svg.classList.add('focused');
    const rSet = new Set(rs);
    routeObjs.forEach(r => r.el.classList.toggle('hot', rSet.has(r)));
    nodeLabs.forEach(n => {
      const k = n.dataset.kind, ix = +n.dataset.idx;
      n.classList.toggle('hot', rs.some(r => (k==='s'&&r.s===ix)||(k==='m'&&r.m===ix)||(k==='d'&&r.d===ix)));
    });
    stText.innerHTML = label;
  };
  const apply = t => {
    const hit = t.closest?.('.hit');
    if(!hit) return null;
    const rg = hit.dataset.route, ng = hit.closest('.nodelab');
    if(rg != null){
      const r = routeObjs[+rg];
      const lbl = `<b>${esc(srcList[r.s].full)}</b> → ${esc(midList[r.m].id)} → <b>${esc(dstList[r.d].label)}</b> · 實捐淨額 <b>${fmtN(r.net)} 元</b>`;
      return () => focusRoutes([r], lbl);
    }
    if(ng){
      const k = ng.dataset.kind, ix = +ng.dataset.idx;
      const rs = routeObjs.filter(r => (k==='s'&&r.s===ix)||(k==='m'&&r.m===ix)||(k==='d'&&r.d===ix));
      const sum = rs.reduce((a,r)=>a+r.net,0);
      const name = k==='s' ? srcList[ix].full : (k==='m' ? midList[ix].id : dstList[ix].label);
      return () => focusRoutes(rs, `<b>${esc(name)}</b> · 圖內呈現 ${rs.length} 條路徑 · 金額合計 <b>${fmtN(sum)} 元</b>`);
    }
    return null;
  };
  svg.onmousemove = e => { if(pinnedFn) return; const f = apply(e.target); f ? f() : clear(); };
  svg.onmouseleave = () => { if(!pinnedFn) clear(); };
  svg.onclick = e => {
    const f = apply(e.target);
    if(f){ pinnedFn = f; f(); spinNote.textContent = '已釘住路徑 · 點擊深色空白處釋放'; }
    else { pinnedFn = null; clear(); }
  };
}

function renderMatrix(res){
  const svg = document.getElementById('matSvg');
  svg.innerHTML = '';

  const entMap = {};
  const addRec = (key, short, full, tag, pcc, party, cand, elStr, net) => {
    if(net <= 0) return;
    if(!entMap[key]) entMap[key] = {key, short, full, tag, pcc, net:0, cands:new Set(), byParty:{}};
    const o = entMap[key];
    o.net += net;
    o.cands.add(cand + '|' + elStr);
    if(!o.byParty[party]) o.byParty[party] = {net:0, cands:new Set(), details:[]};
    o.byParty[party].net += net;
    o.byParty[party].cands.add(cand + '|' + elStr);
    o.byParty[party].details.push(`${cand}（${elStr} ${fmtW(net)}）`);
  };
  for(const e of res.ce){
    if(e.n <= 0) continue;
    const f = DATA.firms[e.tid], c = DATA.cands[e.c];
    const tag = f.pcc > 0 ? `${f.t_num === 1 ? 'T1' : 'T2'}・PCC ${f.pcc}件` : (f.t_num === 1 ? 'T1' : 'T2');
    addRec('F_' + e.tid, f.short, f.name, tag, f.pcc, c.party, c.name, c.el, e.n);
  }
  if(!SW_STATE.t1 && !SW_STATE.t2){
    for(const e of res.le){
      if(e.n <= 0) continue;
      const p = DATA.persons[e.p], c = DATA.cands[e.c];
      addRec('P_' + e.p, `${p.name}〔${p.comp}〕`, `${p.name}（${p.comps}）`, 'L1 自然人', p.pcc, c.party, c.name, c.el, e.n);
    }
  }

  let rows = Object.values(entMap);
  if(UI_STATE.matSort === 'deg'){
    rows.sort((a,b) => b.cands.size - a.cands.size || b.net - a.net);
  } else {
    rows.sort((a,b) => b.net - a.net || b.cands.size - a.cands.size);
  }
  rows = rows.slice(0, 20);
  const cols = PARTY_ORDER.filter(p => rows.some(r => r.byParty[p]?.net > 0));
  if(!rows.length || !cols.length){
    svg.setAttribute('viewBox', '0 0 1240 180');
    txt(svg, {x:620, y:90, 'text-anchor':'middle', 'font-size':13, fill:'#6A6963'}, '目前開關組合無企業或自然人正淨額矩陣紀錄。');
    return;
  }

  const X0 = 265, Y0 = 66, CW = Math.min(110, Math.floor(880 / cols.length)), CH = 22, PX = CW + 8, PY = 26;
  const H = Y0 + rows.length * PY + 46;
  svg.setAttribute('viewBox', `0 0 1240 ${H}`);
  const shade = v => v >= 1000000 ? '#1C1C1A' : v >= 500000 ? '#4A4944' : v >= 250000 ? '#8F8E88' : v >= 100000 ? '#B0AFA9' : '#D8D7D1';

  cols.forEach((p, j) => {
    const cx = X0 + j * PX + CW / 2;
    drawPartyDotSvg(svg, p, cx, Y0 - 30, 8);
    txt(svg, {x: cx, y: Y0 - 11, 'font-size': 11, 'font-weight': 700, fill: '#1C1C1A', 'text-anchor': 'middle'}, partyShort(p));
  });

  rows.forEach((row, i) => {
    const y = Y0 + i * PY;
    if(row.pcc > 0){
      el(svg, 'circle', {cx: X0 - 246, cy: y + CH / 2, r: 4, fill: '#E8C55B', stroke: '#B6891B', 'stroke-width': 1});
    }
    const rLab = txt(svg, {
      x: X0 - 12, y: y + CH / 2 + 4, 'font-size': 11, 'font-weight': 700,
      fill: '#1C1C1A', 'text-anchor': 'end'
    }, `${row.short}（${row.tag}）`);
    bindTip(rLab, () => `<b>${esc(row.full)}</b><br/>總實捐淨額：<b>${fmtN(row.net)} 元</b>（${row.cands.size} 人次）`);

    cols.forEach((p, j) => {
      const x = X0 + j * PX;
      const cell = row.byParty[p];
      if(!cell || cell.net <= 0){
        el(svg, 'circle', {cx: x + CW / 2, cy: y + CH / 2, r: 2, fill: '#C6C5BF'});
        return;
      }
      const rect = el(svg, 'rect', {x, y, width: CW, height: CH, rx: 5, fill: shade(cell.net), class: 'pop'});
      txt(svg, {
        x: x + CW / 2, y: y + CH / 2 + 3.8, 'font-size': 10, 'font-weight': 700,
        fill: cell.net >= 500000 ? '#F0EFEB' : '#1C1C1A', 'text-anchor': 'middle', 'pointer-events': 'none'
      }, `${fmtW(cell.net)}（${cell.cands.size}人）`);
      bindTip(rect, () => `<b>${esc(row.full)} × ${esc(p)}</b><br/>實捐淨額：<b>${fmtN(cell.net)} 元</b>（${cell.cands.size} 人次）<br/>對象：${esc(cell.details.slice(0, 8).join('、'))}${cell.details.length > 8 ? '……' : ''}`);
    });
  });

  const LG = [['#D8D7D1','10 萬以下'],['#B0AFA9','10～24.9 萬'],['#8F8E88','25～49.9 萬'],['#4A4944','50～99.9 萬'],['#1C1C1A','100 萬以上']];
  const ly = Y0 + rows.length * PY + 20;
  txt(svg, {x: X0, y: ly, 'font-size': 10.5, 'font-weight': 700, fill: '#6A6963'}, '實捐淨額色階：');
  LG.forEach(([c, lab], k) => {
    const lx = X0 + 98 + k * 116;
    el(svg, 'rect', {x: lx, y: ly - 9, width: 12, height: 12, rx: 3, fill: c});
    txt(svg, {x: lx + 17, y: ly, 'font-size': 10.5, 'font-weight': 600, fill: '#4A4944'}, lab);
  });
}

function renderTicks(res){
  const svg = document.getElementById('tickSvg');
  svg.innerHTML = '';

  const candMap = {};
  const ensure = cid => {
    if(!candMap[cid]){
      const c = DATA.cands[cid];
      candMap[cid] = {...c, corp: 0, l1: 0, net: 0, firms: new Set(), pccFirms: new Set(), l1Donors: new Set(), detail: []};
    }
    return candMap[cid];
  };
  for(const e of res.ce){
    if(e.n <= 0) continue;
    const f = DATA.firms[e.tid];
    const row = ensure(e.c);
    row.corp += e.n; row.net += e.n;
    row.firms.add(f.short);
    if(f.pcc > 0) row.pccFirms.add(e.tid);
    row.detail.push(`${f.short}（${fmtW(e.n)}）`);
  }
  for(const e of res.le){
    if(e.n <= 0) continue;
    const p = DATA.persons[e.p];
    const row = ensure(e.c);
    row.l1 += e.n; row.net += e.n;
    row.l1Donors.add(p.name);
    row.detail.push(`${p.name}〔自然人〕（${fmtW(e.n)}）`);
  }

  const list = Object.values(candMap).filter(x=>x.net > 0).sort((a,b) => b.net - a.net || b.corp - a.corp).slice(0, 28);
  if(!list.length){
    svg.setAttribute('viewBox', '0 0 1240 160');
    txt(svg, {x:620, y:80, 'text-anchor':'middle', 'font-size':13, fill:'#6A6963'}, '目前開關組合下尚無受贈候選人刻度紀錄。');
    return;
  }

  const H = 36 + list.length * 29;
  svg.setAttribute('viewBox', `0 0 1240 ${H}`);
  const X0 = 265, PX = 11.5;

  list.forEach((it, i) => {
    const y = 26 + i * 29;
    drawPartyDotSvg(svg, it.party, 20, y + 2, 7.5);
    const lbl = txt(svg, {x: X0 - 12, y: y + 5, 'font-size': 11, 'font-weight': 700, fill: '#1C1C1A', 'text-anchor': 'end'}, `${it.name}（${it.el}・${it.vic_lbl}）`);

    const cTicks = Math.round(it.corp / 100000);
    const lTicks = Math.round(it.l1 / 100000);
    const totalTicks = Math.max(1, cTicks + lTicks);
    el(svg, 'line', {x1: X0, y1: y + 9, x2: X0 + Math.max(totalTicks, 18) * PX + 16, y2: y + 9, stroke: '#DEDDD6', 'stroke-width': 0.8});

    let curX = X0;
    for(let k = 0; k < totalTicks; k++){
      const isL1 = k >= cTicks;
      const col = isL1 ? '#C57B27' : partyColor(it.party);
      const h = (k % 5 === 4) ? 16 : 12;
      el(svg, 'line', {
        x1: curX, y1: y + 9, x2: curX, y2: y + 9 - h,
        stroke: col, 'stroke-width': 3.2, 'stroke-linecap': 'round', class: 'fade'
      });
      curX += (k % 5 === 4) ? PX + 5 : PX;
    }

    const metaParts = [];
    if(it.corp > 0 && it.l1 > 0){
      metaParts.push(`企 ${fmtW(it.corp)}＋人 ${fmtW(it.l1)}`);
    } else if(it.l1 > 0){
      metaParts.push(`自然人 ${fmtW(it.l1)}`);
    }
    metaParts.push(`${it.firms.size} 家企業` + (it.l1Donors.size ? `＋${it.l1Donors.size} 位自然人` : ''));
    if(it.pccFirms.size > 0) metaParts.push(`PCC 得標 ${it.pccFirms.size} 家`);

    const valLab = txt(svg, {x: curX + 8, y: y + 5, 'font-size': 11, 'font-weight': 800, fill: '#1C1C1A'}, `${fmtW(it.net)}（${metaParts.join('｜')}）`);
    const tipFn = () => `<b>${esc(it.name)}（${esc(it.party)}・${esc(it.el)}・${esc(it.area)}）</b><br/>合計實收淨額：<b>${fmtN(it.net)} 元</b><br/>捐贈明細：${esc(it.detail.slice(0,8).join('、'))}${it.detail.length > 8 ? '……' : ''}`;
    bindTip(lbl, tipFn);
    bindTip(valLab, tipFn);
  });
}

function renderTwoTermCard(){
  // 依當前企業/自然人/PCC開關計算兩屆各政黨對比（忽略 curr/prev 單獨開關以保持對照兩屆）
  const stPrev = {...SW_STATE, prev: true, curr: false};
  const stCurr = {...SW_STATE, prev: false, curr: true};
  const summarizeByParty = st => {
    const r = evalState(st);
    const m = {};
    for(const e of r.ce){
      const p = DATA.cands[e.c].party;
      m[p] = (m[p] || 0) + e.n;
    }
    for(const e of r.le){
      const p = DATA.cands[e.c].party;
      m[p] = (m[p] || 0) + e.n;
    }
    const tot = Object.values(m).reduce((a,b)=>a+b,0) || 1;
    const rows = Object.entries(m).filter(([,v])=>v>0).sort((a,b)=>b[1]-a[1]).map(([p,v])=>({party:p, net:v, pct:(v/tot*100).toFixed(2)}));
    return {tot: r.totalNet, corp: r.corpNet, l1: r.l1Net, rows};
  };
  const pPrev = summarizeByParty(stPrev);
  const pCurr = summarizeByParty(stCurr);

  const renderBox = (title, obj) => `
    <div class="subbox">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;">
        <strong style="font-size:14.5px;">${esc(title)}</strong>
        <span style="font-size:15px;font-weight:800;font-variant-numeric:tabular-nums;">${fmtN(obj.tot)} 元</span>
      </div>
      ${obj.rows.map(r => `
        <div style="margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;">
            <span style="display:inline-flex;align-items:center;gap:6px;font-weight:700;">${renderPartySvg(r.party,15)}${esc(r.party)}</span>
            <span style="font-variant-numeric:tabular-nums;"><strong>${r.pct}%</strong>（${fmtW(r.net)}）</span>
          </div>
          <div class="p-bar-bg" style="height:8px;"><div class="p-bar-fill" style="width:${Math.max(Number(r.pct), 1.5)}%;background:${partyColor(r.party)};"></div></div>
        </div>
      `).join('') || '<div style="font-size:12px;color:var(--muted);">目前開關條件無紀錄。</div>'}
    </div>
  `;
  document.getElementById('twoTermCmpGrid').innerHTML =
    renderBox('107／109 前屆（107 地方＋109 中央）', pPrev) +
    renderBox('111／113 本屆（111 地方＋113 中央）', pCurr);

  let movers = [...DATA.comp_movers];
  if(UI_STATE.moverFilter === 'only_prev'){
    movers = movers.filter(m => m.status.includes('僅前屆')).sort((a,b) => b.prev - a.prev).slice(0, 24);
  } else if(UI_STATE.moverFilter === 'both'){
    movers = movers.filter(m => m.status.includes('連兩屆')).sort((a,b) => b.tot - a.tot);
  } else {
    movers = movers.sort((a,b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 18);
  }
  document.getElementById('moverTableWrap').innerHTML = `
    <table class="lf-tbl">
      <thead><tr><th>光電企業名稱</th><th>分級／PCC 標案</th><th>跨屆狀態</th><th class="num">前屆實捐</th><th class="num">本屆實捐</th><th class="num">增減變化</th><th>政黨分布</th></tr></thead>
      <tbody>
        ${movers.map(m => `
          <tr>
            <td><strong>${esc(m.name)}</strong></td>
            <td><span class="badge-tier">${esc(m.tier)}</span>${m.pcc > 0 ? ` <span class="badge-pcc">PCC ${m.pcc}件</span>` : ''}</td>
            <td><span class="${m.status.includes('連兩屆') ? 'badge-ok' : 'badge-warn'}">${esc(m.status)}</span></td>
            <td class="num">${fmtN(m.prev)} 元</td>
            <td class="num">${fmtN(m.curr)} 元</td>
            <td class="num" style="font-weight:800;">${m.delta > 0 ? '+' : ''}${fmtN(m.delta)} 元</td>
            <td style="font-size:11.5px;color:var(--muted);">${esc(m.parties)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;

  let reps = [...DATA.repeat_cands];
  const rq = UI_STATE.repeatSearch.trim().toLowerCase();
  if(rq) reps = reps.filter(r => r.cand.toLowerCase().includes(rq) || r.area.toLowerCase().includes(rq) || r.prev_corps.toLowerCase().includes(rq) || r.curr_corps.toLowerCase().includes(rq));
  if(UI_STATE.repeatPccOnly || SW_STATE.pcc) reps = reps.filter(r => r.pcc_cnt > 0);
  document.getElementById('repeatTableWrap').innerHTML = `
    <table class="lf-tbl">
      <thead><tr><th>候選人（選區）</th><th>前屆政黨／選舉</th><th class="num">前屆實捐</th><th>本屆政黨／選舉</th><th class="num">本屆實捐</th><th class="num">兩屆企業合計</th><th>PCC 得標家數</th></tr></thead>
      <tbody>
        ${reps.map(r => `
          <tr>
            <td><strong>${esc(r.cand)}</strong><div style="font-size:11px;color:var(--muted);">${esc(r.area)}</div></td>
            <td><span style="display:inline-flex;align-items:center;gap:4px;">${renderPartySvg(r.prev_party,14)}${esc(partyShort(r.prev_party))}</span><div style="font-size:11px;color:var(--muted);">${esc(r.prev_el)}</div></td>
            <td class="num">${fmtN(r.prev_net)} 元</td>
            <td><span style="display:inline-flex;align-items:center;gap:4px;">${renderPartySvg(r.curr_party,14)}${esc(partyShort(r.curr_party))}</span>${!r.consistent ? ' <span class="badge-warn">政黨異動</span>' : ''}<div style="font-size:11px;color:var(--muted);">${esc(r.curr_el)}</div></td>
            <td class="num">${fmtN(r.curr_net)} 元</td>
            <td class="num" style="font-weight:800;">${fmtN(r.tot_net)} 元</td>
            <td>${r.pcc_cnt > 0 ? `<span class="badge-pcc">PCC ${r.pcc_cnt} 家</span>` : '<span style="color:var(--muted);">0 家</span>'}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function renderZeroPathCard(){
  const wrap = document.getElementById('zeroPathBody');
  if(UI_STATE.zeroPath === 'party_ann'){
    let rows = [...DATA.party_ann];
    if(UI_STATE.zeroOnlyLowCand) rows = rows.filter(r => r.zero || r.seed_net <= 50000);
    const byParty = {};
    for(const r of DATA.party_ann) byParty[r.party] = (byParty[r.party] || 0) + r.net;
    const pBadges = Object.entries(byParty).sort((a,b)=>b[1]-a[1]).map(([p,v]) =>
      `<span style="display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700;${partyPillStyle(p)}">${renderPartySvg(p,14)}${esc(p)}：${fmtN(v)} 元</span>`
    ).join(' ');
    wrap.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px;">
        <div style="display:flex;flex-wrap:wrap;gap:6px;">${pBadges}</div>
        <button class="btn-outline ${UI_STATE.zeroOnlyLowCand ? 'active' : ''}" id="btnLowCandParty" type="button">僅篩候選人捐 0 元或低額本體</button>
      </div>
      <table class="lf-tbl">
        <thead><tr><th>年度／日期</th><th>受贈政黨</th><th>捐贈企業（統編）</th><th class="num">專戶實收</th><th class="num">同機構候選人兩屆實捐</th><th>對應光電脈絡與身分</th></tr></thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td style="white-space:nowrap;">${r.year} 年<div style="font-size:11px;color:var(--muted);">${esc(r.date)}</div></td>
              <td><span style="display:inline-flex;align-items:center;gap:5px;font-weight:700;">${renderPartySvg(r.party,15)}${esc(r.party)}</span></td>
              <td><strong>${esc(r.donor)}</strong><div style="font-size:11px;color:var(--muted);">統編：${esc(r.tid)}</div></td>
              <td class="num" style="font-weight:800;">${fmtN(r.net)} 元${r.ret > 0 ? `<div style="font-size:11px;color:#991B1B;">返還 ${fmtN(r.ret)}</div>` : ''}</td>
              <td class="num">${r.cand_net === 0 ? '<span class="badge-warn">候選人 0 元</span>' : fmtN(r.cand_net) + ' 元'}</td>
              <td style="font-size:12px;">${esc(r.role)}（${esc(r.linked)}）</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
    document.getElementById('btnLowCandParty').addEventListener('click', () => {
      UI_STATE.zeroOnlyLowCand = !UI_STATE.zeroOnlyLowCand;
      renderZeroPathCard();
    });
  } else if(UI_STATE.zeroPath === 'group'){
    const pBadges = DATA.group_party_totals.map(x =>
      `<span style="display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700;${partyPillStyle(x.party)}">${renderPartySvg(x.party,14)}${esc(x.party)}：${fmtN(x.net)} 元</span>`
    ).join(' ');
    wrap.innerHTML = `
      <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;">${pBadges}</div>
      <table class="lf-tbl">
        <thead><tr><th>集團穿透捐款公司（統編）</th><th>關聯類型（與 Tier 1／2 種子）</th><th class="num">兩屆實捐淨額</th><th>政黨流向與主要受贈候選人</th></tr></thead>
        <tbody>
          ${DATA.group_firms.map(g => `
            <tr>
              <td><strong>${esc(g.name)}</strong><div style="font-size:11px;color:var(--muted);">統編：${esc(g.tid)}・代表人：${esc(g.rep)}</div></td>
              <td style="font-size:12px;"><span class="badge-tier">${esc(g.links)}</span>${g.has_zero_seed ? ' <span class="badge-warn">種子候選人 0 元</span>' : ''}<div style="margin-top:4px;color:var(--muted);">${esc(g.seeds)}</div></td>
              <td class="num" style="font-weight:800;">${fmtN(g.net)} 元<div style="font-size:11px;color:var(--muted);">${g.tx} 筆</div></td>
              <td style="font-size:12px;"><div><strong>${esc(g.parties)}</strong></div><div style="color:var(--muted);margin-top:2px;">${esc(g.sample_txt)}</div></td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } else {
    let rows = [...DATA.zero_pcc];
    if(UI_STATE.matrix41Mode === 'controversy') rows = rows.filter(r => r.is_controversy);
    if(UI_STATE.matrix41Mode === 'highpcc_zero') rows = rows.filter(r => r.pcc > 0 && r.cand_net === 0);
    wrap.innerHTML = `
      <div class="pills" style="margin-bottom:12px;" id="m41SubPills">
        <button class="pill ${UI_STATE.matrix41Mode==='all'?'active':''}" data-m41="all" type="button">全部 41 家對照</button>
        <button class="pill ${UI_STATE.matrix41Mode==='controversy'?'active':''}" data-m41="controversy" type="button">水庫與台南爭議 20 家</button>
        <button class="pill ${UI_STATE.matrix41Mode==='highpcc_zero'?'active':''}" data-m41="highpcc_zero" type="button">高 PCC 得標但候選人 0 元</button>
      </div>
      <table class="lf-tbl">
        <thead><tr><th>指標企業（代表人／關鍵人）</th><th>PCC 標案</th><th class="num">候選人企業實捐</th><th class="num">政黨年度專戶</th><th class="num">集團穿透</th><th class="num">自然人 L1</th><th>四路徑摘要</th></tr></thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td><strong>${esc(r.name)}</strong><div style="font-size:11px;color:var(--muted);">${esc(r.cat)}・${esc(r.rep)}</div></td>
              <td>${r.pcc > 0 ? `<span class="badge-pcc">PCC ${r.pcc}件</span><div style="font-size:11px;color:var(--muted);margin-top:2px;">${esc(r.agencies.slice(0,36))}</div>` : '<span style="color:var(--muted);">0 件</span>'}</td>
              <td class="num">${r.cand_net === 0 ? '<span class="badge-warn">0 元</span>' : fmtN(r.cand_net)+' 元'}</td>
              <td class="num">${r.party_net > 0 ? fmtN(r.party_net)+' 元' : '0'}</td>
              <td class="num">${r.grp_net > 0 ? fmtN(r.grp_net)+' 元' : '0'}</td>
              <td class="num">${r.l1_net > 0 ? '<strong>'+fmtN(r.l1_net)+' 元</strong>' : '0'}</td>
              <td style="font-size:12px;">${esc(r.summary || '四路徑皆無公開捐款紀錄')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
    document.querySelectorAll('#m41SubPills .pill').forEach(btn => {
      btn.addEventListener('click', () => {
        UI_STATE.matrix41Mode = btn.dataset.m41;
        renderZeroPathCard();
      });
    });
  }
}

function renderL2Card(){
  let items = DATA.l2_items.filter(x => {
    const tOk = (SW_STATE.curr && x.t === 'c') || (SW_STATE.prev && x.t === 'p');
    if(!tOk) return false;
    if(SW_STATE.pcc && x.pcc !== 1) return false;
    return true;
  });
  const q = UI_STATE.l2Search.trim().toLowerCase();
  if(q){
    items = items.filter(x => x.person.toLowerCase().includes(q) || x.comp.toLowerCase().includes(q) || x.cand.toLowerCase().includes(q));
  }
  const sum = items.reduce((a,x)=>a+x.net,0);
  document.getElementById('l2Sub').textContent = `當前屆別與 PCC 開關條件下共 ${items.length} 筆（合計 ${fmtN(sum)} 元），全數嚴格隔離、絕不併入上方確定總額。`;
  document.getElementById('l2RowsWrap').innerHTML = items.map(x => `
    <div class="l2-row">
      <div style="font-weight:700;">${esc(x.t_lbl)}</div>
      <div style="display:flex;align-items:center;gap:6px;">${renderPartySvg(x.party,16)}<div><strong>${esc(x.cand)}</strong><div style="font-size:11px;color:var(--muted);">${esc(x.el)}・${esc(x.vic)}</div></div></div>
      <div><strong>${esc(x.person)}</strong><div style="font-size:11px;color:var(--muted);">${esc(x.id3)}・${esc(x.city)}</div></div>
      <div><strong>${esc(x.comp)}</strong>${x.pcc ? ' <span class="badge-pcc">關聯 PCC</span>' : ''}<div style="font-size:11px;color:var(--muted);">${esc(x.roles)}</div></div>
      <div class="num" style="font-weight:800;">${fmtN(x.net)} 元</div>
      <div style="font-size:11px;color:var(--muted);">${esc(x.note)}</div>
    </div>
  `).join('') || '<div class="notice-pill">當前篩選下無 L2 疑似紀錄。</div>';
}

function renderDashboard(isInitial, prevTotal){
  const res = evalState(SW_STATE);
  renderSwitchesAndLedger(res, prevTotal ?? res.totalNet, isInitial);
  renderPartyCard(res);
  renderSankey(res);
  renderMatrix(res);
  renderTicks(res);
  renderTwoTermCard();
  renderZeroPathCard();
  renderL2Card();
}

document.getElementById('toggleGlossaryBtn').addEventListener('click', () => {
  const p = document.getElementById('glossaryPanel');
  p.hidden = !p.hidden;
  document.getElementById('toggleGlossaryBtn').classList.toggle('active', !p.hidden);
});
document.getElementById('closeGlossaryBtn').addEventListener('click', () => {
  document.getElementById('glossaryPanel').hidden = true;
  document.getElementById('toggleGlossaryBtn').classList.remove('active');
});
document.getElementById('resetSwitchesBtn').addEventListener('click', () => {
  const oldTotal = lastTotalRendered;
  Object.assign(SW_STATE, {curr:true, prev:true, t1:true, t2:true, l1:true, pcc:false});
  renderDashboard(false, oldTotal);
});
document.querySelectorAll('#sankeyDensityPills .pill').forEach(btn => {
  btn.addEventListener('click', () => {
    UI_STATE.sankeyDensity = btn.dataset.sd;
    document.querySelectorAll('#sankeyDensityPills .pill').forEach(b => b.classList.toggle('active', b === btn));
    renderSankey(evalState(SW_STATE));
  });
});
document.querySelectorAll('#matSortPills .pill').forEach(btn => {
  btn.addEventListener('click', () => {
    UI_STATE.matSort = btn.dataset.ms;
    document.querySelectorAll('#matSortPills .pill').forEach(b => b.classList.toggle('active', b === btn));
    renderMatrix(evalState(SW_STATE));
  });
});
document.querySelectorAll('#moverPills .pill').forEach(btn => {
  btn.addEventListener('click', () => {
    UI_STATE.moverFilter = btn.dataset.mf;
    document.querySelectorAll('#moverPills .pill').forEach(b => b.classList.toggle('active', b === btn));
    renderTwoTermCard();
  });
});
document.getElementById('repeatSearch').addEventListener('input', e => {
  UI_STATE.repeatSearch = e.target.value;
  renderTwoTermCard();
});
document.getElementById('repeatPccToggle').addEventListener('click', e => {
  UI_STATE.repeatPccOnly = !UI_STATE.repeatPccOnly;
  e.target.classList.toggle('active', UI_STATE.repeatPccOnly);
  renderTwoTermCard();
});
document.querySelectorAll('#zeroPathPills .pill').forEach(btn => {
  btn.addEventListener('click', () => {
    UI_STATE.zeroPath = btn.dataset.zp;
    document.querySelectorAll('#zeroPathPills .pill').forEach(b => b.classList.toggle('active', b === btn));
    renderZeroPathCard();
  });
});
document.getElementById('l2Search').addEventListener('input', e => {
  UI_STATE.l2Search = e.target.value;
  renderL2Card();
});

renderDashboard(true, 0);
</script>
</body>
</html>
"""


def main() -> None:
    payload = build_payload()
    party_meta_json = json.dumps(PARTY_STYLES, ensure_ascii=False, separators=(",", ":"))
    party_order_json = json.dumps(PARTY_ORDER, ensure_ascii=False, separators=(",", ":"))
    svg_js = SVG_PARTY_ICON_JS.replace("__PARTY_META__", party_meta_json).replace("__PARTY_ORDER__", party_order_json)
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    out_html = (
        HTML_TEMPLATE
        .replace("__DATA_JSON__", data_json)
        .replace("__SVG_PARTY_ICON_JS__", svg_js)
    )

    p_ov = OUT_DIR / "光電政治獻金_政黨與個人流向總覽.html"
    p_idx = OUT_DIR / "index.html"
    p_net = OUT_DIR / "光電政治獻金_二分關係網絡圖.html"

    p_ov.write_text(out_html, encoding="utf-8")
    p_idx.write_text(out_html, encoding="utf-8")
    if p_net.exists():
        p_net.unlink()
        print(f"已移除舊檔：{p_net.name}")

    print(f"已產出：{p_ov.name} ({p_ov.stat().st_size:,} bytes)")
    print(f"已產出：{p_idx.name} ({p_idx.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
