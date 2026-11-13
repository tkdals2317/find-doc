#!/usr/bin/env python3
"""find-doc helper: Figma 로컬 인덱스 + Atlassian 대체 검색.

stdlib 만 쓴다. 모든 출력은 JSON(stdout). 사람용 메시지는 stderr.

  doctor                         설치·로그인·인덱스 상태 점검
  figma-orgs                     Aside 세션으로 내 Figma 조직 목록
  figma-setup --org ID           조직 저장 + 팀 이름표(teams.json) 갱신
  reindex [--max-queries N]      키워드 순회로 Figma 인덱스 갱신 (중단 시 이어하기)
  figma-query KW... [--live] [--limit N] [--must KW...]
                                 로컬 인덱스 1차 점수 (+실시간 검색 보완, --must 는 필수 맥락)
  atl-search QUERY --kw KW... [--in jira,conf] [--jira P,..] [--conf S,..]
                                 Jira·Confluence JQL/CQL 검색
  add URL [NOTE...]              Figma 링크 직접 등록 (파일 단위)
  focus add URL... | focus add-team TEAM_OR_PROJECT_URL... | focus remove KEY... | focus list
                                 레이어까지 깊게 인덱싱할 '지정 파일' 관리
  crawl [--key KEY...] [--force] [--tab ID]
                                 지정 파일의 .fig 사본을 받아 페이지·프레임·레이어 인덱싱 (파일당 수 분)
  config show | config set KEY VALUE
  cred status                    Atlassian 자격증명 확인 (값은 출력하지 않음)
  cred set                       터미널에서 직접 입력 (Claude 에게 토큰을 넘기지 않는다)
"""
import argparse
import base64
import datetime as dt
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

HOME = os.path.expanduser("~/.config/find-doc")
CONFIG = os.path.join(HOME, "config.json")
CRED = os.path.join(HOME, "credentials")
IDX_DIR = os.path.join(HOME, "index")
IDX = os.path.join(IDX_DIR, "figma.jsonl")
META = os.path.join(IDX_DIR, "meta.json")
TEAMS = os.path.join(IDX_DIR, "teams.json")
PROGRESS = os.path.join(IDX_DIR, "progress.json")
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)

DEFAULT_CONFIG = {
    "atlassian": {
        "jira_base": "",   # 예: https://<site>.atlassian.net  (setup 에서 입력)
        "conf_base": "",   # 예: https://<site>.atlassian.net/wiki
        "jira_projects": [],
        "conf_spaces": [],
    },
    "figma": {"enabled": False, "org_id": "", "org_name": "", "account": "", "focus_files": []},
    "extra_keywords": [],
    "default_scope": ["figma", "jira", "conf"],
}

BATCH = 40            # aside repl 1회 실행(120초 제한) 당 키워드 수
DELAY_MS = 1000       # 키워드 사이 간격
STALE_DAYS = 30       # 이 기간 안 보이면 stale
DROP_DAYS = 60        # 이 기간 안 보이면 인덱스에서 삭제
MAX_QUERIES = 400     # reindex 1회 검색 상한
MARK = "@@FD@@"
FIGMA_URL_RE = re.compile(
    r"https?://(?:www\.)?figma\.com/(design|file|proto|board|slides|deck|make)/([A-Za-z0-9]{10,})(?:/([^\s?#\"'<>)\]]*))?(?:\?[^\s\"'<>)\]]*)?")
STOP = {"copy", "untitled", "design", "file", "page", "new", "ver", "final", "draft", "test",
        "사본", "복사본", "최종", "수정", "작업", "작업공간", "공유", "모음", "and", "the", "for"}


# ---------- 공통 ----------

def out(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


def die(msg, code=1, **extra):
    out({"ok": False, "error": msg, **extra})
    sys.exit(code)


def now():
    return dt.datetime.now(dt.timezone.utc)


def today():
    return now().date().isoformat()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    if mode:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    user = load_json(CONFIG, {})
    for k, v in user.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def load_index():
    rows = {}
    try:
        with open(IDX, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    rows[r["key"]] = r
    except FileNotFoundError:
        pass
    return rows


def save_index(rows):
    os.makedirs(IDX_DIR, exist_ok=True)
    tmp = IDX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in sorted(rows.values(), key=lambda r: r.get("updated_at") or "", reverse=True):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, IDX)


def days_since(iso):
    if not iso:
        return 9999
    try:
        d = dt.date.fromisoformat(iso[:10])
    except ValueError:
        return 9999
    return (now().date() - d).days


def read_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip() and not l.startswith("#")]
    except FileNotFoundError:
        return []


def synonym_terms():
    """synonyms.md 의 '- 대표어: 동의어, 동의어' 줄에서 모든 단어."""
    terms = []
    for line in read_lines(os.path.join(SKILL_DIR, "synonyms.md")):
        m = re.match(r"^[-*]\s*(.+?)\s*:\s*(.+)$", line)
        if m:
            terms.append(m.group(1))
            terms += [t.strip() for t in m.group(2).split(",") if t.strip()]
    return terms


def uniq(seq):
    seen, res = set(), []
    for s in seq:
        k = s.strip().lower()
        if k and k not in seen:
            seen.add(k)
            res.append(s.strip())
    return res


# ---------- Aside / Figma ----------

def have_aside():
    return shutil.which("aside") is not None


