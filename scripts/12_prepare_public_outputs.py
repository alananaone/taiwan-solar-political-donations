#!/usr/bin/env python3
"""公開前整理（在 01～11 跑完、上傳前執行）。
1. L1 高信心：保留真名、受贈候選人、金額、日期、比對到的公司與職稱、判定依據；移除證號、性別、地址欄位（比對用，不必公開）。
2. L2 疑似、L3 同名衝突、X 排除：只公開筆數與金額彙總，不公開逐筆姓名。
3. 互動頁：L1 照列（去掉證號前碼與縣市），L2 逐筆清單清空；41 家對照表拿掉 L2 欄。
4. 08_／11_ 逐筆明細與名冊含 L2、L3、X 姓名，不公開。"""
import csv, json, re
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "output"
SRC = OUT / "11_natural_person_donations_two_terms.csv"
L1_COLS = ["election_years", "election", "area", "candidate", "party", "is_victor", "tx_date", "person_name",
           "gross_amount", "returned_amount", "net_amount", "linked_companies", "linked_roles", "linked_pcc_awarded",
           "evidence_codes", "homonym_flag", "classification_note"]


def read(p):
    with open(p, encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def write(p, rows, cols):
    with open(p, "w", encoding="utf-8-sig", newline="") as h:
        w = csv.DictWriter(h, cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def term_years(t):
    return "2022／2024" if t.startswith("111") else "2018／2020"


def strip_l2(s):
    return " ｜ ".join(x for x in re.split(r"\s*｜\s*", s) if x and "L2" not in x).strip()


def main():
    rows = read(SRC)
    for r in rows:
        r["election_years"] = term_years(r["term"])
    l1 = sorted((r for r in rows if r["match_confidence"] == "L1"),
                key=lambda r: (r["election"], r["area"], r["candidate"], r["tx_date"], r["person_name"]))
    write(OUT / "11_natural_person_L1_donations.csv", l1, L1_COLS)

    g = defaultdict(lambda: {"rows": 0, "gross": 0, "returned": 0, "net": 0, "n": set()})
    for r in rows:
        x = g[(r["match_confidence"], r["election_years"])]
        x["rows"] += 1
        x["n"].add(r["person_name"])
        for k in ("gross", "returned", "net"):
            x[k] += int(float(r[k + "_amount"]))
    summ = [{"level": k[0], "election_years": k[1], "rows": v["rows"], "distinct_names": len(v["n"]), "gross_amount": v["gross"],
             "returned_amount": v["returned"], "net_amount": v["net"], "included_in_total": "是" if k[0] == "L1" else "否"} for k, v in sorted(g.items())]
    write(OUT / "11_natural_person_level_summary.csv", summ, list(summ[0]))

    p = OUT / "11_zero_donation_and_high_pcc_summary.csv"
    z = read(p)
    for r in z:
        r["channel_summary"] = strip_l2(r["channel_summary"])
    write(p, z, [c for c in z[0] if c != "l2_person_excluded_net"])

    for f in ("index.html", "光電政治獻金_政黨與個人流向總覽.html"):
        p = OUT / f
        t = p.read_text(encoding="utf-8")
        i = t.index("const DATA = ") + len("const DATA = ")
        d, n = json.JSONDecoder().raw_decode(t[i:])
        ids = {pid: f"{v['name']}｜{v['comp']}" for pid, v in d["persons"].items()}
        assert len(set(ids.values())) == len(ids)
        d["persons"] = {ids[pid]: {**v, "id": ids[pid], "id3": "", "city": ""} for pid, v in d["persons"].items()}
        for e in d["l1_edges"]:
            e["p"] = ids[e["p"]]
        l2n, l2s = len(d["l2_items"]), sum(x["net"] for x in d["l2_items"])
        d["l2_items"] = []
        for r in d["zero_pcc"]:
            r.update(l2_net=0, summary=strip_l2(r["summary"]))
        t = t[:i] + json.dumps(d, ensure_ascii=False, separators=(",", ":")) + t[i + n:]
        t = t.replace("七、L2 高度疑似自然人待人工查核清單（嚴格隔離・絕不併入確定總額）", "七、L2 高度疑似自然人（只列合計，不公開逐筆）")
        t = re.sub(r"document\.getElementById\('l2Sub'\)\.textContent = `[^`]*`;",
                   f"document.getElementById('l2Sub').textContent = '共 {l2n} 筆、合計 {l2s:,} 元，缺乏旁證，不計入任何總額；為避免誤傷同名民眾，不公開逐筆資料。';", t)
        t = t.replace("當前篩選下無 L2 疑似紀錄。", "逐筆資料已移除。")
        t = re.sub(r'\s*<input class="search-input" id="l2Search"[^>]*>', '<input id="l2Search" type="hidden">', t)
        p.write_text(t, encoding="utf-8")

    for f in ("08_natural_person_donations_matched.csv", "08_natural_person_roster.csv", "11_natural_person_roster_two_terms.csv", SRC.name):
        (OUT / f).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
