# SETUP — Google Drive 업로드 세팅 가이드

이 문서는 **GitHub Actions → Google Drive 자동 업로드** 파이프라인을 활성화하기 위한 1회성 세팅 가이드입니다. 순서대로 따라하면 약 15–20분 소요됩니다.

---

## 전체 흐름

```
[1] Google Cloud 프로젝트 만들기
[2] Drive API 활성화
[3] 서비스 계정 생성 + JSON 키 다운로드
[4] Google Drive에 전용 폴더 만들기 + 서비스 계정에 공유
[5] 폴더 ID 확인
[6] GitHub Secrets에 2개 값 등록
[7] 워크플로우 수동 실행으로 검증
```

---

## [1] Google Cloud 프로젝트 만들기

1. 브라우저에서 <https://console.cloud.google.com/> 접속 (본인 Google 계정으로 로그인)
2. 상단 좌측 프로젝트 선택 드롭다운 클릭 → **「새 프로젝트」** 버튼
3. 프로젝트 이름: `morning-report` (또는 원하는 이름) → **만들기**
4. 생성 후 상단 드롭다운에서 이 프로젝트가 선택된 상태인지 확인

> 📸 **[스크린샷 포인트]** 프로젝트 드롭다운에 방금 만든 프로젝트명이 표시되는지 확인.

---

## [2] Drive API 활성화

1. 좌측 햄버거 메뉴 → **API 및 서비스** → **라이브러리**
2. 검색창에 `Google Drive API` 입력 → 결과 클릭
3. **사용 설정(Enable)** 버튼 클릭
4. 「API가 사용 설정됨」 문구 확인

> 📸 **[스크린샷 포인트]** "API 사용 설정됨" 상태 페이지.

---

## [3] 서비스 계정 생성 + JSON 키 다운로드

### 3-1. 서비스 계정 만들기

1. 좌측 메뉴 → **API 및 서비스** → **사용자 인증 정보(Credentials)**
2. 상단 **「사용자 인증 정보 만들기」** → **「서비스 계정」**
3. 서비스 계정 이름: `morning-report-uploader` (아무거나)
4. 서비스 계정 ID: 자동 입력됨 (예: `morning-report-uploader`)
5. **만들고 계속하기**
6. 역할(Role): **건너뛰기** (폴더 단위 공유로 권한 부여할 것이므로 프로젝트 전체 역할 불필요)
7. **완료**

### 3-2. 서비스 계정 이메일 복사

생성된 서비스 계정 목록에서 방금 만든 계정을 클릭하면 이메일이 보입니다:

```
morning-report-uploader@<프로젝트ID>.iam.gserviceaccount.com
```

**⚠️ 이 이메일을 메모장에 복사해두세요.** 뒤에서 Drive 폴더 공유 시 필요합니다.

### 3-3. JSON 키 발급

1. 서비스 계정 상세 페이지 → 상단 **「키(KEYS)」** 탭
2. **「키 추가」** → **「새 키 만들기」**
3. 키 유형: **JSON** 선택 → **만들기**
4. JSON 파일이 자동 다운로드됨 (예: `morning-report-abc123.json`)

> ⚠️ **이 JSON 파일은 비밀번호와 동급입니다.** 절대 GitHub에 올리거나 타인에게 공유 금지. 지금 당장은 로컬에만 보관.

> 📸 **[스크린샷 포인트]** 키 목록에 방금 만든 JSON 키가 표시되는지 확인.

---

## [4] Google Drive에 전용 폴더 만들기 + 서비스 계정에 공유

1. 브라우저에서 <https://drive.google.com> 접속 (본인 Google 계정)
2. 빈 공간 우클릭 → **새 폴더** → 이름: `ClaudeMorningData` → 만들기
3. 만든 폴더를 **우클릭 → 공유**
4. 공유 대화상자에서 **3-2에서 복사한 서비스 계정 이메일** 입력
5. 권한: **편집자(Editor)** 선택
6. **「알림 보내기」 체크 해제** (로봇 계정이므로 불필요, 실제로는 에러남)
7. **보내기** 또는 **완료**

