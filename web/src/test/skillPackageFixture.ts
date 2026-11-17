import type { CreativeSkill, SkillPackageLimits } from '@/features/creation-agent/skillsApi'

export const packageLimits: SkillPackageLimits = { max_files: 200, max_file_bytes: 5 * 1024 * 1024, max_package_bytes: 20 * 1024 * 1024, max_archive_bytes: 20 * 1024 * 1024 }
export const skillEntry = (body: string) => `---\nname: test-skill\ndescription: A test skill.\n---\n\n${body}`
export const folderSkill = (skill: CreativeSkill): CreativeSkill => ({ ...skill, limits: packageLimits,
  files: skill.files ?? [{ path: 'SKILL.md', content: skillEntry(skill.instructions), encoding: 'utf-8' }] })
