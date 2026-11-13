---
description: Figma 링크 등록 — 파일 링크는 메모와 함께 파일 단위로, 팀·프로젝트 링크는 그 아래 파일 전체를 레이어 단위 인덱싱 대상으로
argument-hint: <figma 파일 URL> [메모] | <팀·프로젝트 URL>
---

`FD = python3 ${CLAUDE_PLUGIN_ROOT}/skills/find-doc/scripts/finddoc.py`

- 링크가 팀(`figma.com/files/…/team/<id>/…`)이나 프로젝트(`…/project/<id>/…`)면: `FD focus add-team $ARGUMENTS`
  새로 추가된 파일 수와 예상 시간을 알려주고, "지금 인덱싱할까요?" 라고 물어 → 좋다고 하면 `FD crawl` 을 Bash `run_in_background` 로.
- 파일 링크(`figma.com/design/…`)면: `FD add $ARGUMENTS` 로 등록하고 등록된 이름·메모를 한 줄로 알려줘.
  레이어까지 찾고 싶다고 하면 `FD focus add <url>` 후 `FD crawl --key <file key>`.

> Windows 에서 `python3` 가 없으면 `py -3` 으로 바꿔 실행한다. 경로의 `${CLAUDE_PLUGIN_ROOT}` 는 그대로 둔다.
URL 이 Figma 링크가 아니면 오류를 그대로 보여줘.
