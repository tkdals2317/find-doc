---
description: Figma 링크를 내 인덱스에 직접 등록 (메모를 달면 검색에 쓰인다)
argument-hint: <figma URL> [메모]
---

`python3 ${CLAUDE_PLUGIN_ROOT}/skills/find-doc/scripts/finddoc.py add $ARGUMENTS` 를 Bash 로 실행하고, 등록된 이름·메모를 한 줄로 알려줘.

> Windows 에서 `python3` 가 없으면 `py -3` 으로 바꿔 실행한다. 경로의 `${CLAUDE_PLUGIN_ROOT}` 는 그대로 둔다.
URL 이 Figma 링크가 아니면 오류를 그대로 보여줘.
