import type { VideoInputImageReference } from '@/types'

/** A Subject can point to a different Picture number. Resolve only explicit, unambiguous definitions. */
export function modelImageMentions(prompt: string, images: VideoInputImageReference[]) {
  const subjects = new Map<string, Set<number>>()
  const definitions = prompt.match(/^subject_definitions:[^\S\n]*\n([\s\S]*?)(?=^\w[\w ]*:\s*$|(?![\s\S]))/im)?.[1] || ''
  for (const line of definitions.split('\n')) {
    const subject = line.match(/^\s*(<Subject\s+\d+>)/i)?.[1]?.toLowerCase()
    if (!subject) continue
    const numbers = subjects.get(subject) || new Set<number>()
    for (const match of line.matchAll(/<Picture\s+(\d+)>/gi)) numbers.add(Number(match[1]))
    subjects.set(subject, numbers)
  }
  // Each definition binds its subject/scene to the pictures in that definition,
  // independent of the number assigned to the subject.
  for (const definition of prompt.matchAll(/(?:将|把)\s*([^。；;！？\n<>]+?)(?:定义为|设定为|记为|命名为)\s*(<(?:主体|场景)\s*\d+>)/gu)) {
    const subject = definition[2]!
    const numbers = subjects.get(subject) || new Set<number>()
    for (const picture of definition[1]!.matchAll(/@图片\s*(\d+)/gu)) numbers.add(Number(picture[1]))
    subjects.set(subject, numbers)
  }
  const result = []
  for (const syntax of new Set(prompt.match(/<(?:Subject|Picture)\s+\d+>|@图片\s*\d+|<(?:主体|场景)\s*\d+>/giu) || [])) {
    const numbers = subjects.get(syntax.toLowerCase())
    const number = /^(?:<Picture|@图片)/i.test(syntax) ? Number(syntax.match(/\d+/)?.[0])
      : numbers?.size === 1 ? [...numbers][0] : undefined
    const image = images.find(item => item.number === number)
    if (image) result.push({ syntax, image })
  }
  return result
}
