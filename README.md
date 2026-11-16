# find-doc

"지원서 기획서 찾아줘"처럼 말하면 Jira 이슈, Confluence 페이지, Figma 기획서 링크를 찾아 관련도 순으로 보여주는 Claude Code 플러그인이다.

- **Jira·Confluence**: JQL/CQL 키워드 검색. 제목에 걸린 것을 먼저, 본문에 걸린 것으로 나머지를 채운다.
- **Figma**: 각자 PC 에 만든 Figma 인덱스. Aside 브라우저로 Figma 조직 검색을 키워드별로 미리 돌려 모아 둔다. 팀에 가입하지 않아도 조직에서 볼 수 있는 파일은 다 잡힌다.
- **레이어 링크**: 설정 때 받은 '지정 파일'(자주 보는 기획서, 또는 팀·프로젝트 링크 아래 파일 전부)은 페이지·프레임·레이어까지 인덱싱해서, Figma 의 Copy link to selection 과 같은 `?node-id=` 링크를 돌려준다.
- **리랭킹**: Sonnet 서브에이전트가 후보를 질문 의도에 맞게 다시 골라 상위 10개와 고른 이유를 보여준다.

## 사용 순서 한눈에

처음엔 **`setup`** → 확인은 **`status`** → 평소엔 **`search`**, 가끔 **`reindex`**.

### 처음 한 번

0. **준비**
   - 플러그인 설치 (아래 "설치" 참고) → Claude Code 재시작
   - Aside 브라우저에서 figma.com 에 **팀 멤버인 계정**으로 로그인 (팀 파일 목록은 멤버만 볼 수 있다)
1. **`/find-doc:setup`** — 차례로 물어보고 진행한다
   1. Atlassian 주소 (Jira, Confluence)
   2. Atlassian API 토큰 — 채팅창이 아니라 **본인 터미널에서 직접** 입력
   3. Jira 프로젝트 선택
   4. Confluence 스페이스 선택
   5. Figma 조직 연결 (Figma 계정이 여러 개 로그인돼 있으면 어느 계정으로 열지)
   6. **레이어까지 찾을 Figma 링크** — **팀 링크**를 주면 그 아래 디자인 파일이 전부 등록된다. 이름으로 봐서 의미 없는 파일(Untitled, 복사본, 백업 …)은 빼고 목록을 보여준다
   7. 첫 인덱싱 (백그라운드): 조직 전체 파일 목록 3~6분 → 레이어 인덱싱 (팀 파일 75개 기준 30~45분)
   - 레이어 인덱싱이 도는 동안 **`/find-doc-progress`** 로 진행률·성공/실패·남은 시간을 채팅 옆 패널(패널 자리가 없으면 입력창 위 한 줄)에서 본다
2. **`/find-doc:status`** — 끝나면 무엇이, 언제 기준으로 들어갔는지, 제외·실패한 파일이 있는지 확인
3. **`/find-doc:search 통계 대시보드 기획서`** — 검색. 슬래시 명령 없이 "○○ 기획서 피그마 링크 찾아줘" 라고 말해도 된다

### 평소에

| 상황 | 명령 |
|---|---|
| 검색 | `/find-doc:search …` (또는 그냥 말로) |
| 갱신 (일주일에 한 번 권장) | `/find-doc:reindex` — 실제로 편집된 파일만 다시 받아서 보통 몇 분 |
| 다른 팀·프로젝트 추가 | `/find-doc:add <팀 또는 프로젝트 링크>` |
| 파일 하나만 추가 | `/find-doc:add <파일 링크> [메모]` |
| 지금 상태 확인 | `/find-doc:status` (인덱싱 뒤 수정된 파일까지 보려면 `--online`) |
| 인덱싱 진행 상황 보기 | `/find-doc-progress` (레이어 인덱싱 중, 3초마다 갱신) |
| 제외된 파일 되돌리기 | `status` 에 나온 file key 로 `finddoc.py focus include <key>` |

### add 와 reindex 의 차이

