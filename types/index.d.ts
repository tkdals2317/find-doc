export type CrawlItem = { name: string; kind: 'ok' | 'skip' | 'fail'; detail: string }

export type CrawlStatus = {
  logPath: string
  total: number
  done: number
  ok: number
  skip: number
  fail: number
  layers: number
  parseQueue: string[]
  recent: CrawlItem[]
  failures: CrawlItem[]
  finished: boolean
  updatedAt: number
  // 남은 시간 추정용: (시각, 처리 수) 표본
  samples: [number, number][]
}

declare module 'claude-code' {
  interface PluginState {
    'find-doc': { status: Shaped<CrawlStatus | null> }
  }
}
