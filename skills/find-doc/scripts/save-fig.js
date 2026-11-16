// find-doc: Figma 파일의 로컬 사본(.fig)을 이미지 없이 저장한다 (aside mcp 세션의 repl 에서 실행)
// finddoc.py 가 __FD_PARAMS__ 를 {mode, key, tabId, budgetMs, mac, account} 로 바꿔 넣는다.
//
// repl 한 번은 120초 제한이라 큰 파일은 한 번에 저장이 안 끝난다. 그래서 같은 aside mcp 세션 안에서
//   mode 'start' : 파일 열기 → (계정 선택) → 빠른 실행 "Save local copy…" → 기다림
//   mode 'poll'  : 같은 탭에서 계속 기다림 (globalThis.__fd 에 탭을 보관)
//   mode 'close' : 탭 정리
// 로 나눠 부른다. 저장 흐름: Figma 가 모든 페이지 내용을 받는 동안("Downloading contents…") 기다리다가
// 이미지 단계("Downloading images…")가 되면 "Save partial file" → 기본 다운로드 폴더에 .fig 가 생긴다.
// Figma 화면 문구에 의존한다. 깨지면 아래 문자열만 고치면 된다.

await (async () => {
  const P = __FD_PARAMS__;
  const T0 = Date.now();
  const emit = (o) => console.log('@@FD@@' + JSON.stringify(o));
  const G = (globalThis.__fd = globalThis.__fd || {});
  const mod = P.mac ? 'Meta' : 'Control';

  async function closeIt(S) {
    if (!S || !S.tab || !S.own) return;
    // 바로 닫는다. 무거운 Figma 탭이라 닫기가 실패했을 때만 페이지를 비우고 다시 닫는다.
    try { await closeTab(S.tab); return; } catch (e) {}
    try { await S.tab.goto('about:blank', { timeout: 10000 }); } catch (e) {}
    try { await closeTab(S.tab); } catch (e) {}
  }

  async function waitSaved(S) {
    // 'saved' 또는 'pending'(아직 받는 중) 을 돌려준다
    while (Date.now() - T0 < P.budgetMs) {
      await sleep(1500);
      const s = await snapshot(S.tab);  // 스냅샷은 한 번만 (새 스냅샷은 이전 ref 를 무효화한다)
      const partial = s.tree.match(/button "Save partial file" \[ref=(e\d+)\]/);
      const al = (s.tree.match(/alert: "[^"]*"/g) || []).join(' | ');
      if (/Downloading/i.test(al)) S.seen = true;
      if (partial && /Downloading images/i.test(al)) {
        await S.tab.locator(partial[1]).click();
        return 'saved';
      }
      if (S.seen && !partial && !/Downloading/i.test(al)) return 'saved';  // 이미지가 없으면 바로 저장된다
    }
    return 'pending';
  }

  if (P.mode === 'close') {
    await closeIt(G[P.key]);
    delete G[P.key];
    emit({ kind: 'done', state: 'closed' });
    return;
  }

  let S = G[P.key];
  try {
    if (P.mode === 'start' || !S) {
      await closeIt(S);
      const own = !P.tabId;
      const tab = own ? await openTab('https://www.figma.com/design/' + P.key) : await attachBrowserTab(P.tabId);
      S = G[P.key] = { tab, own, seen: false };

      // Figma 에 계정이 여러 개 로그인돼 있으면 "Choose an account to open" 화면이 먼저 뜬다 → 설정한 계정을 고른다
      for (let i = 0; i < 20; i++) {
        const t = await tab.evaluate(() => (document.body ? document.body.innerText.slice(0, 400) : ''));
        if (/Choose an account to open/i.test(t)) {
          const sa = await snapshot(tab, { interactive: true });
          const btns = [...sa.tree.matchAll(/button "([^"]*)" \[ref=(e\d+)\]: "([^"]*)"/g)].map(m => ({ name: m[1], ref: m[2], text: m[3] }));
          const want = (P.account || '').toLowerCase();
          const pick = (want && btns.find(b => (b.name + ' ' + b.text).toLowerCase().includes(want)))
            || btns.find(b => /Editor on file/i.test(b.text)) || btns[0];
          if (pick) { await tab.locator(pick.ref).click(); emit({ kind: 'account', picked: pick.name }); await sleep(3000); }
          break;
        }
        if (await tab.evaluate(() => document.querySelectorAll('[data-testid="PagesRowWrapper"]').length)) break;
        await sleep(750);
      }
      // 파일이 열릴 때까지 (페이지 목록이 보이면 준비된 것)
      for (let i = 0; i < 40; i++) {
        if (await tab.evaluate(() => document.querySelectorAll('[data-testid="PagesRowWrapper"]').length)) break;
        await sleep(750);
      }
      // 빠른 실행 열기: ⌘/ → ⌘K → 메인 메뉴 "Actions…" 순서로 시도 (댓글 패널 등이 키보드를 가져가는 파일이 있다)
      let m1 = null;
      for (const how of ['slash', 'k', 'menu']) {
        await tab.keyboard.press('Escape'); await sleep(200); await tab.keyboard.press('Escape'); await sleep(200);
        if (how === 'menu') {
          try {
            const sm = await snapshot(tab, { interactive: true });
            const mm = sm.tree.match(/button "Main menu" \[ref=(e\d+)\]/);
            if (mm) { await tab.locator(mm[1]).click(); await sleep(600); }
            await tab.locator('[role="menuitem"]:has-text("Actions")').first().click({ timeout: 3000 });
          } catch (e) {}
        } else {
          await tab.keyboard.press(mod + (how === 'slash' ? '+/' : '+k'));
        }
        await sleep(1000);
        await tab.keyboard.type('Save local copy'); await sleep(1400);
        const s1 = await snapshot(tab, { interactive: true });
        m1 = s1.tree.match(/button "Save local copy…" \[ref=(e\d+)\]/);
        if (m1) break;
      }
      if (!m1) {
        emit({ kind: 'error', error: 'no-save-action' });
        await closeIt(S); delete G[P.key];
        return;
      }
      await tab.locator(m1[1]).click();
    }

    const state = await waitSaved(S);
    if (state === 'saved') {
      await sleep(8000);  // 브라우저 다운로드가 끝날 시간
      await closeIt(S); delete G[P.key];
    }
    emit({ kind: 'done', state, ms: Date.now() - T0 });
  } catch (e) {
    emit({ kind: 'error', error: String(e).slice(0, 200) });
    await closeIt(S); delete G[P.key];
  }
})();
