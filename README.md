# 🏛️ NPS Portfolio Tracker (국민연금 포트폴리오 트래커)

국민연금(National Pension Service)의 투자 포트폴리오를 시각화하는 대시보드입니다.

## 📊 대시보드

| 대시보드 | 설명 | 데이터 소스 | 업데이트 |
|---------|------|-----------|---------|
| **[US 미국주식](/us/)** | 13F 기반 Top 50 보유종목, 섹터 비중, 매매동향 | SEC EDGAR (무료, 키 불필요) | 분기별 |
| **[KR 한국주식](/kr/)** | 자산배분, 대량보유종목(5%+), 수익률 | 공공데이터포털 + DART | 월별 |

## 🏗️ 프로젝트 구조

```
nps-portfolio/
├── us/                          # 미국 주식 대시보드
│   ├── index.html
│   └── data/
│       ├── holdings_current.json    # 최신 분기 Top 50
│       └── holdings_history.json    # 분기별 추이
├── kr/                          # 한국 주식 + 자산배분 대시보드
│   ├── index.html
│   └── data/
│       ├── asset_allocation.json    # 자산배분 현황
│       └── major_holdings.json      # 5%+ 대량보유 종목
├── scripts/
│   ├── fetch_sec_13f.py         # SEC EDGAR 수집
│   └── fetch_nps_kr.py          # 공공데이터포털/DART 수집
└── .github/workflows/
    ├── update_us.yml            # 분기별 자동 수집
    └── update_kr.yml            # 월별 자동 수집
```

## 🚀 시작하기

### 1. 미국 주식 (API 키 불필요)

```bash
# SEC EDGAR에서 데이터 수집
export SEC_USER_AGENT="YourApp your@email.com"
python scripts/fetch_sec_13f.py
```

### 2. 한국 주식 (무료 API 키 필요)

**API 키 발급:**
- 공공데이터포털: https://www.data.go.kr → 회원가입 → 활용신청
- DART OpenAPI: https://opendart.fss.or.kr → 회원가입 → 인증키 발급

```bash
export DATA_GO_KR_API_KEY="your_key_here"
export DART_API_KEY="your_key_here"
python scripts/fetch_nps_kr.py
```

### 3. GitHub Actions 설정

Repository Settings → Secrets and variables → Actions에 추가:
- `CONTACT_EMAIL` — SEC User-Agent용 이메일
- `DATA_GO_KR_API_KEY` — 공공데이터포털 API 키
- `DART_API_KEY` — DART API 키

### 4. GitHub Pages 활성화

Settings → Pages → Source: `main` branch, `/root` 폴더

## 🔗 HerdVibe 임베딩

```html
<!-- 미국 주식 페이지 -->
<iframe src="https://{username}.github.io/nps-portfolio/us/" 
        width="100%" height="2400" frameborder="0"></iframe>

<!-- 한국 주식 페이지 -->
<iframe src="https://{username}.github.io/nps-portfolio/kr/" 
        width="100%" height="2800" frameborder="0"></iframe>
```

## 📡 데이터 소스

| 소스 | API 키 | 비용 | 국민연금 CIK/ID |
|------|--------|------|----------------|
| SEC EDGAR REST API | 불필요 | 무료 | CIK: 0001608046 |
| 공공데이터포털 | 필요 | 무료 | - |
| DART OpenAPI | 필요 | 무료 | - |
| NPS 빅데이터포털 | 불필요 | 무료 (CSV) | - |

## ⚠️ 면책

본 대시보드는 정보 제공 목적으로만 제작되었으며, 투자 권유가 아닙니다.
데이터의 정확성을 보장하지 않으며, 투자 결정의 책임은 사용자에게 있습니다.

## 📄 License

MIT
