---
description: find-doc 인덱스 현황 — 무엇이, 언제 기준으로 인덱싱됐는지, 제외·실패한 파일, 인덱싱 뒤에 수정된 파일
argument-hint: "[--online]"
---

`FD = python3 ${CLAUDE_PLUGIN_ROOT}/skills/find-doc/scripts/finddoc.py`

> Windows 에서 `python3` 가 없으면 `py -3` 으로 바꿔 실행한다. 경로의 `${CLAUDE_PLUGIN_ROOT}` 는 그대로 둔다.

`FD status $ARGUMENTS` 를 실행하고 아래 순서로 한국어로 보여줘. 시각은 모두 **한국 시간(KST, +9시간)** 으로 바꿔 `11/16 15:08` 처럼 쓴다.

1. **한 줄 요약**: "Figma 파일 N개(파일 단위, MM/DD 기준) · 레이어 단위 M개 파일, 레이어 X만 개(가장 오래된 것 MM/DD, 최신 MM/DD) · Jira·Confluence 는 실시간 검색"
2. **등록된 팀·프로젝트** (`teams`) 와 검색 범위(`atlassian.jira_projects`, `conf_spaces`)
3. **레이어 인덱스 파일 목록** (`files`, 인덱싱이 오래된 순): `파일명 · 팀/폴더 · 인덱싱 시각 · 레이어 수` 표. 10개가 넘으면 오래된 10개만 보여주고 "나머지 N개" 로 접는다.
4. **아직 안 된 파일** (`layer_index.not_indexed`) 이 있으면 목록
5. **마지막 인덱싱 결과** (`last_crawl`): 시각, 새로 인덱싱·건너뜀 수, 실패한 파일과 이유
6. **제외된 파일** (`excluded`): 개수와 이름(이유). "필요하면 `focus include <file key>` 로 되돌릴 수 있어요" 안내
7. `--online` 으로 실행했으면 **인덱싱 뒤에 수정된 파일** (`stale`): 파일명 · 수정 시각 · 인덱싱 시각. 있으면 "`/find-doc:reindex` 로 갱신하세요" 안내.
   `--online` 이 아니면 마지막에 "인덱싱 뒤 수정된 파일을 확인하려면 `/find-doc:status --online` (Figma 조회 1~2분)" 한 줄.
8. 파일 인덱스가 7일 이상 지났거나(`file_index.age_days`) 레이어 인덱스 중 가장 오래된 것이 30일 이상이면 갱신을 권한다.
