# find-doc

"지원서 기획서 찾아줘"처럼 말하면 Jira 이슈, Confluence 페이지, Figma 기획서 링크를 찾아 관련도 순으로 보여주는 Claude Code 플러그인이다.

- **Jira·Confluence**: JQL/CQL 키워드 검색. 제목에 걸린 것을 먼저, 본문에 걸린 것으로 나머지를 채운다.
- **Figma**: 각자 PC 에 만든 Figma 인덱스. Aside 브라우저로 Figma 조직 검색을 키워드별로 미리 돌려 모아 둔다. 팀에 가입하지 않아도 조직에서 볼 수 있는 파일은 다 잡힌다.
- **레이어 링크**: 설정 때 받은 '지정 파일'(자주 보는 핵심 기획서)은 페이지·프레임·레이어까지 인덱싱해서, Figma 의 Copy link to selection 과 같은 `?node-id=` 링크를 돌려준다.
- **리랭킹**: Sonnet 서브에이전트가 후보를 질문 의도에 맞게 다시 골라 상위 10개와 고른 이유를 보여준다.

## 준비물

| 필요 | 용도 | 없으면 |
|---|---|---|
| Claude Code | 플러그인 실행 | 사용 불가 (claude.ai 채팅에서는 안 됨) |
| Python 3 (3.14 이상 권장) | 스크립트 (표준 라이브러리만 씀. 3.13 이하는 레이어 인덱싱에 `pip install zstandard` 필요) | 사용 불가 |
| Atlassian API 토큰 | Jira·Confluence 검색 | Jira·Confluence 검색 불가 |
| [Aside](https://aside.com) + Figma 로그인 | Figma 인덱스 | Jira·Confluence 에 붙은 Figma 링크만 찾음 |

## Aside CLI 설치

- **macOS**: `curl -fsSL https://releases.aside.com/install.sh | bash`
- **Windows**: 설치 스크립트는 macOS·Linux 전용이라 수동으로 넣는다. PowerShell 에서:
  ```powershell
  $d = "$env:LOCALAPPDATA\Programs\aside"; New-Item -ItemType Directory -Force $d | Out-Null
  Invoke-WebRequest https://releases.aside.com/cli/AsideCLI-win-x64-latest.zip -OutFile "$env:TEMP\aside-cli.zip"
  Expand-Archive "$env:TEMP\aside-cli.zip" $d -Force
  [Environment]::SetEnvironmentVariable("Path", "$([Environment]::GetEnvironmentVariable('Path','User'));$d", "User")
  ```
  새 터미널에서 `aside --version`, `aside repl "console.log(1)"` 이 되면 준비 끝. (Aside 브라우저 앱도 설치·로그인되어 있어야 한다)
- Python 은 macOS `python3`, Windows `py -3` (python.org 설치본).

## 설치

터미널에서:

```bash
claude plugin marketplace add tkdals2317/find-doc
claude plugin install find-doc@find-doc
```

또는 Claude Code 에 "GitHub tkdals2317/find-doc 플러그인 설치해줘" 라고 말해도 된다.

Claude Code 를 재시작한 뒤:

```
/find-doc:setup
```

설정 순서: Atlassian 주소 입력 → 토큰 등록(본인 터미널에서 직접 입력) → Jira 프로젝트 선택 → Confluence 스페이스 선택 → Figma 조직 연결 → 자주 보는 Figma 기획서 링크 등록 → 첫 인덱싱(조직 전체 3~6분 + 지정 파일당 1~3분).

업데이트:

```bash
claude plugin marketplace update find-doc
claude plugin update find-doc@find-doc
```

## 사용

```
/find-doc:search 지원서 기획서
/find-doc:search 면접 일정 알림 --in figma
/find-doc:search 공고 마감 정책 --in jira,conf
```

슬래시 명령 없이 "지원서 기획서 링크 찾아줘"라고 말해도 된다.

| 명령 | 하는 일 |
|---|---|
| `/find-doc:search <질문> [--in figma,jira,conf]` | 검색 |
| `/find-doc:setup` | 최초 설정 / 설정 변경 |
| `/find-doc:reindex` | Figma 인덱스 갱신. 일주일에 한 번 권장. 중간에 끊겨도 이어서 진행 |
| `/find-doc:add <figma URL> [메모]` | 링크 직접 등록 (파일 단위) |

지정 파일 관리: `finddoc.py focus add <url...>` / `focus list` / `focus remove <key>` → `/find-doc:reindex` 로 레이어 인덱싱.

## 파일 위치

```
~/.config/find-doc/
├── config.json       # 프로젝트·스페이스·Figma 조직·개인 키워드
├── credentials       # Atlassian 이메일·토큰 (권한 600)
└── index/
    ├── figma.jsonl   # Figma 인덱스 (한 줄 = 파일 1개)
    ├── teams.json    # Figma team_id → 팀 이름
    ├── layers/       # 지정 파일별 레이어 인덱스 (<file key>.jsonl)
    └── meta.json     # 마지막 갱신 시각, 돌린 키워드
```

인덱스는 각자 권한 기준이라 공유하지 않는다.

## 키워드·동의어 키우기

- `skills/find-doc/seed-keywords.txt`: 인덱싱 기본 키워드. 팀 공통 도메인 용어를 PR 로 추가한다.
- `skills/find-doc/synonyms.md`: 질문을 키워드로 바꿀 때와 인덱싱에 함께 쓰는 동의어 사전.
- 개인 용어: `/find-doc:setup` 에서 넣거나 `finddoc.py config set extra_keywords '["…"]'`.

## 알아둘 점

- Figma 인덱싱은 Figma 웹이 내부적으로 쓰는 검색 API(`/api/search/full_results`)를 내 로그인 세션으로 조회만 한다. 공개 API 가 아니라서 Figma 가 바꾸면 깨질 수 있다. 깨지면 reindex 가 "응답 모양이 바뀌었습니다"라고 알리고 기존 인덱스는 그대로 쓴다. 고칠 곳은 `scripts/finddoc.py` 의 `figma_search()` 하나다.
- Figma 검색은 한 번에 최대 약 70개만 돌려준다. 그래서 키워드를 여러 개 돌려서 합치고, 새로 찾은 파일명에서 키워드를 더 뽑아 최대 2바퀴 더 돈다.
- Atlassian Rovo(MCP)는 쓰지 않는다. 회사 IP 허용 목록 때문에 Claude 커넥터가 막히고, 크레딧도 소모한다.
- 레이어 인덱싱은 Aside 로 Figma 의 "Save local copy" 를 실행해 **.fig 사본(이미지 제외)** 을 받고, `scripts/figfile.py` 가 그 안의 kiwi 형식을 직접 해석한다. 모든 페이지·프레임·텍스트와 node-id 가 들어 있어 화면을 펼칠 필요가 없다. 노드 83만 개짜리 파일 기준 저장 약 1.5분 + 해석 약 80초. 받은 .fig 는 다운로드 폴더에서 옮겨 해석한 뒤 지운다.
  - 저장 흐름이 깨지면(Figma 문구 변경) `scripts/save-fig.js`, 형식이 바뀌면 `scripts/figfile.py` 를 고친다.
  - .fig 데이터는 zstd 압축이다. Python 3.14 이상은 기본 지원, 그 아래는 `pip install zstandard`.
  - 120초 안에 저장이 안 끝나는 아주 큰 파일은 Aside 에서 파일을 직접 열어 두고 `crawl --tab <탭 id>` 로 실행한다.
- 인덱싱에는 LLM 토큰이 들지 않는다 (Python + Aside 브라우저 스크립트). Claude 토큰은 명령을 실행하고 결과를 요약할 때만 든다.

## 고친 내용 반영하기 (관리자)

설치된 플러그인은 버전이 바뀔 때만 새로 받는다. 원본을 고친 뒤:

1. `.claude-plugin/plugin.json` 의 `version` 을 올린다 (예: 0.1.3 → 0.1.4)
2. 커밋하고 GitHub 에 푸시한다
3. 사용자는 위 "업데이트" 명령 두 줄 → Claude Code 재시작