def aside_js(js, timeout=170):
    """aside repl 에 JS 를 넣고 MARK 줄만 JSON 으로 돌려준다."""
    if not have_aside():
        die("aside CLI 가 없습니다. https://aside.com 에서 설치하면 Figma 인덱스를 쓸 수 있습니다.", code=3)
    try:
        p = subprocess.run([shutil.which("aside"), "repl"], input=js, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return [], "timeout"
    rows = []
    for line in (p.stdout or "").splitlines():
        i = line.find(MARK)
        if i >= 0:
            try:
                rows.append(json.loads(line[i + len(MARK):]))
            except json.JSONDecodeError:
                pass
    tail = "\n".join((p.stdout or "").splitlines()[-3:] + (p.stderr or "").splitlines()[-3:])
    return rows, tail


def js_prelude(tag):
    # 변수 이름은 REPL 세션 간 충돌을 피하려고 tag 를 붙인다
    return f"const fdTab{tag} = await openTab('https://www.figma.com/files/');\n"


def js_fetch(tag, expr_var, path_expr):
    return (f"const {expr_var} = await fdTab{tag}.evaluate(async (p) => {{\n"
            f"  try {{ const r = await fetch(p); const t = await r.text();\n"
            f"    let j = null; try {{ j = JSON.parse(t); }} catch (e) {{}}\n"
            f"    return {{ status: r.status, json: j, head: j ? null : t.slice(0, 120) }}; }}\n"
            f"  catch (e) {{ return {{ status: -1, err: String(e) }}; }}\n"
            f"}}, {path_expr});\n")


def figma_get(paths):
    """같은 탭에서 여러 경로를 GET. [{path,status,json}]"""
    tag = "G" + str(os.getpid())
    js = js_prelude(tag)
    for i, p in enumerate(paths):
        v = f"fdR{tag}_{i}"
        js += js_fetch(tag, v, json.dumps(p))
        js += f"console.log({json.dumps(MARK)} + JSON.stringify({{ path: {json.dumps(p)}, ...{v} }}));\n"
    js += f"await closeTab(fdTab{tag});\n"
    rows, tail = aside_js(js)
    if not rows:
        raise RuntimeError("Aside 로 Figma 를 열지 못했습니다. " + tail[-300:])
    return rows


def search_path(org, kw):
    q = urllib.parse.urlencode({
        "query": kw, "sort": "relevancy", "desc": "false", "is_global": "false",
        "org_id": org, "workspace_id": "", "current_org_id": org, "search_model_type": "files"})
    return "/api/search/full_results?" + q


def figma_search(org, keywords, on_result):
    """키워드 목록을 BATCH 단위로 검색. on_result(kw, status, items) 호출. 중단 사유 반환."""
    for b in range(0, len(keywords), BATCH):
        chunk = keywords[b:b + BATCH]
        tag = f"S{os.getpid()}_{b}"
        js = js_prelude(tag)
        js += f"const fdKws{tag} = {json.dumps(chunk, ensure_ascii=False)};\n"
        js += f"const fdOrg{tag} = {json.dumps(org)};\n"
        js += (
            f"for (const kw of fdKws{tag}) {{\n"
            f"  const qs = new URLSearchParams({{ query: kw, sort: 'relevancy', desc: 'false', is_global: 'false',"
            f" org_id: fdOrg{tag}, workspace_id: '', current_org_id: fdOrg{tag}, search_model_type: 'files' }});\n"
            f"  const r = await fdTab{tag}.evaluate(async (u) => {{\n"
            f"    try {{ const r = await fetch(u); if (r.status !== 200) return {{ status: r.status }};\n"
            f"      const j = await r.json(); const res = j && j.meta && j.meta.results;\n"
            f"      if (!Array.isArray(res)) return {{ status: 200, shape: false }};\n"
            f"      return {{ status: 200, items: res.map(x => {{ const m = x.model || {{}}; return {{\n"
            f"        key: m.key, name: m.name, url: m.url, editor_type: m.editor_type, team_id: m.team_id,\n"
            f"        folder_id: m.folder_id, updated_at: m.updated_at, created_at: m.created_at,\n"
            f"        trashed: !!(m.trashed_at || m.deleted_at), mq: x.matched_queries || [] }}; }}) }};\n"
            f"    }} catch (e) {{ return {{ status: -1, err: String(e) }}; }}\n"
            f"  }}, '/api/search/full_results?' + qs.toString());\n"
            f"  console.log({json.dumps(MARK)} + JSON.stringify({{ kw, ...r }}));\n"
            f"  if (r.status === 429) await sleep(30000); else if (r.status !== 200 || r.shape === false) break;\n"
            f"  else await sleep({DELAY_MS});\n"
            f"}}\n"
            f"await closeTab(fdTab{tag});\n")
        rows, tail = aside_js(js)
        if not rows:
            return f"aside 실행 실패: {tail}"
        for r in rows:
            st = r.get("status")
            if st in (401, 403):
                return "Figma 로그인이 필요합니다. Aside 브라우저에서 figma.com 에 로그인해 주세요."
            if st == 200 and r.get("shape") is False:
                return "Figma 내부 검색 API 응답 모양이 바뀌었습니다. figma-search 부분 수정이 필요합니다."
            if st != 200:
                continue
            on_result(r["kw"], r.get("items") or [])
    return None


def hit_kinds(mq):
    """matched_queries(예: page-name, frame-name, deep-search-text, fuzzy-name) → name/page/frame/text"""
    kinds = []
    for q in mq:
        kind = ("page" if q.startswith("page") else "frame" if q.startswith("frame")
                else "text" if q.startswith("deep-search") else "name" if "name" in q else "text")
        if kind not in kinds:
            kinds.append(kind)
    return kinds or ["text"]


def merge_item(rows, it, kw, teams, seen_day):
    key = it.get("key")
    if not key or it.get("trashed"):
        return False
    r = rows.get(key)
    is_new = r is None
    if is_new:
        r = {"key": key, "first_seen": seen_day, "source": "search", "hits": {}, "note": None}
        rows[key] = r
    r.update({
        "name": it.get("name") or r.get("name"),
        "url": it.get("url") or f"https://www.figma.com/design/{key}",
        "editor_type": it.get("editor_type") or r.get("editor_type"),
        "team_id": it.get("team_id") or r.get("team_id"),
        "team": teams.get(str(it.get("team_id")), r.get("team")),
        "folder_id": it.get("folder_id") or r.get("folder_id"),
        "updated_at": (it.get("updated_at") or r.get("updated_at") or "")[:10],
        "created_at": (it.get("created_at") or r.get("created_at") or "")[:10],
        "last_seen": seen_day,
    })
    r.setdefault("hits", {})[kw] = hit_kinds(it.get("mq") or [])
    return is_new


def name_tokens(name):
    toks = re.split(r"[^0-9A-Za-z가-힣]+", name or "")
    return [t for t in toks if len(t) >= 2 and not t.isdigit() and t.lower() not in STOP]


# ---------- 명령: doctor / config / cred ----------

def cred_load():
    e, t = os.environ.get("FIND_DOC_ATL_EMAIL"), os.environ.get("FIND_DOC_ATL_TOKEN")
    if e and t:
        return e, t
    c = load_json(CRED, {})
    return c.get("email"), c.get("token")


def cmd_cred(a):
    if a.action == "set":
        if not sys.stdin.isatty():
            die("터미널에서 직접 실행해 주세요: python3 " + os.path.abspath(__file__) + " cred set")
        email = input("Atlassian 이메일: ").strip()
        token = getpass.getpass("Atlassian API 토큰 (입력 내용은 안 보임): ").strip()
        if not email or not token:
            die("이메일과 토큰이 모두 필요합니다.")
        save_json(CRED, {"email": email, "token": token}, mode=0o600)
        print("저장했습니다:", CRED, file=sys.stderr)
    e, t = cred_load()
    out({"ok": bool(e and t), "credentials": bool(e and t), "path": CRED})


def cmd_config(a):
    cfg = load_config()
    if a.action == "set":
        try:
            val = json.loads(a.value)
        except (json.JSONDecodeError, TypeError):
            val = a.value
        node = cfg
        parts = a.key.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = val
        save_json(CONFIG, cfg)
    out({"ok": True, "config": cfg, "path": CONFIG})


def atl_request(base, path, params):
    if not base:
        raise RuntimeError("Atlassian 주소가 설정되지 않았습니다. /find-doc:setup 을 실행하세요.")
    e, t = cred_load()
    if not (e and t):
        raise RuntimeError("Atlassian 자격증명이 없습니다. 터미널에서 'finddoc.py cred set' 을 실행하세요.")
    url = base.rstrip("/") + path + "?" + urllib.parse.urlencode(params)
    auth = base64.b64encode(f"{e}:{t}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def cmd_doctor(a):
    cfg = load_config()
    meta = load_json(META, {})
    rep = {"ok": True, "config_path": CONFIG, "aside": have_aside(),
           "figma": {"enabled": cfg["figma"]["enabled"], "org_id": cfg["figma"]["org_id"],
                     "org_name": cfg["figma"]["org_name"]},
           "index": {"files": len(load_index()), "indexed_at": meta.get("indexed_at"),
                     "age_days": days_since(meta.get("indexed_at")) if meta.get("indexed_at") else None,
                     "resumable": os.path.exists(PROGRESS)},
           "atlassian": {"credentials": all(cred_load()),
                         "jira_projects": cfg["atlassian"]["jira_projects"],
                         "conf_spaces": cfg["atlassian"]["conf_spaces"]}}
    if a.online:
        if rep["aside"]:
            try:
                r = figma_get(["/api/user/plans"])[0]
                rep["figma"]["login"] = r.get("status") == 200
            except RuntimeError as ex:
                rep["figma"]["login"] = False
                rep["figma"]["error"] = str(ex)[:300]
        if rep["atlassian"]["credentials"]:
            for svc, base, path in (("jira", cfg["atlassian"]["jira_base"], "/rest/api/3/myself"),
                                    ("conf", cfg["atlassian"]["conf_base"], "/rest/api/space")):
                try:
                    atl_request(base, path, {"limit": 1} if svc == "conf" else {})
                    rep["atlassian"][svc + "_ok"] = True
                except Exception as ex:  # noqa: BLE001
                    rep["atlassian"][svc + "_ok"] = False
                    rep["atlassian"][svc + "_error"] = str(ex)[:200]
    out(rep)


# ---------- 명령: Figma 설정 ----------

def cmd_figma_orgs(a):
    try:
        r = figma_get(["/api/user/plans"])[0]
    except RuntimeError as ex:
        die(str(ex))
    if r.get("status") != 200:
        die("Figma 로그인이 필요합니다. Aside 브라우저에서 figma.com 에 로그인해 주세요.", status=r.get("status"))
    plans = ((r.get("json") or {}).get("meta") or {}).get("plans") or []
    orgs = [{"org_id": p.get("plan_id"), "name": p.get("plan_name")} for p in plans if p.get("plan_type") == "org"]
    out({"ok": True, "orgs": orgs})


def cmd_figma_setup(a):
    try:
        r = figma_get([f"/api/orgs/{a.org}/teams"])[0]
    except RuntimeError as ex:
        die(str(ex))
    teams = {}
    if r.get("status") == 200:
        for t in (r.get("json") or {}).get("meta") or []:
            teams[str(t.get("id"))] = t.get("name")
    cfg = load_config()
    cfg["figma"].update({"enabled": True, "org_id": a.org, "org_name": a.name or cfg["figma"].get("org_name", "")})
    save_json(CONFIG, cfg)
    save_json(TEAMS, teams)
    out({"ok": True, "org_id": a.org, "teams": len(teams), "teams_status": r.get("status")})


# ---------- 명령: reindex ----------

def cmd_reindex(a):
    cfg = load_config()
    org = cfg["figma"]["org_id"]
    if not cfg["figma"]["enabled"] or not org:
        die("Figma 설정이 없습니다. /find-doc:setup 을 먼저 실행하세요.")
    teams = load_json(TEAMS, {})
    meta = load_json(META, {})
    rows = load_index()
    day = today()

    prog = load_json(PROGRESS, None)
    if prog and days_since(prog.get("started")) <= 1 and not a.restart:
        queue, done, run_id = prog["queue"], prog["done"], prog["started"]
        print(f"이전 인덱싱을 이어서 진행합니다 ({len(done)}개 완료).", file=sys.stderr)
    else:
        base = (read_lines(os.path.join(SKILL_DIR, "seed-keywords.txt")) + synonym_terms()
                + cfg.get("extra_keywords", []) + meta.get("keywords", []))
        queue, done, run_id = uniq(base), [], day
    cap = a.max_queries
    new_files = 0
    rounds = prog.get("rounds", 0) if prog else 0

    def on_result(kw, items):
        nonlocal new_files
        for it in items:
            if merge_item(rows, it, kw, teams, day):
                new_files += 1

    while True:
        todo = [k for k in queue if k not in done][: max(0, cap - len(done))]
        if not todo:
            break
        before = len(rows)
        for b in range(0, len(todo), BATCH):
            chunk = todo[b:b + BATCH]
            err = figma_search(org, chunk, on_result)
            done += chunk if not err else []
            save_index(rows)
            save_json(PROGRESS, {"started": run_id, "queue": queue, "done": done, "rounds": rounds})
            print(f"  {len(done)}/{min(len(queue), cap)} 키워드, 파일 {len(rows)}개", file=sys.stderr)
            if err:
                die(err, progress=PROGRESS, done=len(done), files=len(rows))
        rounds += 1
        grown = len(rows) - before
        # 파일명에서 새 키워드를 뽑아 다음 바퀴 (최대 2바퀴 추가, 새 파일 2% 미만이면 종료)
        if rounds > 2 or len(done) >= cap or grown < max(1, int(len(rows) * 0.02)):
            break
        known = {k.lower() for k in queue}
        extra = []
        for r in rows.values():
            for t in name_tokens(r.get("name")):
                if t.lower() not in known:
                    known.add(t.lower())
                    extra.append(t)
        if not extra:
            break
        queue += extra[:150]

    # 오래 안 보인 검색 출처 파일 정리
    for k in [k for k, r in rows.items() if r.get("source") == "search" and days_since(r.get("last_seen")) > DROP_DAYS]:
        del rows[k]
    save_index(rows)
    meta.update({"indexed_at": now().isoformat(timespec="seconds"), "files": len(rows),
                 "keywords": uniq(meta.get("keywords", []) + done), "org_id": org})
    save_json(META, meta)
    if os.path.exists(PROGRESS):
        os.remove(PROGRESS)
    out({"ok": True, "files": len(rows), "new_files": new_files, "queries": len(done), "index": IDX})


# ---------- 명령: figma-query ----------

_ASCII = re.compile(r"^[0-9a-z ._-]+$")


def has(k, text):
    """k(소문자)가 text(소문자)에 있는가. 영문·숫자 키워드는 단어 경계로 (MB 가 combo 에 걸리지 않게)."""
    if _ASCII.match(k):
        return re.search(r"(?<![0-9a-z])" + re.escape(k) + r"(?![0-9a-z])", text) is not None
    return k in text


def score_row(r, kws):
    name = (r.get("name") or "").lower()
    hits = {k.lower(): v for k, v in (r.get("hits") or {}).items()}
    s, why = 0.0, []
    for kw in kws:
        k = kw.lower()
        got = False
        if has(k, name):
            s += 3
            got = True
        kinds = hits.get(k, [])
        if "name" in kinds and not has(k, name):
            s += 2
            got = True
        if "page" in kinds or "frame" in kinds:
            s += 1.5
            got = True
        elif "text" in kinds:
            s += 0.7
            got = True
        if r.get("note") and has(k, r["note"].lower()):
            s += 2
            got = True
        if got:
            why.append(kw)
    if not why:
        return 0, why
    if re.search(r"기획|spec|정책", name):
        s += 1
    age = days_since(r.get("updated_at"))
    s += 1 if age <= 90 else 0.5 if age <= 365 else 0
    if r.get("source") == "manual":
        s += 1
    if days_since(r.get("last_seen")) > STALE_DAYS and r.get("source") == "search":
        s -= 2
    return round(s, 2), why


def compact(r, score=None, why=None):
    return {"key": r["key"], "name": r.get("name"), "url": r.get("url"), "type": r.get("editor_type"),
            "team": r.get("team"), "updated_at": r.get("updated_at"),
            "hit_keywords": list((r.get("hits") or {}).keys())[:12], "note": r.get("note"),
            "stale": days_since(r.get("last_seen")) > STALE_DAYS and r.get("source") == "search",
            "score": score, "matched": why}


def cmd_figma_query(a):
    cfg = load_config()
    rows = load_index()
    kws = uniq(a.keywords)
    live = {"used": False}
    meta = load_json(META, {})
    if a.live and cfg["figma"]["enabled"] and have_aside():
        teams = load_json(TEAMS, {})
        day = today()
        added = []
        # 인덱스가 한 번도 돌리지 않은 질문 단어를 우선 실시간 검색 (없으면 앞 2개로 새 파일 확인)
        known = {k.lower() for k in meta.get("keywords", [])}
        unknown = [k for k in uniq((a.must or []) + kws) if k.lower() not in known]  # 필수 맥락 단어 우선
        live_kws = unknown[:4] or kws[:2]

        def on_result(kw, items):
            for it in items:
                if merge_item(rows, it, kw, teams, day):
                    added.append(it.get("name"))
        err = figma_search(cfg["figma"]["org_id"], live_kws, on_result)
        save_index(rows)
        if not err and unknown:
            # 다음 reindex 부터 이 단어도 같이 돌린다
            meta["keywords"] = uniq(meta.get("keywords", []) + live_kws)
            save_json(META, meta)
        live = {"used": True, "keywords": live_kws, "error": err, "new_files": added}
    must = [m.lower() for m in (a.must or [])]
    scored = []
    for r in rows.values():
        if must:
            # 필수 맥락: 파일 이름에 있거나, 그 단어로 검색했을 때 이 파일이 걸렸어야 한다
            hk = {k.lower() for k in (r.get("hits") or {})}
            if not all(has(m, (r.get("name") or "").lower()) or m in hk for m in must):
                continue
        s, why = score_row(r, kws)
        if s > 0:
            scored.append((s, r, why))
    focus = {f["key"] for f in cfg["figma"].get("focus_files", [])}
    for i, (s, r, why) in enumerate(scored):
        if r["key"] in focus:
            scored[i] = (s + 2, r, why)
    scored.sort(key=lambda x: (-x[0], x[1].get("updated_at") or ""))
    layers = layer_query(kws, a.layer_limit, must)
    out({"ok": True, "keywords": kws, "must": must, "index_files": len(rows),
         "index_age_days": days_since(meta.get("indexed_at")) if meta.get("indexed_at") else None,
         "live": live, "candidates": [dict(compact(r, s, w), focus=r["key"] in focus) for s, r, w in scored[: a.limit]],
         "layer_index": {"files": len(meta.get("layers", {}))}, "layer_candidates": layers})


# ---------- 지정 파일 (focus) + 레이어 인덱스 ----------

LAYER_DIR = os.path.join(IDX_DIR, "layers")
KEEP_TYPES = {"FRAME", "SECTION", "TEXT", "COMPONENT", "COMPONENT_SET", "GROUP", "SHAPE_WITH_TEXT", "STICKY"}
SAVE_BUDGET_MS = 100000     # aside repl 1회(120초 제한) 안에서 저장을 기다리는 시간


def node_url(key, node):
    return f"https://www.figma.com/design/{key}?node-id={node.replace(':', '-')}"


TEAM_RE = re.compile(r"figma\.com/files/(?:[^/]+/)?team/(\d+)")
FOLDER_RE = re.compile(r"figma\.com/files/(?:[^/]+/)?project/(\d+)")
CRAWL_TYPES = {"design"}  # .fig 로 저장·해석되는 종류 (FigJam·Slides 는 형식이 달라 제외)


def team_files(url):
    """팀 또는 프로젝트(폴더) 링크 → (출처 설명, 파일 목록). 팀 멤버여야 목록을 볼 수 있다."""
    m_team, m_folder = TEAM_RE.search(url), FOLDER_RE.search(url)
    if not (m_team or m_folder):
        raise RuntimeError("팀(…/files/…/team/<id>/…) 또는 프로젝트(…/project/<id>/…) 링크가 아닙니다.")
    if m_team:
        tid = m_team.group(1)
        r = figma_get([f"/api/teams/{tid}", f"/api/teams/{tid}/folders"])
        if r[1].get("status") != 200:
            raise RuntimeError(f"팀 폴더 목록을 볼 수 없습니다 (HTTP {r[1].get('status')}). 이 팀의 멤버인지 확인하세요.")
        tname = ((r[0].get("json") or {}).get("meta") or {}).get("name") or tid
        rows = ((r[1].get("json") or {}).get("meta") or {}).get("folder_rows") or []
        folders = [(f["id"], f.get("name") or f.get("path") or f["id"]) for f in rows
                   if not f.get("trashed_at") and not f.get("deleted_at")]
        src = {"kind": "team", "id": tid, "name": tname, "url": url}
    else:
        fid = m_folder.group(1)
        folders = [(fid, None)]
        src = {"kind": "project", "id": fid, "name": None, "url": url}
    files = []
    if folders:
        r = figma_get([f"/api/folders/{fid}/files" for fid, _ in folders])
        for (fid, fname), resp in zip(folders, r):
            if resp.get("status") != 200:
                print(f"  프로젝트 {fname or fid}: 볼 수 없음 (HTTP {resp.get('status')})", file=sys.stderr)
                continue
            meta = (resp.get("json") or {}).get("meta") or {}
            fname = fname or (meta.get("folder") or {}).get("name") or (meta.get("folder") or {}).get("path") or fid
            if src["kind"] == "project" and not src["name"]:
                src["name"] = fname
            for f in meta.get("files") or []:
                if f.get("trashed_at") or f.get("deleted_at") or f.get("source_file_key"):
                    continue  # 휴지통·삭제·브랜치 제외
                files.append({"key": f["key"], "name": f.get("name") or f["key"], "editor_type": f.get("editor_type"),
                              "updated_at": (f.get("updated_at") or "")[:10], "folder": fname,
                              "url": f"https://www.figma.com/design/{f['key']}"})
    return src, files


def sync_focus_teams(cfg, verbose=True):
    """등록된 팀·프로젝트의 파일 목록을 다시 받아 지정 파일에 반영한다 (새 파일 추가, 수정일 갱신)."""
    files = cfg["figma"].setdefault("focus_files", [])
    by_key = {f["key"]: f for f in files}
    added, skipped_types = [], 0
    for t in cfg["figma"].get("focus_teams", []):
        try:
            src, tf = team_files(t["url"])
        except RuntimeError as ex:
            print(f"  팀 {t.get('name')}: {ex}", file=sys.stderr)
            continue
        for f in tf:
            if f["editor_type"] not in CRAWL_TYPES:
                skipped_types += 1
                continue
            cur = by_key.get(f["key"])
            if cur:
                cur.update({"name": f["name"], "updated_at": f["updated_at"], "folder": f["folder"]})
            else:
                e = {"key": f["key"], "name": f["name"], "url": f["url"], "updated_at": f["updated_at"],
                     "folder": f["folder"], "team": src["name"]}
                files.append(e)
                by_key[f["key"]] = e
                added.append(f["name"])
    save_json(CONFIG, cfg)
    if verbose and added:
        print(f"  팀에서 새 파일 {len(added)}개 추가", file=sys.stderr)
    return added, skipped_types


def cmd_focus(a):
    cfg = load_config()
    files = cfg["figma"].setdefault("focus_files", [])
    if a.action == "add":
        rows = load_index()
        added = []
        for u in a.urls:
            f = parse_figma_url(u)
            if not f:
                print(f"Figma 링크가 아니라서 건너뜀: {u}", file=sys.stderr)
                continue
            if any(x["key"] == f["key"] for x in files):
                continue
            name = (rows.get(f["key"]) or {}).get("name") or f["name"] or f["key"]
            files.append({"key": f["key"], "name": name, "url": f"https://www.figma.com/design/{f['key']}"})
            added.append(name)
        save_json(CONFIG, cfg)
        out({"ok": True, "added": added, "focus_files": files})
    elif a.action == "add-team":
        if not a.urls:
            die("팀 또는 프로젝트 링크가 필요합니다.")
        teams = cfg["figma"].setdefault("focus_teams", [])
        srcs = []
        for u in a.urls:
            try:
                src, tf = team_files(u)
            except RuntimeError as ex:
                die(str(ex), url=u)
            if not any(t["kind"] == src["kind"] and t["id"] == src["id"] for t in teams):
                teams.append(src)
            srcs.append({**src, "files": len(tf), "design_files": sum(f["editor_type"] in CRAWL_TYPES for f in tf)})
        added, skipped = sync_focus_teams(cfg, verbose=False)
        todo = len(added)
        out({"ok": True, "sources": srcs, "added": len(added), "added_names": added[:30],
             "skipped_non_design": skipped, "focus_files": len(cfg["figma"]["focus_files"]),
             "estimate_minutes": [todo * 1, todo * 3],
             "next": "crawl 을 실행하면 새로 추가된 파일을 하나씩 인덱싱합니다 (파일당 1~3분, 중간에 멈춰도 다시 실행하면 이어서)."})
    elif a.action == "remove":
        cfg["figma"]["focus_files"] = [x for x in files if x["key"] not in a.urls]
        cfg["figma"]["focus_teams"] = [t for t in cfg["figma"].get("focus_teams", []) if t["id"] not in a.urls]
        save_json(CONFIG, cfg)
        out({"ok": True, "focus_files": cfg["figma"]["focus_files"]})
    else:
        lm = load_json(META, {}).get("layers", {})
        out({"ok": True, "focus_teams": cfg["figma"].get("focus_teams", []),
             "focus_files": [dict(x, layers=(lm.get(x["key"]) or {}).get("layers")) for x in files]})


# Figma 가 자동으로 붙인 이름 (Frame 427320828, Group 3472520 …) — 검색에 쓸모없어 저장·표시에서 뺀다
AUTO_NAME = re.compile(r"^(Frame|Group|Auto layout|Section|Rectangle|Vector|Ellipse|Line|Polygon|Component|"
                       r"Instance|Image|Mask|Union|Subtract|Text|Container|Slice)\s*\d+$", re.I)


def clean_path(path):
    return " › ".join(p for p in path.split(" › ") if not AUTO_NAME.match(p))


def downloads_dir():
    return os.path.join(os.path.expanduser("~"), "Downloads")


_LOCK = threading.Lock()          # meta.json·config 쓰기, 다운로드 파일 선점
_PARSE_LOCK = threading.Lock()    # .fig 해석은 메모리를 많이 써서 한 번에 하나
_NAME_LOCKS = {}                  # 같은 이름 파일은 동시에 저장하지 않는다 (다운로드 이름이 겹침)
_CLAIMED = set()


def _norm(n):
    return re.sub(r"[^0-9a-z가-힣]+", "", (n or "").lower())


def find_saved_fig(after_ts, name):
    """다운로드 폴더에서 방금 저장된 '<파일명>( - Partial file saved …).fig' 를 이름으로 찾아 선점한다."""
    d = downloads_dir()
    want = _norm(name)
    best = None
    with _LOCK:
        for fn in os.listdir(d) if os.path.isdir(d) else []:
            if not fn.lower().endswith(".fig"):
                continue
            p = os.path.join(d, fn)
            if p in _CLAIMED or os.path.getmtime(p) < after_ts - 2:
                continue
            if want and not _norm(fn).startswith(want[:60]):
                continue
            mt = os.path.getmtime(p)
            if best is None or mt > best[0]:
                best = (mt, p)
        if best:
            _CLAIMED.add(best[1])
    return best[1] if best else None


def save_fig(f, tab_id=None):
    """Aside 로 .fig 로컬 사본을 저장하고 경로를 돌려준다. 같은 이름 파일은 동시에 저장하지 않는다."""
    with _LOCK:
        lk = _NAME_LOCKS.setdefault(_norm(f["name"]), threading.Lock())
    with lk:
        return _save_fig(f, tab_id)


def _save_fig(f, tab_id=None):
    tpl = open(os.path.join(HERE, "save-fig.js"), encoding="utf-8").read()
    params = {"key": f["key"], "tabId": tab_id, "budgetMs": SAVE_BUDGET_MS, "mac": sys.platform == "darwin",
              "account": load_config()["figma"].get("account", "")}
    t0 = now().timestamp()
    js = tpl.replace("__TAG__", f"F{os.getpid()}").replace("__FD_PARAMS__", json.dumps(params))
    rows, tail = aside_js(js, timeout=170)
    done = next((r for r in rows if r.get("kind") in ("done", "error")), None)
    if not done:
        return None, f"aside 실행 실패: {tail[-200:]}"
    if done["kind"] == "error":
        hint = ""
        if done.get("error") == "no-save-action":
            hint = (" — 자동으로 'Save local copy' 를 열지 못했습니다. Figma 에서 직접 메인 메뉴 › File › Save local copy 로 "
                    "받은 뒤 'crawl --key <file key> --fig <받은 .fig 경로>' 로 인덱싱하세요.")
        return None, f"Figma 저장 실패: {done.get('error')}{hint}"
    if done.get("state") != "saved":
        return None, ("120초 안에 저장이 끝나지 않았습니다 (아주 큰 파일). Aside 에서 이 파일을 직접 열어 두고 "
                      "'crawl --tab' 으로 다시 실행하세요.")
    for _ in range(30):  # 다운로드 마무리 대기
        p = find_saved_fig(t0, f["name"])
        if p and not os.path.exists(p + ".crdownload"):
            return p, None
        import time as _t
        _t.sleep(1)
    return None, "다운로드 폴더에서 .fig 를 찾지 못했습니다."


def crawl_file(f, force, tab_id=None, fig_path=None):
    import figfile
    key = f["key"]
    meta = load_json(META, {})
    prev = meta.get("layers", {}).get(key, {})
    file_updated = f.get("updated_at") or (load_index().get(key) or {}).get("updated_at")
    if (not force and prev.get("complete") and days_since(prev.get("crawled_at")) < 30
            and (not file_updated or file_updated <= (prev.get("crawled_at") or "")[:10])):
        return {"key": key, "name": f["name"], "skipped": "최근에 인덱싱했고 파일 수정이 없음"}
    t0 = now()
    os.makedirs(LAYER_DIR, exist_ok=True)
    work = os.path.join(LAYER_DIR, key + ".fig")
    if fig_path:  # 사용자가 직접 받은 .fig (아주 큰 파일용)
        shutil.copyfile(fig_path, work)
    else:
        path, err = save_fig(f, tab_id)
        if err:
            return {"key": key, "name": f["name"], "error": err}
        shutil.move(path, work)  # 다운로드 폴더에 남기지 않는다
    size_mb = round(os.path.getsize(work) / 1e6, 1)
    try:
        t1 = now()
        with _PARSE_LOCK:
            rows = figfile.layers(work)
        parse_s = int((now() - t1).total_seconds())
    except Exception as ex:  # noqa: BLE001
        bad = work + ".failed"
        os.replace(work, bad)  # 해석기 수정용으로 남긴다 (다음 성공 시 지움)
        return {"key": key, "name": f["name"], "error": f".fig 해석 실패: {type(ex).__name__}: {str(ex)[:120]}",
                "kept_for_debug": bad}
    os.remove(work)
    if os.path.exists(work + ".failed"):
        os.remove(work + ".failed")
    tmp = os.path.join(LAYER_DIR, key + ".jsonl.tmp")
    kept = 0
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            if r["type"] not in KEEP_TYPES or not r["name"] or AUTO_NAME.match(r["name"]):
                continue
            if r["type"] == "TEXT" and r["level"] > 12:
                continue
            fh.write(json.dumps({"key": key, "file": f["name"], **r, "path": clean_path(r["path"])},
                                ensure_ascii=False) + "\n")
            kept += 1
    os.replace(tmp, os.path.join(LAYER_DIR, key + ".jsonl"))
    with _LOCK:
        _save_layer_meta(key, f["name"], rows, kept)
    return {"key": key, "name": f["name"], "fig_mb": size_mb, "nodes": len(rows), "layers": kept,
            "parse_seconds": parse_s, "seconds": int((now() - t0).total_seconds())}


def _save_layer_meta(key, name, rows, kept):
    meta = load_json(META, {})
    meta.setdefault("layers", {})[key] = {"name": name, "crawled_at": now().isoformat(timespec="seconds"),
                                          "pages": len({r["page_id"] for r in rows}), "nodes": len(rows),
                                          "layers": kept, "complete": True}
    save_json(META, meta)


def cmd_crawl(a):
    cfg = load_config()
    if cfg["figma"].get("focus_teams") and not a.key and not a.fig:
        sync_focus_teams(cfg)
    files = cfg["figma"].get("focus_files", [])
    if a.key:
        files = [f for f in files if f["key"] in a.key]
    if not files:
        die("지정 파일이 없습니다. 'focus add <figma URL...>' 로 먼저 등록하세요.")
    if a.limit:
        files = files[: a.limit]
    res, cnt = [], [0]
    workers = max(1, min(a.workers, 6)) if not (a.fig or a.tab) else 1

    def run(f):
        r = crawl_file(f, a.force, a.tab, a.fig)
        with _LOCK:
            cnt[0] += 1
            msg = r.get("error") or r.get("skipped") or f"{r.get('layers')}개 레이어 ({r.get('seconds')}초)"
            print(f"  [{cnt[0]}/{len(files)}] {f['name']}: {msg}", file=sys.stderr, flush=True)
        return r

    if workers == 1:
        res = [run(f) for f in files]
    else:
        from concurrent.futures import ThreadPoolExecutor
        print(f"  {len(files)}개 파일을 탭 {workers}개로 동시에 처리합니다", file=sys.stderr, flush=True)
        with ThreadPoolExecutor(workers) as ex:
            res = list(ex.map(run, files))
    done = [r for r in res if "layers" in r]
    out({"ok": all("error" not in r for r in res), "indexed": len(done),
         "skipped": sum("skipped" in r for r in res), "errors": [r for r in res if "error" in r],
         "layers_total": sum(r["layers"] for r in done), "files": res if len(res) <= 10 else done[:10]})


def layer_query(kws, limit, must=None):
    if not os.path.isdir(LAYER_DIR):
        return []
    ks = [k.lower() for k in kws]
    hits = []
    for fn in os.listdir(LAYER_DIR):
        if not fn.endswith(".jsonl"):
            continue
        with open(os.path.join(LAYER_DIR, fn), encoding="utf-8") as fh:
            pages_seen = set()
            for line in fh:
                r = json.loads(line)
                if r["page_id"] not in pages_seen:
                    # 페이지 자체도 후보 (페이지는 레이어 행이 아니라서 따로 만든다)
                    pages_seen.add(r["page_id"])
                    pn = r["page"].lower()
                    pw = [k for k in ks if has(k, pn)]
                    if pw and all(has(m, pn) for m in must or []):
                        s = 3 * len(pw) + (3 if len(pw) == len(ks) and len(ks) > 1 else 0) + 1.5
                        hits.append((round(s, 2), {"key": r["key"], "file": r["file"], "page": r["page"],
                                                   "page_id": r["page_id"], "node": r["page_id"], "name": r["page"],
                                                   "type": "Page", "level": -1, "path": r["page"]}, pw))
                if AUTO_NAME.match(r["name"]):
                    continue
                name = (r["name"] + " " + (r.get("text") or "")).lower()
                path = r["path"].lower()
                if must and not all(has(m, path) or has(m, name) for m in must):
                    continue  # 필수 맥락(페이지·상위 프레임·이름)에 없는 레이어는 제외
                s, in_name, in_path = 0.0, [], []
                for k in ks:
                    if has(k, name):
                        s += 3
                        in_name.append(k)
                    elif has(k, path):
                        s += 1.5  # 상위 페이지·프레임이 맥락을 준다
                        in_path.append(k)
                why = in_name + in_path
                if not in_name:
                    continue  # 레이어 이름에 하나도 없으면 상위 노드가 대신 걸린다
                if len(why) == len(ks) and len(ks) > 1:
                    s += 3  # 질문 단어를 모두 덮음
                if len(ks) > 1 and has(" ".join(ks), name):
                    s += 3  # 질문 구절이 이름에 그대로
                if r.get("type") in ("FRAME", "SECTION", "COMPONENT", "COMPONENT_SET"):
                    s += 1
                elif r.get("type") == "TEXT" and len(r["name"]) > 60:
                    s -= 1.5  # 긴 본문 텍스트보다 제목·프레임을 우선
                s -= 0.15 * min(r.get("level", 0), 10)  # 얕은(대표) 노드 우선
                hits.append((round(s, 2), r, why))
    hits.sort(key=lambda x: (-x[0], x[1].get("level", 0)))
    kept, res, same = [], [], set()
    for s, r, why in hits:
        cp = (r["key"], clean_path(r["path"]))
        if cp in same:
            continue  # 같은 경로의 사본 프레임은 하나만
        same.add(cp)
        # 이미 고른 노드의 자손이면서 새 단어를 더 덮지 않으면 건너뜀
        if any(r["key"] == k["key"] and r["path"].startswith(k["path"] + " › ") and set(why) <= set(k["why"])
               for k in kept if k["type"] != "Page"):
            continue
        kept.append({"key": r["key"], "path": r["path"], "why": why, "type": r.get("type")})
        res.append({"file": r["file"], "key": r["key"], "page": r["page"], "name": r["name"], "type": r["type"],
                    "path": clean_path(r["path"])[:200], "url": node_url(r["key"], r["node"]), "score": s,
                    "matched": why})
        if len(res) >= limit:
            break
    return res


# ---------- 명령: add ----------

def parse_figma_url(u):
    m = FIGMA_URL_RE.search(u)
    if not m:
        return None
    slug = urllib.parse.unquote(m.group(3) or "").replace("-", " ").strip()
    node = urllib.parse.parse_qs(urllib.parse.urlparse(m.group(0)).query).get("node-id", [None])[0]
    return {"kind": m.group(1), "key": m.group(2), "name": slug or None, "node": node, "url": m.group(0)}


def cmd_add(a):
    f = parse_figma_url(a.url)
    if not f:
        die("Figma 링크 형식이 아닙니다.")
    rows = load_index()
    r = rows.get(f["key"]) or {"key": f["key"], "first_seen": today(), "hits": {}, "source": "manual"}
    r.update({"name": r.get("name") or f["name"] or f["key"], "url": r.get("url") or f["url"].split("?")[0],
              "note": " ".join(a.note) or r.get("note"), "last_seen": today()})
    if r.get("source") != "search":
        r["source"] = "manual"
    rows[f["key"]] = r
    save_index(rows)
    out({"ok": True, "entry": compact(r)})


# ---------- 명령: atl-search (Jira·Confluence) ----------

def adf_text(node, acc, urls):
    if isinstance(node, dict):
        if node.get("type") == "text":
            acc.append(node.get("text", ""))
            for mk in node.get("marks") or []:
                href = (mk.get("attrs") or {}).get("href")
                if href:
                    urls.append(href)
        url = (node.get("attrs") or {}).get("url")
        if url:
            urls.append(url)
        for c in node.get("content") or []:
            adf_text(c, acc, urls)
    elif isinstance(node, list):
        for c in node:
            adf_text(c, acc, urls)


def snippet(text, kws, width=160):
    text = re.sub(r"\s+", " ", text or "").strip()
    low = text.lower()
    for kw in kws:
        i = low.find(kw.lower())
        if i >= 0:
            s = max(0, i - width // 2)
            return ("…" if s else "") + text[s:s + width] + ("…" if s + width < len(text) else "")
    return text[:width]


def figma_links(urls_or_text):
    found = {}
    for u in urls_or_text:
        for m in FIGMA_URL_RE.finditer(u or ""):
            f = parse_figma_url(m.group(0))
            if f:
                found.setdefault(f["key"], f)
    return list(found.values())


def jql_quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def cmd_atl_search(a):
    cfg = load_config()
    at = cfg["atlassian"]
    scope = [s.strip() for s in a.scope.split(",")]
    kws = uniq(a.kw or [a.query])
    res = {"ok": True, "query": a.query, "keywords": kws, "jira": [], "confluence": [], "errors": []}

    index = load_index()

    def name_links(links):
        for f in links:
            r = index.get(f["key"])
            if r:
                f["name"] = r.get("name")
                f["team"] = r.get("team")
        return links

    if "jira" in scope:
        projects = [p for p in (a.jira or ",".join(at["jira_projects"])).split(",") if p]
        pre = f"project in ({','.join(projects)}) AND " if projects else ""
        wild = lambda kw: jql_quote(kw + "*") if " " not in kw else jql_quote(kw)  # noqa: E731
        # 제목에 걸린 이슈를 먼저, 본문·댓글에 걸린 이슈로 나머지를 채운다 (최신순에 묻히지 않게)
        jqls = [pre + "(" + " OR ".join(f"summary ~ {wild(k)}" for k in kws[:6]) + ") ORDER BY updated DESC",
                pre + "(" + " OR ".join(f"text ~ {wild(k)}" for k in kws[:6]) + ") ORDER BY updated DESC"]
        try:
            issues, seen = [], set()
            for jql in jqls:
                j = atl_request(at["jira_base"], "/rest/api/3/search/jql",
                                {"jql": jql, "maxResults": a.limit,
                                 "fields": "summary,status,updated,description,issuetype"})
                for it in j.get("issues", []):
                    if it["key"] not in seen and len(issues) < a.limit:
                        seen.add(it["key"])
                        issues.append(it)
            for it in issues:
                fl = it.get("fields") or {}
                acc, urls = [], []
                adf_text(fl.get("description"), acc, urls)
                body = " ".join(acc)
                res["jira"].append({
                    "id": it["key"], "type": "jira", "title": fl.get("summary"),
                    "url": at["jira_base"].rstrip("/") + "/browse/" + it["key"],
                    "status": (fl.get("status") or {}).get("name"),
                    "issuetype": (fl.get("issuetype") or {}).get("name"),
                    "updated": (fl.get("updated") or "")[:10],
                    "title_hit": any(k.lower() in (fl.get("summary") or "").lower() for k in kws),
                    "snippet": snippet(body, kws), "figma_links": name_links(figma_links(urls + [body]))})
        except Exception as ex:  # noqa: BLE001
            res["errors"].append({"source": "jira", "error": str(ex)[:300], "jql": jqls})

    if "conf" in scope:
        spaces = [s for s in (a.conf or ",".join(at["conf_spaces"])).split(",") if s]
        pre = ("space in (" + ",".join(jql_quote(x) for x in spaces) + ") AND ") if spaces else ""
        # 제목에 걸린 페이지를 먼저, 본문에 걸린 페이지로 나머지를 채운다 (최신순에 묻히지 않게)
        cqls = [pre + "type = page AND (" + " AND ".join(f"title ~ {jql_quote(k)}" for k in kws[:4]) + ") ORDER BY lastmodified DESC",
                pre + "type = page AND (" + " OR ".join(f"title ~ {jql_quote(k)}" for k in kws[:6]) + ") ORDER BY lastmodified DESC",
                pre + "type = page AND (" + " AND ".join(f"text ~ {jql_quote(k)}" for k in kws[:4]) + ") ORDER BY lastmodified DESC",
                pre + "type = page AND (" + " OR ".join(f"text ~ {jql_quote(k)}" for k in kws[:6]) + ") ORDER BY lastmodified DESC"]
        cql = cqls
        try:
            results, seen = [], set()
            for q in cqls:
                if len(results) >= a.limit:
                    break
                j = atl_request(at["conf_base"], "/rest/api/content/search",
                                {"cql": q, "limit": a.limit, "expand": "body.storage,version,space"})
                for it in j.get("results", []):
                    if it.get("id") not in seen and len(results) < a.limit:
                        seen.add(it.get("id"))
                        results.append(it)
            j = {"results": results}
            for it in j.get("results", []):
                html = ((it.get("body") or {}).get("storage") or {}).get("value", "")
                text = re.sub(r"<[^>]+>", " ", html)
                res["confluence"].append({
                    "id": it.get("id"), "type": "confluence", "title": it.get("title"),
                    "url": at["conf_base"].rstrip("/") + ((it.get("_links") or {}).get("webui") or ""),
                    "space": (it.get("space") or {}).get("key"),
                    "updated": ((it.get("version") or {}).get("when") or "")[:10],
                    "title_hit": any(k.lower() in (it.get("title") or "").lower() for k in kws),
                    "snippet": snippet(text, kws), "figma_links": name_links(figma_links([html]))})
        except Exception as ex:  # noqa: BLE001
            res["errors"].append({"source": "confluence", "error": str(ex)[:300], "cql": cql})
    out(res)


def cmd_atl_list(a):
    """setup 용: 접근 가능한 Jira 프로젝트 / Confluence 스페이스 목록 (최근 활동 순)"""
    at = load_config()["atlassian"]
    try:
        if a.what == "jira":
            j = atl_request(at["jira_base"], "/rest/api/3/project/search",
                            {"maxResults": 100, "orderBy": "-lastIssueUpdatedTime", "expand": "insight"})
            items = [{"key": p["key"], "name": p["name"],
                      "last_update": ((p.get("insight") or {}).get("lastIssueUpdateTime") or "")[:10]}
                     for p in j.get("values", [])]
        else:
            j = atl_request(at["conf_base"], "/api/v2/spaces", {"limit": 250, "type": "global", "status": "current"})
            items = [{"key": s["key"], "name": s["name"]} for s in j.get("results", [])]
    except Exception as ex:  # noqa: BLE001
        die(f"{a.what} 목록 조회 실패: {str(ex)[:200]}")
    out({"ok": True, "what": a.what, "items": items})


# ---------- main ----------

def main():
    # Windows 콘솔(cp949)에서 한글·이모지 출력이 깨지거나 오류 나지 않게
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("doctor"); p.add_argument("--online", action="store_true"); p.set_defaults(fn=cmd_doctor)
    p = sp.add_parser("figma-orgs"); p.set_defaults(fn=cmd_figma_orgs)
    p = sp.add_parser("figma-setup"); p.add_argument("--org", required=True); p.add_argument("--name", default="")
    p.set_defaults(fn=cmd_figma_setup)
    p = sp.add_parser("reindex"); p.add_argument("--max-queries", type=int, default=MAX_QUERIES)
    p.add_argument("--restart", action="store_true"); p.set_defaults(fn=cmd_reindex)
    p = sp.add_parser("figma-query"); p.add_argument("keywords", nargs="+"); p.add_argument("--live", action="store_true")
    p.add_argument("--limit", type=int, default=30); p.add_argument("--layer-limit", type=int, default=20)
    p.add_argument("--must", nargs="*", help="필수 맥락 단어: 페이지·상위 프레임·이름에 반드시 있어야 하는 단어 (예: 파싱)")
    p.set_defaults(fn=cmd_figma_query)
    p = sp.add_parser("focus"); p.add_argument("action", choices=["add", "add-team", "remove", "list"]); p.add_argument("urls", nargs="*")
    p.set_defaults(fn=cmd_focus)
    p = sp.add_parser("crawl"); p.add_argument("--key", nargs="*"); p.add_argument("--force", action="store_true")
    p.add_argument("--tab", help="Aside 에 직접 열어 둔 Figma 탭 id (큰 파일용)")
    p.add_argument("--fig", help="직접 받은 .fig 파일 경로 (--key 하나와 함께)")
    p.add_argument("--limit", type=int, help="이번에 처리할 최대 파일 수 (나머지는 다음 실행 때)")
    p.add_argument("--workers", type=int, default=3, help="동시에 여는 Figma 탭 수 (기본 3, 최대 6)")
    p.set_defaults(fn=cmd_crawl)
    p = sp.add_parser("atl-search"); p.add_argument("query"); p.add_argument("--kw", nargs="*")
    p.add_argument("--in", dest="scope", default="jira,conf"); p.add_argument("--jira"); p.add_argument("--conf")
    p.add_argument("--limit", type=int, default=25); p.set_defaults(fn=cmd_atl_search)
    p = sp.add_parser("atl-list"); p.add_argument("what", choices=["jira", "conf"]); p.set_defaults(fn=cmd_atl_list)
    p = sp.add_parser("add"); p.add_argument("url"); p.add_argument("note", nargs="*"); p.set_defaults(fn=cmd_add)
    p = sp.add_parser("config"); p.add_argument("action", choices=["show", "set"]); p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_config)
    p = sp.add_parser("cred"); p.add_argument("action", choices=["status", "set"]); p.set_defaults(fn=cmd_cred)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
