---
description: find-doc 최초 설정 (Atlassian 주소·자격증명, Jira 프로젝트·Confluence 스페이스 선택, Figma 조직 연결, 첫 인덱싱). 다시 실행하면 설정을 바꿀 수 있다.
---

아래 순서로 find-doc 을 설정해. 스크립트는 `FD = python3 ${CLAUDE_PLUGIN_ROOT}/skills/find-doc/scripts/finddoc.py`.

> Windows 에서 `python3` 가 없으면 `py -3` 으로 바꿔 실행한다. 경로의 `${CLAUDE_PLUGIN_ROOT}` 는 그대로 둔다.
각 단계 결과를 한두 줄로 알려주고, 사용자가 고를 것은 AskUserQuestion 으로 물어.

1. **현재 상태**: `FD doctor` 실행.

2. **Atlassian 주소** (`FD config show` 에서 `atlassian.jira_base` 나 `conf_base` 가 비어 있을 때만)
   - "회사 Jira 주소를 알려 주세요 (예: `https://회사이름.atlassian.net`)" 라고 묻는다. 브라우저 주소창의 앞부분이다.
   - Confluence 는 보통 같은 사이트의 `/wiki` 다. 다른 사이트를 쓰는지 한 번 확인한다 (회사마다 Jira·Confluence 사이트가 다를 수 있다).
   - 저장 (끝의 `/` 는 빼고):
     `FD config set atlassian.jira_base '"https://<site>.atlassian.net"'`
     `FD config set atlassian.conf_base '"https://<site>.atlassian.net/wiki"'`

3. **Atlassian 자격증명** (`atlassian.credentials` 가 false 일 때만)
   - 토큰을 대화창에 붙여 넣지 말라고 먼저 말해.
   - https://id.atlassian.com/manage-profile/security/api-tokens 에서 API 토큰을 만들고, **본인 터미널**에서 아래를 직접 실행하라고 안내해:
     ```bash
     python3 ${CLAUDE_PLUGIN_ROOT}/skills/find-doc/scripts/finddoc.py cred set
     ```
     (`${CLAUDE_PLUGIN_ROOT}` 는 실제 경로로 바꿔서 보여줘.)
   - 사용자가 끝났다고 하면 `FD doctor --online` 으로 `jira_ok`, `conf_ok` 를 확인해.

4. **Jira 프로젝트 선택**: `FD atl-list jira` → 최근 활동 순 상위 4개를 선택지로(multiSelect), 그 밖은 "Other" 로 키를 직접 입력받아.
   저장: `FD config set atlassian.jira_projects '["PROJ","..."]'`

5. **Confluence 스페이스 선택**: `FD atl-list conf` → 목록이 길면 사용자가 말한 팀·업무 이름으로 좁혀서 상위 4개를 선택지로(multiSelect).
   저장: `FD config set atlassian.conf_spaces '["SPACE","..."]'`

6. **Figma** (doctor 의 `aside` 가 true 일 때만; false 면 README 의 'Aside CLI 설치'(Windows 는 수동 설치 PowerShell) 를 보여주고, "Aside 를 설치하면 Figma 전체 검색이 돼요. 지금은 Jira·Confluence 에 붙은 Figma 링크만 찾아요" 라고 알리고 7번으로)
   - `FD figma-orgs` → 로그인 오류면 Aside 브라우저에서 figma.com 에 로그인해 달라고 하고 기다려.
   - 조직이 하나면 그대로, 여럿이면 고르게 해서 `FD figma-setup --org <id> --name <이름>`.
   - Aside 브라우저에 Figma 계정이 여러 개 로그인돼 있으면 파일을 열 때 "Choose an account to open" 화면이 뜬다. 어떤 계정으로 열지 물어보고(팀 멤버인 계정) `FD config set figma.account '"<계정 이름 또는 이메일 앞부분>"'` 로 저장. 비워 두면 "Editor on file" 계정을 고른다.
   - **지정 파일(레이어까지 찾을 기획서) 받기**: "레이어 단위까지 찾고 싶은 Figma 링크를 붙여 주세요. 파일 링크도 되고, 팀이나 프로젝트 링크를 주면 그 아래 파일을 전부 등록해요" 라고 물어. 건너뛰어도 된다.
     - 파일 링크(`figma.com/design/…`) → `FD focus add <url> ...`
     - 팀 링크(`figma.com/files/…/team/<id>/…`)나 프로젝트 링크(`…/project/<id>/…`) → `FD focus add-team <url> ...`
       결과의 `added`(새 파일 수)와 `estimate_minutes`(예상 시간)를 알려줘. 팀 멤버가 아니면 403 이 난다 → 팀에 가입된 계정으로 Aside 에 로그인했는지 확인.
       등록한 팀은 기억해 두고, 이후 `/find-doc:reindex` 때마다 새로 생긴 파일을 자동으로 추가한다.
   - 개인 키워드가 있는지 물어(선택): 있으면 `FD config set extra_keywords '["…"]'`.
   - 첫 인덱싱 (둘 다 Bash `run_in_background`, 순서대로):
     1. `FD reindex` — 조직 전체 파일 단위, 3~6분
     2. 지정 파일이 있으면 `FD crawl --workers 3` — Aside 탭 3개로 동시에, 각 파일의 로컬 사본(.fig, 이미지 제외)을 받아 페이지·프레임·레이어를 읽는다.
        파일당 1~3분. 받은 .fig 는 다운로드 폴더에서 바로 옮겨 해석하고 지운다고 미리 알려.
        파일이 수십 개면 오래 걸리니 백그라운드로 돌리고, 중간에 멈춰도 다시 실행하면 끝난 파일은 건너뛰고 이어서 한다고 알려.
        한 번에 일부만 하려면 `FD crawl --limit 20`.
        실행 중에는 Aside 브라우저에 Figma 탭이 잠깐씩 열렸다 닫힌다 (그동안 Aside 를 다른 용도로 쓰지 않는 게 좋다).
        "120초 안에 저장이 끝나지 않았습니다" 가 나오면: 사용자에게 Aside 에서 그 Figma 파일을 직접 열어 두게 하고,
        `aside repl "console.log(JSON.stringify((await listBrowserTabs()).filter(t=>t.url.includes('<file key>'))))"` 로 탭 id 를 찾아
        `FD crawl --key <file key> --tab <탭 id>` 로 다시 실행.
   - 끝나면 파일 수·레이어 수를 알려줘.

7. 마지막으로 `FD doctor` 요약과 사용 예시 `/find-doc:search 지원서 기획서` 를 보여줘.
