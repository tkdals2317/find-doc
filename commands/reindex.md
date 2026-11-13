---
description: Figma 인덱스 갱신 — 조직 전체(파일 단위, 3~6분) + 지정 파일(.fig 사본으로 레이어 단위, 바뀐 파일만, 파일당 2~4분)
argument-hint: "[--restart] [--layers-only] [--force]"
---

아래를 Bash `run_in_background` 로 순서대로 실행해. `FD = python3 ${CLAUDE_PLUGIN_ROOT}/skills/find-doc/scripts/finddoc.py`

> Windows 에서 `python3` 가 없으면 `py -3` 으로 바꿔 실행한다. 경로의 `${CLAUDE_PLUGIN_ROOT}` 는 그대로 둔다.

1. `--layers-only` 가 없으면: `FD reindex` (+ `--restart` 가 있으면 붙여서)
2. 지정 파일이 있으면: `FD crawl` (+ `--force` 가 있으면 붙여서). 수정되지 않은 파일은 자동으로 건너뛴다.

- 진행 상황(stderr)은 길게 옮기지 말고, 끝났을 때 한두 줄로 요약해: 파일 수, 새 파일 수, 레이어 수, 일부만 읽힌 페이지 수.
- `ok: false` 면 `error` 를 그대로 보여주고 안내해:
  - 로그인 문제 → Aside 브라우저에서 figma.com 에 로그인한 뒤 다시 `/find-doc:reindex` (중단 지점부터 이어서 진행)
  - "Figma 설정이 없습니다" / "지정 파일이 없습니다" → `/find-doc:setup`
  - "120초 안에 저장이 끝나지 않았습니다" → setup.md 의 `--tab` 방법 안내
  - "zstd 압축 해제가 필요합니다" → Python 3.14 이상 설치 또는 `pip install zstandard`
  - "응답 모양이 바뀌었습니다", "no-save-action" → Figma 화면이 바뀐 것. 플러그인 관리자에게 알려 달라고 안내 (기존 인덱스는 그대로 쓸 수 있음)
