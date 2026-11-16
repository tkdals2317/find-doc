import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { CrawlItem, CrawlStatus } from '../types'

// find-doc 레이어 인덱싱(crawl) 로그를 몇 초마다 읽어 패널에 진행 상황을 보여준다.
// finddoc.py crawl 이 쓰는 ~/.config/find-doc/index/crawl.log 를 읽는다 (Windows: %USERPROFILE%\.config\find-doc\index\crawl.log).
const PANE = 'find-doc-progress'
const status = atom({ plugin: 'find-doc', key: 'status' } as const, null, { shape: 'status-1' })

const RESULT = /^\s+\[(\d+)\/(\d+)\]\s+(.+?):\s+(.*)$/
const QUEUED = /^\s+↳\s+(.+?):\s+저장 완료/
const TOTAL = /^\s+(\d+)개 파일:/

function parse(text: string, logPath: string, prev: CrawlStatus | null, nowMs: number): CrawlStatus {
  let total = 0
  let ok = 0
  let skip = 0
  let fail = 0
  let layers = 0
  const results: CrawlItem[] = []
  const queued: string[] = []
  const finishedNames = new Set<string>()
  for (const line of text.split('\n')) {
    const t = TOTAL.exec(line)
    if (t) total = Number(t[1])
    const q = QUEUED.exec(line)
    if (q) queued.push(q[1])
    const m = RESULT.exec(line)
    if (!m) continue
    total = Number(m[2])
    const name = m[3]
    const msg = m[4]
    finishedNames.add(name)
    if (msg.includes('개 레이어')) {
      ok++
      layers += Number((/(\d+)개 레이어/.exec(msg) || ['', '0'])[1])
      results.push({ name, kind: 'ok', detail: msg })
    } else if (msg.includes('최근에 인덱싱')) {
      skip++
      results.push({ name, kind: 'skip', detail: '이미 인덱싱됨' })
    } else if (!msg.includes('확인 중')) {
      fail++
      results.push({ name, kind: 'fail', detail: msg.slice(0, 120) })
    }
  }
  const done = ok + skip + fail
  const samePath = prev && prev.logPath === logPath
  const samples: [number, number][] = [...(samePath ? prev.samples : []), [nowMs, done] as [number, number]].slice(-40)
  return {
    logPath,
    total,
    done,
    ok,
    skip,
    fail,
    layers,
    parseQueue: queued.filter(n => !finishedNames.has(n)).slice(-10),
    recent: results.filter(r => r.kind !== 'skip').slice(-6).reverse(),
    failures: results.filter(r => r.kind === 'fail').slice(-5),
    finished: total > 0 && done >= total,
    updatedAt: nowMs,
    samples,
  }
}

function eta(s: CrawlStatus): string {
  if (s.finished) return '완료'
  const first = s.samples[0]
  const last = s.samples[s.samples.length - 1]
  if (!first || !last || last[1] <= first[1]) return '계산 중…'
  const perMs = (last[1] - first[1]) / (last[0] - first[0])
  const leftMin = Math.ceil((s.total - s.done) / perMs / 60000)
  return leftMin <= 1 ? '1분 이내' : `약 ${leftMin}분`
}

function bar(done: number, total: number, width: number): string {
  const n = total ? Math.round((done / total) * width) : 0
  return '█'.repeat(n) + '░'.repeat(Math.max(0, width - n))
}

let home = ''

