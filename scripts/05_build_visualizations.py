#!/usr/bin/env python3
"""
從已交叉驗證之光電政治獻金資料集生成兩份互動式視覺化 HTML：
1. output/光電政治獻金_二分關係網絡圖.html（基於 lieflat-charts B2 Force 範本）
2. output/光電政治獻金_交互分布密度與流向總覽.html（基於 lieflat-charts L16 Matrix Heat / B3 Threads / L12 Type Colonnade / F5 Tick Rows 範本）
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "output"
DETAILS_CSV = OUT_DIR / "04_donation_details_matched.csv"
COMPANY_CSV = OUT_DIR / "04_company_summary.csv"

OUT_NETWORK = OUT_DIR / "光電政治獻金_二分關係網絡圖.html"
OUT_OVERVIEW = OUT_DIR / "光電政治獻金_交互分布密度與流向總覽.html"

ELECTION_SHORT = {
    "113年總統、副總統選舉": "113 總統副總統",
    "113年立法委員選舉": "113 立法委員",
    "111年直轄市市長選舉": "111 直轄市長",
    "111年縣(市)長選舉": "111 縣市長",
    "111年直轄市議員選舉": "111 直轄市議員",
    "111年縣(市)議員選舉": "111 縣市議員",
}


def clean_str(val) -> str:
    if pd.isna(val):
        return ""
    return str(val).strip()


def short_corp_name(name: str) -> str:
    for suf in (
        "科技股份有限公司",
        "開發股份有限公司",
        "工程股份有限公司",
        "企業股份有限公司",
        "事業股份有限公司",
        "股份有限公司",
        "有限公司",
    ):
        if name.endswith(suf) and len(name) > len(suf) + 1:
            return name[: -len(suf)]
    return name


def load_verified_data():
    df = pd.read_csv(DETAILS_CSV, dtype={"tax_id": str})
    comp_df = pd.read_csv(COMPANY_CSV, dtype={"tax_id": str})
    df["area"] = df["area"].fillna("")
    df["region"] = df.apply(
        lambda r: "全國（總統）"
        if "總統" in str(r["election"])
        else (clean_str(r["area"]) or "未填"),
        axis=1,
    )

    comp_meta = {}
    for _, r in comp_df.iterrows():
        comp_meta[clean_str(r["tax_id"])] = {
            "tax_id": clean_str(r["tax_id"]),
            "name": clean_str(r["gcis_name"]),
            "short": short_corp_name(clean_str(r["gcis_name"])),
            "tier": clean_str(r["tier"]),
            "rep": clean_str(r["rep_name"]),
            "assoc": clean_str(r["associations"]),
            "official": clean_str(r["official_lists"]),
            "codes": clean_str(r["core_codes"]),
            "reason": clean_str(r["classification_reason"]),
        }

    # Filter strictly to Tier 1 + Tier 2 as default interactive scope
    t12 = df[df["tier"].isin(["Tier 1", "Tier 2"])].copy()
    t12["cand_key"] = t12["election"] + "|" + t12["area"] + "|" + t12["candidate"]

    grouped_edges = (
        t12.groupby(
            ["tax_id", "gcis_name", "tier", "cand_key", "election", "area", "region", "candidate"],
            as_index=False,
        )
        .agg(
            gross=("gross_amount", "sum"),
            returned=("returned_amount", "sum"),
            net=("net_amount", "sum"),
            cnt=("tx_date", "count"),
            dates=("tx_date", lambda s: "、".join(sorted({clean_str(x) for x in s if clean_str(x)}))),
        )
    )

    # Connected components for Tier 1+2
    adj = defaultdict(set)
    for _, r in grouped_edges.iterrows():
        u = "C:" + r["tax_id"]
        v = "P:" + r["cand_key"]
        adj[u].add(v)
        adj[v].add(u)

    vis = set()
    comp_id_map = {}
    comp_sizes = {}
    comps = []
    for node in adj:
        if node in vis:
            continue
        stack = [node]
        vis.add(node)
        members = []
        while stack:
            cur = stack.pop()
            members.append(cur)
            for nxt in adj[cur]:
                if nxt not in vis:
                    vis.add(nxt)
                    stack.append(nxt)
        comps.append(members)
    comps.sort(key=len, reverse=True)
    for idx, members in enumerate(comps, start=1):
        for m in members:
            comp_id_map[m] = idx
        comp_sizes[idx] = len(members)

    return t12, grouped_edges, comp_meta, comp_id_map, comp_sizes


def build_network_payload(grouped_edges, comp_meta, comp_id_map, comp_sizes):
    # Aggregate company stats across Tier 1+2
    corp_nodes = {}
    for tax_id, g in grouped_edges.groupby("tax_id"):
        meta = comp_meta.get(tax_id, {})
        cid = comp_id_map.get("C:" + tax_id, 0)
        corp_nodes[tax_id] = {
            "id": "C:" + tax_id,
            "kind": "corp",
            "tax_id": tax_id,
            "name": meta.get("name", g["gcis_name"].iloc[0]),
            "short": meta.get("short", short_corp_name(g["gcis_name"].iloc[0])),
            "tier": g["tier"].iloc[0],
            "rep": meta.get("rep", ""),
            "assoc": meta.get("assoc", ""),
            "codes": meta.get("codes", ""),
            "net": int(g["net"].sum()),
            "gross": int(g["gross"].sum()),
            "returned": int(g["returned"].sum()),
            "deg": int(g["cand_key"].nunique()),
            "comp": cid,
            "comp_size": comp_sizes.get(cid, 0),
        }

    cand_nodes = {}
    for cand_key, g in grouped_edges.groupby("cand_key"):
        el_full = g["election"].iloc[0]
        region = g["region"].iloc[0]
        cand_name = g["candidate"].iloc[0]
        cid = comp_id_map.get("P:" + cand_key, 0)
        cand_nodes[cand_key] = {
            "id": "P:" + cand_key,
            "kind": "cand",
            "cand_key": cand_key,
            "name": cand_name,
            "election": el_full,
            "el_short": ELECTION_SHORT.get(el_full, el_full),
            "region": region,
            "net": int(g["net"].sum()),
            "gross": int(g["gross"].sum()),
            "returned": int(g["returned"].sum()),
            "deg": int(g["tax_id"].nunique()),
            "comp": cid,
            "comp_size": comp_sizes.get(cid, 0),
        }

    edges_list = []
    for _, r in grouped_edges.iterrows():
        edges_list.append(
            {
                "s": "C:" + r["tax_id"],
                "t": "P:" + r["cand_key"],
                "tier": r["tier"],
                "election": r["election"],
                "el_short": ELECTION_SHORT.get(r["election"], r["election"]),
                "region": r["region"],
                "net": int(r["net"]),
                "gross": int(r["gross"]),
                "returned": int(r["returned"]),
                "cnt": int(r["cnt"]),
                "dates": r["dates"],
            }
        )

    return {
        "corps": list(corp_nodes.values()),
        "cands": list(cand_nodes.values()),
        "edges": edges_list,
    }


def build_overview_payload(t12, grouped_edges, comp_meta):
    # 1. Matrix Heat (L16): Top 18 companies by (a) out-degree and (b) net_amount x Top 12 regions
    top12_regions = (
        grouped_edges.groupby("region")["net"]
        .sum()
        .sort_values(ascending=False)
        .head(12)
        .index.tolist()
    )

    corp_totals = (
        grouped_edges.groupby(["tax_id", "gcis_name", "tier"], as_index=False)
        .agg(
            net=("net", "sum"),
            gross=("gross", "sum"),
            returned=("returned", "sum"),
            deg=("cand_key", "nunique"),
        )
    )

    def make_matrix(sort_cols):
        sub_c = corp_totals.sort_values(sort_cols, ascending=[False, False]).head(18)
        rows = []
        cells = []
        for idx, cr in enumerate(sub_c.itertuples()):
            meta = comp_meta.get(cr.tax_id, {})
            rows.append(
                {
                    "tax_id": cr.tax_id,
                    "name": cr.gcis_name,
                    "short": short_corp_name(cr.gcis_name),
                    "tier": cr.tier,
                    "net": int(cr.net),
                    "deg": int(cr.deg),
                    "rep": meta.get("rep", ""),
                }
            )
            c_edges = grouped_edges[grouped_edges["tax_id"] == cr.tax_id]
            for r_idx, reg in enumerate(top12_regions):
                sub_r = c_edges[c_edges["region"] == reg]
                if len(sub_r) == 0:
                    continue
                net_val = int(sub_r["net"].sum())
                gross_val = int(sub_r["gross"].sum())
                ret_val = int(sub_r["returned"].sum())
                cands_txt = "、".join(
                    f"{x['candidate']}（{int(x['net'])//10000 if x['net']>=10000 else int(x['net'])}{'萬' if x['net']>=10000 else '元'}）"
                    for _, x in sub_r.sort_values("net", ascending=False).iterrows()
                )
                cells.append(
                    {
                        "r": idx,
                        "c": r_idx,
                        "net": net_val,
                        "gross": gross_val,
                        "returned": ret_val,
                        "cands": int(sub_r["cand_key"].nunique()),
                        "detail": cands_txt,
                    }
                )
        return {"rows": rows, "cols": top12_regions, "cells": cells}

    matrix_by_deg = make_matrix(["deg", "net"])
    matrix_by_net = make_matrix(["net", "deg"])

    # 2. B3 Threads:
    # Mode A: Multi-donor hubs (in_deg >= 3, 13 cands) <- Elections <- All 49 donor corps
    cand_in = (
        grouped_edges.groupby(["cand_key", "election", "region", "candidate"], as_index=False)
        .agg(deg=("tax_id", "nunique"), net=("net", "sum"), gross=("gross", "sum"))
        .sort_values(["deg", "net"], ascending=[False, False])
    )
    hub_cands = cand_in[cand_in["deg"] >= 3].copy()
    hub_edges = grouped_edges[grouped_edges["cand_key"].isin(hub_cands["cand_key"])].copy()

    # Order corps in hub_edges by net descending, then out_deg descending
    hub_corp_order = (
        hub_edges.groupby(["tax_id", "gcis_name", "tier"], as_index=False)
        .agg(net=("net", "sum"), gross=("gross", "sum"), deg=("cand_key", "nunique"))
        .sort_values(["net", "deg"], ascending=[False, False])
    )
    el_order_all = [
        "113年立法委員選舉",
        "111年直轄市議員選舉",
        "111年縣(市)長選舉",
        "111年縣(市)議員選舉",
        "111年直轄市市長選舉",
        "113年總統、副總統選舉",
    ]
    hub_els = [e for e in el_order_all if e in set(hub_edges["election"])]

    src_a = [
        {
            "id": r.tax_id,
            "label": f"{short_corp_name(r.gcis_name)}（{'T1' if r.tier=='Tier 1' else 'T2'}）",
            "full": r.gcis_name,
            "tier": r.tier,
        }
        for r in hub_corp_order.itertuples()
    ]
    mid_a = [{"id": e, "label": ELECTION_SHORT[e]} for e in hub_els]
    dst_a = [
        {
            "id": r.cand_key,
            "label": f"{r.candidate}（{r.region} · {r.deg}家）",
            "full": f"{r.candidate}（{ELECTION_SHORT[r.election]} · {r.region}）",
        }
        for r in hub_cands.itertuples()
    ]
    src_a_idx = {x["id"]: i for i, x in enumerate(src_a)}
    mid_a_idx = {x["id"]: i for i, x in enumerate(mid_a)}
    dst_a_idx = {x["id"]: i for i, x in enumerate(dst_a)}
    routes_a = [
        {
            "s": src_a_idx[r["tax_id"]],
            "m": mid_a_idx[r["election"]],
            "d": dst_a_idx[r["cand_key"]],
            "net": int(r["net"]),
            "gross": int(r["gross"]),
            "ret": int(r["returned"]),
        }
        for _, r in hub_edges.iterrows()
    ]

    # Mode B: Top 28 corporations by net -> 6 Elections -> Top 21 Counties/Regions
    top28_corps = corp_totals.sort_values(["net", "deg"], ascending=[False, False]).head(28)
    edges_28 = grouped_edges[grouped_edges["tax_id"].isin(top28_corps["tax_id"])].copy()
    agg_reg = (
        edges_28.groupby(["tax_id", "gcis_name", "tier", "election", "region"], as_index=False)
        .agg(
            net=("net", "sum"),
            gross=("gross", "sum"),
            returned=("returned", "sum"),
            cands=("cand_key", "nunique"),
        )
    )
    els_b = [e for e in el_order_all if e in set(agg_reg["election"])]
    regs_b = (
        agg_reg.groupby("region")["net"].sum().sort_values(ascending=False).index.tolist()
    )
    src_b = [
        {
            "id": r.tax_id,
            "label": f"{short_corp_name(r.gcis_name)}（{'T1' if r.tier=='Tier 1' else 'T2'}）",
            "full": r.gcis_name,
            "tier": r.tier,
        }
        for r in top28_corps.itertuples()
    ]
    mid_b = [{"id": e, "label": ELECTION_SHORT[e]} for e in els_b]
    dst_b = [{"id": reg, "label": reg, "full": reg} for reg in regs_b]
    src_b_idx = {x["id"]: i for i, x in enumerate(src_b)}
    mid_b_idx = {x["id"]: i for i, x in enumerate(mid_b)}
    dst_b_idx = {x["id"]: i for i, x in enumerate(dst_b)}
    routes_b = [
        {
            "s": src_b_idx[r["tax_id"]],
            "m": mid_b_idx[r["election"]],
            "d": dst_b_idx[r["region"]],
            "net": int(r["net"]),
            "gross": int(r["gross"]),
            "ret": int(r["returned"]),
            "cands": int(r["cands"]),
        }
        for _, r in agg_reg.iterrows()
    ]

    # 3. L12 Type Colonnade: Top 26 multi-donor candidates -> 6 Election Categories
    top26_multi = cand_in[cand_in["deg"] >= 2].head(26).copy()
    col_items = []
    for _, r in top26_multi.iterrows():
        c_rows = grouped_edges[grouped_edges["cand_key"] == r["cand_key"]].sort_values(
            "net", ascending=False
        )
        donors_list = "、".join(
            f"{short_corp_name(x['gcis_name'])}（{int(x['net'])//10000 if x['net']>=10000 else int(x['net'])}{'萬' if x['net']>=10000 else '元'}）"
            for _, x in c_rows.iterrows()
        )
        col_items.append(
            {
                "name": f"{r['candidate']}（{r['region']}）",
                "election": r["election"],
                "el_idx": el_order_all.index(r["election"]),
                "deg": int(r["deg"]),
                "net": int(r["net"]),
                "gross": int(r["gross"]),
                "donors": donors_list,
            }
        )

    el_summary = []
    for e in el_order_all:
        sub_e = grouped_edges[grouped_edges["election"] == e]
        el_summary.append(
            {
                "election": e,
                "label": ELECTION_SHORT[e],
                "net": int(sub_e["net"].sum()),
                "corps": int(sub_e["tax_id"].nunique()),
                "cands": int(sub_e["cand_key"].nunique()),
                "multi_in_top26": sum(1 for x in col_items if x["election"] == e),
            }
        )

    # 4. F5 Tick Rows: Top 18 companies by net amount (1 tick = NT$100,000)
    top18_net = corp_totals.sort_values(["net", "deg"], ascending=[False, False]).head(18)
    tick_items = []
    for _, r in top18_net.iterrows():
        meta = comp_meta.get(r["tax_id"], {})
        tick_items.append(
            {
                "tax_id": r["tax_id"],
                "name": r["gcis_name"],
                "short": short_corp_name(r["gcis_name"]),
                "tier": r["tier"],
                "net": int(r["net"]),
                "gross": int(r["gross"]),
                "returned": int(r["returned"]),
                "deg": int(r["deg"]),
                "rep": meta.get("rep", ""),
                "assoc": meta.get("assoc", "") or "無七大公協會登錄紀錄",
            }
        )

    return {
        "matrix": {"by_deg": matrix_by_deg, "by_net": matrix_by_net},
        "threads": {
            "hub": {"src": src_a, "mid": mid_a, "dst": dst_a, "routes": routes_a},
            "top28": {"src": src_b, "mid": mid_b, "dst": dst_b, "routes": routes_b},
        },
        "colonnade": {"items": col_items, "elections": el_summary},
        "ticks": tick_items,
    }


def render_network_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>光電政治獻金二分關係網絡圖（Tier 1 ＋ Tier 2）</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@6/dist/echarts.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root{{--bg:#F0EFEB;--dark:#1C1C1A;--paper:#F0EFEB;--muted:#8F8E88;--faint:#55554F;--pillbg:#2A2925;--aaa:#1F2526}}
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:var(--bg);font-family:'Inter','Noto Sans TC',sans-serif;padding:28px;-webkit-font-smoothing:antialiased;display:flex;justify-content:center}}
  .card{{background:var(--dark);color:var(--paper);border-radius:24px;padding:30px 30px 22px;width:min(1320px,100%)}}
  .topbar{{display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:8px}}
  h2{{font-weight:700;font-size:19px;letter-spacing:-.02em;margin-bottom:5px}}
  .sub{{font-size:12px;color:var(--muted);line-height:1.6;margin-bottom:14px;max-width:960px}}
  .navlink{{display:inline-flex;align-items:center;padding:7px 14px;border-radius:99px;background:var(--paper);color:var(--aaa);font-size:11.5px;font-weight:700;text-decoration:none;white-space:nowrap}}
  .navlink:hover{{background:#DCDAD2}}
  .controls{{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:12px}}
  .pills{{display:inline-flex;flex-wrap:wrap;background:var(--pillbg);padding:3px;border-radius:99px;gap:2px}}
  .pill{{border:none;background:transparent;color:#B3B0A4;font-family:inherit;font-size:11.5px;font-weight:600;padding:6px 13px;border-radius:99px;cursor:pointer;transition:background .15s,color .15s}}
  .pill.active{{background:var(--paper);color:var(--aaa);font-weight:700}}
  .pill:hover:not(.active){{color:var(--paper)}}
  .sel{{background:var(--pillbg);color:var(--paper);border:1px solid #3D3C36;border-radius:99px;padding:6px 14px;font-family:inherit;font-size:11.5px;font-weight:600;cursor:pointer;outline:none}}
  .searchbox{{display:inline-flex;align-items:center;gap:6px;background:var(--pillbg);border:1px solid #3D3C36;border-radius:99px;padding:4px 12px}}
  .searchbox input{{background:transparent;border:none;color:var(--paper);font-family:inherit;font-size:11.5px;width:190px;outline:none}}
  .searchbox input::placeholder{{color:#7C7A72}}
  .clrbtn{{border:none;background:#3A3934;color:var(--paper);font-size:10.5px;font-weight:600;padding:3px 9px;border-radius:99px;cursor:pointer}}
  #ch{{height:68vh;min-height:540px;cursor:grab}}
  #status{{background:#252420;border-radius:14px;padding:12px 16px;margin-top:10px;font-size:12px;color:#B3B0A4;line-height:1.65;display:flex;flex-wrap:wrap;justify-content:space-between;gap:10px}}
  #status b{{color:var(--paper);font-weight:700}}
  .src{{font-size:9.5px;color:var(--faint);margin-top:12px;letter-spacing:.06em;font-weight:500}}
</style>
</head>
<body>
<div class="card">
  <div class="topbar">
    <div>
      <h2>139 家太陽光電關聯企業與 200 人次候選人的政治獻金二分網絡</h2>
      <div class="sub">白色圓點＝Tier 1 核心光電專營企業（104 家） · 暖灰圓點＝Tier 2 泛綠能與供應鏈企業（35 家） · 菱形＝受贈候選人（面積按實捐淨額平方根縮放） · 實線＝實捐淨額，虛線＝全數返還（淨額 0） · 懸停或點擊任一節點聚焦鄰接關係，點擊空白重置</div>
    </div>
    <a class="navlink" href="光電政治獻金_交互分布密度與流向總覽.html">切換至分布密度與流向總覽</a>
  </div>
  <div class="controls">
    <div class="pills" id="scopePills">
      <button class="pill active" data-scope="all">全部 Tier 1＋Tier 2（139 家）</button>
      <button class="pill" data-scope="t1">僅核心專營 Tier 1（104 家）</button>
      <button class="pill" data-scope="core">多重交叉聚落（連通元件 ≥ 4 節點）</button>
    </div>
    <select class="sel" id="elSelect" aria-label="篩選選舉類別">
      <option value="ALL">全部六大選舉（合計）</option>
      <option value="113年立法委員選舉">113 年立法委員選舉</option>
      <option value="111年直轄市議員選舉">111 年直轄市議員選舉</option>
      <option value="111年縣(市)長選舉">111 年縣（市）長選舉</option>
      <option value="111年縣(市)議員選舉">111 年縣（市）議員選舉</option>
      <option value="111年直轄市市長選舉">111 年直轄市市長選舉</option>
      <option value="113年總統、副總統選舉">113 年總統、副總統選舉</option>
    </select>
    <div class="searchbox">
      <input id="qInput" type="text" placeholder="搜尋公司、代表人或候選人……" />
      <button class="clrbtn" id="qClear" type="button">重設</button>
    </div>
  </div>
  <div id="ch"></div>
  <div id="status">
    <div id="stMain">將滑鼠懸停或點擊圖中任一企業圓點或候選人菱形，可檢視完整統編、公協會身分及每一筆淨捐贈與返還明細。</div>
    <div id="stStats"></div>
  </div>
  <div class="src">FORCE BIPARTITE GRAPH · LIEFLAT B2 · 資料來源：監察院政治獻金會計報告書原始 CSV × 經濟部商工登記及七大光電公協會名錄雙向交叉驗證</div>
</div>
<script>
const RAW = {data_json};
const INK = '#1C1C1A', PAPER = '#F0EFEB';
const g = echarts.init(document.getElementById('ch'));
const fmtNT = v => 'NT$' + Number(v || 0).toLocaleString('en-US');

let curScope = 'all';
let curEl = 'ALL';
let curQuery = '';

const corpMap = new Map(RAW.corps.map(c => [c.id, c]));
const candMap = new Map(RAW.cands.map(p => [p.id, p]));

function renderGraph() {{
  const q = curQuery.trim().toLowerCase();
  const filteredEdges = RAW.edges.filter(e => {{
    if (curScope === 't1' && e.tier !== 'Tier 1') return false;
    if (curEl !== 'ALL' && e.election !== curEl) return false;
    const c = corpMap.get(e.s), p = candMap.get(e.t);
    if (curScope === 'core' && (!c || c.comp_size < 4)) return false;
    return true;
  }});

  // If search query is set, keep edges matching corp/rep/cand, or highlight matches
  const activeIds = new Set();
  const cSubStats = new Map();
  const pSubStats = new Map();

  filteredEdges.forEach(e => {{
    activeIds.add(e.s);
    activeIds.add(e.t);
    const cs = cSubStats.get(e.s) || {{ net: 0, gross: 0, ret: 0, deg: 0 }};
    cs.net += e.net; cs.gross += e.gross; cs.ret += e.returned; cs.deg += 1;
    cSubStats.set(e.s, cs);

    const ps = pSubStats.get(e.t) || {{ net: 0, gross: 0, ret: 0, deg: 0 }};
    ps.net += e.net; ps.gross += e.gross; ps.ret += e.returned; ps.deg += 1;
    pSubStats.set(e.t, ps);
  }});

  const matchedIds = new Set();
  if (q) {{
    activeIds.forEach(id => {{
      const obj = corpMap.get(id) || candMap.get(id);
      if (!obj) return;
      const hay = (obj.name + ' ' + (obj.short || '') + ' ' + (obj.rep || '') + ' ' + (obj.region || '') + ' ' + (obj.assoc || '')).toLowerCase();
      if (hay.includes(q)) matchedIds.add(id);
    }});
  }}

  const nodes = [];
  let cCount = 0, pCount = 0, sumNet = 0, sumGross = 0;

  activeIds.forEach(id => {{
    if (id.startsWith('C:')) {{
      cCount++;
      const c = corpMap.get(id);
      const st = cSubStats.get(id);
      sumNet += st.net; sumGross += st.gross;
      const isHit = matchedIds.size === 0 || matchedIds.has(id);
      const rSize = Math.max(6, Math.min(34, 4.5 + Math.sqrt(Math.max(st.net, 10000) / 10000) * 2.6));
      nodes.push({{
        id: c.id,
        name: c.short,
        value: st.net,
        raw: c,
        subStat: st,
        symbol: 'circle',
        symbolSize: rSize,
        itemStyle: {{
          color: c.tier === 'Tier 1' ? '#F0EFEB' : '#9C9A91',
          borderColor: matchedIds.has(id) ? '#F0EFEB' : '#1C1C1A',
          borderWidth: matchedIds.has(id) ? 2.5 : 1,
          opacity: isHit ? 1 : 0.16
        }},
        label: {{
          show: matchedIds.has(id) || st.deg >= 4 || st.net >= 900000,
          position: 'right',
          color: c.tier === 'Tier 1' ? '#F0EFEB' : '#C9C7BD',
          fontSize: 10.5,
          fontWeight: 600
        }}
      }});
    }} else {{
      pCount++;
      const p = candMap.get(id);
      const st = pSubStats.get(id);
      const isHit = matchedIds.size === 0 || matchedIds.has(id);
      const rSize = Math.max(6, Math.min(30, 5 + Math.sqrt(Math.max(st.net, 10000) / 10000) * 2.4));
      nodes.push({{
        id: p.id,
        name: p.name + '（' + p.el_short.replace(/選舉$/, '') + '）',
        value: st.net,
        raw: p,
        subStat: st,
        symbol: 'diamond',
        symbolSize: rSize,
        itemStyle: {{
          color: st.deg >= 3 ? '#DCDAD2' : st.deg === 2 ? '#B3B0A4' : '#6A6963',
          borderColor: matchedIds.has(id) ? '#F0EFEB' : '#1C1C1A',
          borderWidth: matchedIds.has(id) ? 2.5 : 1,
          opacity: isHit ? 1 : 0.16
        }},
        label: {{
          show: matchedIds.has(id) || st.deg >= 3 || st.net >= 900000,
          position: 'left',
          color: '#D8D7D1',
          fontSize: 10.5,
          fontWeight: 600
        }}
      }});
    }}
  }});

  const links = filteredEdges.map(e => {{
    const isHit = matchedIds.size === 0 || matchedIds.has(e.s) || matchedIds.has(e.t);
    const w = e.net > 0 ? Math.max(0.8, Math.min(5.2, 0.7 + Math.sqrt(e.net / 10000) * 0.48)) : 0.9;
    return {{
      source: e.s,
      target: e.t,
      raw: e,
      lineStyle: {{
        width: w,
        type: e.net === 0 ? 'dashed' : 'solid',
        color: e.net === 0 ? '#6A6963' : '#7C7A72',
        opacity: isHit ? (e.net === 0 ? 0.45 : 0.52) : 0.05,
        curveness: 0.08
      }}
    }};
  }});

  document.getElementById('stStats').innerHTML =
    `目前視圖：<b>${{cCount}} 家企業</b> × <b>${{pCount}} 人次候選人</b> · <b>${{links.length}} 條捐贈關係</b> · 實捐淨額合計 <b>${{fmtNT(sumNet)}}</b>`;

  const opt = {{
    animationDuration: 320,
    tooltip: {{
      backgroundColor: PAPER,
      borderWidth: 0,
      padding: [10, 14],
      textStyle: {{ color: INK, fontFamily: 'Inter, Noto Sans TC', fontSize: 12 }},
      formatter: p => {{
        if (p.dataType === 'node') {{
          const d = p.data.raw, s = p.data.subStat;
          if (d.kind === 'corp') {{
            return `<b>${{d.name}}</b>（${{d.tier}} · 統編 ${{d.tax_id}}）<br/>代表人：${{d.rep || '未載明'}}<br/>目前篩選淨額：<b>${{fmtNT(s.net)}}</b>（捐贈 ${{s.deg}} 人次）`;
          }}
          return `<b>${{d.name}}</b>（${{d.el_short}} · ${{d.region}}）<br/>目前篩選受贈淨額：<b>${{fmtNT(s.net)}}</b>（來自 ${{s.deg}} 家企業）`;
        }}
        const e = p.data.raw;
        const cs = corpMap.get(e.s), ps = candMap.get(e.t);
        return `<b>${{cs.name}}</b> → <b>${{ps.name}}</b><br/>選舉：${{e.el_short}}（${{e.region}}）<br/>實捐淨額：<b>${{fmtNT(e.net)}}</b>（申報 ${{fmtNT(e.gross)}}，返還 ${{fmtNT(e.returned)}}）`;
      }}
    }},
    series: [{{
      type: 'graph',
      layout: 'force',
      force: {{
        repulsion: cCount > 80 ? 94 : 145,
        edgeLength: [28, 78],
        gravity: 0.13,
        friction: 0.24,
        layoutAnimation: true
      }},
      labelLayout: {{ hideOverlap: true }},
      roam: true,
      draggable: true,
      left: 16, right: 16, top: 16, bottom: 16,
      data: nodes,
      links: links,
      emphasis: {{
        focus: 'adjacency',
        lineStyle: {{ color: PAPER, opacity: 0.95, width: 2.2 }},
        label: {{ show: true, color: PAPER }}
      }},
      blur: {{
        itemStyle: {{ opacity: 0.08 }},
        lineStyle: {{ opacity: 0.03 }}
      }}
    }}]
  }};
  g.clear();
  g.setOption(opt);
}}

g.on('click', params => {{
  if (params.dataType === 'node') {{
    const d = params.data.raw, s = params.data.subStat;
    const rels = RAW.edges.filter(e => (e.s === d.id || e.t === d.id) && (curEl === 'ALL' || e.election === curEl));
    if (d.kind === 'corp') {{
      const list = rels.sort((a,b) => b.net - a.net).slice(0, 8).map(e => {{
        const p = candMap.get(e.t);
        return `${{p.name}}（${{fmtNT(e.net)}}${{e.returned > 0 ? '，含返還 ' + fmtNT(e.returned) : ''}}）`;
      }}).join('、');
      document.getElementById('stMain').innerHTML =
        `<b>${{d.name}}</b>（${{d.tier}} · 統編 ${{d.tax_id}} · 代表人：${{d.rep || '無'}}）｜公協會：${{d.assoc || '無登錄紀錄'}}｜實捐淨額 <b>${{fmtNT(s.net)}}</b>（${{s.deg}} 人次）：${{list}}${{rels.length > 8 ? '……等共 ' + rels.length + ' 筆' : ''}}`;
    }} else {{
      const list = rels.sort((a,b) => b.net - a.net).map(e => {{
        const c = corpMap.get(e.s);
        return `${{c.short}}（${{fmtNT(e.net)}}${{e.returned > 0 ? '，已返還 ' + fmtNT(e.returned) : ''}}）`;
      }}).join('、');
      document.getElementById('stMain').innerHTML =
        `<b>${{d.name}}</b>（${{d.el_short}} · ${{d.region}}）｜受贈淨額合計 <b>${{fmtNT(s.net)}}</b>（${{s.deg}} 家光電企業）：${{list}}`;
    }}
  }}
}});

g.getZr().on('click', e => {{
  if (!e.target) {{
    document.getElementById('stMain').textContent =
      '將滑鼠懸停或點擊圖中任一企業圓點或候選人菱形，可檢視完整統編、公協會身分及每一筆淨捐贈與返還明細。';
    renderGraph();
  }}
}});

document.querySelectorAll('#scopePills .pill').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('#scopePills .pill').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    curScope = btn.dataset.scope;
    renderGraph();
  }});
}});
document.getElementById('elSelect').addEventListener('change', e => {{
  curEl = e.target.value;
  renderGraph();
}});
document.getElementById('qInput').addEventListener('input', e => {{
  curQuery = e.target.value;
  renderGraph();
}});
document.getElementById('qClear').addEventListener('click', () => {{
  curQuery = '';
  document.getElementById('qInput').value = '';
  renderGraph();
}});

renderGraph();
addEventListener('resize', () => g.resize());
</script>
</body>
</html>
"""


