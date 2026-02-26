#!/usr/bin/env python3
"""
국민연금(National Pension Service) SEC EDGAR 13F Filing 수집 스크립트
- SEC EDGAR REST API (무료, 키 불필요)
- CIK: 0001608046
- 분기별 13F-HR filing에서 보유 종목 파싱
"""

import gzip
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# ─── 설정 ───────────────────────────────────────────────
NPS_CIK = "0001608046"
BASE_URL = "https://data.sec.gov"
ALT_URL = "https://www.sec.gov"
USER_AGENT = os.environ.get("SEC_USER_AGENT", "NPS-Portfolio-Tracker admin@example.com")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "us", "data")

# 섹터 매핑 (티커 기반)
SECTOR_MAP = {
    "AAPL": "Information Technology", "MSFT": "Information Technology",
    "NVDA": "Information Technology", "GOOGL": "Information Technology",
    "GOOG": "Information Technology", "META": "Communication Services",
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "BRK-B": "Financials", "JPM": "Financials", "V": "Financials",
    "MA": "Financials", "BAC": "Financials", "WFC": "Financials",
    "UNH": "Health Care", "JNJ": "Health Care", "LLY": "Health Care",
    "PFE": "Health Care", "ABBV": "Health Care", "MRK": "Health Care",
    "AVGO": "Information Technology", "ORCL": "Information Technology",
    "CRM": "Information Technology", "AMD": "Information Technology",
    "ADBE": "Information Technology", "INTC": "Information Technology",
    "CSCO": "Information Technology", "ACN": "Information Technology",
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy",
    "PG": "Consumer Staples", "KO": "Consumer Staples", "PEP": "Consumer Staples",
    "COST": "Consumer Staples", "WMT": "Consumer Staples",
    "HD": "Consumer Discretionary", "MCD": "Consumer Discretionary",
    "DIS": "Communication Services", "NFLX": "Communication Services",
    "T": "Communication Services", "VZ": "Communication Services",
    "LIN": "Materials", "NEE": "Utilities",
}


def sec_request(url: str) -> bytes:
    """SEC EDGAR API 요청 (User-Agent 필수, rate limit 준수, gzip 자동 해제)"""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        resp = urlopen(req, timeout=30)
        raw = resp.read()
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
        return raw
    except HTTPError as e:
        print(f"[ERROR] HTTP {e.code} for {url}")
        raise
    finally:
        time.sleep(0.15)


def sec_request_with_fallback(url: str) -> bytes:
    """data.sec.gov 실패 시 www.sec.gov로 재시도"""
    try:
        return sec_request(url)
    except HTTPError:
        if "data.sec.gov" in url:
            alt = url.replace("data.sec.gov", "www.sec.gov")
            print(f"[INFO] Retrying with www.sec.gov: {alt}")
            return sec_request(alt)
        raise


def get_13f_filings() -> list:
    """CIK에 대한 13F-HR filing 목록 조회"""
    url = f"{BASE_URL}/submissions/CIK{NPS_CIK}.json"
    print(f"[INFO] Fetching submissions: {url}")
    data = json.loads(sec_request(url))

    filings = []
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    periods = recent.get("reportDate", [])

    for i, form in enumerate(forms):
        if form in ("13F-HR", "13F-HR/A"):
            filings.append({
                "form": form,
                "filing_date": dates[i],
                "accession": accessions[i],
                "primary_doc": primary_docs[i],
                "period": periods[i],
            })

    filings.sort(key=lambda x: x["period"], reverse=True)
    print(f"[INFO] Found {len(filings)} 13F filings")
    return filings