async function refresh($: EngineInterface): Promise<void> {
  if (!home) {
    // macOS·Linux 는 HOME, Windows 는 USERPROFILE
    home = ((await $.env.get('HOME')) || (await $.env.get('USERPROFILE')) || '').replace(/\\/g, '/')
  }
  const candidates = [`${home}/.config/find-doc/index/crawl.log`]
  let best: { path: string; mtime: number } | null = null
  for (const path of candidates) {
    try {
      const st = await $.fs.stat(path)
      if (st.kind === 'file' && (!best || st.mtimeMs > best.mtime)) best = { path, mtime: st.mtimeMs }
    } catch {
      // 없는 로그는 건너뜀
    }
  }
  if (!best) return
  const text = await $.fs.read(best.path)
  const nowMs = await $.clock.now()
  await update($, status, prev => parse(text, best!.path, prev, nowMs))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'find-doc-progress', description: 'find-doc 레이어 인덱싱 진행 상황 패널 열기' })
    void $.ui.open({ id: PANE, title: 'find-doc 인덱싱' })
    $.clock.every(3000, () => {
      void refresh($)
    })
    void refresh($)
    return next(e)
  })

  on('command.run', { command: 'find-doc-progress' }, async $ => {
    await refresh($)
    const opened = await $.ui.open({ id: PANE, title: 'find-doc 인덱싱' })
    const s = await read($, status)
    const line = s ? `${s.done}/${s.total} 처리 · 성공 ${s.ok} · 실패 ${s.fail} · 남은 시간 ${eta(s)}` : '진행 중인 인덱싱 로그가 없어요.'
    return {
      text: opened.isPlaced
        ? `find-doc 인덱싱 패널을 열었어요. (${line})`
        : `이 화면에는 패널을 놓을 자리가 없어서, 입력창 위 한 줄로 보여드려요. 지금: ${line}`,
    }
  })

  // 입력창 바로 위 한 줄: 인덱싱이 돌고 있을 때만 (로그가 1분 안에 바뀌었고 아직 안 끝났을 때)
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const s = await read($, status)
    if (!s || s.finished || s.total === 0) return next(e)
    const st = await $.fs.stat(s.logPath).catch(() => null)
    const nowMs = await $.clock.now()
    if (!st || nowMs - st.mtimeMs > 60000) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const pct = Math.floor((s.done / s.total) * 100)
    return (
      <Box>
        <Text dimColor>
          find-doc 인덱싱 {bar(s.done, s.total, 12)} {s.done}/{s.total} ({pct}%) · 성공 {s.ok} · 실패 {s.fail}
          {s.parseQueue.length > 0 ? ` · 해석 대기 ${s.parseQueue.length}` : ''} · {eta(s)}
        </Text>
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const s = await read($, status)
    if (!s) {
      return (
        <Box flexDirection="column" padding={1}>
          <Text dimColor>진행 중인 인덱싱 로그가 없어요.</Text>
        </Box>
      )
    }
    const pct = s.total ? Math.floor((s.done / s.total) * 100) : 0
    return (
      <Box flexDirection="column" padding={1} gap={1}>
        <Box flexDirection="column">
          <Text weight="semibold">{s.finished ? '✅ 인덱싱 완료' : '⏳ 레이어 인덱싱 중'}</Text>
          <Text mono>
            {bar(s.done, s.total, 24)} {s.done}/{s.total} ({pct}%)
          </Text>
          <Text dimColor>남은 시간: {eta(s)}</Text>
        </Box>
        <Box flexDirection="column">
          <Text color="success">성공 {s.ok}개 · 레이어 {s.layers.toLocaleString()}개</Text>
          <Text dimColor>건너뜀 {s.skip}개 (이미 인덱싱됨)</Text>
          <Text color={s.fail ? 'error' : undefined} dimColor={!s.fail}>
            실패 {s.fail}개
          </Text>
          {s.parseQueue.length > 0 && <Text color="warning">해석 대기 {s.parseQueue.length}개</Text>}
        </Box>
        {s.recent.length > 0 && (
          <Box flexDirection="column">
            <Text weight="semibold">최근 처리</Text>
            {s.recent.map(r => (
              <Text color={r.kind === 'fail' ? 'error' : undefined}>
                {r.kind === 'fail' ? '✗' : '✓'} {r.name.slice(0, 40)} — {r.detail.slice(0, 40)}
              </Text>
            ))}
          </Box>
        )}
        {s.failures.length > 0 && (
          <Box flexDirection="column">
            <Text weight="semibold" color="error">실패한 파일</Text>
            {s.failures.map(r => (
              <Text dimColor>
                {r.name.slice(0, 40)}: {r.detail.slice(0, 60)}
              </Text>
            ))}
          </Box>
        )}
        <Text dimColor size="caption">
          {s.logPath.split('/').slice(-1)[0]} · 3초마다 갱신
        </Text>
      </Box>
    )
  })
}
