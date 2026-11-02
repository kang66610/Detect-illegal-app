import assert from 'node:assert/strict'
import test from 'node:test'

let motion = null
try {
  motion = await import('../src/utils/uiMotion.js')
} catch {
  // The first red run intentionally reaches this branch before the module exists.
}

test('任务状态映射应让排队、运行、结束状态使用不同的反馈模式', () => {
  assert.equal(motion?.motionProfileForStatus?.('queued'), 'queued')
  assert.equal(motion?.motionProfileForStatus?.('traversing'), 'running')
  assert.equal(motion?.motionProfileForStatus?.('completed'), 'completed')
  assert.equal(motion?.motionProfileForStatus?.('paused'), 'stopped')
  assert.equal(motion?.motionProfileForStatus?.('failed'), 'stopped')
})

test('滚动阈值应只在页面明显离开顶部后收紧导航', () => {
  assert.equal(motion?.isNavigationCondensed?.(0), false)
  assert.equal(motion?.isNavigationCondensed?.(47), false)
  assert.equal(motion?.isNavigationCondensed?.(48), true)
})

test('风险数字应从起始值平滑递进且不会超过目标值', () => {
  assert.equal(motion?.interpolateInteger?.(0, 8, 0), 0)
  assert.equal(motion?.interpolateInteger?.(0, 8, 0.5), 4)
  assert.equal(motion?.interpolateInteger?.(0, 8, 1), 8)
  assert.equal(motion?.interpolateInteger?.(4, 8, 2), 8)
})