def parse_13f_xml(accession: str) -> list:
    """13F filing의 information table XML 파싱"""
    acc_no_dash = accession.replace("-", "")
    cik_num = NPS_CIK.lstrip('0')
    filing_base = f"{BASE_URL}/Archives/edgar/data/{cik_num}/{acc_no_dash}"
    filing_base_alt = f"{ALT_URL}/Archives/edgar/data/{cik_num}/{acc_no_dash}"

    xml_url = None

    # 방법 1: index.json 시도
    index_url = f"{filing_base}/index.json"
    print(f"[INFO] Trying index.json: {index_url}")
    try:
        index_data = json.loads(sec_request(index_url))
        for item in index_data.get("directory", {}).get("item", []):
            name = item.get("name", "").lower()
            if "infotable" in name and name.endswith(".xml"):
                xml_url = f"{filing_base}/{item['name']}"
                break
        if not xml_url:
            for item in index_data.get("directory", {}).get("item", []):
                name = item.get("name", "").lower()
                if name.endswith(".xml") and "primary" not in name:
                    xml_url = f"{filing_base}/{item['name']}"
                    break
    except Exception as e:
        print(f"[WARN] index.json failed: {e}")

    # 방법 2: index.json 실패 시 HTML index 페이지 파싱
    if not xml_url:
        index_htm_url = f"{ALT_URL}/Archives/edgar/data/{cik_num}/{acc_no_dash}/"
        print(f"[INFO] Trying HTML index: {index_htm_url}")
        try:
            html_data = sec_request(index_htm_url).decode("utf-8", errors="replace")
            xml_matches = re.findall(r'href="([^"]*\.xml)"', html_data, re.IGNORECASE)
            for m in xml_matches:
                fname = m.split("/")[-1]
                if "primary" not in fname.lower() and fname.lower() != "r.xml":
                    xml_url = f"{filing_base}/{fname}"
                    break
        except Exception as e:
            print(f"[WARN] HTML index failed: {e}")

    # 방법 3: 일반적인 파일명 직접 시도
    if not xml_url:
        common_names = ["infotable.xml", "INFOTABLE.XML", "InfoTable.xml"]
        for fname in common_names:
            test_url = f"{filing_base}/{fname}"
            print(f"[INFO] Trying direct: {test_url}")
            try:
                test_data = sec_request(test_url)
                if test_data and len(test_data) > 100:
                    xml_url = test_url
                    break
            except Exception:
                continue

    if not xml_url:
        print("[WARN] Could not find infotable XML by any method")
        return []

    # XML 다운로드 (data.sec.gov 실패 시 www.sec.gov로 재시도)
    print(f"[INFO] Parsing infotable: {xml_url}")
    try:
        xml_data = sec_request_with_fallback(xml_url)
    except Exception as e:
        print(f"[WARN] Could not download XML: {e}")
        return []

    root = ET.fromstring(xml_data)

    ns_match = re.match(r'\{(.+?)\}', root.tag)
    default_ns = ns_match.group(1) if ns_match else ""

    holdings = []
    info_tables = []

    if default_ns:
        info_tables = root.findall(f".//{{{default_ns}}}infoTable")

    if not info_tables:
        info_tables = root.findall(".//infoTable")

    if not info_tables:
        for elem in root.iter():
            if elem.tag.lower().endswith("infotable"):
                info_tables.append(elem)

    print(f"[INFO] Found {len(info_tables)} infoTable entries")

    for info in info_tables:
        tag_ns = ""
        ns_m = re.match(r'\{(.+?)\}', info.tag)
        if ns_m:
            tag_ns = ns_m.group(1)

        def find_text(parent, tag, default=""):
            if tag_ns:
                elem = parent.find(f"{{{tag_ns}}}{tag}")
                if elem is not None and elem.text:
                    return elem.text.strip()
            elem = parent.find(tag)
            if elem is not None and elem.text:
                return elem.text.strip()
            for child in parent:
                local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if local.lower() == tag.lower():
                    return child.text.strip() if child.text else default
            return default

        def find_nested_text(parent, path, default=""):
            parts = path.split("/")
            current = parent
            for part in parts:
                found = None
                if tag_ns:
                    found = current.find(f"{{{tag_ns}}}{part}")
                if found is None:
                    found = current.find(part)
                if found is None:
                    for child in current:
                        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        if local.lower() == part.lower():
                            found = child
                            break
                if found is None:
                    return default
                current = found
            return current.text.strip() if current is not None and current.text else default

        name = find_text(info, "nameOfIssuer")
        title = find_text(info, "titleOfClass")
        cusip = find_text(info, "cusip")
        value_str = find_text(info, "value", "0")
        shares_str = find_nested_text(info, "shrsOrPrnAmt/sshPrnamt", "0")
        share_type = find_nested_text(info, "shrsOrPrnAmt/sshPrnamtType", "SH")

        try:
            value = int(value_str) * 1000
        except (ValueError, TypeError):
            value = 0
        try:
            shares = int(shares_str)
        except (ValueError, TypeError):
            shares = 0

        if name:
            holdings.append({
                "name": name,
                "title": title,
                "cusip": cusip,
                "value": value,
                "shares": shares,
                "share_type": share_type,
            })

    print(f"[INFO] Parsed {len(holdings)} holdings")
    return holdings


