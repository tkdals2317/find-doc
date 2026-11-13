// find-doc: Figma 파일의 로컬 사본(.fig)을 이미지 없이 저장한다 (aside repl 에서 실행)
// finddoc.py 가 __FD_PARAMS__ 를 {key, tabId, budgetMs} 로, __TAG__ 를 고유 접미사로 바꿔 넣는다.
// 흐름: 파일 열기 → 빠른 실행(⌘/ 또는 Ctrl+/)에서 "Save local copy…" → Figma 가 모든 페이지 내용을
//       받는 동안("Downloading contents…") 기다림 → 이미지 단계("Downloading images…")가 되면 "Save partial file".
//       → 브라우저 기본 다운로드 폴더에 "<파일명> - Partial file saved <날짜>.fig" 로 저장된다.
// Figma 화면 문구에 의존한다. 깨지면 아래 문자열만 고치면 된다.

const P__TAG__ = __FD_PARAMS__;
const T0__TAG__ = Date.now();
const emit__TAG__ = (o) => console.log('@@FD@@' + JSON.stringify(o));
const own__TAG__ = !P__TAG__.tabId;
const pg__TAG__ = own__TAG__ ? await openTab('https://www.figma.com/design/' + P__TAG__.key)
                            : await attachBrowserTab(P__TAG__.tabId);
const mod__TAG__ = P__TAG__.mac ? 'Meta' : 'Control';

let state__TAG__ = 'opening';
try {
  // Figma 에 계정이 여러 개 로그인돼 있으면 "Choose an account to open" 화면이 먼저 뜬다 → 설정한 계정을 고른다
  for (let i = 0; i < 20; i++) {
    const t = await pg__TAG__.evaluate(() => document.body ? document.body.innerText.slice(0, 400) : '');
    if (/Choose an account to open/i.test(t)) {
      const sa = await snapshot(pg__TAG__, { interactive: true });
      const btns = [...sa.tree.matchAll(/button "([^"]*)" \[ref=(e\d+)\]: "([^"]*)"/g)].map(m => ({ name: m[1], ref: m[2], text: m[3] }));
      const want = (P__TAG__.account || '').toLowerCase();
      const pick = (want && btns.find(b => (b.name + ' ' + b.text).toLowerCase().includes(want)))
        || btns.find(b => /Editor on file/i.test(b.text)) || btns[0];
      if (pick) { await pg__TAG__.locator(pick.ref).click(); emit__TAG__({ kind: 'account', picked: pick.name }); await sleep(3000); }
      break;
    }
    if (await pg__TAG__.evaluate(() => document.querySelectorAll('[data-testid="PagesRowWrapper"]').length)) break;
    await sleep(750);
  }
  // 파일이 열릴 때까지 (페이지 목록이 보이면 준비된 것)
  for (let i = 0; i < 40; i++) {
    const n = await pg__TAG__.evaluate(() => document.querySelectorAll('[data-testid="PagesRowWrapper"]').length);
    if (n) break;
    await sleep(750);
  }
  // 빠른 실행 열기: ⌘/ → ⌘K → 메인 메뉴 "Actions…" 순서로 시도 (댓글 패널 등이 키보드를 가져가는 파일이 있다)
  let m1 = null;
  for (const how of ['slash', 'k', 'menu']) {
    await pg__TAG__.keyboard.press('Escape'); await sleep(200); await pg__TAG__.keyboard.press('Escape'); await sleep(200);
    if (how === 'menu') {
      try {
        const sm = await snapshot(pg__TAG__, { interactive: true });
        const mm = sm.tree.match(/button "Main menu" \[ref=(e\d+)\]/);
        if (mm) { await pg__TAG__.locator(mm[1]).click(); await sleep(600); }
        await pg__TAG__.locator('[role="menuitem"]:has-text("Actions")').first().click({ timeout: 3000 });
      } catch (e) {}
    } else {
      await pg__TAG__.keyboard.press(mod__TAG__ + (how === 'slash' ? '+/' : '+k'));
    }
    await sleep(1000);
    await pg__TAG__.keyboard.type('Save local copy'); await sleep(1400);
    const s1 = await snapshot(pg__TAG__, { interactive: true });
    m1 = s1.tree.match(/button "Save local copy…" \[ref=(e\d+)\]/);
    if (m1) break;
  }
  if (!m1) { emit__TAG__({ kind: 'error', error: 'no-save-action' }); }
  else {
    await pg__TAG__.locator(m1[1]).click();
    state__TAG__ = 'contents';
    let seen__TAG__ = false;
    while (Date.now() - T0__TAG__ < P__TAG__.budgetMs) {
      await sleep(1500);
      const s = await snapshot(pg__TAG__);  // 스냅샷은 한 번만 (새 스냅샷은 이전 ref 를 무효화한다)
      const partial = s.tree.match(/button "Save partial file" \[ref=(e\d+)\]/);
      const al = (s.tree.match(/alert: "[^"]*"/g) || []).join(' | ');
      if (/Downloading/i.test(al)) seen__TAG__ = true;
      if (partial && /Downloading images/i.test(al)) {
        await pg__TAG__.locator(partial[1]).click();
        state__TAG__ = 'saved';
        break;
      }
      if (seen__TAG__ && !partial && !/Downloading/i.test(al)) {
        // 이미지가 없거나 이미 다 받은 파일은 확인 창 없이 바로 저장된다
        state__TAG__ = 'saved';
        break;
      }
    }
    if (state__TAG__ === 'saved') await sleep(8000);  // 브라우저 다운로드가 끝날 시간
    emit__TAG__({ kind: 'done', state: state__TAG__, ms: Date.now() - T0__TAG__ });
  }
} catch (e) {
  emit__TAG__({ kind: 'error', error: String(e).slice(0, 200), state: state__TAG__ });
}
if (own__TAG__) {
  // 바로 닫는다. 무거운 Figma 탭이라 닫기가 실패했을 때만 페이지를 비우고 다시 닫는다.
  let closed__TAG__ = true;
  try { await closeTab(pg__TAG__); } catch (e) { closed__TAG__ = false; }
  if (!closed__TAG__) {
    try { await pg__TAG__.goto('about:blank', { timeout: 10000 }); } catch (e) {}
    try { await closeTab(pg__TAG__); } catch (e) {}
  }
}
