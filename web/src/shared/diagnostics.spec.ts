import { expect, it } from 'vitest'
import { diagnosticReport, diagnosticScope, recordRequestFailure } from './diagnostics'

it('caps the merged report at 100, omits sensitive paths and isolates session changes', () => {
  diagnosticScope('first')
  for (let n = 0; n < 105; n++) recordRequestFailure('first', '/remake/uploads?token=SECRET', 'POST', 413, 413)
  recordRequestFailure('first', '/CUSTOMER_FILE/SECRET', 'POST', 500, 500)
  const report = diagnosticReport('first', [{source:'task',time:'2099-01-01T00:00:00Z',task_id:'one'}], true)
  expect(report.entries).toHaveLength(100)
  expect(report.entries[0]?.source).toBe('task')
  expect(JSON.stringify(report)).not.toMatch(/SECRET|CUSTOMER_FILE|first/)
  diagnosticScope('second')
  recordRequestFailure('first', '/remake', 'GET', 500, 500)
  expect(diagnosticReport('second', [], false)).toMatchObject({count:0, backend_available:false})
})
