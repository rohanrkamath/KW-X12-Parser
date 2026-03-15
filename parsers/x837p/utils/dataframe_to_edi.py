"""
Build 837P EDI from a DataFrame (full column schema from to_claims_dataframe_full).
Use when the original EDI file is not available; construction is from scratch.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas  # type: ignore[import-untyped]

from .segment_parser import Delimiters


def _v(row: dict[str, Any], col: str, default: str = "") -> str:
    """Get value from row, coerce to string, strip .0 from integers. Default if missing."""
    val = row.get(col)
    if val is None or (isinstance(val, float) and (val != val or val == float("inf"))):  # NaN check
        return default
    s = str(val).strip()
    return _fmt_val(s)


def _fmt_val(val: str) -> str:
    """Strip .0 from integer-looking floats (e.g. 2.0 -> 2, 1407052160.0 -> 1407052160)."""
    if not val:
        return val
    # "2.0" -> "2", "1407052160.0" -> "1407052160", "10.25" -> "10.25"
    if val.endswith(".0") and val[:-2].replace("-", "").isdigit():
        return val[:-2]
    return val


def _fmt_amt(val: str) -> str:
    """Format amount to 2 decimal places (e.g. 108 -> 108.00, 318.8 -> 318.80)."""
    if not val:
        return val
    try:
        f = float(val)
        return f"{f:.2f}"
    except (ValueError, TypeError):
        return val


def _fmt_amt_compact(val: str) -> str:
    """Format amount: whole numbers without decimals (0 -> 0), else 2 decimals (318.8 -> 318.80)."""
    if not val:
        return val
    try:
        f = float(val)
        return str(int(f)) if f == int(f) else f"{f:.2f}"
    except (ValueError, TypeError):
        return val


def _fmt_svd_payer_id(val: str) -> str:
    """Preserve leading zeros in SVD PayerIdentifier; pad 5-digit numeric to 6 digits."""
    if not val:
        return val
    s = _fmt_val(str(val).strip())
    if not s or not s.replace(".", "").isdigit():
        return s
    try:
        n = int(float(s))
        if 9999 < n < 100000:  # 5 digits, likely had leading 0
            return "0" + str(n)
        return s
    except (ValueError, TypeError):
        return s


def _fmt_zip(val: str) -> str:
    """Trim malformed zip: XXXXX00000 (10-digit) or XXXXX0000 (9-digit) to XXXXX."""
    if not val or len(val) < 9:
        return val
    if len(val) == 10 and val[:5].isdigit() and val[5:] == "00000":
        return val[:5]
    if len(val) == 9 and val[:5].isdigit() and val[5:] == "0000":
        return val[:5]
    return val


def _seg(
    seg_id: str,
    elements: list[str],
    d: Delimiters,
    trim_trailing_empty: bool = False,
) -> str:
    """Build segment string: SEG*elem1*elem2*elem3~"""
    parts = [seg_id]
    for i, e in enumerate(elements):
        if trim_trailing_empty and i == len(elements) - 1 and not e:
            continue
        # X12: empty elements are valid; preserve single space (e.g. REF*1G* ~)
        s = str(e) if (e is not None and (str(e).strip() or str(e) == " ")) else ""
        parts.append(s)
    if trim_trailing_empty:
        while len(parts) > 1 and parts[-1] == "":
            parts.pop()
    return d.element.join(parts) + d.segment_term


def _hi_from_row(row: dict[str, Any]) -> str:
    """Build HI segment from HI_01..HI_12 or HI_Codes."""
    codes = _v(row, "HI_Codes")
    if codes:
        # HI_Codes is pipe-joined: ABK:Z932|ABF:L089
        parts = [p.strip() for p in codes.split("|") if p.strip()]
        if parts:
            return d.element.join(parts)
    # Fallback: HI_01..HI_12
    parts = []
    for i in range(1, 13):
        v = _v(row, f"HI_{i:02d}")
        if v:
            parts.append(v)
    return d.element.join(parts) if parts else ""


def _sv1_composite(row: dict[str, Any], n: int) -> str:
    """Build SV1-01 composite: HC:code or HC:code:mod1:mod2:mod3:mod4."""
    code = _v(row, f"SV1_{n}_HCPCS_CODE")
    if not code:
        return "HC:"
    mods = []
    for i in range(1, 5):
        m = _v(row, f"SV1_{n}_MODIFIER_{i}")
        if m:
            mods.append(m)
    if mods:
        return "HC:" + code + ":" + ":".join(mods)
    return "HC:" + code


# Module-level delimiters for _hi_from_row (set per build)
d: Delimiters = Delimiters("*", ":", "~")


def build_edi_from_dataframe(
    df: "pandas.DataFrame",
    *,
    element_sep: str = "*",
    subelement_sep: str = ":",
    segment_term: str = "~",
    segments_per_line: bool = True,
    blank_line_between_segments: bool = False,
    normalize_zips: bool = False,
) -> str:
    """
    Build valid 837P EDI from a DataFrame with full column schema.

    Expects columns from to_claims_dataframe_full(): ISA_elem_*, GS_elem_*,
    ST_*, BHT_*, NM1_*, N3_*, N4_*, CLM_*, DMG_*, SBR_*, HI_*, REF_*,
    SV1_n_*, LX_n_*, DTP_*, etc.

    Args:
        df: DataFrame with one row per claim.
        element_sep: Element delimiter (default *).
        subelement_sep: Subelement delimiter (default :).
        segment_term: Segment terminator (default ~).

    Returns:
        Valid 837P EDI string.

    If segments_per_line is True (default), each segment is on its own line.
    If blank_line_between_segments is True, a blank line is inserted between segments (matches zircaid).
    If normalize_zips is False (default), N4 zip codes are output as-is. If True,
    malformed XXXXX0000/XXXXX00000 patterns are trimmed to XXXXX.
    """
    try:
        import pandas as pd  # type: ignore[import-untyped]
    except ImportError as e:
        raise ImportError("pandas required for build_edi_from_dataframe") from e

    global d
    d = Delimiters(element_sep, subelement_sep, segment_term)

    def _zip_val(val: str, trim_10_to_9: bool = False) -> str:
        if normalize_zips:
            return _fmt_zip(val or "")
        # Preserve raw format; avoid scientific notation for large numeric zips
        raw = val or ""
        if not raw:
            return ""
        s = _fmt_val(str(raw).strip())
        try:
            n = int(float(s))
            if 0 <= n <= 9999999999:  # 5-10 digit zip range
                s = str(n)
                # Fix mis-captured primary subscriber zip: 3080900000 -> 308090000
                if trim_10_to_9 and len(s) == 10 and s.endswith("00000") and s[5:9] == "0000":
                    s = s[:9]
                return s
        except (ValueError, TypeError):
            pass
        return s

    if df.empty:
        raise ValueError("DataFrame is empty")

    rows = df.to_dict("records")
    first = rows[0]
    segments: list[str] = []

    def v(c: str, default: str = "") -> str:
        return _v(first, c, default)

    # --- Envelope: ISA (must be 106 chars for X12 00501; positions 103-105 = delimiters) ---
    ISA_FIELD_LENGTHS = (2, 10, 2, 10, 2, 15, 2, 15, 6, 4, 1, 5, 9, 1, 1, 1)

    def _pad_isa(values: list[str]) -> str:
        """Build 106-char ISA with fixed-length fields; chars 103-105 = delimiters."""
        # Zero-pad: 0,2 (ISA01,03 auth qual), 8,9,11,12 (date, time, version, control)
        numeric_idx = {0, 2, 8, 9, 11, 12}  # 0-based
        padded = []
        for i, (val, size) in enumerate(zip(values, ISA_FIELD_LENGTHS)):
            raw = (str(val)[:size] if val else "").strip()
            if i in numeric_idx and raw and raw.replace("-", "").isdigit():
                s = raw.rjust(size, "0")[:size]
            else:
                s = raw.ljust(size)[:size]
            padded.append(s)
        body = d.element.join(["ISA"] + padded)
        # Must be 106 chars; last 3 (103,104,105) are component sep, repetition sep, segment term
        if len(body) < 103:
            body = body.ljust(103)
        elif len(body) > 103:
            body = body[:103]
        return body + d.element + d.subelement + d.segment_term  # positions 103,104,105 = elem, subelem, term

    isa_els = [v(f"ISA_elem_{i:02d}") for i in range(1, 17)]
    if any(isa_els):
        segments.append(_pad_isa(isa_els))
    else:
        default_isa = ["00", "", "00", "", "ZZ", "SENDER", "ZZ", "RECEIVER", "230101", "1200", "^", "00501", "000000001", "0", "P", ":"]
        segments.append(_pad_isa(default_isa))

    # --- GS ---
    gs_els = [v(f"GS_elem_{i:02d}") for i in range(1, 9)]
    if any(gs_els):
        segments.append(_seg("GS", gs_els, d))
    else:
        gs_fixed = [
            "HC",
            v("BHT_Reference_Identification", "1"),
            (v("NM1_SUBMITTER_Name_Last_or_Organization_Name") or "SENDER")[:50],
            (v("NM1_RECEIVER_Name_Last_or_Organization_Name") or "RECEIVER")[:50],
            v("BHT_Date", "20250101"),
            v("BHT_Time", "1200"),
            "1",
            "005010X222A1",
        ]
        segments.append(_seg("GS", gs_fixed, d))

    # --- ST ---
    st_id = v("ST_Transaction_Set_Identifier_Code", "837")
    st_ctrl = (v("ST_Transaction_Set_Control_Number", "0001") or "0001").rjust(4, "0")
    segments.append(_seg("ST", [st_id, st_ctrl, "005010X222A1"], d))

    # --- BHT ---
    bht_purpose = (v("BHT_Transaction_Set_Purpose_Code", "00") or "00").rjust(4, "0")  # 0019
    bht_type = (v("BHT_Transaction_Type_Code", "19") or "00").rjust(2, "0")
    bht = [
        bht_purpose,
        bht_type,
        v("BHT_Reference_Identification", "REF01"),
        v("BHT_Date", ""),
        v("BHT_Time", ""),
        v("BHT_Hierarchical_Structure_Code", "CH"),
    ]
    segments.append(_seg("BHT", bht, d))

    # --- Loop 1000A: Submitter (match original: ***** = 5 asterisks) ---
    nm1_sub = [
        "41", "2",
        v("NM1_SUBMITTER_Name_Last_or_Organization_Name", "SUBMITTER"),
        v("NM1_SUBMITTER_Name_First"),
        v("NM1_SUBMITTER_Name_Middle"),
        "", "",  # 2 empties -> 5 asterisks when first/middle empty
        v("NM1_SUBMITTER_Identification_Code_Qualifier", "46"),
        v("NM1_SUBMITTER_Identification_Code"),
    ]
    segments.append(_seg("NM1", nm1_sub, d))
    if v("PER_SUBMITTER_ContactQualifier") or v("PER_SUBMITTER_Name"):
        per_sub = [
            v("PER_SUBMITTER_ContactQualifier", "IC"),
            v("PER_SUBMITTER_Name"),
            v("PER_SUBMITTER_Comm1_Qualifier", "TE"),
            v("PER_SUBMITTER_Comm1_Number"),
            v("PER_SUBMITTER_Comm2_Qualifier"),
            v("PER_SUBMITTER_Comm2_Number"),
            v("PER_SUBMITTER_Comm3_Qualifier"),
            v("PER_SUBMITTER_Comm3_Number"),
        ]
        segments.append(_seg("PER", per_sub, d, trim_trailing_empty=True))

    # --- Loop 1000B: Receiver (match original: *****) ---
    nm1_rec = [
        "40", "2",
        v("NM1_RECEIVER_Name_Last_or_Organization_Name", "RECEIVER"),
        v("NM1_RECEIVER_Name_First"),
        v("NM1_RECEIVER_Name_Middle"),
        "", "",  # 2 empties
        v("NM1_RECEIVER_Identification_Code_Qualifier", "46"),
        v("NM1_RECEIVER_Identification_Code"),
    ]
    segments.append(_seg("NM1", nm1_rec, d))

    # --- Loop 2000A: Billing Provider (HL*1**20*1) ---
    segments.append(_seg("HL", ["1", "", "20", "1"], d))
    if v("PRV_ProviderCode"):
        segments.append(_seg("PRV", [v("PRV_ProviderCode", "BI"), v("PRV_ReferenceQualifier", "ZZ"), v("PRV_ReferenceId") or ""], d))
    nm1_bp = [
        "85", v("NM1_BILLING_PROVIDER_Entity_Type_Qualifier", "2"),
        v("NM1_BILLING_PROVIDER_Name_Last_or_Organization_Name"),
        v("NM1_BILLING_PROVIDER_Name_First"),
        v("NM1_BILLING_PROVIDER_Name_Middle"),
        "", "",  # 2 empties -> match original *****
        v("NM1_BILLING_PROVIDER_Identification_Code_Qualifier", "XX"),
        v("NM1_BILLING_PROVIDER_Identification_Code"),
    ]
    segments.append(_seg("NM1", nm1_bp, d))
    if v("N3_BILLING_PROVIDER_Address_Line1"):
        segments.append(_seg("N3", [v("N3_BILLING_PROVIDER_Address_Line1"), v("N3_BILLING_PROVIDER_Address_Line2")], d, trim_trailing_empty=True))
    if v("N4_BILLING_PROVIDER_City"):
        segments.append(_seg("N4", [v("N4_BILLING_PROVIDER_City"), v("N4_BILLING_PROVIDER_State"), _zip_val(v("N4_BILLING_PROVIDER_Zip"))], d, trim_trailing_empty=True))
    for q in ["EI", "0B"]:
        all_val = v(f"REF_{q}_All", "")
        if all_val:
            for part in all_val.split("|")[:3]:
                if part.strip():
                    segments.append(_seg("REF", [q, part.strip()], d))
        else:
            for i in range(1, 6):
                val = v(f"REF_{q}_{i}")
                if val:
                    segments.append(_seg("REF", [q, val], d))

    # Pay-to (NM1*87) if present
    if v("NM1_PAY_TO_ADDRESS_Name_Last_or_Organization_Name") or v("N3_PAY_TO_ADDRESS_Address_Line1"):
        nm1_pt = ["87", "2", v("NM1_PAY_TO_ADDRESS_Name_Last_or_Organization_Name"), v("NM1_PAY_TO_ADDRESS_Name_First"), v("NM1_PAY_TO_ADDRESS_Name_Middle"), "", "", v("NM1_PAY_TO_ADDRESS_Identification_Code_Qualifier"), v("NM1_PAY_TO_ADDRESS_Identification_Code")]
        segments.append(_seg("NM1", nm1_pt, d, trim_trailing_empty=True))
        if v("N3_PAY_TO_ADDRESS_Address_Line1"):
            segments.append(_seg("N3", [v("N3_PAY_TO_ADDRESS_Address_Line1"), v("N3_PAY_TO_ADDRESS_Address_Line2")], d, trim_trailing_empty=True))
        if v("N4_PAY_TO_ADDRESS_City"):
            segments.append(_seg("N4", [v("N4_PAY_TO_ADDRESS_City"), v("N4_PAY_TO_ADDRESS_State"), _zip_val(v("N4_PAY_TO_ADDRESS_Zip"))], d, trim_trailing_empty=True))

    # --- Claims (Loop 2000B + 2300 + 2400) ---
    hl_bp_id = v("HL_BillingProvider_ID", "1")
    for idx, row in enumerate(rows):
        claim_hl = _v(row, "HL_Claim_ID") or str(idx + 2)
        segments.append(_seg("HL", [str(claim_hl), hl_bp_id, "22", "0"], d))

        # SBR: COB uses SBR*S first, then SBR*P after REF*1G
        sbr_s = _v(row, "SBR_S_Payer_Responsibility")
        has_cob = bool(sbr_s and str(sbr_s).strip() == "S")  # only when first SBR is secondary
        if has_cob and sbr_s:
            sbr_els = [
                sbr_s,
                _v(row, "SBR_S_Relationship_Code", "18"),
                _v(row, "SBR_S_Subscriber_GroupNumber", ""),
                "", "", "", "", "",
                _v(row, "SBR_S_Subscriber_PatientRelationship", "MC"),
            ]
        else:
            sbr_p = _v(row, "SBR_P_Payer_Responsibility") or "P"
            sbr_els = [
                sbr_p,
                _v(row, "SBR_P_Relationship_Code", "18"),
                "", "", "", "", "", "",
                _v(row, "SBR_P_Subscriber_PatientRelationship", "MC"),
            ]
        segments.append(_seg("SBR", sbr_els, d))

        # NM1*IL (Subscriber) - last*first****idq*id (4 asterisks) per original
        nm1_il = [
            "IL", _v(row, "NM1_SUBSCRIBER_Entity_Type_Qualifier", "1"),
            _v(row, "NM1_SUBSCRIBER_Name_Last_or_Organization_Name"),
            _v(row, "NM1_SUBSCRIBER_Name_First"),
            _v(row, "NM1_SUBSCRIBER_Name_Middle"),
            "", "",  # 2 empties -> 4 asterisks when middle empty (one fewer)
            _v(row, "NM1_SUBSCRIBER_Identification_Code_Qualifier", "MI"),
            _v(row, "NM1_SUBSCRIBER_Identification_Code"),
        ]
        segments.append(_seg("NM1", nm1_il, d))
        if _v(row, "N3_SUBSCRIBER_Address_Line1"):
            segments.append(_seg("N3", [_v(row, "N3_SUBSCRIBER_Address_Line1"), _v(row, "N3_SUBSCRIBER_Address_Line2")], d, trim_trailing_empty=True))
        if _v(row, "N4_SUBSCRIBER_City"):
            segments.append(_seg("N4", [_v(row, "N4_SUBSCRIBER_City"), _v(row, "N4_SUBSCRIBER_State"), _zip_val(_v(row, "N4_SUBSCRIBER_Zip"), trim_10_to_9=True)], d, trim_trailing_empty=True))

        # DMG
        dmg = [
            _v(row, "DMG_Date_Time_Period_Format_Qualifier", "D8"),
            _v(row, "DMG_Date_Time_Period"),
            _v(row, "DMG_Gender_Code"),
        ]
        segments.append(_seg("DMG", dmg, d))

        # NM1*PR (Payer) - match original (one fewer empty)
        nm1_pr = [
            "PR", "2",
            _v(row, "NM1_PAYER_Name_Last_or_Organization_Name"),
            _v(row, "NM1_PAYER_Name_First"),
            _v(row, "NM1_PAYER_Name_Middle"),
            "", "",  # 2 empties
            _v(row, "NM1_PAYER_Identification_Code_Qualifier", "PI"),
            _v(row, "NM1_PAYER_Identification_Code"),
        ]
        segments.append(_seg("NM1", nm1_pr, d))
        # REF*G2 (first only before CLM); REF*0B and additional G2s after last service line N4
        ref_0b_val = _v(row, "REF_0B_1")
        if not ref_0b_val and _v(row, "REF_0B_All"):
            ref_0b_val = _fmt_val(_v(row, "REF_0B_All").split("|")[0].strip())
        all_g2 = _v(row, "REF_G2_All")
        g2_parts = []
        if all_g2:
            g2_parts = [_fmt_val(p.strip()) for p in all_g2.split("|")[:5] if _fmt_val(p.strip())]
        else:
            for i in range(1, 6):
                val = _v(row, f"REF_G2_{i}")
                if val:
                    g2_parts.append(val)
        if g2_parts:
            segments.append(_seg("REF", ["G2", g2_parts[0]], d))

        # CLM (06 Accept, 07 Release, 08 PatientSig, 09 BenefitAssign, 10 Freq)
        # full_columns: elem7->YesNo1(A), elem8->Release(Y), elem9->PatientSig(Y) - per 837P order
        clm = [
            _v(row, "CLM_Claim_Submitters_Identifier"),
            _fmt_amt(_v(row, "CLM_Monetary_Amount")),
            "", "",  # 3, 4
            _v(row, "CLM_HEALTH_CARE_SERVICE_LOCATION_INFORMATION"),
            _v(row, "CLM_Provider_Accept_Assignment_Code", "Y"),
            _v(row, "CLM_Yes_No_Condition_or_Response_Code_1", "A"),  # 07 Release
            _v(row, "CLM_Release_of_Information_Code", "Y"),  # 08 PatientSig (parser elem8)
            _v(row, "CLM_Yes_No_Condition_or_Response_Code_2", "Y"),  # 09 BenefitAssign
            _v(row, "CLM_Claim_Frequency_Type_Code", "P"),
        ]
        segments.append(_seg("CLM", clm, d, trim_trailing_empty=True))

        # HI
        hi_str = _hi_from_row(row)
        if hi_str:
            segments.append("HI" + d.element + hi_str + d.segment_term)

        # NM1*DN (Referring) if present
        if _v(row, "NM1_REFERRING_PROVIDER_Name_Last_or_Organization_Name"):
            nm1_dn = ["DN", "1", _v(row, "NM1_REFERRING_PROVIDER_Name_Last_or_Organization_Name"), _v(row, "NM1_REFERRING_PROVIDER_Name_First"), _v(row, "NM1_REFERRING_PROVIDER_Name_Middle"), "", "", _v(row, "NM1_REFERRING_PROVIDER_Identification_Code_Qualifier", "XX"), _v(row, "NM1_REFERRING_PROVIDER_Identification_Code")]
            segments.append(_seg("NM1", nm1_dn, d, trim_trailing_empty=True))

        # REF*1G before LX (always; empty element when no value, per zircaid REF*1G*~)
        ref_1g_val = ""
        all_1g = _v(row, "REF_1G_All")
        if all_1g:
            first_part = _fmt_val(all_1g.split("|")[0].strip())
            ref_1g_val = first_part if first_part else ""
        else:
            ref_1g_val = _v(row, "REF_1G_1") or ""
        segments.append(_seg("REF", ["1G", ref_1g_val], d))

        # COB block: SBR*P, AMT*D, OI, OTHER_SUBSCRIBER, OTHER_PAYER (after REF*1G, before LX)
        if has_cob:
            # SBR*P*18*[PatientName] per zircaid (e.g. SBR*P*18*MARTHA)
            sbr_p_els = [
                _v(row, "SBR_P_Payer_Responsibility", "P"),
                _v(row, "SBR_P_Relationship_Code", "18"),
                _v(row, "SBR_P_Subscriber_GroupNumber", ""),  # element 3: patient name when COB
            ]
            segments.append(_seg("SBR", sbr_p_els, d, trim_trailing_empty=True))
            # AMT*D always required for COB (amount paid by primary); default 0
            amt_d = _v(row, "AMT_D")
            amt_val = _fmt_amt_compact(amt_d) if (amt_d is not None and str(amt_d).strip() != "") else "0"
            segments.append(_seg("AMT", ["D", amt_val], d))
            oi_els = []
            for i in range(1, 10):
                oi_els.append(_v(row, f"SEG_OI_1_elem_{i:02d}", ""))
            if not any(str(x or "").strip() for x in oi_els):
                oi_els = ["", "", "", "Y", "B", "", "", "", "Y"]  # default OI***Y*B**Y
            segments.append(_seg("OI", oi_els, d, trim_trailing_empty=True))
            if _v(row, "NM1_OTHER_SUBSCRIBER_Name_Last_or_Organization_Name"):
                nm1_os = [
                    "IL", "1",
                    _v(row, "NM1_OTHER_SUBSCRIBER_Name_Last_or_Organization_Name"),
                    _v(row, "NM1_OTHER_SUBSCRIBER_Name_First"),
                    _v(row, "NM1_OTHER_SUBSCRIBER_Name_Middle"),
                    "", "",  # 4 asterisks when middle empty
                    _v(row, "NM1_OTHER_SUBSCRIBER_Identification_Code_Qualifier", "MI"),
                    _v(row, "NM1_OTHER_SUBSCRIBER_Identification_Code"),
                ]
                segments.append(_seg("NM1", nm1_os, d, trim_trailing_empty=True))
                if _v(row, "N3_OTHER_SUBSCRIBER_Address_Line1"):
                    segments.append(_seg("N3", [_v(row, "N3_OTHER_SUBSCRIBER_Address_Line1"), _v(row, "N3_OTHER_SUBSCRIBER_Address_Line2")], d, trim_trailing_empty=True))
                if _v(row, "N4_OTHER_SUBSCRIBER_City"):
                    segments.append(_seg("N4", [_v(row, "N4_OTHER_SUBSCRIBER_City"), _v(row, "N4_OTHER_SUBSCRIBER_State"), _zip_val(_v(row, "N4_OTHER_SUBSCRIBER_Zip"))], d, trim_trailing_empty=True))
            if _v(row, "NM1_OTHER_PAYER_Name_Last_or_Organization_Name"):
                nm1_op = [
                    "PR", "2",
                    _v(row, "NM1_OTHER_PAYER_Name_Last_or_Organization_Name"),
                    "", "", "", "",  # 5 asterisks: 4 empties (pos 4-7) + implicit
                    _v(row, "NM1_OTHER_PAYER_Identification_Code_Qualifier", "PI"),
                    _v(row, "NM1_OTHER_PAYER_Identification_Code"),
                ]
                segments.append(_seg("NM1", nm1_op, d, trim_trailing_empty=True))

        # Service lines (LX, SV1, DTP, NM1*DK, N3, N4, SVD, CAS, DTP*573)
        n_lines = int(float(_v(row, "SV1_LINE_COUNT", "1") or 1))
        for n in range(1, min(n_lines + 1, 21)):
            lx_num = _v(row, f"LX_{n}_LineNumber") or str(n)
            segments.append(_seg("LX", [lx_num], d))

            sv1_01 = _sv1_composite(row, n)
            sv1_02 = _fmt_amt(_v(row, f"SV1_{n}_LINE_CHARGE"))
            sv1_03 = _v(row, f"SV1_{n}_UNIT_OF_MEASURE", "UN")
            sv1_04 = _v(row, f"SV1_{n}_QUANTITY")
            sv1_05 = _v(row, f"SV1_{n}_PLACE_OF_SERVICE", "12")
            sv1_06 = _v(row, f"SV1_{n}_SERVICE_DATE") or _v(row, f"DTP_Line{n}_472_Date") or _v(row, "DTP_472_Date")
            sv1_07 = _v(row, f"SV1_{n}_Service_Type_Code", "1")  # SV1-07; default 1
            segments.append(_seg("SV1", [sv1_01, sv1_02, sv1_03, sv1_04, sv1_05, "", sv1_07], d, trim_trailing_empty=True))

            dtp_q = _v(row, f"DTP_Line{n}_472_Qualifier", "472")
            dtp_f = _v(row, f"DTP_Line{n}_472_Format", "D8")
            dtp_d = _v(row, f"DTP_Line{n}_472_Date") or _v(row, f"SV1_{n}_SERVICE_DATE") or _v(row, "DTP_472_Date")
            if dtp_d:
                segments.append(_seg("DTP", [dtp_q, dtp_f, dtp_d], d))

            # Per-line rendering (NM1*DK)
            r_last = _v(row, f"NM1_RENDERING_{n}_Name_Last_or_Organization_Name") or _v(row, "NM1_RENDERING_PROVIDER_Name_Last_or_Organization_Name")
            r_first = _v(row, f"NM1_RENDERING_{n}_Name_First") or _v(row, "NM1_RENDERING_PROVIDER_Name_First")
            if r_last or r_first:
                r_idq = _v(row, f"NM1_RENDERING_{n}_Identification_Code_Qualifier") or _v(row, "NM1_RENDERING_PROVIDER_Identification_Code_Qualifier", "XX")
                r_id = _v(row, f"NM1_RENDERING_{n}_Identification_Code") or _v(row, "NM1_RENDERING_PROVIDER_Identification_Code")
                nm1_dk = ["DK", "1", r_last, r_first, "", "", "", r_idq, r_id]
                segments.append(_seg("NM1", nm1_dk, d, trim_trailing_empty=True))
                r_a1 = _v(row, f"N3_RENDERING_{n}_Address_Line1") or _v(row, "N3_RENDERING_PROVIDER_Address_Line1")
                if r_a1:
                    segments.append(_seg("N3", [r_a1, _v(row, f"N3_RENDERING_{n}_Address_Line2") or _v(row, "N3_RENDERING_PROVIDER_Address_Line2")], d, trim_trailing_empty=True))
                r_city = _v(row, f"N4_RENDERING_{n}_City") or _v(row, "N4_RENDERING_PROVIDER_City")
                if r_city:
                    zip_val = _v(row, f"N4_RENDERING_{n}_Zip") or _v(row, "N4_RENDERING_PROVIDER_Zip")
                    segments.append(_seg("N4", [r_city, _v(row, f"N4_RENDERING_{n}_State") or _v(row, "N4_RENDERING_PROVIDER_State"), _zip_val(zip_val)], d, trim_trailing_empty=True))
            # SVD, CAS, DTP*573 (COB) after N4 per line
            if has_cob:
                svd_id = _v(row, f"SVD_{n}_PayerIdentifier")
                svd_amt = _v(row, f"SVD_{n}_Amount")
                svd_comp = _v(row, f"SVD_{n}_Composite")
                if svd_id is not None or svd_amt is not None or svd_comp:
                    svd_qty = _v(row, f"SV1_{n}_QUANTITY", "")
                    svd_id_str = _fmt_svd_payer_id(svd_id) if svd_id is not None else ""
                    segments.append(_seg("SVD", [svd_id_str, _fmt_amt_compact(svd_amt) if svd_amt is not None else "0", svd_comp or "", "", svd_qty], d, trim_trailing_empty=True))
                cas_gc = _v(row, f"CAS_{n}_GroupCode") or _v(row, "CAS_1_GroupCode")
                cas_cagc = _v(row, f"CAS_{n}_ClaimAdjustmentGroupCode") or _v(row, "CAS_1_ClaimAdjustmentGroupCode")
                cas_amt = _v(row, f"CAS_{n}_Amount") or _v(row, "CAS_1_Amount")
                if cas_gc or cas_cagc or cas_amt is not None:
                    segments.append(_seg("CAS", [cas_gc or "PR", cas_cagc or "96", _fmt_amt(cas_amt) if cas_amt is not None else "0"], d))
                dtp573 = _v(row, f"DTP_Line{n}_573_Date") or _v(row, "DTP_573_Date") or dtp_d
                if dtp573:
                    segments.append(_seg("DTP", ["573", _v(row, f"DTP_Line{n}_573_Format", "D8"), dtp573], d))
        # After last service line N4: REF*1G (if value present), REF*0B (if present), additional REF*G2
        if ref_1g_val and ref_1g_val.strip():
            segments.append(_seg("REF", ["1G", ref_1g_val], d))
        if ref_0b_val:
            segments.append(_seg("REF", ["0B", _fmt_val(ref_0b_val)], d))
        for p in g2_parts[1:]:
            if p:
                segments.append(_seg("REF", ["G2", p], d))

    # --- SE (segment count = count from ST through SE) ---
    st_idx = next(i for i, s in enumerate(segments) if s.startswith("ST" + d.element))
    body_count = len(segments) - st_idx + 1  # ST..body..SE; SE counts itself
    se_ctrl_raw = v("ST_Transaction_Set_Control_Number", "0001") or "0001"
    se_ctrl = str(se_ctrl_raw).split(".")[0] if se_ctrl_raw else "0001"
    if se_ctrl and se_ctrl.replace("-", "").isdigit():
        se_ctrl = se_ctrl.rjust(9, "0")[-9:]
    else:
        se_ctrl = se_ctrl.rjust(4, "0")
    segments.append(_seg("SE", [str(body_count), se_ctrl], d))

    # --- GE, IEA ---
    ge_els = [v(f"GE_elem_{i:02d}") for i in range(1, 3)]
    if any(ge_els):
        segments.append(_seg("GE", ge_els, d))
    else:
        segments.append(_seg("GE", ["1", v("GS_elem_06", "1")], d))

    iea_els = [v(f"IEA_elem_{i:02d}") for i in range(1, 3)]
    if any(iea_els):
        # Pad IEA02 (interchange control) to 9 digits
        if iea_els[1]:
            s = str(iea_els[1]).split(".")[0]
            if s and s.replace("-", "").isdigit():
                iea_els[1] = s.rjust(9, "0")[-9:]
        segments.append(_seg("IEA", iea_els, d))
    else:
        iea_ctrl = v("ISA_elem_13", "000000001")
        # Preserve leading zeros (9 digits for interchange control number)
        s = str(iea_ctrl).split(".")[0] if iea_ctrl else ""
        if s and s.replace("-", "").isdigit():
            iea_ctrl = s.rjust(9, "0")[-9:]
        segments.append(_seg("IEA", ["1", iea_ctrl], d))

    if segments_per_line:
        sep = "\n\n" if blank_line_between_segments else "\n"
    else:
        sep = ""
    result = sep.join(segments)
    # Trailing newline per POSIX / common EDI practice (matches zircaid)
    if result and not result.endswith("\n"):
        result += "\n"
    return result


def write_edi_from_dataframe(
    df: "pandas.DataFrame",
    path: str | Path,
    **kwargs: Any,
) -> None:
    """Build EDI from DataFrame and write to file."""
    content = build_edi_from_dataframe(df, **kwargs)
    Path(path).write_text(content, encoding="utf-8")