> 📸 **[스크린샷 포인트]** 공유 대상에 서비스 계정 이메일 + "편집자" 역할이 들어가 있는지 확인.

---

## [5] 폴더 ID 확인

1. `ClaudeMorningData` 폴더를 **더블클릭으로 열기**
2. 브라우저 주소창 URL 확인:

   ```
   https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz123456
                                          └────────── 폴더 ID ──────────┘
   ```

3. `folders/` 뒤의 문자열이 **폴더 ID** 입니다. 복사해두세요.

---

## [6] GitHub Secrets 등록

1. GitHub에서 `gengar200005/morning-report` 레포 열기
2. **Settings** 탭 → 좌측 **Secrets and variables** → **Actions**
3. **New repository secret** 버튼

### Secret 1: `GDRIVE_SERVICE_ACCOUNT_JSON`

- Name: `GDRIVE_SERVICE_ACCOUNT_JSON`
- Secret: **3-3에서 다운로드한 JSON 파일의 전체 내용을 그대로 붙여넣기**
  - 메모장/VS Code로 열어 **Ctrl+A → Ctrl+C → 붙여넣기**
  - 중괄호 `{` 부터 `}` 까지 전체
- **Add secret**

### Secret 2: `GDRIVE_FOLDER_ID`

- Name: `GDRIVE_FOLDER_ID`
- Secret: **5단계에서 복사한 폴더 ID** (예: `1AbCdEfGhIjKlMnOpQrStUvWxYz123456`)
- **Add secret**

> 📸 **[스크린샷 포인트]** Secrets 목록에 `GDRIVE_SERVICE_ACCOUNT_JSON`, `GDRIVE_FOLDER_ID` 2개가 보이면 성공.

---

## [7] 워크플로우 수동 실행으로 검증

1. 레포 **Actions** 탭 → 좌측 **모닝 리포트** 워크플로우 선택
2. 우측 **Run workflow** 버튼 → **Run workflow** 확정
3. 약 2–5분 대기 후 실행 로그 확인
4. `데이터 통합 (…)` 스텝 로그에서 다음 메시지 찾기:

   ```
   ✅ Drive 업로드 완료: morning_data.txt (id=...)
   ✅ Drive 업로드 완료: morning_data_YYYYMMDD.txt (id=...)
   ```

5. Drive 폴더 `ClaudeMorningData`에 두 파일이 있는지 브라우저에서 직접 확인.

실패 시 로그의 `❌` 메시지를 확인하고 Secrets 오타, 폴더 공유 누락 여부 점검.

---

## [8] Claude.ai 연결 (최종 단계)

1. <https://claude.ai/> 접속 → 본인 Google 계정으로 Drive 커넥터 연결 (이미 되어있으면 패스)
2. 해당 모닝리포트용 **프로젝트(Project)** 로 이동
3. 프로젝트 시스템 프롬프트(Instructions)에 `claude_project_prompt.md` 내용 붙여넣기
4. 채팅창에서 **「모닝리포트」** 입력 → 파일이 읽히는지 확인

---

## 트러블슈팅

| 증상 | 원인·조치 |
|---|---|
| `File not found: <folder_id>` | Drive 폴더를 서비스 계정에 공유 안 함 → [4] 재확인 |
| `HttpError 403 … insufficientPermissions` | 권한이 "뷰어"로 되어 있음 → "편집자"로 변경 |
| `JSONDecodeError` | Secret 붙여넣기 시 앞뒤 따옴표 섞여 들어감 → JSON 원본 그대로 붙여넣기 |
| Claude가 파일 못 찾음 | 커넥터 검색은 인덱싱 지연 수 분 있을 수 있음. 2–3분 후 재시도 |
| 토/일요일 생성 안 됨 | 원래 cron이 `0-4`(월–금)로 설정됨. 정상 동작. |
