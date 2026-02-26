#!/usr/bin/env python3
"""
국민연금(National Pension Service) SEC EDGAR 13F Filing 수집 스크립트
- SEC EDGAR REST API (무료, 키 불필요)
- CIK: 0001608046
- 분기별 13F-HR filing에서 보유 종목 파싱
"""

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
USER_AGENT = os.environ.get("SEC_USER_AGENT", "NPS-Portfolio-Tracker admin@example.com")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "us", "data")

# 섹터 매핑 (CUSIP 기반 대략적 분류, 티커 기반으로 보완)
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
    """SEC EDGAR API 요청 (User-Agent 필수, rate limit 준수)"""
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    try:
        resp = urlopen(req, timeout=30)
        return resp.read()
    except HTTPError as e:
        print(f"[ERROR] HTTP {e.code} for {url}")
        raise
    finally:
        time.sleep(0.15)  # SEC rate limit: ~10 req/sec


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

    # 최신순 정렬
    filings.sort(key=lambda x: x["period"], reverse=True)
    print(f"[INFO] Found {len(filings)} 13F filings")
    return filings


def parse_13f_xml(accession: str) -> list:
    """13F filing의 information table XML 파싱"""
    acc_no_dash = accession.replace("-", "")
    # Filing index 페이지에서 infotable XML 찾기
    index_url = f"{BASE_URL}/Archives/edgar/data/{NPS_CIK.lstrip('0')}/{acc_no_dash}/index.json"
    print(f"[INFO] Fetching filing index: {index_url}")

    try:
        index_data = json.loads(sec_request(index_url))
    except Exception:
        # fallback: index.json이 없으면 직접 XML 경로 추정
        index_url = f"https://www.sec.gov/Archives/edgar/data/{NPS_CIK.lstrip('0')}/{acc_no_dash}/"
        print(f"[WARN] Trying alternative index: {index_url}")
        return []

    # infotable 파일 찾기
    xml_url = None
    for item in index_data.get("directory", {}).get("item", []):
        name = item.get("name", "").lower()
        if "infotable" in name and name.endswith(".xml"):
            xml_url = f"{BASE_URL}/Archives/edgar/data/{NPS_CIK.lstrip('0')}/{acc_no_dash}/{item['name']}"
            break

    if not xml_url:
        # primary doc이 XML인 경우도 있음
        for item in index_data.get("directory", {}).get("item", []):
            name = item.get("name", "").lower()
            if name.endswith(".xml") and "primary" not in name:
                xml_url = f"{BASE_URL}/Archives/edgar/data/{NPS_CIK.lstrip('0')}/{acc_no_dash}/{item['name']}"
                break

    if not xml_url:
        print("[WARN] Could not find infotable XML")
        return []

    print(f"[INFO] Parsing infotable: {xml_url}")
    xml_data = sec_request(xml_url)

    # XML 네임스페이스 처리
    ns = {"ns": "http://www.sec.gov/Archives/edgar/xbrl/13f/13fDocument"}
    root = ET.fromstring(xml_data)

    holdings = []
    for info in root.findall(".//ns:infoTable", ns):
        name = info.findtext("ns:nameOfIssuer", "", ns).strip()
        title = info.findtext("ns:titleOfClass", "", ns).strip()
        cusip = info.findtext("ns:cusip", "", ns).strip()
        value = info.findtext("ns:value", "0", ns).strip()
        shares_elem = info.find("ns:shrsOrPrnAmt/ns:sshPrnamt", ns)
        shares = shares_elem.text.strip() if shares_elem is not None else "0"
        share_type_elem = info.find("ns:shrsOrPrnAmt/ns:sshPrnamtType", ns)
        share_type = share_type_elem.text.strip() if share_type_elem is not None else "SH"

        holdings.append({
            "name": name,
            "title": title,
            "cusip": cusip,
            "value": int(value) * 1000,  # 13F value는 천 달러 단위
            "shares": int(shares),
            "share_type": share_type,
        })

    print(f"[INFO] Parsed {len(holdings)} holdings")
    return holdings


