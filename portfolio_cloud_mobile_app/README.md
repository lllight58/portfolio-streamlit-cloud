# 클라우드 모바일 자산관리 앱

가장 쉬운 사용 방식은 Streamlit Cloud에 배포한 뒤, 모바일 브라우저에서 배포 주소를 열고 홈 화면에 추가하는 것입니다.
이렇게 하면 PC가 꺼져 있어도 모바일에서 앱에 접속할 수 있습니다.
데이터는 Supabase에 저장되므로 PC와 모바일이 같은 데이터를 봅니다.

## 1. 최종 구조

```text
Streamlit Cloud 앱
↓
Supabase PostgreSQL
↓
PC 브라우저 / 모바일 브라우저 / 홈 화면 추가 앱
```

PC가 서버 역할을 하지 않습니다. PC와 모바일은 같은 Streamlit Cloud 주소로 접속하고, 앱은 같은 Supabase DB를 읽고 씁니다.

## 2. 왜 192.168.x.x 주소는 불편한가

기존 로컬 방식:

```text
PC에서 Streamlit 실행
→ 휴대폰이 http://192.168.x.x:8502 로 접속
```

이 방식은 PC가 켜져 있어야 하고, PC와 휴대폰이 같은 Wi-Fi에 있어야 하며, 방화벽 문제도 생길 수 있습니다.

`http://192.168.x.x:8502` 방식은 보조적인 로컬 테스트용으로만 사용하세요. 실제 모바일 앱처럼 쓰려면 Streamlit Cloud 배포 주소를 홈 화면에 추가해서 사용하세요.

## 3. Streamlit Cloud에 배포하는 방법

필수 파일:

```text
portfolio_cloud_mobile_app/app.py
portfolio_cloud_mobile_app/requirements.txt
portfolio_cloud_mobile_app/.streamlit/config.toml
portfolio_cloud_mobile_app/README.md
```

배포 순서:

1. 이 폴더를 GitHub 저장소에 올립니다.
2. Streamlit Cloud에서 새 앱을 만듭니다.
3. Main file path를 다음으로 지정합니다.

```text
portfolio_cloud_mobile_app/app.py
```

4. Secrets에 Supabase 설정을 넣습니다.
5. 배포된 주소를 PC와 모바일에서 같이 사용합니다.

예:

```text
https://your-portfolio-app.streamlit.app
```

## 4. Secrets에 Supabase 설정 넣기

Streamlit Cloud에서는 `.env` 파일보다 Secrets를 사용합니다.

앱 설정 우선순위:

1. `st.secrets`
2. OS 환경변수
3. 로컬 `.env`

Supabase 연결은 `SUPABASE_POOLER_DATABASE_URL`을 먼저 사용하고, 없으면 `DATABASE_URL`을 사용합니다.

Streamlit Cloud의 App settings → Secrets에 다음 형식으로 입력합니다.

```toml
DATABASE_BACKEND = "supabase"
SUPABASE_POOLER_DATABASE_URL = "postgresql://postgres.<PROJECT_REF>:<DB_PASSWORD>@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres"
DATABASE_URL = "postgresql://postgres.<PROJECT_REF>:<DB_PASSWORD>@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres"
SUPABASE_DIRECT_DATABASE_URL = "postgresql://postgres:<DB_PASSWORD>@db.<PROJECT_REF>.supabase.co:5432/postgres"
SUPABASE_PROJECT_URL = "https://<PROJECT_REF>.supabase.co"
OPENAI_API_KEY = ""
OPENDART_API_KEY = ""
SEC_USER_AGENT = "Personal Portfolio Disclosure Tracker your_email@example.com"
```

배포 후 앱의 `설정` 메뉴에서 다음을 확인합니다.

```text
Supabase 연결 테스트
Supabase 테이블 생성/점검
```

## 5. 모바일에서 홈 화면에 추가하기

이 방식은 네이티브 앱은 아니지만, 사용자는 홈 화면에서 앱처럼 실행할 수 있습니다.

Android:

```text
1. Streamlit Cloud 배포 주소를 Chrome에서 연다.
2. 우측 상단 점 세 개 메뉴를 누른다.
3. 홈 화면에 추가 또는 앱 설치를 누른다.
4. 홈 화면 아이콘으로 실행한다.
```

iPhone:

```text
1. Streamlit Cloud 배포 주소를 Safari에서 연다.
2. 공유 버튼을 누른다.
3. 홈 화면에 추가를 누른다.
4. 홈 화면 아이콘으로 실행한다.
```

## 6. PC와 모바일 데이터 연동

```text
PC에서 자산 수정
→ Supabase 저장
→ 모바일 새로고침 후 반영

모바일에서 추가매수
→ Supabase 저장
→ PC 새로고침 후 반영
```

현재 방식은 실시간 자동 동기화가 아니라, 같은 Supabase DB를 공유하고 새로고침 후 반영되는 구조입니다.

## 7. 로컬 테스트 방법

로컬 테스트용 `run.bat`은 유지합니다.

```bat
cd portfolio_cloud_mobile_app
run.bat
```

`run.bat` 실행 명령:

```bat
streamlit run app.py --server.port 8502 --server.address 0.0.0.0
```

PC에서 확인:

```text
http://localhost:8502
```

휴대폰에서 로컬 테스트:

```text
http://192.168.x.x:8502
```

로컬 테스트 주소인 `http://192.168.x.x:8502` 방식은 PC가 켜져 있고 같은 Wi-Fi에 있을 때만 됩니다. 실제 모바일 앱처럼 쓰려면 Streamlit Cloud 배포 주소를 홈 화면에 추가해서 사용하세요.

## 모바일 UI

모바일 앱 모드는 앱처럼 쓰기 쉽게 구성되어 있습니다.

- 카드형 대시보드
- 홈, 자산, 매수, 원금, 공시, 설정 메뉴
- 큰 버튼
- 세로형 그래프
- 보유 종목 간략 표 + 상세보기
- 자산 입력 카드형 UI
- 추가매수 카드형 UI
- 투자원금 카드형 UI
- 그래프 터치 확대/줌 방지

PC에서 넓은 화면으로 작업하려면 상단에서 `PC 넓은 화면 모드`를 선택하면 됩니다.
