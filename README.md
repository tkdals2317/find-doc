# find-doc

"지원서 기획서 찾아줘"처럼 말하면 Jira 이슈, Confluence 페이지, Figma 기획서 링크를 찾아 관련도 순으로 보여주는 Claude Code 플러그인이다.

- **Jira·Confluence**: JQL/CQL 키워드 검색. 제목에 걸린 것을 먼저, 본문에 걸린 것으로 나머지를 채운다.
- **Figma**: 각자 PC 에 만든 Figma 인덱스. Aside 브라우저로 Figma 조직 검색을 키워드별로 미리 돌려 모아 둔다. 팀에 가입하지 않아도 조직에서 볼 수 있는 파일은 다 잡힌다.
- **레이어 링크**: 설정 때 받은 '지정 파일'(자주 보는 기획서, 또는 팀·프로젝트 링크 아래 파일 전부)은 페이지·프레임·레이어까지 인덱싱해서, Figma 의 Copy link to selection 과 같은 `?node-id=` 링크를 돌려준다.
- **리랭킹**: Sonnet 서브에이전트가 후보를 질문 의도에 맞게 다시 골라 상위 10개와 고른 이유를 보여준다.

## 준비물

| 필요 | 용도 | 없으면 |
|---|---|---|
| Claude Code | 플러그인 실행 | 사용 불가 (claude.ai 채팅에서는 안 됨) |
| Python 3 (3.14 이상 권장) | 스크립트 (표준 라이브러리만 씀. 3.13 이하는 레이어 인덱싱에 `pip install zstandard` 필요) | 사용 불가 |
| Atlassian API 토큰 | Jira·Confluence 검색 | Jira·Confluence 검색 불가 |
| [Aside](https://aside.com) + Figma 로그인 | Figma 인덱스 | Jira·Confluence 에 붙은 Figma 링크만 찾음 |

## 설치 — macOS

1. **Python 3.14 이상**: `brew install python@3.14` 후 `python3 --version` 으로 확인.
   3.13 이하를 계속 쓸 거면 `python3 -m pip install zstandard` (레이어 인덱싱용).
2. **Aside** (Figma 검색용, 없으면 Jira·Confluence 만 검색)
   - 브라우저 앱: https://aside.com/download 에서 설치 → 로그인 → Aside 안에서 figma.com 로그인
   - CLI: `curl -fsSL https://releases.aside.com/install.sh | bash` → `aside --version` 확인
3. **플러그인**
   ```bash
   claude plugin marketplace add tkdals2317/find-doc
   claude plugin install find-doc@find-doc
   ```
4. Claude Code 재시작 → `/find-doc:setup`

## 설치 — Windows

> Windows 는 아직 실사용 검증 전이다. 막히는 곳이 있으면 화면과 오류 문구를 이슈로 남겨 주세요.

1. **Python 3.14 이상** — PowerShell 에서:
   ```powershell
   winget install -e --id Python.Python.3.14
   ```
   (또는 python.org 설치 파일 — 설치 첫 화면에서 **"Add python.exe to PATH" 체크**)
   새 PowerShell 창에서 `py -3 --version` 이 3.14 이상이면 끝. 3.13 이하를 쓸 거면 `py -3 -m pip install zstandard`.
2. **Claude Code** — 공식 안내대로 설치하고 `claude --version` 확인. (Windows 용 Claude Code 는 Git for Windows 가 필요할 수 있다)
3. **Aside 브라우저** — https://aside.com/download 에서 Windows 버전 설치 → 로그인 → Aside 안에서 figma.com 로그인.
   다운로드 폴더는 기본값(`%USERPROFILE%\Downloads`)으로 둔다. Figma 사본을 여기서 찾는다.
4. **Aside CLI** — 공식 설치 스크립트가 macOS·Linux 전용이라 수동으로 넣는다. PowerShell 에서 한 줄씩:
   ```powershell
   $d = "$env:LOCALAPPDATA\Programs\aside"; New-Item -ItemType Directory -Force $d | Out-Null
   Invoke-WebRequest https://releases.aside.com/cli/AsideCLI-win-x64-latest.zip -OutFile "$env:TEMP\aside-cli.zip"
   Expand-Archive "$env:TEMP\aside-cli.zip" $d -Force
   [Environment]::SetEnvironmentVariable("Path", "$([Environment]::GetEnvironmentVariable('Path','User'));$d", "User")
   ```
   **새** PowerShell 창에서 확인 (Aside 브라우저가 켜져 있어야 함):
   ```powershell
   aside --version
   aside repl "console.log(1)"
   ```
   두 번째가 `1` 을 출력하면 준비 끝.
5. **플러그인** — PowerShell 에서:
   ```powershell
   claude plugin marketplace add tkdals2317/find-doc
   claude plugin install find-doc@find-doc
   ```
6. Claude Code 재시작 → `/find-doc:setup`
   - 토큰 등록 단계에서 안내하는 `py -3 "…\finddoc.py" cred set` 은 **PowerShell 에 직접** 붙여 실행한다 (토큰은 입력해도 화면에 안 보이는 게 정상).
   - 설정·인덱스는 `%USERPROFILE%\.config\find-doc\` 에 생긴다.

## 설정 (공통, `/find-doc:setup`)

순서: Atlassian 주소 → 토큰 등록(본인 터미널에서 직접 입력) → Jira 프로젝트 → Confluence 스페이스 → Figma 조직 연결 → **레이어까지 찾을 Figma 링크**(파일·팀·프로젝트 링크) → 첫 인덱싱.

- 조직 전체 파일 인덱스: 3~6분
- 레이어 인덱스: 파일당 1~3분. **팀이나 프로젝트 링크를 주면 그 아래 디자인 파일을 전부** 등록하고, 이후 reindex 때 새 파일도 자동으로 추가한다 (팀 멤버여야 목록이 보인다). 파일이 많으면 오래 걸리니 백그라운드로 돌리고, 멈춰도 다시 실행하면 이어서 한다.

## 업데이트

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
| `/find-doc:add <figma 파일 URL> [메모]` | 파일 링크 직접 등록 |
| `/find-doc:add <팀·프로젝트 URL>` | 그 아래 디자인 파일 전부를 레이어 인덱싱 대상으로 등록 |

지정 파일 관리(직접 실행할 때): `finddoc.py focus add <파일 url...>` / `focus add-team <팀·프로젝트 url...>` / `focus list` / `focus remove <file key 또는 team id>` → `finddoc.py crawl [--workers 3] [--limit N]` 로 레이어 인덱싱. `--workers` 는 동시에 여는 Figma 탭 수(기본 3, 최대 6). 같은 이름 파일은 다운로드가 섞이지 않게 한 번에 하나씩 처리한다.

## 파일 위치

macOS `~/.config/find-doc/`, Windows `%USERPROFILE%\.config\find-doc\`

```
~/.config/find-doc/
├── config.json       # Atlassian 주소·프로젝트·스페이스·Figma 조직·지정 파일/팀·개인 키워드
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

