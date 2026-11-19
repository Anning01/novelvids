import type { AgentMessage } from './types'

/** A production turn is created before its prerequisite runs. Present their execution order. */
export function productionTimeline(messages: AgentMessage[]): (AgentMessage & { waitingForMemory?: boolean })[] {
  const turns = new Map<string, AgentMessage[]>()
  for (const message of messages) {
    const turn = turns.get(message.task_id)
    if (turn) turn.push(message)
    else turns.set(message.task_id, [message])
  }

  const result: (AgentMessage & { waitingForMemory?: boolean })[] = []
  const displayed = new Set<number>()
  for (const message of messages) {
    if (displayed.has(message.id)) continue
    displayed.add(message.id)
    const receipts = message.production || []
    const owner = receipts.find(receipt => receipt.task_id === message.task_id)
    const prerequisites = receipts.filter(receipt => receipt.operation === 'story_memory_analyze')
    if (message.role !== 'assistant' || !owner || !['screenplay', 'assets', 'storyboard'].includes(owner.operation)
        || !prerequisites.length) {
      result.push(message)
      continue
    }

    const represented = new Set<string>()
    const childSteps = new Set<string>()
    const activeIds = new Set(prerequisites.filter(receipt => [1, 2, 6].includes(receipt.status)).map(receipt => receipt.task_id))
    // History is chronological. A post-save refresh has its own task and no prerequisite receipt.
    const childIds = new Set(prerequisites.map(receipt => receipt.task_id))
    for (const [taskId, turn] of turns) {
      if (!childIds.has(taskId)) continue
      const assistant = turn.find(item => item.role === 'assistant')
      if (!assistant) continue
      represented.add(taskId)
      for (const step of assistant.activity || []) childSteps.add(step.id)
      if (![1, 2, 6].includes(assistant.status)) activeIds.delete(taskId)
      for (const part of turn) {
        if (!displayed.has(part.id)) {
          displayed.add(part.id)
          result.push(part)
        }
      }
    }
    result.push({ ...message, waitingForMemory: activeIds.size > 0 && [1, 2, 6].includes(message.status),
      activity: message.activity?.filter(step => !childSteps.has(step.id)),
      production: [...prerequisites.filter(receipt => !represented.has(receipt.task_id)),
        ...receipts.filter(receipt => !childIds.has(receipt.task_id))] })
  }
  return result
}