def cusip_to_ticker_lookup(holdings: list) -> dict:
    name_ticker = {
        "APPLE INC": "AAPL", "MICROSOFT CORP": "MSFT", "NVIDIA CORP": "NVDA",
        "AMAZON COM INC": "AMZN", "AMAZON.COM INC": "AMZN",
        "ALPHABET INC": "GOOGL", "META PLATFORMS INC": "META",
        "META PLATFORMS": "META",
        "TESLA INC": "TSLA", "BERKSHIRE HATHAWAY": "BRK-B",
        "JPMORGAN CHASE": "JPM", "VISA INC": "V",
        "UNITEDHEALTH GROUP": "UNH", "UNITEDHEALTH GRP": "UNH",
        "JOHNSON & JOHNSON": "JNJ", "JOHNSON &amp; JOHNSON": "JNJ",
        "EXXON MOBIL CORP": "XOM", "EXXON MOBIL": "XOM",
        "PROCTER & GAMBLE": "PG", "PROCTER &amp; GAMBLE": "PG",
        "MASTERCARD INC": "MA", "ELI LILLY & CO": "LLY",
        "ELI LILLY": "LLY",
        "BROADCOM INC": "AVGO", "HOME DEPOT INC": "HD",
        "HOME DEPOT": "HD",
        "CHEVRON CORP": "CVX", "ABBVIE INC": "ABBV",
        "MERCK & CO INC": "MRK", "MERCK & CO": "MRK",
        "COCA COLA CO": "KO", "COCA-COLA CO": "KO",
        "PEPSICO INC": "PEP", "COSTCO WHOLESALE": "COST",
        "PFIZER INC": "PFE", "WALMART INC": "WMT",
        "ORACLE CORP": "ORCL", "SALESFORCE INC": "CRM",
        "ADVANCED MICRO DEVICES": "AMD", "ADOBE INC": "ADBE",
        "INTEL CORP": "INTC", "CISCO SYSTEMS": "CSCO",
        "ACCENTURE PLC": "ACN", "NETFLIX INC": "NFLX",
        "WALT DISNEY CO": "DIS", "WALT DISNEY": "DIS",
        "CONOCOPHILLIPS": "COP",
        "BANK OF AMERICA": "BAC", "BANK AMER CORP": "BAC",
        "WELLS FARGO": "WFC",
        "AT&T INC": "T", "AT&AMP;T INC": "T",
        "VERIZON COMMUNICATIONS": "VZ", "VERIZON COMMUN": "VZ",
        "LINDE PLC": "LIN", "NEXTERA ENERGY": "NEE",
        "MCDONALDS CORP": "MCD",
        "THERMO FISHER": "TMO", "DANAHER CORP": "DHR",
        "SERVICENOW": "NOW", "INTUIT INC": "INTU",
        "TEXAS INSTRUMENTS": "TXN", "CATERPILLAR INC": "CAT",
        "BOOKING HOLDINGS": "BKNG",
    }

    mapping = {}
    for h in holdings:
        name_upper = h["name"].upper()
        for key, ticker in name_ticker.items():
            if key in name_upper:
                mapping[h["cusip"]] = ticker
                break
    return mapping


def build_top50(holdings: list, ticker_map: dict) -> list:
    merged = {}
    for h in holdings:
        cusip6 = h["cusip"][:6]
        if cusip6 in merged:
            merged[cusip6]["value"] += h["value"]
            merged[cusip6]["shares"] += h["shares"]
        else:
            merged[cusip6] = {
                "name": h["name"],
                "cusip": h["cusip"],
                "value": h["value"],
                "shares": h["shares"],
            }

    sorted_holdings = sorted(merged.values(), key=lambda x: x["value"], reverse=True)
    total_value = sum(h["value"] for h in sorted_holdings)

    top50 = []
    for i, h in enumerate(sorted_holdings[:50]):
        ticker = ticker_map.get(h["cusip"], "")
        sector = SECTOR_MAP.get(ticker, "Other")
        top50.append({
            "rank": i + 1,
            "name": h["name"],
            "ticker": ticker,
            "cusip": h["cusip"],
            "sector": sector,
            "shares": h["shares"],
            "value": h["value"],
            "weight": round(h["value"] / total_value * 100, 2) if total_value > 0 else 0,
        })

    return top50, total_value, len(sorted_holdings)


