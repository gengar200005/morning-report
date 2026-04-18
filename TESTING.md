# TESTING — 파이프라인 검증 절차

`SETUP.md` 완료 후 다음 순서로 전체 파이프라인 동작을 검증합니다.

---

## 단계 1: GitHub Actions 수동 실행

- [ ] 레포 **Actions** 탭 → **모닝 리포트** 워크플로우 선택
- [ ] 우측 **Run workflow** → 브랜치 `main` → **Run workflow**
- [ ] 실행 시작까지 약 10초 대기, 이후 2–5분 소요

## 단계 2: 로그 확인

실행된 job 클릭 → `데이터 통합 (…)` 스텝 펼쳐서 로그 확인.

### ✅ 성공 시 나와야 하는 로그

```
✅ morning_data.txt 저장 완료 (XXXX chars)
✅ public 레포 저장 완료
   Raw URL: https://raw.githubusercontent.com/gengar200005/morning-data/main/morning_data.txt
✅ morning_data_YYYYMMDD.txt 저장 완료
✅ YYYY/MM/morning_data_YYYYMMDD.txt 저장 완료
✅ Drive 업로드 완료: morning_data.txt (id=...)
✅ Drive 업로드 완료: morning_data_YYYYMMDD.txt (id=...)
```

### ⚠️ 실패 패턴과 조치

- [ ] `⚠️  GDRIVE_FOLDER_ID 또는 GDRIVE_SERVICE_ACCOUNT_JSON 미설정` → Secrets 누락. `SETUP.md` [6] 재확인.
- [ ] `❌ Drive 업로드 실패 (…): HttpError 404` → 폴더 ID 오타 또는 공유 누락. `SETUP.md` [4][5] 재확인.
- [ ] `❌ Drive 업로드 실패 (…): HttpError 403 … insufficientPermissions` → 공유 권한이 "뷰어". "편집자"로 변경.
- [ ] `❌ Drive 업로드 중 예외: JSONDecodeError` → JSON Secret 값에 이상한 문자 섞임. 원본 파일 내용을 그대로 재등록.

## 단계 3: Drive 확인

- [ ] 브라우저에서 `ClaudeMorningData` 폴더 열기
- [ ] `morning_data.txt` 파일 존재 확인
- [ ] `morning_data_YYYYMMDD.txt` (오늘 날짜) 파일 존재 확인
- [ ] 각 파일 열어서 내용이 비어있지 않고 미장/국장/섹터/매크로 섹션이 모두 있는지 확인

## 단계 4: 같은 날 재실행(덮어쓰기) 검증

- [ ] 10분 내 **Run workflow** 한 번 더 실행
- [ ] Drive에서 `morning_data_YYYYMMDD.txt`가 **중복 생성되지 않고** 하나만 있는지 확인
- [ ] 파일 상세 정보에서 "수정 시간"이 방금 시각으로 갱신되었는지 확인

## 단계 5: Claude.ai 커넥터 연동

- [ ] <https://claude.ai/> 로그인
- [ ] 설정 → Connectors → **Google Drive**가 연결되어 있는지 확인
- [ ] 본인 Google 계정(Drive 소유자)과 동일 계정으로 연결되어 있어야 함

## 단계 6: 프로젝트 시스템 프롬프트 적용

- [ ] 모닝리포트용 Project 열기 → Project instructions 수정
- [ ] `claude_project_prompt.md` 내용 전체 복사 → 붙여넣기 → 저장

## 단계 7: 최종 End-to-End 테스트

- [ ] 프로젝트 새 대화 시작
- [ ] 채팅창에 **`모닝리포트`** 입력 후 전송
- [ ] Claude가 Drive 검색 도구를 호출하고 오늘자 파일을 읽어오는지 관찰
- [ ] 리포트 결과에 오늘 날짜가 포함되어 있는지 확인
- [ ] 미장/국장/섹터/매크로 섹션이 모두 반영되었는지 확인

## 단계 8: 주말·휴일 동작 확인 (선택)

- [ ] 토요일 오전 "모닝리포트" 입력 → 금요일자(가장 최신) 파일 사용 + Claude가 **"오늘 날짜 파일 없음, 금요일 파일로 대신 답변"** 안내를 주는지 확인

---

## 합격 기준

위 모든 체크박스가 통과되면 파이프라인 완성. 이후 매일 KST 06:05에 자동으로 Drive가 갱신되며, 채팅창에 "모닝리포트" 한 마디로 리포트가 나옵니다.
