---
description: 세션 시작 시 프로젝트 현재 상태 파악 (+ 원격 drift + 브랜치 누락 체크)
---

다음 순서로 이 프로젝트의 현재 상태를 파악해줘:

## 0-A. 원격 동기화 상태 확인 (가장 먼저) ⚠️

PC/웹 등 여러 환경에서 작업하면 로컬이 원격에 수십 커밋 뒤처질 수 있음.
세션 시작 시 반드시 양방향 drift 체크.

```bash
git fetch --all --prune
git log --oneline origin/main..main    # 로컬이 앞선 커밋 (미푸시 대기)
git log --oneline main..origin/main    # 원격이 앞선 커밋 (미풀 상태)
```

- **원격이 앞섰으면** → 사용자에게 보고 + fast-forward 또는 rebase 동의 받기
- **로컬이 앞섰으면** → 이전 세션 push 보류 상태 확인 (의도적인지 물어보기)
- 둘 다 비어있으면 동기 완료, 0-B 로 진행

⚠️ drift 발견 시 **해결 전까지 CLAUDE.md 등 로컬 문서를 "진실의 원천" 으로
믿지 말 것** — 원격 `main` 의 CLAUDE.md 와 로컬 본을 비교해서 반영 누락된
작업을 먼저 파악. 원격이 앞서있으면 그 변경들을 본 세션 작업 전제로 삼음.

## 0-B. 브랜치 누락 체크 ⚠️

웹 Claude는 세션마다 새 브랜치를 만들기 때문에 **이전 세션 작업이 다른 브랜치에만 있을 수 있음**.

```bash
git log --all --oneline --since="14 days ago" | grep -vE "(auto|Daily report|데이터 업데이트|state 업데이트|섹터 ETF|보유 종목)" | head -30
```

그리고 현재 브랜치 HEAD에 포함되지 않은 최근 커밋이 있는지 확인:

```bash
# 모든 원격 claude/* 브랜치에서 현재 HEAD에 없는 커밋 탐지
for br in $(git branch -r | grep 'origin/claude/' | grep -v HEAD); do
  ahead=$(git log HEAD..$br --oneline 2>/dev/null)
  if [ -n "$ahead" ]; then
    echo "=== $br (ahead of HEAD) ==="
    echo "$ahead" | head -10
  fi
done
```

**CLAUDE.md 맨 위의 `Last session branch:` 포인터도 확인** — 거기에 기록된 브랜치가
현재 브랜치와 다르고 ahead 커밋이 있으면 **작업 누락 경고** 표시하고 사용자에게
병합/cherry-pick 여부 물어봐.

## 1. 프로젝트 문서 읽기

1. `CLAUDE.md` 읽고 "현재 상태" 섹션 요약 (맨 위의 `Last session branch:` 포인터도)
2. `SESSION_LOG.md` 최근 3개 세션 확인
3. `git log --oneline -5` 로 현재 브랜치 최근 커밋 확인
4. `git status` 로 브랜치와 변경사항 확인
5. `docs/decisions/` 폴더에 ADR 파일 있으면 목록만 나열

## 2. 정리해서 알려주기

- 지금 어느 프로젝트의 어느 단계에 있는지
- **[0.에서 다른 브랜치 누락 발견 시 최우선으로 알림]**
- 다음에 해야 할 일 (CLAUDE.md "활성 작업" 섹션 기준)
- 주의해야 할 미해결 이슈 (SESSION_LOG 최근 "미해결" 항목)
- 최근 주요 결정 (CLAUDE.md "최근 주요 결정" 섹션)

끝으로 "작업 시작 준비 됐어요. 뭐부터 할까요?" 물어봐줘.