def compute_changes(current: list, previous: list) -> list:
    prev_map = {h["cusip"][:6]: h for h in previous}

    for h in current:
        cusip6 = h["cusip"][:6]
        prev = prev_map.get(cusip6)
        if prev is None:
            h["status"] = "new"
            h["change_shares"] = h["shares"]
            h["change_pct"] = 100.0
        else:
            diff = h["shares"] - prev.get("shares", 0)
            prev_shares = prev.get("shares", 1)
            pct = round(diff / prev_shares * 100, 1) if prev_shares > 0 else 0
            if diff > 0:
                h["status"] = "increased"
            elif diff < 0:
                h["status"] = "decreased"
            else:
                h["status"] = "unchanged"
            h["change_shares"] = diff
            h["change_pct"] = pct

    return current


def find_sold_positions(current: list, prev_all: list) -> list:
    current_cusips = {h["cusip"][:6] for h in current}
    sold = []
    for h in prev_all:
        if h["cusip"][:6] not in current_cusips:
            sold.append({
                "name": h["name"],
                "ticker": h.get("ticker", ""),
                "value": h["value"],
                "shares": h["shares"],
            })
    return sorted(sold, key=lambda x: x["value"], reverse=True)[:10]


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    filings = get_13f_filings()
    if len(filings) < 1:
        print("[ERROR] No 13F filings found")
        sys.exit(1)

    # 최신 filing부터 시도, 실패하면 다음 filing으로 (최대 3개)
    current_holdings = []
    current_filing = None
    for f in filings[:3]:
        print(f"\n[INFO] === Trying: {f['period']} (filed {f['filing_date']}) ===")
        holdings = parse_13f_xml(f["accession"])
        if holdings:
            current_holdings = holdings
            current_filing = f
            break
        else:
            print(f"[WARN] Filing {f['period']} failed, trying next...")

    if not current_holdings or not current_filing:
        print("[ERROR] Could not parse any recent 13F filing")
        sys.exit(1)

    print(f"\n[INFO] Using filing: {current_filing['period']}")

    ticker_map = cusip_to_ticker_lookup(current_holdings)
    current_top50, total_value, total_positions = build_top50(current_holdings, ticker_map)

    prev_top50 = []
    prev_all_holdings = []
    sold_positions = []

    # 현재 filing 이후의 filing에서 이전 분기 찾기
    current_idx = filings.index(current_filing)
    remaining = filings[current_idx + 1:]
    for f in remaining[:3]:
        print(f"\n[INFO] === Previous: {f['period']} (filed {f['filing_date']}) ===")
        prev_holdings = parse_13f_xml(f["accession"])
        if prev_holdings:
            prev_ticker_map = cusip_to_ticker_lookup(prev_holdings)
            prev_top50, prev_total, _ = build_top50(prev_holdings, prev_ticker_map)
            prev_all_holdings = prev_top50
            current_top50 = compute_changes(current_top50, prev_top50)
            sold_positions = find_sold_positions(current_top50, prev_top50)
            break
        else:
            print(f"[WARN] Previous filing {f['period']} failed, trying next...")

    current_data = {
        "filing_date": current_filing["filing_date"],
        "period": current_filing["period"],
        "total_value": total_value,
        "total_positions": total_positions,
        "top50_value": sum(h["value"] for h in current_top50),
        "top50": current_top50,
        "sold_positions": sold_positions,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }

    with open(os.path.join(OUTPUT_DIR, "holdings_current.json"), "w", encoding="utf-8") as f:
        json.dump(current_data, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] Saved holdings_current.json ({len(current_top50)} positions, total ${total_value:,.0f})")

    if prev_top50:
        prev_f = remaining[0] if remaining else filings[1]
        prev_data = {
            "filing_date": prev_f["filing_date"],
            "period": prev_f["period"],
            "total_value": prev_total,
            "top50": prev_top50,
        }
        with open(os.path.join(OUTPUT_DIR, "holdings_prev.json"), "w", encoding="utf-8") as f:
            json.dump(prev_data, f, ensure_ascii=False, indent=2)
        print(f"[OK] Saved holdings_prev.json")

    history_path = os.path.join(OUTPUT_DIR, "holdings_history.json")
    if os.path.exists(history_path):
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = []

    existing_periods = {h["period"] for h in history}
    if current_filing["period"] not in existing_periods:
        history.append({
            "period": current_filing["period"],
            "filing_date": current_filing["filing_date"],
            "total_value": total_value,
            "total_positions": total_positions,
            "top50_value": sum(h["value"] for h in current_top50),
        })
        history.sort(key=lambda x: x["period"])

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"[OK] Saved holdings_history.json ({len(history)} quarters)")

    print("\n[DONE] All data files updated successfully!")


if __name__ == "__main__":
    main()
