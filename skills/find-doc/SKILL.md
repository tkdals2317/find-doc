---
name: find-doc
description: 자연어로 Jira 이슈·Confluence 페이지·Figma 기획서 링크를 찾는다. "지원서 기획서 찾아줘", "면접 일정 관련 피그마 어디 있어?", "공고 정책 문서 링크", "OO 기획서 링크 줘"처럼 기획서·시안·정책 문서나 그 링크를 찾는 요청이면 사용한다. "피그마에서만", "지라랑 컨플만"처럼 범위를 말하면 그 범위만 찾는다.
---

# find-doc

Jira·Confluence 키워드 검색(거기 붙은 Figma 링크 포함) + 로컬 Figma 인덱스(조직 전체 파일)를 합쳐 후보를 넓게 모은 뒤, `doc-reranker` 서브에이전트로 다시 골라 상위 10개를 보여준다.

스크립트: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/find-doc/scripts/finddoc.py <명령>` (아래 `FD`). 출력은 모두 JSON.

> Windows 에서 `python3` 가 없으면 `py -3` 으로 바꿔 실행한다. 경로의 `${CLAUDE_PLUGIN_ROOT}` 는 그대로 둔다.

## 0. 준비 상태 확인

`FD doctor` 를 실행한다.
- `atlassian.credentials` 가 false 이거나 `jira_projects` 가 비어 있으면 `/find-doc:setup` 을 먼저 하라고 안내하고 멈춘다.
- `index.age_days` 가 7 이상이면 결과 끝에 "Figma 인덱스가 N일 지났어요. `/find-doc:reindex` 로 갱신하세요"를 한 줄 붙인다. (검색은 그대로 진행)

## 1. 질문 해석

- **범위**: `--in figma,jira,conf` 옵션이나 "피그마에서만", "지라만", "컨플이랑 지라" 같은 말. 없으면 config 의 `default_scope`.
  - `figma` 만: 결과로 Figma 파일만 보여준다. 단 Jira·Confluence 에 붙은 Figma 링크도 후보 수집에는 쓴다.
- **키워드**: 질문에서 핵심어 2~5개를 뽑고 `synonyms.md` 로 동의어를 1~3개 더한다. "찾아줘/링크/관련" 같은 말은 버린다.
  예: "지원서 기획서" → `지원서 입사지원 기획서`
- **문서 종류 의도**: 기획서 / 시안 / 정책 / 이슈 중 무엇을 원하는지 메모해 리랭커에 넘긴다.
- **필수 맥락(`--must`)**: 질문이 특정 기능·화면 "안에서" 찾으라고 하면(예: "지원서 **파싱**에서 파일 용량", "**평가 에이전트** 쪽 녹음") 그 기능 이름을 필수 맥락으로 뺀다.
  필수 맥락은 레이어의 페이지·상위 프레임·이름 어딘가에 반드시 있어야 하고, 없으면 후보에서 빠진다. 나머지 단어(용량, MB …)는 일반 키워드로 둔다.
  예: "지원서 파싱에서 파일 용량" → 키워드 `용량 MB 업로드 초과`, `--must 파싱`
  필수 맥락으로 후보가 0개면 `--must` 없이 한 번 더 찾고, 그 사실을 결과에 한 줄 적는다.

## 2. 후보 모으기 (서로 독립이면 병렬로)

### A. Jira·Confluence — JQL/CQL 키워드 검색
```
FD atl-search "<질문>" --kw <키워드...> --in <jira,conf>
```
- 제목에 걸린 이슈를 먼저, 본문에 걸린 이슈로 나머지를 채운다. 검색 대상은 config 의 `jira_projects`, `conf_spaces`.
- 결과의 `figma_links` 를 Figma 후보에 합친다.
- Atlassian MCP(Rovo) 는 쓰지 않는다. (회사 IP 허용 목록 때문에 막힌다)

### B. Figma — 로컬 인덱스
범위에 figma 가 있고 config 의 `figma.enabled` 가 true 일 때:
```
FD figma-query <키워드...> [--must <필수 맥락...>] --live --limit 30
```
- `--live` 는 인덱스가 모르는 질문 단어(없으면 앞 2개)로 Figma 실시간 검색을 더 해서 보완한다. Aside 가 없으면 자동으로 건너뛴다.
- `candidates`: 파일 단위 후보. `focus: true` 는 사용자가 지정한 핵심 기획서.
- `layer_candidates`: 지정 파일 안의 **페이지·프레임·레이어 단위** 후보. `url` 은 `?node-id=` 가 붙은 레이어 직접 링크(Copy link to selection 과 같음), `path` 는 `페이지 › 상위 프레임 › … › 레이어`.
  레이어 후보가 질문과 잘 맞으면 파일 링크보다 레이어 링크를 우선 보여준다.
- `live.error` 가 로그인 문제면 "Aside 브라우저에서 figma.com 에 로그인해 주세요" 를 결과 끝에 알린다.

## 3. 합치기

- Figma 는 `key` 로 합친다. 같은 파일이 인덱스와 Jira/Confluence 에 모두 있으면 하나로 두고 `refs` 에 참조한 이슈·페이지 ID·제목·node-id 를 모은다.
- 후보가 60개를 넘으면 1차 점수(제목에 걸림, 여러 출처, 최신)로 60개까지 자른다.
- 후보 하나당 300자 안쪽으로 줄인다: `id, source, title|name, url, team/space/status, updated, snippet|hit_keywords|matched, refs, stale`.
- 레이어 후보는 `source: "figma-layer"`, `id: <file key>#<node>`, `name`, `type`, `path`, `url` 로 넣는다 (상위 15개).