- **`add`** 는 **등록**한다: 팀·파일을 "레이어까지 인덱싱할 대상"에 넣고, 원하면 그 파일들의 레이어 인덱싱까지 돌린다.
- **`reindex`** 는 **실제 인덱싱**을 한다: 조직 전체 파일 목록을 새로 만들고, 등록된 팀의 새 파일을 추가한 뒤, 지정 파일의 레이어를 인덱싱한다.
- 팀은 그대로 두고 인덱스(내용)만 다시 채울 때는 `reindex` 한 번이면 된다. 인덱스를 통째로 지웠을 때도 마찬가지다 (`~/.config/find-doc/index` 삭제 → `reindex`).
- 설정까지 처음부터 하려면 `~/.config/find-doc/config.json` 을 지우고 `setup` 부터 (토큰 파일 `credentials` 는 남겨두면 다시 입력하지 않는다).

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
- 레이어 인덱스: 파일당 1~3분. **팀이나 프로젝트 링크를 주면 그 아래 디자인 파일을 전부** 등록하되, 이름으로 봐서 의미 없는 파일(Untitled, 커뮤니티 복사본, `(Copy)`·사본, 백업·보관함, 테스트)은 빼고 그 목록을 보여준다(`focus include <file key>` 로 되돌리기). 이후 이후 reindex 때 새 파일도 자동으로 추가한다 (팀 멤버여야 목록이 보인다). 파일이 많으면 오래 걸리니 백그라운드로 돌리고, 멈춰도 다시 실행하면 이어서 한다.

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
| `/find-doc:status [--online]` | 무엇이 언제 기준으로 인덱싱됐는지, 제외·실패 파일, (`--online`) 인덱싱 뒤 수정된 파일 |
| `/find-doc:reindex` | Figma 인덱스 갱신. 일주일에 한 번 권장. 중간에 끊겨도 이어서 진행 |
| `/find-doc:add <figma 파일 URL> [메모]` | 파일 링크 직접 등록 |
| `/find-doc:add <팀·프로젝트 URL>` | 그 아래 디자인 파일 전부를 레이어 인덱싱 대상으로 등록 |

지정 파일 관리(직접 실행할 때): `finddoc.py focus add <파일 url...>` / `focus add-team <팀·프로젝트 url...>` / `focus list` / `focus remove <file key 또는 team id>` → `finddoc.py crawl [--workers 3] [--limit N]` 로 레이어 인덱싱. `--workers` 는 동시에 받는 파일 수(기본 4, 최대 6), `--parse-workers` 는 해석 프로세스 수(기본: CPU 코어 수 - 2, 최대 6). 일시적 오류(Aside 연결 끊김·시간 초과)로 실패한 파일은 끝에 한 번 하나씩 다시 시도한다. 같은 이름 파일은 다운로드가 섞이지 않게 한 번에 하나씩 처리한다.

## 파일 위치

macOS `~/.config/find-doc/`, Windows `%USERPROFILE%\.config\find-doc\`

```
~/.config/find-doc/
├── config.json       # Atlassian 주소·프로젝트·스페이스·Figma 조직·지정 파일/팀·개인 키워드
├── credentials       # Atlassian 이메일·토큰 (권한 600)
└── index/
    ├── figma.jsonl   # Figma 인덱스 (한 줄 = 파일 1개)
    ├── teams.json    # Figma team_id → 팀 이름
    ├── layers.db     # 레이어 인덱스 (SQLite: 레이어 행 + 검색용 좁은 테이블)
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
- 레이어 인덱싱은 파일의 **버전 기록**(`/api/versions/<key>`)에서 최신 버전을 찾고, 그 버전의 **파일 전체 내용(canvas, fig-kiwi 형식)** 을 받아 `scripts/figfile.py` 가 직접 해석한다. 모든 페이지·프레임·텍스트와 node-id 가 들어 있어 화면을 펼칠 필요가 없다.
  - 링크는 로그인된 Aside 탭 하나로 여러 파일 것을 한꺼번에 받고, 내용은 Figma 저장소(S3) 서명 링크라 Python 이 직접 받는다. 오래된 일부 파일은 Figma 가 직접 내주는데 로그인이 필요해서, 그때는 Aside 탭 안에서 받아 다운로드 폴더에 `<key>.canvas.fig` 로 저장한 뒤 옮겨 해석하고 지운다.
  - 변경 감지는 버전 기록의 **실제 편집 시각**과 마지막 인덱싱 시각을 시각 단위로 비교한다 (파일 목록의 `updated_at` 은 내용 편집과 상관없어서 쓰지 않는다).
  - 이 방식이 안 되면 예전 방식(브라우저에서 "Save local copy" 로 .fig 저장)으로 자동으로 넘어간다. 저장 흐름이 깨지면 `scripts/save-fig.js`, 형식이 바뀌면 `scripts/figfile.py` 를 고친다.
  - 참고 속도(팀 75개, 다운로드 4개·해석 6개 동시): 바뀐 파일 25개를 7분 안에 받고, 큰 파일(노드 17만 개) 해석은 3~4분.
  - .fig 데이터는 zstd 압축이다. Python 3.14 이상은 기본 지원, 그 아래는 `pip install zstandard` 또는 `zstd` 명령줄 도구(`brew install zstd` / `winget install zstd`)를 쓴다. `doctor` 의 `zstd` 가 false 면 셋 중 하나를 설치한다.
- 인덱싱에는 LLM 토큰이 들지 않는다 (Python + Aside 브라우저 스크립트). Claude 토큰은 명령을 실행하고 결과를 요약할 때만 든다.

## 고친 내용 반영하기 (관리자)

설치된 플러그인은 버전이 바뀔 때만 새로 받는다. 원본을 고친 뒤:

1. `.claude-plugin/plugin.json` 의 `version` 을 올린다 (예: 0.1.3 → 0.1.4)
2. 커밋하고 GitHub 에 푸시한다
3. 사용자는 위 "업데이트" 명령 두 줄 → Claude Code 재시작

