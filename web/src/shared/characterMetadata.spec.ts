import { expect, it } from 'vitest'
import { resolveCharacterFormMetadata } from './characterMetadata'

it('reads English visual labels without changing canonical form values', () => {
  expect(resolveCharacterFormMetadata({ base_traits: '**Gender**: female\n**Age**: 32 years', metadata: {} })).toEqual({ gender: '女', ageGroup: '青年' })
})
it('keeps legacy Chinese fields and explicit metadata authoritative', () => {
  expect(resolveCharacterFormMetadata({ base_traits: '性别：男\n年龄：65岁', metadata: {} })).toEqual({ gender: '男', ageGroup: '老年' })
  expect(resolveCharacterFormMetadata({ base_traits: 'Gender: female\nAge: 32', metadata: { gender: '男', age: 70 } })).toEqual({ gender: '男', ageGroup: '老年' })
})