def cusip_to_ticker_lookup(holdings: list) -> dict:
    """
    CUSIP → 티커 매핑 (간단한 이름 기반 매핑)
    실제 운영 시 OpenFIGI API (무료) 활용 권장
    """
    name_ticker = {
        "APPLE INC": "AAPL", "MICROSOFT CORP": "MSFT", "NVIDIA CORP": "NVDA",
        "AMAZON COM INC": "AMZN", "AMAZON.COM INC": "AMZN",
        "ALPHABET INC": "GOOGL", "META PLATFORMS INC": "META",
        "TESLA INC": "TSLA", "BERKSHIRE HATHAWAY": "BRK-B",
        "JPMORGAN CHASE": "JPM", "VISA INC": "V",
        "UNITEDHEALTH GROUP": "UNH", "JOHNSON & JOHNSON": "JNJ",
        "EXXON MOBIL CORP": "XOM", "PROCTER & GAMBLE": "PG",
        "MASTERCARD INC": "MA", "ELI LILLY & CO": "LLY",
        "BROADCOM INC": "AVGO", "HOME DEPOT INC": "HD",
        "CHEVRON CORP": "CVX", "ABBVIE INC": "ABBV",
        "MERCK & CO INC": "MRK", "COCA COLA CO": "KO", "COCA-COLA CO": "KO",
        "PEPSICO INC": "PEP", "COSTCO WHOLESALE": "COST",
        "PFIZER INC": "PFE", "WALMART INC": "WMT",
        "ORACLE CORP": "ORCL", "SALESFORCE INC": "CRM",
        "ADVANCED MICRO DEVICES": "AMD", "ADOBE INC": "ADBE",
        "INTEL CORP": "INTC", "CISCO SYSTEMS": "CSCO",
        "ACCENTURE PLC": "ACN", "NETFLIX INC": "NFLX",
        "WALT DISNEY CO": "DIS", "CONOCOPHILLIPS": "COP",
        "BANK OF AMERICA": "BAC", "WELLS FARGO": "WFC",
        "AT&T INC": "T", "VERIZON COMMUNICATIONS": "VZ",
        "LINDE PLC": "LIN", "NEXTERA ENERGY": "NEE",
        "MCDONALDS CORP": "MCD",
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
    """보유금액 기준 Top 50 종목 추출"""
    # 같은 종목 합산 (여러 클래스 보유 가능)
    merged = {}
    for h in holdings:
        cusip6 = h["cusip"][:6]  # 같은 회사는 CUSIP 앞 6자리 동일
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

    # 정렬
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
    """현재 vs 이전 분기 비교하여 변동 계산"""
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
    """이전 분기에 있었지만 현재 없는 종목 (완전 매도)"""
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

    # 1. Filing 목록 조회
    filings = get_13f_filings()
    if len(filings) < 1:
        print("[ERROR] No 13F filings found")
        sys.exit(1)

    # 2. 최신 + 직전 분기 파싱
    current_filing = filings[0]
    print(f"\n[INFO] === Current: {current_filing['period']} (filed {current_filing['filing_date']}) ===")
    current_holdings = parse_13f_xml(current_filing["accession"])
    ticker_map = cusip_to_ticker_lookup(current_holdings)
    current_top50, total_value, total_positions = build_top50(current_holdings, ticker_map)

    prev_top50 = []
    prev_all_holdings = []
    sold_positions = []

    if len(filings) >= 2:
        prev_filing = filings[1]
        print(f"\n[INFO] === Previous: {prev_filing['period']} (filed {prev_filing['filing_date']}) ===")
        prev_holdings = parse_13f_xml(prev_filing["accession"])
        prev_ticker_map = cusip_to_ticker_lookup(prev_holdings)
        prev_top50, prev_total, _ = build_top50(prev_holdings, prev_ticker_map)
        prev_all_holdings = prev_top50

        # 변동 계산
        current_top50 = compute_changes(current_top50, prev_top50)
        sold_positions = find_sold_positions(current_top50, prev_top50)

    # 3. JSON 저장 — holdings_current.json
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
    print(f"\n[OK] Saved holdings_current.json ({len(current_top50)} positions)")

    # 4. JSON 저장 — holdings_prev.json
    if prev_top50:
        prev_data = {
            "filing_date": filings[1]["filing_date"],
            "period": filings[1]["period"],
            "total_value": prev_total,
            "top50": prev_top50,
        }
        with open(os.path.join(OUTPUT_DIR, "holdings_prev.json"), "w", encoding="utf-8") as f:
            json.dump(prev_data, f, ensure_ascii=False, indent=2)
        print(f"[OK] Saved holdings_prev.json")

    # 5. 히스토리 업데이트 — holdings_history.json
    history_path = os.path.join(OUTPUT_DIR, "holdings_history.json")
    if os.path.exists(history_path):
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = []

    # 중복 방지
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
