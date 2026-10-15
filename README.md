# 📈 Daily ATH Stock Emailer

월~금 미국(S&P 500)·한국(KOSPI/KOSDAQ) 장 결과의 52주 신고가 종목을 **화~토요일 오전 7시(KST)**에 이메일로 자동 발송하는 GitHub Actions 자동화입니다. 일요일과 월요일에는 예약 발송하지 않습니다.

---

## 📁 파일 구조

```
daily-ath-emailer/
├── .github/
│   └── workflows/
│       └── daily_ath_email.yml   ← GitHub Actions 스케줄러
├── src/
│   └── main.py                   ← 핵심 Python 스크립트
├── requirements.txt
└── README.md
```

---

## 🚀 설정 방법 (4단계)

### STEP 1 — 이 저장소를 GitHub에 올리기

```bash
# 새 GitHub 저장소 생성 후:
git init
git add .
git commit -m "init: daily ATH emailer"
git remote add origin https://github.com/YOUR_USERNAME/daily-ath-emailer.git
git push -u origin main
```

---

### STEP 2 — Gmail 앱 비밀번호 발급

> 일반 Gmail 비밀번호가 아닌 **앱 비밀번호** 를 사용해야 함.

1. [Google 계정 보안 설정](https://myaccount.google.com/security) 접속
2. **2단계 인증** 활성화 (이미 된 경우 스킵)
3. **앱 비밀번호** 메뉴 접속
4. 앱: `메일`, 기기: `기타(직접 입력)` → `ATH Emailer` 입력
5. 생성된 **16자리 비밀번호** 복사해 보관

---

### STEP 3 — GitHub Secrets 등록

GitHub 저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| Secret 이름          | 값 예시                          | 설명                   |
|---------------------|----------------------------------|------------------------|
| `GMAIL_USER`        | `yourname@gmail.com`             | 발신 Gmail 주소        |
| `GMAIL_APP_PASSWORD`| `abcd efgh ijkl mnop`            | STEP 2에서 발급한 앱 비밀번호 |
| `RECIPIENT_EMAIL`   | `ykhan@dacpole.com`              | 수신 이메일 주소       |

---

### STEP 4 — GitHub Actions 활성화

1. 저장소 상단 **Actions** 탭 클릭
2. `I understand my workflows, go ahead and enable them` 클릭
3. 왼쪽 `📈 Daily ATH Stock Email` 선택
4. **Run workflow** 버튼으로 즉시 테스트 실행 가능

---

## ⏰ 실행 스케줄

| 항목        | 내용                           |
|------------|-------------------------------|
| 실행 시각   | 매일 오전 7:00 KST             |
| 실행 요일   | 화 ~ 토 (일·월요일 발송 없음, 휴장일에는 최근 거래일 기준) |
| GitHub cron | `0 22 * * 1-5` (UTC 월~금 → KST 화~토) |

GitHub Actions 예약은 화~토요일 오전 7시(KST) 실행을 요청합니다. 월요일 장 결과는 화요일 아침, 금요일 장 결과는 토요일 아침에 발송합니다. 일요일과 월요일에는 예약 발송하지 않습니다. GitHub 실행 대기열에 따라 시작과 이메일 도착이 늦어질 수 있으며 정확한 시각의 배달을 보장하지는 않습니다.

종목 수가 많아 본문이 길어져도 모든 종목을 그대로 발송합니다. Gmail에서 본문 끝이 접힐 가능성이 있는 큰 리포트에는 국기와 전체 표를 포함한 `ath-full-report.html` 파일을 함께 첨부합니다. 본문 크기만으로 발송을 중단하거나 종목을 삭제하지 않습니다. 데이터·링크·글꼴 검증과 실제 SMTP 용량 제한은 계속 적용합니다.

---

## 📊 데이터 기준

| 항목           | 내용                                      |
|---------------|------------------------------------------|
| US 종목 범위   | S&P 500 전체 (~500종목)                   |
| KR 종목 범위   | KOSPI/KOSDAQ 시총 상위 200종목씩           |
| ATH 정의       | 52주 고가 대비 현재가 ≥ 99.5%             |
| 데이터 소스    | yfinance (미국), FinanceDataReader (한국)  |

---

## 🛠 로컬 테스트

```bash
pip install -r requirements.txt

export GMAIL_USER="yourname@gmail.com"
export GMAIL_APP_PASSWORD="your-app-password"
export RECIPIENT_EMAIL="ykhan@dacpole.com"

python src/main.py
```

---

## ❓ 자주 발생하는 오류

| 오류 메시지                       | 원인 & 해결                                      |
|----------------------------------|------------------------------------------------|
| `SMTPAuthenticationError`        | 앱 비밀번호 오류 → STEP 2 재발급                  |
| `No module named 'yfinance'`     | `pip install -r requirements.txt` 재실행         |
| 이메일은 왔는데 종목 0개          | 주말 또는 공휴일로 시장 데이터 없음 (정상)         |
| Actions 탭에 워크플로우 안 보임   | STEP 4의 활성화 버튼 클릭 필요                    |


종목 수는 상단 한국·미국 합계, 신규 등장 한국·미국 합계, 국가별 표 설명에 `한국 11종목( 4종목 주식, 7종목 ETF )` 형식으로 표시합니다. 주식·ETF 구분은 각 목록의 실제 종목 유형에서 매번 계산하며, 신규 등장 수는 신규 목록만 별도로 집계합니다.

긴 종목명은 현재 글자 크기를 유지하며 한 줄 말줄임표(`…`)로 표시합니다. ETF 비교 표에는 누적수익률 오른쪽에 **연평균 누적수익률**, 설립일 오른쪽에 계산에 사용한 **누적연수**를 표시합니다. 연평균 누적수익률은 `[(1 + 누적수익률/100)^(1/누적연수) - 1] × 100`으로 계산하고, 반올림 전 값의 오름차순으로 최대 20개를 표시합니다. 누적연수는 유효한 설립일부터 최신 주가 기준일까지의 실제 일수 ÷ 365.25이며, 설립일이 없으면 최초 거래일을 사용합니다. 누적수익률의 가격 이력은 최초 수집 가능한 종가부터이며 한국은 분배금 미반영, 미국은 배당 재투자 반영 수정주가 기준입니다.
