export async function runVideoGenerationQueue<T>(
  items: T[],
  concurrency: number,
  sequential: boolean,
  generate: (item: T) => Promise<boolean>,
): Promise<number> {
  let nextIndex = 0
  let completedCount = 0
  const workerCount = sequential
    ? 1
    : Math.max(1, Math.min(Math.floor(concurrency) || 1, items.length))
  const worker = async () => {
    while (nextIndex < items.length) {
      const item = items[nextIndex++]
      if (item !== undefined && await generate(item)) completedCount += 1
    }
  }
  await Promise.all(Array.from({ length: workerCount }, worker))
  return completedCount
}
