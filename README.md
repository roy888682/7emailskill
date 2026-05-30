# 📈 Daily ATH Stock Emailer

매일 **오전 7시(KST)** 에 미국(S&P 500) + 한국(KOSPI/KOSDAQ) 52주 신고가 종목을 이메일로 자동 발송하는 GitHub Actions 자동화.

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
| 실행 요일   | 월 ~ 금 (주말 제외)            |
| GitHub cron | `0 22 * * 0-4` (UTC 기준)     |

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