## 4. 리랭킹

`doc-reranker` 서브에이전트(Agent 도구, subagent_type `find-doc:doc-reranker`)에 넘긴다. 프롬프트:
```
질문: <원문>
원하는 문서 종류: <기획서|시안|정책|이슈|미지정>
범위: <figma,jira,conf>
후보(JSON 배열):
<합친 후보>
```
돌아온 JSON 의 `results` 순서대로 보여준다. `clarify` 가 있으면 결과 위에 그 질문을 한 줄로 되묻는다.
리랭커 호출이 실패하면 1차 점수 순으로 보여주고 "리랭킹 없이 보여드려요" 를 붙인다.

## 5. 출력 형식

```
🔎 "지원서 기획서" — 범위 figma·jira·conf · Figma 인덱스 2일 전

1. 🎯 [D. 공통 규칙](https://www.figma.com/design/…?node-id=…)   레이어 · 서비스 기획
   🗝️통계 대시보드 기반 › 대시보드 위젯 기본 디자인 › 퍼널 › Funnel – 구성 가이드 › D. 공통 규칙
2. 🎨 [지원서 리뉴얼 기획서](https://www.figma.com/design/…)   기획서 · 서비스기획팀 · 2024-06
   지원서 작성·제출 화면 리뉴얼 본문. PROJ-1204·1230 에서 참조
2. 📄 [지원서 항목 설정 정책](https://…/wiki/…)   정책 · SPACE · 2026-09
   …
3. 🎫 [PROJ-1230 지원서 임시저장 오류](https://…/browse/PROJ-1230)   이슈 · 완료
   ↳ 화면: [지원서 리뉴얼 기획서 › 123-456](https://www.figma.com/design/…?node-id=123-456)

이전 버전 2개 접음 · 더 보려면 "더 보여줘"
```
- 아이콘: 🎯 Figma 레이어, 🎨 Figma 파일, 🎫 Jira, 📄 Confluence. 링크는 항상 클릭 가능한 마크다운 링크.
- 이유 한 줄은 리랭커의 `reason` 을 쓰되 참조 이슈가 있으면 붙인다.
- 결과가 없으면 시도한 키워드·범위를 보여주고 다른 표현을 제안한다.

## 하지 말 것

- Atlassian 토큰을 대화에 받거나 출력하지 않는다. 자격증명은 사용자가 터미널에서 `cred set` 으로 직접 넣는다.
- Figma 내부 API 는 조회(GET)만 한다. 파일을 만들거나 바꾸지 않는다.
- 인덱스·설정 파일(`~/.config/find-doc/`)을 손으로 고치지 않는다. 바꿀 때는 `FD config set`, `FD add` 를 쓴다.
