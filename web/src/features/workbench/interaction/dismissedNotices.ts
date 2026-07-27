const DISMISSED_NOTICE_STORAGE_KEY = 'vf:workbench:dismissed-notices';
const MAX_DISMISSED_NOTICES = 200;

function messageHash(value: string) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index++) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function readDismissedNotices() {
  if (typeof window === 'undefined')
    return new Set<string>();
  try {
    const value = JSON.parse(window.localStorage.getItem(DISMISSED_NOTICE_STORAGE_KEY) || '[]');
    return new Set(Array.isArray(value) ? value.filter(item => typeof item === 'string') : []);
  }
  catch {
    return new Set<string>();
  }
}

export function workbenchFailureNoticeKey(runKey: string | undefined, message: string | null | undefined) {
  const normalizedRunKey = String(runKey || '').trim();
  const normalizedMessage = String(message || '').trim();
  if (!normalizedRunKey)
    return '';
  return `run:${normalizedRunKey}:${messageHash(normalizedMessage || '运行失败')}`;
}

export function isWorkbenchNoticeDismissed(key: string) {
  return Boolean(key) && readDismissedNotices().has(key);
}

export function dismissWorkbenchNotice(key: string) {
  if (!key || typeof window === 'undefined')
    return;
  const values = [...readDismissedNotices().values()].filter(item => item !== key);
  values.push(key);
  try {
    window.localStorage.setItem(
      DISMISSED_NOTICE_STORAGE_KEY,
      JSON.stringify(values.slice(-MAX_DISMISSED_NOTICES)),
    );
  }
  catch {
    // The in-memory component state still dismisses the notice when storage is unavailable.
  }
}
