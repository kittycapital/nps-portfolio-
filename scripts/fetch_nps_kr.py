#!/usr/bin/env python3
"""
국민연금 한국 데이터 수집 스크립트
- 공공데이터포털: 기금 포트폴리오 현황, 대량보유주식
- DART OpenAPI: 대량보유 공시 (보완용)

필요 환경변수:
  DATA_GO_KR_API_KEY  - 공공데이터포털 API 키 (무료 발급)
  DART_API_KEY        - DART OpenAPI 키 (무료 발급)
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote_plus
from urllib.error import HTTPError

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "kr", "data")

DATA_GO_KR_KEY = os.environ.get("DATA_GO_KR_API_KEY", "")
DART_KEY = os.environ.get("DART_API_KEY", "")


def api_request(url: str, timeout: int = 30) -> dict:
    """Generic API request with retry"""
    for attempt in range(3):
        try:
            req = Request(url, headers={"Accept": "application/json"})
            resp = urlopen(req, timeout=timeout)
            data = json.loads(resp.read())
            return data
        except HTTPError as e:
            print(f"  [WARN] HTTP {e.code}, attempt {attempt + 1}/3")
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            print(f"  [WARN] {e}, attempt {attempt + 1}/3")
            time.sleep(2 * (attempt + 1))
    return {}


def fetch_portfolio_from_data_go_kr():
    """
    공공데이터포털 - 국민연금공단_기금 포트폴리오 현황
    API: https://www.data.go.kr/data/15106894/fileData.do
    """
    if not DATA_GO_KR_KEY:
        print("[SKIP] DATA_GO_KR_API_KEY not set, using existing data")
        return None

    print("[INFO] Fetching portfolio from data.go.kr...")
    base = "https://api.odcloud.kr/api/15106894/v1/uddi:954db54e-6079-4e89-a32e-1dbf776f3958"
    params = {
        "serviceKey": DATA_GO_KR_KEY,
        "page": 1,
        "perPage": 100,
    }
    url = f"{base}?{urlencode(params, quote_via=quote_plus)}"
    data = api_request(url)

    if not data or "data" not in data:
        print("[WARN] No portfolio data returned")
        return None

    records = data["data"]
    print(f"[INFO] Got {len(records)} portfolio records")
    return records


def fetch_major_holdings_from_data_go_kr():
    """
    공공데이터포털 - 국민연금공단_대량보유주식 보고내역
    API: https://www.data.go.kr/data/15106890/fileData.do
    """
    if not DATA_GO_KR_KEY:
        print("[SKIP] DATA_GO_KR_API_KEY not set")
        return None

    print("[INFO] Fetching major holdings from data.go.kr...")
    base = "https://api.odcloud.kr/api/15106890/v1/uddi:07a0c48f-5c5f-4640-90ed-0f3042e7c98a"
    params = {
        "serviceKey": DATA_GO_KR_KEY,
        "page": 1,
        "perPage": 500,
    }
    url = f"{base}?{urlencode(params, quote_via=quote_plus)}"
    data = api_request(url)

    if not data or "data" not in data:
        print("[WARN] No holdings data returned")
        return None

    records = data["data"]
    print(f"[INFO] Got {len(records)} holdings records")
    return records


def fetch_dart_major_holdings():
    """
    DART OpenAPI - 대량보유 보고 현황
    https://opendart.fss.or.kr/
    """
    if not DART_KEY:
        print("[SKIP] DART_API_KEY not set")
        return None

    print("[INFO] Fetching from DART OpenAPI...")
    # DART의 대량보유 현황 조회
    # 국민연금 고유번호 조회 필요 - 여기서는 기본 구조만 작성
    base = "https://opendart.fss.or.kr/api/majorstock.json"
    params = {
        "crtfc_key": DART_KEY,
        # corp_code는 각 종목별로 조회 필요
    }
    print("[INFO] DART API requires per-company queries, skipping bulk fetch")
    return None


def update_asset_allocation(records):
    """공공데이터포털 포트폴리오 데이터를 JSON 포맷으로 변환"""
    alloc_path = os.path.join(OUTPUT_DIR, "asset_allocation.json")

    # 기존 데이터 로드
    if os.path.exists(alloc_path):
        with open(alloc_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = {"monthly_history": [], "yearly_total": []}

    if records:
        # 공공데이터포털 레코드 구조에 맞게 파싱
        # (실제 API 응답 구조에 따라 필드명 조정 필요)
        print(f"[INFO] Processing {len(records)} portfolio records")
        # TODO: 실제 API 응답 구조에 맞게 파싱 로직 구현
        # 현재는 수동으로 업데이트하거나 CSV 다운로드 후 변환

    existing["updated_at"] = datetime.utcnow().isoformat() + "Z"

    with open(alloc_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"[OK] Saved asset_allocation.json")


def update_major_holdings(records):
    """대량보유 데이터를 JSON 포맷으로 변환"""
    path = os.path.join(OUTPUT_DIR, "major_holdings.json")

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = {"holdings": []}

    if records:
        print(f"[INFO] Processing {len(records)} holdings records")
        # TODO: 실제 API 응답 구조에 맞게 파싱 로직 구현

    existing["updated_at"] = datetime.utcnow().isoformat() + "Z"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"[OK] Saved major_holdings.json")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 50)
    print("국민연금 한국 데이터 수집 시작")
    print("=" * 50)

    # 1. 포트폴리오 현황
    portfolio_records = fetch_portfolio_from_data_go_kr()
    update_asset_allocation(portfolio_records)

    # 2. 대량보유 주식
    holdings_records = fetch_major_holdings_from_data_go_kr()
    update_major_holdings(holdings_records)

    # 3. DART 보완 (선택적)
    fetch_dart_major_holdings()

    print("\n[DONE] All KR data files updated!")
    print("─" * 50)
    print("NOTE: 공공데이터포털 API 응답 구조가 변경될 수 있으므로")
    print("      첫 실행 시 응답 구조를 확인하고 파싱 로직을 조정하세요.")
    print("      API 키가 없으면 기존 데이터를 유지합니다.")


if __name__ == "__main__":
    main()
