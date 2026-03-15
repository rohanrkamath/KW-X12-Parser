#!/usr/bin/env python
"""
Generate notional X12 837P EDI sample files (20-100 claims each).
Output: kw_x12_parser/x837p/edi_examples/edi_sample_*.txt
Uses notional data; adheres to X12 005010X222A1 837P structure.

 richness: "minimal" (~311 cols), "medium" (~550 cols), "full" (~800+ cols like home_trdplntr)
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

# HCPCS codes - simple and with RR/KX modifiers (DME)
HCPCS_SIMPLE = [
    "A4369", "A4371", "A4385", "A4394", "A4406", "A4407", "A4409",
    "A4414", "A4419", "A4425", "A4432", "A4452", "A4456", "A4357",
    "A4362", "A5063", "A5120", "A5057", "A6196", "A6197", "A6216",
]
HCPCS_DME = [
    ("E1390", "RR", "KX", "O2 CONCENTRATOR 05 LTR"),
    ("E1392", "RR", "KX", "O2 CONC PORTABLE"),
    ("E0600", "RR", "", "SUCTION UNIT ORAL PORTABLE ACDC"),
    ("E0630", "RR", "", "LIFT PATIENT WSLING"),
    ("K0004", "RR", "KX", "WC REHAB HIGH STRENGTH LW RECL"),
    ("K0738", "RR", "", "O2 GAS SYSTEM HOME TRANSFILL UNIT"),
    ("E0601", "RR", "", "CPAP UNITSELF TITRATING SYSTEM"),
]
ICD_ABK = ["R32", "R0902", "Z933", "Z936", "Z932", "I872", "G4733", "K219", "M5432", "J449"]
ICD_ABF = ["R339", "N39498", "S31114D", "Z433", "L97222", "K5720", "L89151", "J9601", "R262"]
FIRST = ["JAMES", "MARY", "ROBERT", "PATRICIA", "JOHN", "JENNIFER", "MICHAEL", "LINDA",
         "WILLIAM", "ELIZABETH", "DAVID", "BARBARA", "RICHARD", "SUSAN", "CHARLES", "KAREN"]
LAST = ["SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES", "GARCIA", "MILLER", "DAVIS",
        "RODRIGUEZ", "MARTINEZ", "HERNANDEZ", "LOPEZ", "GONZALEZ", "WILSON", "THOMAS", "TAYLOR"]
STREETS = ["100 MAIN ST", "200 OAK AVE", "150 ELM DR", "75 MAPLE LN", "300 CEDAR RD",
           "42 PINE BLVD", "88 BROADWAY", "120 MARKET ST", "255 RIVER RD"]
CITIES = [
    ("ATLANTA", "GA", "30301"), ("AUGUSTA", "GA", "30901"), ("COLUMBUS", "GA", "31901"),
    ("SAVANNAH", "GA", "31401"), ("MACON", "GA", "31201"), ("ROME", "GA", "30161"),
    ("VALDOSTA", "GA", "31601"), ("LAWRENCEVILLE", "GA", "30044"),
]
COB_PAYERS = [("DEMO COMMERCIAL PPO", "62308"), ("DEMO MEDICARE ADV", "87726"), ("DEMO MEDICARE HMO", "38333")]


def _seg(*parts: str) -> str:
    return "*".join(str(p) for p in parts) + "~"


def _rand_dob() -> str:
    d = date(1940, 1, 1) + timedelta(days=random.randint(0, 28000))
    return d.strftime("%Y%m%d")


def _rand_npi() -> str:
    return str(random.randint(1000000000, 1999999999))


def _rand_member_id() -> str:
    return f"{random.randint(100000000, 999999999)}{random.choice('ABCDEFGHIJ')}"


def _date_range(d: date, days: int = 30) -> str:
    end = d + timedelta(days=days)
    return f"{d.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"


def generate_edi(num_claims: int, file_id: str, richness: str = "minimal", seed: int | None = None) -> str:
    if seed is not None:
        random.seed(seed)
    segs: list[str] = []
    def add(s: str): segs.append(s)

    gs_num = file_id
    isa_num = file_id
    base_dt = date.today() - timedelta(days=random.randint(0, 30))
    date_str_6 = base_dt.strftime("%y%m%d")   # YYMMDD for ISA09
    date_str_8 = base_dt.strftime("%Y%m%d")   # YYYYMMDD for GS04, BHT04 (required)
    time_str = f"{random.randint(8,17):02d}{random.randint(0,59):02d}"

    sender = ("99999DEMO" + " " * 15)[:15]
    recv = ("DEMO" + " " * 15)[:15]
    ctrl_9 = str(isa_num).zfill(9)[-9:]
    add(f"ISA*00*          *00*          *ZZ*{sender}*ZZ*{recv}*{date_str_6}*{time_str}*^*00501*{ctrl_9}*0*P*:~")

    add(_seg("GS", "HC", "99999DEMO", "DEMO", date_str_8, time_str, gs_num, "X", "005010X222A1"))
    add(_seg("ST", "837", "0001", "005010X222A1"))
    add(_seg("BHT", "0019", "00", gs_num, date_str_8, time_str, "CH"))
    add(_seg("NM1", "41", "2", "DEMO MEDICAL SUPPLIES", "", "", "", "", "46", "99999DEMO"))
    add(_seg("PER", "IC", "HELP DESK", "TE", "8005551234"))
    add(_seg("NM1", "40", "2", "DEMO CLEARINGHOUSE", "", "", "", "", "46", "DEMO"))

    # Billing provider
    add(_seg("HL", "1", "", "20", "1"))
    if richness == "full":
        add(_seg("PRV", "BI", "PXC", "332B00000X"))
    else:
        add(_seg("PRV", "BI", "ZZ", ""))
    bp_npi = _rand_npi()
    add(_seg("NM1", "85", "2", "DEMO DME PROVIDER LLC", "", "", "", "", "XX", bp_npi))
    add(_seg("N3", f"{random.randint(100,999)} EXAMPLE WAY"))
    city, st, zip_ = random.choice(CITIES)
    add(_seg("N4", city, st, zip_))
    add(_seg("REF", "EI", f"{random.randint(10,99)}{random.randint(1000000,9999999)}"))
    if richness == "full":
        add(_seg("PER", "IC", "DEMO HEALTHCARE INC", "TE", "8005551234"))
    add(_seg("NM1", "87", "2"))
    add(_seg("N3", "PO BOX 12345"))
    add(_seg("N4", "PHILADELPHIA", "PA", "191012345"))

    base_claim_id = random.randint(52000000, 52999999)
    base_d = date.today() - timedelta(days=random.randint(10, 60))

    for i in range(num_claims):
        hl_id = i + 2
        add(_seg("HL", str(hl_id), "1", "22", "0"))
        last = random.choice(LAST)
        first = random.choice(FIRST)
        mid = random.choice(["", "A", "B", "J"]) if richness != "minimal" else ""
        sub_mi = _rand_member_id()
        npi_dn = _rand_npi()

        # SBR must come first in claim loop (2000B)
        if richness == "minimal":
            add(_seg("SBR", "P", "18", "", "", "", "", "", "MC"))
        elif richness in ("medium", "full"):
            grp = random.choice(["NA", "", str(random.randint(100000, 999999))])
            add(_seg("SBR", "S", "18", grp, "", "", "", "", "CI"))
        add(_seg("NM1", "IL", "1", last, first, mid, "", "", "MI", sub_mi))
        add(_seg("N3", f"{random.randint(1,999)} {random.choice(STREETS)}"))
        city, st, zip_ = random.choice(CITIES)
        add(_seg("N4", city, st, f"{zip_}0000"))
        add(_seg("DMG", "D8", _rand_dob(), random.choice(["M", "F"])))
        add(_seg("NM1", "PR", "2", "DEMO PRIMARY PAYER", "", "", "", "", "PI", "95327"))
        if richness == "minimal":
            add(_seg("REF", "G2", f"00{random.randint(100000, 999999)}A"))
        else:
            add(_seg("REF", "FY", "NOCD"))

        claim_suffix = f"-{1000 + i:04d}" if richness == "full" else ""
        claim_id = f"{base_claim_id - i}{claim_suffix}"
        num_lines = random.randint(1, 4) if richness == "minimal" else (random.randint(2, 4) if richness == "medium" else random.randint(2, 6))
        total = 0.0
        line_amts = []
        for _ in range(num_lines):
            amt = round(random.uniform(50.0, 800.0), 2)
            total += amt
            line_amts.append(amt)
        total = round(total, 2)

        clm_pos = f"12:B:1" if richness in ("medium", "full") else "12::1"
        add(_seg("CLM", claim_id, f"{total:.2f}", "", "", clm_pos, "Y", "A", "Y", "Y", "P"))
        abk = random.choice(ICD_ABK)
        abfs = [random.choice(ICD_ABF) for _ in range(random.randint(1, 3))]
        hi = "ABK:" + abk + "".join("*ABF:" + c for c in abfs)
        add(_seg("HI", hi))
        add(_seg("NM1", "DN", "1", last, first, mid, "", "", "XX", npi_dn))
        if richness == "minimal":
            add(_seg("REF", "1G", ""))
        if richness == "full" and random.random() < 0.2:
            add(_seg("REF", "G1", "NAR"))
        if richness == "full" and random.random() < 0.3:
            add(_seg("REF", "G2", "CONVERSION"))

        # NM1*82 + PRV*PE for medium/full
        if richness in ("medium", "full"):
            add(_seg("NM1", "82", "2", "DEMO DME PROVIDER LLC", "", "", "", "", "XX", bp_npi))
            add(_seg("PRV", "PE", "PXC", "332B00000X"))

        # COB block: SBR*P, AMT*D, OI, NM1*IL (other sub), NM1*PR (COB payer), REF*FY
        if richness in ("medium", "full"):
            cob_grp = random.choice(["", "000003CA", "HCFA66", str(random.randint(100, 999))])
            add(_seg("SBR", "P", "18", cob_grp, "", "", "", "", "CI"))
            amt_d = round(total * random.uniform(0.1, 0.9), 2) if random.random() > 0.2 else 0
            add(_seg("AMT", "D", f"{amt_d:.2f}"))
            add(_seg("OI", "", "", "Y", "P", "", "Y"))
            add(_seg("NM1", "IL", "1", last, first, mid, "", "", "MI", _rand_member_id()))
            add(_seg("N3", f"{random.randint(1,999)} {random.choice(STREETS)}"))
            city, st, zip_ = random.choice(CITIES)
            add(_seg("N4", city, st, zip_))
            cob_name, cob_pi = random.choice(COB_PAYERS)
            add(_seg("NM1", "PR", "2", cob_name, "", "", "", "", "PI", cob_pi))
            add(_seg("N3", "PO BOX 30968"))
            add(_seg("N4", "SALT LAKE CITY", "UT", "841300968"))
            add(_seg("REF", "FY", "NOCD"))

        # Service lines
        for lx in range(1, num_lines + 1):
            add(_seg("LX", str(lx)))
            amt = line_amts[lx - 1]
            if richness == "full":
                code, mod1, mod2, desc = random.choice(HCPCS_DME)
                mods = f":{mod1}" if mod1 else ""
                if mod2:
                    mods += f":{mod2}"
                sv1_01 = f"HC:{code}:RR{mods}::::{desc}" if mods else f"HC:{code}:RR::::{desc}"
                qty = 1
                add(_seg("SV1", sv1_01, f"{amt:.2f}", "UN", str(qty), "", "", "1"))
            else:
                hcpcs = random.choice(HCPCS_SIMPLE)
                qty = random.randint(1, 30)
                add(_seg("SV1", f"HC:{hcpcs}", f"{amt:.2f}", "UN", str(qty), "12", "", "1"))

            dt_start = base_d + timedelta(days=random.randint(0, 20))
            if richness in ("medium", "full"):
                add(_seg("DTP", "472", "RD8", _date_range(dt_start)))
                add(_seg("REF", "6R", f"33000{random.randint(100000, 999999)}"))
            else:
                add(_seg("DTP", "472", "D8", dt_start.strftime("%Y%m%d")))
            if richness == "full" and random.random() < 0.4:
                add(_seg("REF", "0B", f"{random.randint(100000, 999999)}"))

            add(_seg("NM1", "DK", "1", last, first, mid, "", "", "XX", npi_dn))
            add(_seg("N3", f"{random.randint(1,999)} {random.choice(STREETS)}"))
            city, st, zip_ = random.choice(CITIES)
            add(_seg("N4", city, st, zip_))

            # SVD, CAS, DTP*573 for full
            if richness == "full":
                payer_pi = random.choice([cob_pi, "95327"])
                svd_amt = round(amt * random.uniform(0.5, 1.0), 2)
                add(_seg("SVD", payer_pi, f"{svd_amt:.2f}", f"HC:{code}", "", str(qty)))
                add(_seg("CAS", "CO", "45", f"{round(amt - svd_amt, 2)}", "1"))
                add(_seg("CAS", "PR", random.choice(["2", "3"]), f"{round(svd_amt * 0.2, 2)}", "1"))
                adj_d = dt_start + timedelta(days=random.randint(5, 15))
                add(_seg("DTP", "573", "D8", adj_d.strftime("%Y%m%d")))

    st_idx = next(i for i, s in enumerate(segs) if s.startswith("ST*"))
    add(_seg("SE", str(len(segs) - st_idx), "000000001"))
    add(_seg("GE", "1", gs_num))
    add(_seg("IEA", "1", isa_num))

    return "\n".join(segs)


def main():
    out_dir = Path(__file__).resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)
    configs = [
        (25, "edi_sample_25_claims.txt", 42, "minimal"),
        (50, "edi_sample_50_claims.txt", 101, "medium"),
        (75, "edi_sample_75_claims.txt", 202, "full"),
    ]
    for n, name, seed, richness in configs:
        path = out_dir / name
        content = generate_edi(n, f"{100000000 + seed}", richness=richness, seed=seed)
        path.write_text(content, encoding="utf-8")
        print(f"Wrote {path} ({n} claims, {richness})")


if __name__ == "__main__":
    main()
