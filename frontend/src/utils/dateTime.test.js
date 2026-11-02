import assert from 'node:assert/strict'
import test from 'node:test'
import { formatTaskDuration } from './dateTime.js'

test('paused task duration stays at the frozen active seconds', () => {
  const task = {
    status: 'paused',
    started_at: '2026-08-27T10:00:00',
    progress: { timing_active_seconds: 12 },
  }

  assert.equal(formatTaskDuration(task), '12秒')
})