def render_overview_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>光電政治獻金交互分布密度與流向總覽（Tier 1 ＋ Tier 2）</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root{{--bg:#F0EFEB;--card:#F6F5F1;--dark:#1C1C1A;--ink:#1C1C1A;--muted:#6A6963;--faint:#8F8E88;--grid:#DEDDD6;--aaa:#1F2526}}
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:var(--bg);font-family:'Inter','Noto Sans TC',sans-serif;color:var(--ink);padding:34px;-webkit-font-smoothing:antialiased}}
  .pagehead{{max-width:1360px;margin:0 auto 24px;display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:14px}}
  .pagehead h1{{font-size:22px;letter-spacing:-.02em;font-weight:800;margin-bottom:6px}}
  .pagehead p{{font-size:12px;color:var(--muted);line-height:1.65;max-width:880px}}
  .navlink{{display:inline-flex;align-items:center;padding:8px 16px;border-radius:99px;background:var(--dark);color:#F0EFEB;font-size:12px;font-weight:700;text-decoration:none;white-space:nowrap}}
  .navlink:hover{{background:#3A3934}}
  .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:22px;max-width:1360px;margin:0 auto}}
  @media (max-width:1020px){{.grid2{{grid-template-columns:1fr}}}}
  .card{{background:var(--card);border:1px solid #E3E2DB;border-radius:24px;padding:26px 26px 20px;position:relative}}
  .card.dark{{background:var(--dark);border:1px solid var(--dark);color:#F0EFEB}}
  .card.dark .sub{{color:#8F8E88}}
  .card.dark .src{{color:#55554F}}
  .card.wide{{grid-column:1/-1}}
  .cardhead{{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:4px}}
  h2{{font-weight:700;font-size:16.5px;letter-spacing:-.02em;margin-bottom:3px}}
  .sub{{font-size:11.5px;color:var(--muted);margin-bottom:14px;line-height:1.55}}
  .src{{font-size:9.5px;color:var(--faint);margin-top:12px;letter-spacing:.06em;font-weight:500}}
  .pills{{display:inline-flex;background:#DEDDD6;padding:3px;border-radius:99px;gap:2px}}
  .pill{{border:none;background:transparent;color:var(--aaa);font-family:inherit;font-size:11px;font-weight:600;padding:5px 12px;border-radius:99px;cursor:pointer}}
  .pill.active{{background:var(--dark);color:#F0EFEB;font-weight:700}}
  .card.dark .pills{{background:#2A2925}}
  .card.dark .pill{{color:#B3B0A4}}
  .card.dark .pill.active{{background:#F0EFEB;color:var(--aaa)}}
  svg{{width:100%;display:block;margin:0 auto}}
  svg text{{font-family:'Inter','Noto Sans TC',sans-serif;user-select:none}}
  #statusBar{{background:#262522;border-radius:12px;padding:10px 14px;margin-top:8px;font-size:12px;color:#B3B0A4;display:flex;justify-content:space-between;align-items:center;gap:12px}}
  #statusBar b{{color:#F0EFEB;font-weight:700}}
  #spinNote{{font-size:10px;letter-spacing:.08em;color:#7C7A72;font-weight:700}}
  .thread{{transition:opacity .16s ease,stroke-width .16s ease}}
  .thread.hot{{opacity:.96 !important}}
  svg.focused .thread:not(.hot){{opacity:.045 !important}}
  .nodelab{{cursor:pointer;transition:opacity .16s ease}}
  svg.focused .nodelab:not(.hot){{opacity:.24}}
  .hit{{cursor:pointer}}
  #hoverTip{{position:fixed;pointer-events:none;z-index:999;background:var(--dark);color:#F0EFEB;border-radius:12px;padding:10px 14px;font-size:11.5px;line-height:1.55;max-width:340px;display:none;box-shadow:0 8px 24px rgba(0,0,0,.18)}}
  .pop{{transform-box:fill-box;transform-origin:center;animation:pop .42s cubic-bezier(.2,.7,.3,1.3) both}}
  @keyframes pop{{from{{transform:scale(0)}}to{{transform:none}}}}
  .fade{{animation:fade .65s ease both}}
  @keyframes fade{{from{{opacity:0}}}}
  .draw{{stroke-dasharray:1;stroke-dashoffset:1;animation:draw .8s cubic-bezier(.4,0,.2,1) both}}
  @keyframes draw{{to{{stroke-dashoffset:0}}}}
  @media (prefers-reduced-motion:reduce){{
    .pop,.fade{{animation:none}}
    .draw{{animation:none;stroke-dasharray:none;stroke-dashoffset:0}}
  }}
</style>
</head>
<body>
<div class="pagehead">
  <div>
    <h1>台灣光電機構政治獻金交互分布密度與流向總覽（Tier 1 ＋ Tier 2）</h1>
    <p>全數資料採自監察院 111 年及 113 年六大選舉會計報告書原始 CSV，經經濟部商工登記及七大太陽光電公協會名錄雙向比對後，扣除返還金額得出實捐淨額（合計 139 家企業、200 人次候選人、NT$39,196,000）。</p>
  </div>
  <a class="navlink" href="光電政治獻金_二分關係網絡圖.html">開啟完整 339 節點力導向二分網絡圖</a>
</div>

<div class="grid2">
  <!-- Card 1: L16 Matrix Heat -->
  <div class="card wide">
    <div class="cardhead">
      <div>
        <h2>交互分布密度（一）：前 18 家光電企業 × 12 大主要縣市／全國選區熱力矩陣</h2>
        <div class="sub">方格明度＝實捐淨額分級（越深越高） · 小灰點＝無捐贈紀錄 · 空心圓圈＝全數返還（淨額 0） · 虛線框＝目前列表單格最高金額 · 懸停方格檢視個別候選人明細</div>
      </div>
      <div class="pills" id="matPills">
        <button class="pill active" data-mode="by_deg">依受贈人數排序（多點分布）</button>
        <button class="pill" data-mode="by_net">依實捐淨額排序（高額集中）</button>
      </div>
    </div>
    <svg id="matSvg" viewBox="0 0 1180 560"></svg>
    <div class="src">MATRIX HEAT · LIEFLAT L16 · TIER 1（T1）＋ TIER 2（T2）實捐淨額交叉密度</div>
  </div>

  <!-- Card 2: B3 Threads -->
  <div class="card dark wide">
    <div class="cardhead">
      <div>
        <h2>交互分布密度（二）：光電企業 → 選舉類別 → 主要受贈者三段絲線流向</h2>
        <div class="sub">左欄＝光電企業 · 中欄＝六大選舉 · 右欄＝受贈候選人或縣市選區 · 虛線＝已全數返還（實捐淨額 0） · 懸停標籤抽出整束路徑，點擊釘住明細，點擊深色背景釋放</div>
      </div>
      <div class="pills" id="thrPills">
        <button class="pill active" data-mode="hub">多重受贈核心（49 家企業 → 13 位獲 ≥3 家捐贈候選人）</button>
        <button class="pill" data-mode="top28">前 28 大高額企業全流向（涵蓋總淨額 75.0%）</button>
      </div>
    </div>
    <svg id="thrSvg" viewBox="0 0 1200 780" preserveAspectRatio="xMidYMid meet"></svg>
    <div id="statusBar">
      <span id="stText">懸停任一條絲線或標籤，追蹤單筆或整束資金流向</span>
      <span id="spinNote"></span>
    </div>
    <div class="src">THREAD TRIPTYCH · LIEFLAT B3 · 完整涵蓋全部已返還與未返還紀錄（淨額計）</div>
  </div>

  <!-- Card 3: L12 Type Colonnade -->
  <div class="card">
    <h2>哪些人匯聚多家企業捐贈：前 26 位跨企業受贈候選人</h2>
    <div class="sub">篩選獲 2 家以上 Tier 1＋Tier 2 企業同時捐贈者（共 39 位，此圖列前 26 位） · 右側圓點面積反映各選舉受贈淨額 · 懸停顯示全部捐贈企業</div>
    <svg id="colSvg" viewBox="0 0 610 560"></svg>
    <div class="src">TYPE COLONNADE · LIEFLAT L12 · 依受贈企業家數與淨額排序</div>
  </div>

  <!-- Card 4: F5 Tick Rows -->
  <div class="card">
    <h2>哪些公司捐得最多與最廣：前 18 大捐贈企業刻度條</h2>
    <div class="sub">每根垂直刻度＝NT$10 萬元實捐淨額（每 5 根下方標記圓點＝50 萬） · 深墨＝Tier 1 核心專營，中灰＝Tier 2 關聯企業 · 行尾標示實捐淨額與受贈人次</div>
    <svg id="tickSvg" viewBox="0 0 610 560"></svg>
    <div class="src">TICK ROWS · LIEFLAT F5 · ONE TICK = NT$100,000 NET DONATION</div>
  </div>
</div>

<div id="hoverTip"></div>

<script>
const D = {data_json};
const INK = '#1C1C1A', PAPER = '#F0EFEB', MUTED = '#6A6963', GRID = '#DEDDD6';
const NS = 'http://www.w3.org/2000/svg';
const el = (p, t, a) => {{ const n = document.createElementNS(NS, t); for (const k in a) n.setAttribute(k, a[k]); p.appendChild(n); return n; }};
const txt = (p, a, s) => {{ const n = el(p, 'text', a); n.textContent = s; return n; }};
const fmtNT = v => 'NT$' + Number(v || 0).toLocaleString('en-US');
const fmtW = v => v >= 10000 ? (v / 10000).toFixed(v % 10000 === 0 ? 0 : 1) + ' 萬' : fmtNT(v);

const tipBox = document.getElementById('hoverTip');
function bindTip(node, htmlFn) {{
  node.style.cursor = 'pointer';
  node.addEventListener('mouseenter', e => {{
    tipBox.innerHTML = htmlFn();
    tipBox.style.display = 'block';
    moveTip(e);
  }});
  node.addEventListener('mousemove', moveTip);
  node.addEventListener('mouseleave', () => {{ tipBox.style.display = 'none'; }});
}}
function moveTip(e) {{
  const pad = 14;
  let x = e.clientX + pad, y = e.clientY + pad;
  if (x + 340 > window.innerWidth) x = e.clientX - 350;
  if (y + 180 > window.innerHeight) y = e.clientY - 140;
  tipBox.style.left = x + 'px';
  tipBox.style.top = y + 'px';
}}

// ════ 1 · L16 MATRIX HEAT ════
let matMode = 'by_deg';
function renderMatrix() {{
  const svg = document.getElementById('matSvg');
  svg.innerHTML = '';
  const m = D.matrix[matMode];
  const X0 = 248, Y0 = 96, CW = 66, CH = 20, PX = 72, PY = 24;

  const shade = v => v >= 1000000 ? '#1C1C1A' : v >= 500000 ? '#4A4944' : v >= 250000 ? '#8F8E88' : v >= 100000 ? '#B0AFA9' : '#D8D7D1';
  const cellMap = new Map(m.cells.map(c => [c.r + '_' + c.c, c]));
  let maxVal = -1, maxCell = null;
  m.cells.forEach(c => {{ if (c.net > maxVal) {{ maxVal = c.net; maxCell = c; }} }});

  m.cols.forEach((col, j) => {{
    const cx = X0 + j * PX + CW / 2;
    txt(svg, {{
      x: cx, y: Y0 - 12, 'font-size': 11, 'font-weight': 700, fill: '#4A4944',
      'text-anchor': 'start', transform: `rotate(-38 ${{cx}} ${{Y0 - 12}})`, class: 'fade'
    }}, col);
  }});

  m.rows.forEach((row, i) => {{
    const y = Y0 + i * PY;
    const tag = row.tier === 'Tier 1' ? 'T1' : 'T2';
    const rLab = txt(svg, {{
      x: X0 - 12, y: y + CH / 2 + 4, 'font-size': 11, 'font-weight': 600,
      fill: row.tier === 'Tier 1' ? INK : '#6A6963', 'text-anchor': 'end', class: 'fade'
    }}, `${{row.short}}〔${{tag}}〕（${{row.deg}}人）`);
    bindTip(rLab, () => `<b>${{row.name}}</b>（${{row.tier}} · 統編 ${{row.tax_id}}）<br/>代表人：${{row.rep || '無'}}<br/>總實捐淨額：<b>${{fmtNT(row.net)}}</b>（${{row.deg}} 人次）`);

    m.cols.forEach((col, j) => {{
      const x = X0 + j * PX;
      const cell = cellMap.get(i + '_' + j);
      if (!cell || cell.net === 0) {{
        const dot = el(svg, 'circle', {{ cx: x + CW / 2, cy: y + CH / 2, r: 2.1, fill: '#C6C5BF', class: 'pop', style: `animation-delay:${{(i + j) * 0.008}}s` }});
        if (cell && cell.gross > 0) {{
          dot.setAttribute('r', '3.5');
          dot.setAttribute('fill', 'none');
          dot.setAttribute('stroke', '#8F8E88');
          dot.setAttribute('stroke-width', '1.2');
          bindTip(dot, () => `<b>${{row.short}} × ${{col}}</b><br/>原申報 ${{fmtNT(cell.gross)}}，全數返還，淨額 NT$0<br/>明細：${{cell.detail}}`);
        }}
        return;
      }}
      const fill = shade(cell.net);
      const rect = el(svg, 'rect', {{
        x, y, width: CW, height: CH, rx: 4, fill, class: 'pop',
        style: `animation-delay:${{(i + j) * 0.008}}s`
      }});
      txt(svg, {{
        x: x + CW / 2, y: y + CH / 2 + 3.5, 'font-size': 9.5, 'font-weight': 700,
        fill: cell.net >= 500000 ? '#F0EFEB' : INK, 'text-anchor': 'middle',
        'pointer-events': 'none'
      }}, fmtW(cell.net));
      bindTip(rect, () => `<b>${{row.name}} × ${{col}}</b><br/>實捐淨額：<b>${{fmtNT(cell.net)}}</b>（${{cell.cands}} 人次${{cell.returned > 0 ? '，含返還 ' + fmtNT(cell.returned) : ''}}）<br/>對象：${{cell.detail}}`);
      if (maxCell && maxCell.r === i && maxCell.c === j) {{
        el(svg, 'rect', {{
          x: x - 3.5, y: y - 3.5, width: CW + 7, height: CH + 7, rx: 6,
          fill: 'none', stroke: INK, 'stroke-width': 1.2, 'stroke-dasharray': '3 3'
        }});
      }}
    }});
  }});

  // Legend at bottom
  const LG = [
    ['#D8D7D1', '10 萬以下'], ['#B0AFA9', '10–24.9 萬'], ['#8F8E88', '25–49.9 萬'],
    ['#4A4944', '50–99.9 萬'], ['#1C1C1A', '100 萬以上']
  ];
  txt(svg, {{ x: X0, y: 542, 'font-size': 10, 'font-weight': 700, fill: '#8F8E88' }}, '實捐淨額色階：');
  LG.forEach(([c, lab], k) => {{
    const lx = X0 + 95 + k * 112;
    el(svg, 'rect', {{ x: lx, y: 532, width: 12, height: 12, rx: 3, fill: c }});
    txt(svg, {{ x: lx + 17, y: 542, 'font-size': 10, 'font-weight': 600, fill: '#4A4944' }}, lab);
  }});
}}

// ════ 2 · B3 THREADS ════
let thrMode = 'hub';
let pinnedFn = null;
function renderThreads() {{
  const svg = document.getElementById('thrSvg');
  svg.innerHTML = '';
  svg.classList.remove('focused');
  pinnedFn = null;
  const stText = document.getElementById('stText');
  const spinNote = document.getElementById('spinNote');
  stText.textContent = '懸停任一條絲線或標籤，追蹤單筆或整束資金流向';
  spinNote.textContent = '';

  const T = D.threads[thrMode];
  const X1 = 235, X2 = 600, X3 = 945;
  const H_TOP = 44, H_BOT = 755;
  const span = (n, idx) => n <= 1 ? (H_TOP + H_BOT) / 2 : H_TOP + idx * ((H_BOT - H_TOP) / (n - 1));
  const sy = i => span(T.src.length, i);
  const my = i => 120 + i * ((640 - 120) / Math.max(1, T.mid.length - 1));
  const dy = i => span(T.dst.length, i);

  const pathD = r =>
    `M${{X1 + 6}} ${{sy(r.s)}} C${{(X1 + X2) / 2}} ${{sy(r.s)}} ${{(X1 + X2) / 2}} ${{my(r.m)}} ${{X2}} ${{my(r.m)}}` +
    ` C${{(X2 + X3) / 2}} ${{my(r.m)}} ${{(X2 + X3) / 2}} ${{dy(r.d)}} ${{X3 - 6}} ${{dy(r.d)}}`;

  [[X1 - 60, '① 光電企業'], [X2, '② 六大選舉類別'], [X3 + 55, thrMode === 'hub' ? '③ 受贈候選人（≥3家）' : '③ 縣市／全國選區']].forEach(([x, t]) => {{
    txt(svg, {{ x, y: 18, 'font-size': 10.5, 'font-weight': 800, fill: PAPER, 'letter-spacing': '.12em', 'text-anchor': 'middle' }}, t);
  }});

  const gThreads = el(svg, 'g', {{}});
  const routeObjs = T.routes.map((r, ri) => {{
    const w = r.net > 0 ? Math.max(0.8, Math.min(5.5, 0.7 + Math.sqrt(r.net / 10000) * 0.45)) : 0.9;
    const pEl = el(gThreads, 'path', {{
      d: pathD(r), fill: 'none', stroke: r.net === 0 ? '#8F8E88' : PAPER,
      'stroke-width': w, 'stroke-dasharray': r.net === 0 ? '4 4' : 'none',
      class: 'thread', opacity: r.net === 0 ? 0.25 : 0.14 + Math.min(0.28, r.net / 1500000),
      'stroke-linecap': 'round'
    }});
    const hit = el(gThreads, 'path', {{
      d: pathD(r), fill: 'none', stroke: '#000', 'stroke-opacity': 0, 'stroke-width': 10, class: 'hit'
    }});
    hit.dataset.route = ri;
    return {{ ...r, el: pEl, hit }};
  }});

  const mkNode = (x, y, label, anchor, kind, idx, fsize, fill) => {{
    const g = el(svg, 'g', {{ class: 'nodelab' }});
    g.dataset.kind = kind; g.dataset.idx = idx;
    el(g, 'rect', {{ x: x - 3, y: y - 1.8, width: 6, height: 3.6, fill: PAPER, opacity: 0.85 }});
    txt(g, {{ x: anchor === 'end' ? x - 10 : x + 10, y: y + 3.5, 'font-size': fsize, 'font-weight': 600, fill, 'text-anchor': anchor }}, label);
    el(g, 'rect', {{ x: anchor === 'end' ? x - 210 : x - 8, y: y - 7, width: 218, height: 14, fill: '#000', 'fill-opacity': 0, class: 'hit' }});
    return g;
  }};

  T.src.forEach((s, i) => mkNode(X1, sy(i), s.label, 'end', 's', i, T.src.length > 35 ? 9.5 : 10.5, s.tier === 'Tier 1' ? '#DCDAD2' : '#9C9A91'));
  T.mid.forEach((m, i) => {{
    const g = el(svg, 'g', {{ class: 'nodelab' }});
    g.dataset.kind = 'm'; g.dataset.idx = i;
    el(g, 'rect', {{ x: X2 - 52, y: my(i) - 11, width: 104, height: 22, rx: 11, fill: '#2B2A26', stroke: '#4A4944', 'stroke-width': 1 }});
    txt(g, {{ x: X2, y: my(i) + 3.8, 'font-size': 10.5, 'font-weight': 700, fill: PAPER, 'text-anchor': 'middle' }}, m.label);
    el(g, 'rect', {{ x: X2 - 56, y: my(i) - 12, width: 112, height: 24, fill: '#000', 'fill-opacity': 0, class: 'hit' }});
  }});
  T.dst.forEach((d, i) => mkNode(X3, dy(i), d.label, 'start', 'd', i, T.dst.length > 18 ? 10.5 : 11.5, '#DCDAD2'));

  const nodeLabs = [...svg.querySelectorAll('.nodelab')];
  const clear = () => {{
    svg.classList.remove('focused');
    routeObjs.forEach(r => r.el.classList.remove('hot'));
    nodeLabs.forEach(n => n.classList.remove('hot'));
    stText.textContent = '懸停任一條絲線或標籤，追蹤單筆或整束資金流向';
    spinNote.textContent = '';
  }};
  const focusRoutes = (rs, label) => {{
    svg.classList.add('focused');
    const rSet = new Set(rs);
    routeObjs.forEach(r => r.el.classList.toggle('hot', rSet.has(r)));
    nodeLabs.forEach(n => {{
      const k = n.dataset.kind, ix = +n.dataset.idx;
      n.classList.toggle('hot', rs.some(r => (k === 's' && r.s === ix) || (k === 'm' && r.m === ix) || (k === 'd' && r.d === ix)));
    }});
    stText.innerHTML = label;
  }};
  const routeLabel = r =>
    `<b>${{T.src[r.s].full}}</b> → ${{T.mid[r.m].label}} → <b>${{T.dst[r.d].full}}</b> · 實捐淨額 <b>${{fmtNT(r.net)}}</b>${{r.ret > 0 ? '（已返還 ' + fmtNT(r.ret) + '）' : ''}}`;
  const nodeSel = (kind, idx) => {{
    const rs = routeObjs.filter(r => (kind === 's' && r.s === idx) || (kind === 'm' && r.m === idx) || (kind === 'd' && r.d === idx));
    const total = rs.reduce((a, r) => a + r.net, 0);
    const totalRet = rs.reduce((a, r) => a + r.ret, 0);
    const name = kind === 's' ? T.src[idx].full : kind === 'm' ? T.mid[idx].label : T.dst[idx].full;
    return [rs, `<b>${{name}}</b> · 共 ${{rs.length}} 條路徑 · 實捐淨額 <b>${{fmtNT(total)}}</b>${{totalRet > 0 ? '（含返還 ' + fmtNT(totalRet) + '）' : ''}}`];
  }};
  const apply = t => {{
    const hit = t.closest?.('.hit');
    if (!hit) return null;
    const rg = hit.dataset.route, ng = hit.closest('.nodelab');
    if (rg != null) {{ const r = routeObjs[+rg]; return () => focusRoutes([r], routeLabel(r)); }}
    if (ng) {{ const [rs, lab] = nodeSel(ng.dataset.kind, +ng.dataset.idx); return () => focusRoutes(rs, lab); }}
    return null;
  }};
  svg.onmousemove = e => {{ if (pinnedFn) return; const f = apply(e.target); f ? f() : clear(); }};
  svg.onmouseleave = () => {{ if (!pinnedFn) clear(); }};
  svg.onclick = e => {{
    const f = apply(e.target);
    if (f) {{ pinnedFn = f; f(); spinNote.textContent = '已釘住 · 點擊深色空白處釋放'; }}
    else {{ pinnedFn = null; clear(); }}
  }};
}}

// ════ 3 · L12 TYPE COLONNADE ════
function renderColonnade() {{
  const svg = document.getElementById('colSvg');
  svg.innerHTML = '';
  const items = D.colonnade.items;
  const els = D.colonnade.elections;
  const itemY = i => 24 + i * 19.8;
  const elY = j => 72 + j * 82;
  const maxElNet = Math.max(...els.map(e => e.net), 1);

  items.forEach((it, i) => {{
    const yi = itemY(i), yj = elY(it.el_idx);
    const lab = txt(svg, {{ x: 168, y: yi + 3.5, 'font-size': 10.5, 'font-weight': 600, fill: it.deg >= 4 ? INK : '#4A4944', 'text-anchor': 'end', class: 'fade' }}, `${{it.name}} · ${{it.deg}}家`);
    const barW = Math.min(48, Math.max(4, it.net / 45000));
    el(svg, 'rect', {{ x: 174, y: yi - 2.5, width: barW, height: 5, rx: 2, fill: it.deg >= 4 ? INK : '#8F8E88', class: 'fade' }});
    const arc = el(svg, 'path', {{
      d: `M${{178 + barW}} ${{yi}} C 285 ${{yi}} 315 ${{yj}} 415 ${{yj}}`,
      fill: 'none', stroke: '#9C9A91', 'stroke-width': 0.9, opacity: 0.55, pathLength: 1, class: 'draw'
    }});
    const info = () => `<b>${{it.name}}</b>（${{els[it.el_idx].label}}）<br/>受贈淨額：<b>${{fmtNT(it.net)}}</b>（共 ${{it.deg}} 家企業）<br/>捐贈企業：${{it.donors}}`;
    bindTip(lab, info);
    bindTip(arc, info);
  }});

  els.forEach((e, j) => {{
    const y = elY(j);
    const r = 4.5 + Math.sqrt(e.net / maxElNet) * 14;
    const dot = el(svg, 'circle', {{ cx: 424, cy: y, r, fill: e.net >= 5000000 ? INK : '#6A6963', class: 'pop' }});
    const elab = txt(svg, {{ x: 432 + r, y: y + 4, 'font-size': 11, 'font-weight': 700, fill: INK, class: 'fade' }}, `${{e.label}}（${{fmtW(e.net)}}）`);
    const info = () => `<b>${{e.election}}</b><br/>Tier 1＋Tier 2 實捐淨額：<b>${{fmtNT(e.net)}}</b><br/>捐贈企業 ${{e.corps}} 家 → 受贈候選人 ${{e.cands}} 人次`;
    bindTip(dot, info);
    bindTip(elab, info);
  }});
}}

// ════ 4 · F5 TICK ROWS ════
function renderTicks() {{
  const svg = document.getElementById('tickSvg');
  svg.innerHTML = '';
  const items = D.ticks;
  const X0 = 184, PX = 8.4;
  const y0 = i => 24 + i * 28.5;

  items.forEach((it, i) => {{
    const y = y0(i);
    const label = txt(svg, {{
      x: X0 - 10, y: y + 4, 'font-size': 10.5, 'font-weight': 600,
      fill: it.tier === 'Tier 1' ? INK : '#6A6963', 'text-anchor': 'end', class: 'fade'
    }}, `${{it.short}}〔${{it.tier === 'Tier 1' ? 'T1' : 'T2'}}〕`);
    const ticks = Math.max(1, Math.round(it.net / 100000));
    el(svg, 'line', {{ x1: X0, y1: y + 8, x2: X0 + 36 * PX, y2: y + 8, stroke: GRID, 'stroke-width': 0.7 }});
    for (let k = 0; k < ticks; k++) {{
      const x = X0 + k * PX + PX / 2;
      const h = 11 + ((k * 7 + i * 3) % 5);
      el(svg, 'line', {{
        x1: x, y1: y + 8, x2: x, y2: y + 8 - h,
        stroke: it.tier === 'Tier 1' ? INK : '#6A6963', 'stroke-width': 2.2,
        opacity: 0.72 + ((k % 3) * 0.1), class: 'fade'
      }});
      if (k % 5 === 4) {{
        el(svg, 'circle', {{ cx: x, cy: y + 12.5, r: 1.4, fill: '#8F8E88' }});
      }}
    }}
    const valLab = txt(svg, {{
      x: X0 + ticks * PX + 8, y: y + 4.5, 'font-size': 10.5, 'font-weight': 800,
      fill: it.tier === 'Tier 1' ? INK : '#4A4944', class: 'fade'
    }}, `${{fmtW(it.net)}} · ${{it.deg}}人`);
    const info = () => `<b>${{it.name}}</b>（${{it.tier}} · 統編 ${{it.tax_id}}）<br/>代表人：${{it.rep || '無'}}<br/>實捐淨額：<b>${{fmtNT(it.net)}}</b>（申報 ${{fmtNT(it.gross)}}，返還 ${{fmtNT(it.returned)}}）<br/>捐贈對象：${{it.deg}} 人次<br/>公協會：${{it.assoc}}`;
    bindTip(label, info);
    bindTip(valLab, info);
  }});
}}

document.querySelectorAll('#matPills .pill').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('#matPills .pill').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    matMode = btn.dataset.mode;
    renderMatrix();
  }});
}});
document.querySelectorAll('#thrPills .pill').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('#thrPills .pill').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    thrMode = btn.dataset.mode;
    renderThreads();
  }});
}});

renderMatrix();
renderThreads();
renderColonnade();
renderTicks();
</script>
</body>
</html>
"""


def main():
    t12, grouped_edges, comp_meta, comp_id_map, comp_sizes = load_verified_data()
    net_payload = build_network_payload(grouped_edges, comp_meta, comp_id_map, comp_sizes)
    ov_payload = build_overview_payload(t12, grouped_edges, comp_meta)

    OUT_NETWORK.write_text(render_network_html(net_payload), encoding="utf-8")
    OUT_OVERVIEW.write_text(render_overview_html(ov_payload), encoding="utf-8")

    print("Generated:", OUT_NETWORK, f"({OUT_NETWORK.stat().st_size:,} bytes)")
    print("  Network payload:", len(net_payload["corps"]), "corps,", len(net_payload["cands"]), "cands,", len(net_payload["edges"]), "edges")
    print("Generated:", OUT_OVERVIEW, f"({OUT_OVERVIEW.stat().st_size:,} bytes)")
    print("  Overview matrix cells (by_deg / by_net):", len(ov_payload["matrix"]["by_deg"]["cells"]), "/", len(ov_payload["matrix"]["by_net"]["cells"]))
    print("  Overview threads routes (hub / top28):", len(ov_payload["threads"]["hub"]["routes"]), "/", len(ov_payload["threads"]["top28"]["routes"]))


if __name__ == "__main__":
    main()
