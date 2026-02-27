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

# NPS 미국 주식 포트폴리오 합리적 범위 (달러)
# $1B ~ $500B 사이가 정상, $1T 이상이면 *1000 오류
SANITY_MAX = 1_000_000_000_000  # $1 trillion

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
            print(f"[INFO] Fallback to www.sec.gov")
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

    xml_url = None

    # 방법 1: index.json 시도
    index_url = f"{filing_base}/index.json"
    print(f"[INFO] Trying index.json...")
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
    except Exception:
        print(f"[INFO] index.json not available, trying HTML index...")

    # 방법 2: HTML index 페이지 파싱
    if not xml_url:
        index_htm_url = f"{ALT_URL}/Archives/edgar/data/{cik_num}/{acc_no_dash}/"
        try:
            html_data = sec_request(index_htm_url).decode("utf-8", errors="replace")
            xml_matches = re.findall(r'href="([^"]*\.xml)"', html_data, re.IGNORECASE)
            for m in xml_matches:
                fname = m.split("/")[-1]
                if "primary" not in fname.lower() and fname.lower() != "r.xml":
                    xml_url = f"{filing_base}/{fname}"
                    print(f"[INFO] Found XML from HTML index: {fname}")
                    break
        except Exception:
            print(f"[WARN] HTML index also failed")

    # 방법 3: 일반적인 파일명 직접 시도
    if not xml_url:
        common_names = ["infotable.xml", "INFOTABLE.XML", "InfoTable.xml"]
        for fname in common_names:
            test_url = f"{filing_base}/{fname}"
            try:
                test_data = sec_request(test_url)
                if test_data and len(test_data) > 100:
                    xml_url = test_url
                    break
            except Exception:
                continue

    if not xml_url:
        print("[WARN] Could not find infotable XML")
        return []

    # XML 다운로드 (data.sec.gov 실패 시 www.sec.gov로 재시도)
    print(f"[INFO] Downloading infotable XML...")
    try:
        xml_data = sec_request_with_fallback(xml_url)
    except Exception:
        print(f"[WARN] Could not download XML")
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
            value = int(value_str)
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
                "value_raw": value,  # 원본 값 (천 달러 단위일 수 있음)
                "shares": shares,
                "share_type": share_type,
            })

    # 13F value는 보통 천 달러(thousands) 단위
    # 전체 합산 후 sanity check: $1T 넘으면 이미 달러 단위로 간주
    raw_total = sum(h["value_raw"] for h in holdings)
    raw_total_x1000 = raw_total * 1000

    if raw_total_x1000 > SANITY_MAX:
        # 값이 이미 달러 단위 (곱하면 비정상적으로 큼)
        multiplier = 1
        print(f"[INFO] Values appear to be in dollars (raw total: ${raw_total:,.0f})")
    else:
        # 표준 13F: 천 달러 단위 → 달러로 변환
        multiplier = 1000
        print(f"[INFO] Values in thousands, converting (raw total: ${raw_total:,} x1000)")

    for h in holdings:
        h["value"] = h["value_raw"] * multiplier
        del h["value_raw"]

    print(f"[INFO] Parsed {len(holdings)} holdings (total: ${sum(h['value'] for h in holdings):,.0f})")
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
    prev_total = 0

    # 현재 filing 이후의 filing에서 이전 분기 찾기
    current_idx = filings.index(current_filing)
    remaining = filings[current_idx + 1:]
    prev_filing_used = None
    for f in remaining[:3]:
        print(f"\n[INFO] === Previous: {f['period']} (filed {f['filing_date']}) ===")
        prev_holdings = parse_13f_xml(f["accession"])
        if prev_holdings:
            prev_ticker_map = cusip_to_ticker_lookup(prev_holdings)
            prev_top50, prev_total, _ = build_top50(prev_holdings, prev_ticker_map)
            prev_all_holdings = prev_top50
            current_top50 = compute_changes(current_top50, prev_top50)
            sold_positions = find_sold_positions(current_top50, prev_top50)
            prev_filing_used = f
            break
        else:
            print(f"[WARN] Previous filing {f['period']} failed, trying next...")

    # current 데이터 sanity check
    if total_value > SANITY_MAX:
        print(f"[FIX] Current total_value ${total_value:,} > $1T, dividing by 1000")
        total_value = total_value // 1000
        for h in current_top50:
            h["value"] = h["value"] // 1000
            h["weight"] = round(h["value"] / total_value * 100, 2) if total_value > 0 else 0

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

    if prev_top50 and prev_filing_used:
        prev_data = {
            "filing_date": prev_filing_used["filing_date"],
            "period": prev_filing_used["period"],
            "total_value": prev_total,
            "top50": prev_top50,
        }
        with open(os.path.join(OUTPUT_DIR, "holdings_prev.json"), "w", encoding="utf-8") as f:
            json.dump(prev_data, f, ensure_ascii=False, indent=2)
        print(f"[OK] Saved holdings_prev.json")

    # ─── 히스토리: 전체 filing을 다시 파싱하여 정확한 값으로 빌드 ───
    history_path = os.path.join(OUTPUT_DIR, "holdings_history.json")
    history = []
    seen_periods = set()

    # 현재 분기는 이미 파싱했으므로 바로 추가
    history.append({
        "period": current_filing["period"],
        "filing_date": current_filing["filing_date"],
        "total_value": total_value,
        "total_positions": total_positions,
        "top50_value": sum(h["value"] for h in current_top50),
    })
    seen_periods.add(current_filing["period"])

    # 나머지 filing들도 파싱 (최대 12개 분기 = 3년)
    for f in filings:
        if f["period"] in seen_periods:
            continue
        if len(history) >= 12:
            break
        print(f"\n[INFO] === History: {f['period']} (filed {f['filing_date']}) ===")
        try:
            h_holdings = parse_13f_xml(f["accession"])
            if h_holdings:
                h_merged = {}
                for h in h_holdings:
                    c6 = h["cusip"][:6]
                    if c6 in h_merged:
                        h_merged[c6]["value"] += h["value"]
                    else:
                        h_merged[c6] = {"value": h["value"]}
                h_total = sum(v["value"] for v in h_merged.values())
                h_positions = len(h_merged)
                h_top50_val = sum(v["value"] for v in sorted(h_merged.values(), key=lambda x: x["value"], reverse=True)[:50])
                history.append({
                    "period": f["period"],
                    "filing_date": f["filing_date"],
                    "total_value": h_total,
                    "total_positions": h_positions,
                    "top50_value": h_top50_val,
                })
                seen_periods.add(f["period"])
                print(f"[OK] History {f['period']}: ${h_total:,.0f} ({h_positions} positions)")
            else:
                print(f"[WARN] History {f['period']}: parse failed, skipping")
        except Exception as e:
            print(f"[WARN] History {f['period']}: error {e}, skipping")

    history.sort(key=lambda x: x["period"])

    # 최종 sanity check: $1T 넘는 값은 1000으로 나누기
    for entry in history:
        if entry["total_value"] > SANITY_MAX:
            old = entry["total_value"]
            entry["total_value"] = entry["total_value"] // 1000
            entry["top50_value"] = entry.get("top50_value", 0) // 1000
            print(f"[FIX] History {entry['period']}: ${old:,} → ${entry['total_value']:,} (÷1000)")

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] Saved holdings_history.json ({len(history)} quarters, fully rebuilt)")

    print("\n[DONE] All data files updated successfully!")


if __name__ == "__main__":
    main()
