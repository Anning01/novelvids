<script setup lang="ts">
import type { MaterialMention, MaterialMentionOption } from './materialMentionTypes';
import { AudioLines, FileText, Film, Image as ImageIcon, Search } from 'lucide-vue-next';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

const props = defineProps<{
  modelValue: string;
  materials: MaterialMentionOption[];
  mentions: MaterialMention[];
  label: string;
  imageLimit?: number;
  videoLimit?: number;
  audioLimit?: number;
  hint?: string;
  placeholder?: string;
  showHint?: boolean;
  showReferenceCounts?: boolean;
}>();
const emit = defineEmits<{
  'update:modelValue': [value: string];
  'add': [material: MaterialMentionOption, prompt: string];
}>();

interface MentionTrigger {
  start: number;
  end: number;
  query: string;
}

interface EditorSelection {
  anchorOffset: number;
  focusOffset: number;
}

interface MentionHistoryEntry {
  before: string;
  after: string;
  undoCaretOffset: number;
  redoCaretOffset: number;
}

const editor = ref<HTMLDivElement | null>(null);
const container = ref<HTMLDivElement | null>(null);
const optionList = ref<HTMLDivElement | null>(null);
const trigger = ref<MentionTrigger | null>(null);
const menuStyle = ref<Record<string, string>>({});
const activeIndex = ref(0);
const focused = ref(false);
const selectedMentionElement = ref<HTMLElement | null>(null);
const failedPreviewUrls = ref(new Set<string>());
const listboxId = `material-mentions-${Math.random().toString(36).slice(2, 9)}`;
let applyingDom = false;
let pendingCaretOffset: number | null = null;
let lastExternalPointerDownAt = 0;
let previousMentionNames = new Map(props.mentions.map(item => [item.edgeKey, item.name]));
const mentionUndoStack: MentionHistoryEntry[] = [];
const mentionRedoStack: MentionHistoryEntry[] = [];
const machineMentionPattern = /[ \t]*@([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}|[0-9a-f]{40,})(?=$|[\s，。！？、,.;；:：])/gi;

interface MentionNameChange {
  previousName: string;
  currentName?: string;
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function cleanupMentionWhitespace(value: string) {
  return value
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/(^|\n)[ \t]+/g, '$1')
    .replace(/[ \t]+(?=\n|$)/g, '');
}

function rewriteMentionMarkers(value: string, changes: MentionNameChange[]) {
  let rewritten = value;
  const replacements: Array<{ placeholder: string; value: string }> = [];
  let removed = false;

  changes.forEach((change, index) => {
    const previousName = change.previousName.trim();
    if (!previousName)
      return;
    const escapedName = escapeRegExp(previousName);
    const placeholder = (kind: string) => `\uE000mention-${index}-${kind}\uE001`;
    const nextName = change.currentName?.trim();
    const patterns = [
      { kind: 'wrapped-at', pattern: new RegExp(`【@${escapedName}】`, 'g'), next: nextName ? `【@${nextName}】` : '' },
      { kind: 'wrapped', pattern: new RegExp(`【${escapedName}】`, 'g'), next: nextName ? `【${nextName}】` : '' },
      { kind: 'braced-at', pattern: new RegExp(`@\\{${escapedName}\\}`, 'g'), next: nextName ? `@{${nextName}}` : '' },
      {
        kind: 'at',
        pattern: new RegExp(`@${escapedName}(?=$|[\\s，。！？、,.;；:：)）\\]】}])`, 'g'),
        next: nextName ? `@${nextName}` : '',
      },
    ];
    for (const item of patterns) {
      const marker = placeholder(item.kind);
      if (!item.pattern.test(rewritten))
        continue;
      item.pattern.lastIndex = 0;
      rewritten = rewritten.replace(item.pattern, marker);
      replacements.push({ placeholder: marker, value: item.next });
      removed ||= !nextName;
    }
  });

  for (const replacement of replacements)
    rewritten = rewritten.split(replacement.placeholder).join(replacement.value);
  return removed ? cleanupMentionWhitespace(rewritten) : rewritten;
}

const filteredMaterials = computed(() => {
  const query = trigger.value?.query.trim().toLocaleLowerCase() ?? '';
  return props.materials.filter((item) => {
    if (!query)
      return true;
    return item.name.toLocaleLowerCase().includes(query)
      || item.prompt.toLocaleLowerCase().includes(query);
  });
});
const menuOpen = computed(() => focused.value && trigger.value !== null);
const activeOptionId = computed(() => menuOpen.value && filteredMaterials.value[activeIndex.value]
  ? `${listboxId}-option-${activeIndex.value}`
  : undefined);

watch(() => trigger.value?.query, () => {
  activeIndex.value = 0;
  void nextTick(() => {
    scrollActiveOptionIntoView();
    updateMentionMenuPosition();
  });
});
watch(() => filteredMaterials.value.length, (length) => {
  activeIndex.value = Math.min(activeIndex.value, Math.max(0, length - 1));
  void nextTick(updateMentionMenuPosition);
});
watch(
  () => [props.modelValue, props.mentions.map(item => `${item.edgeKey}:${item.mode}:${item.name}:${item.previewUrl}:${item.assetCategory ?? ''}`).join('|')],
  () => void nextTick(() => {
    const currentMentionNames = new Map(props.mentions.map(item => [item.edgeKey, item.name]));
    const connectedNames = new Set(props.mentions.map(item => item.name.toLocaleLowerCase()));
    const changes: MentionNameChange[] = [];
    for (const [edgeKey, previousName] of previousMentionNames) {
      const currentName = currentMentionNames.get(edgeKey);
      if (currentName !== previousName)
        changes.push({ previousName, currentName });
    }
    const sanitized = rewriteMentionMarkers(props.modelValue, changes).replace(machineMentionPattern, (marker, name: string) => {
      return connectedNames.has(name.toLocaleLowerCase()) ? marker : '';
    });
    previousMentionNames = currentMentionNames;
    if (sanitized !== props.modelValue) {
      emit('update:modelValue', sanitized);
      return;
    }
    syncEditor();
    if (pendingCaretOffset === null)
      return;
    placeCaretAtOffset(pendingCaretOffset);
    pendingCaretOffset = null;
  }),
  { immediate: true },
);
onMounted(() => {
  window.addEventListener('keydown', handleCapturedKeydown, true);
  window.addEventListener('pointerdown', handleCapturedPointerdown, true);
  window.addEventListener('resize', updateMentionMenuPosition);
  void nextTick(syncEditor);
});
onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleCapturedKeydown, true);
  window.removeEventListener('pointerdown', handleCapturedPointerdown, true);
  window.removeEventListener('resize', updateMentionMenuPosition);
});

function mentionPattern() {
  const names = props.mentions.map(item => item.name).filter(Boolean).sort((left, right) => right.length - left.length);
  if (!names.length)
    return null;
  const escaped = names.map(name => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const options = escaped.join('|');
  return new RegExp(`(@\\{(?:${options})\\}|@(?:${options})|【@?(?:${options})】)`, 'g');
}

function markerName(marker: string) {
  if (marker.startsWith('@{'))
    return marker.slice(2, -1);
  if (marker.startsWith('【@'))
    return marker.slice(2, -1);
  return marker.startsWith('【') ? marker.slice(1, -1) : marker.slice(1);
}

function appendText(container: HTMLElement, value: string) {
  if (value)
    container.append(document.createTextNode(value));
}

function createAudioFallbackElement() {
  const fallback = document.createElement('span');
  fallback.className = 'workbench-inline-mention__fallback is-audio';
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '14');
  svg.setAttribute('height', '14');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  for (const pathData of ['M2 10v3', 'M6 6v11', 'M10 3v18', 'M14 8v7', 'M18 5v13', 'M22 10v3']) {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', pathData);
    svg.append(path);
  }
  fallback.append(svg);
  return fallback;
}

function markPreviewFailed(url: string) {
  failedPreviewUrls.value = new Set([...failedPreviewUrls.value, url]);
}

function createMentionElement(mention: MaterialMention, marker = `@{${mention.name}}`) {
  const token = document.createElement('span');
  token.className = [
    'workbench-inline-mention',
    `is-${mention.mode}`,
    mention.assetCategory ? `is-asset-${mention.assetCategory}` : '',
  ].filter(Boolean).join(' ');
  token.contentEditable = 'false';
  token.dataset.edgeKey = mention.edgeKey;
  token.dataset.marker = marker;
  if (mention.assetCategory)
    token.dataset.assetCategory = mention.assetCategory;
  token.setAttribute('role', 'button');
  token.setAttribute('tabindex', '-1');
  token.setAttribute('aria-label', `素材引用 ${mention.name}`);
  token.title = `${mention.mode === 'reference_image' ? '参考图' : mention.mode === 'reference_video' ? '参考视频' : mention.mode === 'reference_audio' ? '参考音频' : '文字素材'}：${mention.name}（点击后按 Backspace/Delete 删除）`;

  if (mention.mode === 'reference_audio') {
    if (mention.previewUrl) {
      const image = document.createElement('img');
      image.src = mention.previewUrl;
      image.alt = '';
      image.className = 'workbench-inline-mention__audio-avatar';
      image.addEventListener('error', () => image.replaceWith(createAudioFallbackElement()), { once: true });
      token.append(image);
    }
    else {
      token.append(createAudioFallbackElement());
    }
  }
  else if (mention.mode === 'reference_image' || mention.mode === 'reference_video') {
    if (mention.previewUrl) {
      if (mention.mode === 'reference_video') {
        const video = document.createElement('video');
        video.src = mention.previewUrl;
        video.muted = true;
        video.preload = 'metadata';
        token.append(video);
      }
      else {
        const image = document.createElement('img');
        image.src = mention.previewUrl;
        image.alt = '';
        token.append(image);
      }
    }
    else {
      const icon = document.createElement('span');
      icon.className = 'workbench-inline-mention__fallback';
      icon.textContent = '▧';
      token.append(icon);
    }
  }
  const name = document.createElement('span');
  name.className = 'workbench-inline-mention__name';
  name.textContent = `@${mention.name}`;
  name.title = `@${mention.name}`;
  token.append(name);
  return token;
}

function syncEditor() {
  const root = editor.value;
  if (!root || (document.activeElement === root && serializeEditor() === props.modelValue))
    return;
  const preservedSelection = pendingCaretOffset === null ? currentEditorSelection() : null;
  applyingDom = true;
  root.replaceChildren();
  const pattern = mentionPattern();
  let cursor = 0;
  if (pattern) {
    for (const match of props.modelValue.matchAll(pattern)) {
      const index = match.index ?? 0;
      appendText(root, props.modelValue.slice(cursor, index));
      const mention = props.mentions.find(item => item.name === markerName(match[0]));
      if (mention) {
        root.append(createMentionElement(mention, match[0]));
      }
      else {
        appendText(root, match[0]);
      }
      cursor = index + match[0].length;
    }
  }
  appendText(root, props.modelValue.slice(cursor));
  applyingDom = false;
  if (preservedSelection) {
    placeSelectionAtOffsets(
      Math.min(preservedSelection.anchorOffset, props.modelValue.length),
      Math.min(preservedSelection.focusOffset, props.modelValue.length),
    );
  }
}

function logicalOffsetAt(container: Node, offset: number) {
  const root = editor.value;
  if (!root || (container !== root && !root.contains(container)))
    return null;
  const range = document.createRange();
  range.selectNodeContents(root);
  try {
    range.setEnd(container, offset);
  }
  catch {
    return null;
  }
  return range.toString().length;
}

function currentEditorSelection(): EditorSelection | null {
  const root = editor.value;
  const selection = window.getSelection();
  if (!root || document.activeElement !== root || !selection?.rangeCount)
    return null;
  const current = selection.getRangeAt(0);
  if (!root.contains(current.commonAncestorContainer))
    return null;
  const anchorOffset = selection.anchorNode ? logicalOffsetAt(selection.anchorNode, selection.anchorOffset) : null;
  const focusOffset = selection.focusNode ? logicalOffsetAt(selection.focusNode, selection.focusOffset) : null;
  return anchorOffset === null || focusOffset === null ? null : { anchorOffset, focusOffset };
}

function currentCaretOffset() {
  const selection = window.getSelection();
  const current = currentEditorSelection();
  return selection?.isCollapsed && current ? current.anchorOffset : null;
}

function domPointAtOffset(offset: number): { container: Node; offset: number } | null {
  const root = editor.value;
  if (!root)
    return null;
  let remaining = Math.max(0, offset);

  function visit(container: Node): { container: Node; offset: number } | null {
    for (const [index, child] of Array.from(container.childNodes).entries()) {
      const length = serializeNode(child).length;
      if (child.nodeType === Node.TEXT_NODE && remaining <= length)
        return { container: child, offset: remaining };
      if (child instanceof HTMLElement && child.classList.contains('workbench-inline-mention') && remaining <= length)
        return { container, offset: index + 1 };
      if (remaining < length && child.childNodes.length) {
        const nested = visit(child);
        if (nested)
          return nested;
      }
      remaining -= length;
    }
    return null;
  }

  return visit(root) ?? { container: root, offset: root.childNodes.length };
}

function placeSelectionAtOffsets(anchorOffset: number, focusOffset: number) {
  const root = editor.value;
  if (!root)
    return;
  // Focusing a contenteditable can reset its selection to the beginning.
  // Focus first, then restore both ends so selected text survives an external
  // model refresh just like a collapsed caret does.
  root.focus();
  const selection = window.getSelection();
  const anchor = domPointAtOffset(anchorOffset);
  const focus = domPointAtOffset(focusOffset);
  if (!selection || !anchor || !focus)
    return;
  selection.removeAllRanges();
  selection.setBaseAndExtent(anchor.container, anchor.offset, focus.container, focus.offset);
}

function placeCaretAtOffset(offset: number) {
  placeSelectionAtOffsets(offset, offset);
}

function serializeNode(node: Node): string {
  if (node instanceof HTMLElement && node.classList.contains('workbench-inline-mention'))
    return node.dataset.marker ?? '';
  if (node.nodeType === Node.TEXT_NODE)
    return node.textContent ?? '';
  if (node instanceof HTMLBRElement)
    return '\n';
  const content = Array.from(node.childNodes).map(serializeNode).join('');
  return node instanceof HTMLDivElement && node !== editor.value ? `${content}\n` : content;
}

function serializeEditor() {
  return editor.value ? Array.from(editor.value.childNodes).map(serializeNode).join('').replace(/\n+$/, '') : '';
}

function textBeforeCaret() {
  const root = editor.value;
  const selection = window.getSelection();
  if (!root || !selection?.rangeCount)
    return serializeEditor();
  const current = selection.getRangeAt(0);
  if (!root.contains(current.startContainer))
    return serializeEditor();
  const range = document.createRange();
  range.selectNodeContents(root);
  range.setEnd(current.startContainer, current.startOffset);
  return range.toString();
}

function currentCaretRect() {
  const root = editor.value;
  const selection = window.getSelection();
  if (!root || !selection?.rangeCount || !selection.isCollapsed)
    return null;
  const current = selection.getRangeAt(0);
  if (!root.contains(current.startContainer))
    return null;
  const caret = current.cloneRange();
  caret.collapse(false);
  let rect = caret.getBoundingClientRect();
  if (rect.height || rect.width)
    return rect;
  if (caret.startContainer.nodeType === Node.TEXT_NODE && caret.startOffset > 0) {
    caret.setStart(caret.startContainer, caret.startOffset - 1);
    rect = caret.getBoundingClientRect();
    if (rect.height || rect.width) {
      return {
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        left: rect.right,
        width: 0,
        height: rect.height,
        x: rect.right,
        y: rect.top,
        toJSON: () => ({}),
      } as DOMRect;
    }
  }
  return null;
}

function updateMentionMenuPosition() {
  if (!menuOpen.value)
    return;
  const root = editor.value;
  const host = container.value;
  const caretRect = currentCaretRect();
  if (!root || !host || !caretRect)
    return;
  const hostRect = host.getBoundingClientRect();
  const scaleY = host.offsetHeight > 0 ? hostRect.height / host.offsetHeight : 1;
  const caretTop = (caretRect.top - hostRect.top) / scaleY;
  const caretBottom = (caretRect.bottom - hostRect.top) / scaleY;
  const spaceAbove = Math.max(0, caretTop);
  const spaceBelow = Math.max(0, host.offsetHeight - caretBottom);
  const optionHeight = Math.min(filteredMaterials.value.length * 44 + 10, 216);
  const menuHeight = 36 + (filteredMaterials.value.length ? optionHeight : 55);
  const openAbove = spaceBelow < menuHeight && spaceAbove > spaceBelow;
  const top = openAbove
    ? Math.max(4, caretTop - menuHeight - 6)
    : Math.max(4, caretBottom + 6);
  const availableOptionsHeight = Math.max(44, (openAbove ? spaceAbove : spaceBelow) - 48);
  menuStyle.value = {
    top: `${Math.round(top)}px`,
    bottom: 'auto',
    '--workbench-mention-options-height': `${Math.round(Math.min(216, availableOptionsHeight))}px`,
  };
}

function refreshTrigger() {
  const beforeCaret = textBeforeCaret();
  const match = /@([^@\s，。！？、,.;；:：]*)$/.exec(beforeCaret);
  trigger.value = match && match.index !== undefined
    ? { start: match.index, end: beforeCaret.length, query: match[1] ?? '' }
    : null;
  if (trigger.value)
    void nextTick(updateMentionMenuPosition);
}

function handleInput(event: InputEvent) {
  if (applyingDom)
    return;
  selectedMentionElement.value = null;
  emit('update:modelValue', serializeEditor());
  // An existing inline mention serializes to `@name` too. Only arm mention
  // search when the user actually inserts a new `@`; otherwise clicking or
  // editing next to an existing token would reopen the picker and cover the
  // editor. Once armed, subsequent input keeps the current query updated.
  if (trigger.value || event.data?.includes('@'))
    refreshTrigger();
  else
    trigger.value = null;
}

function insertPlainTextAtSelection(value: string) {
  const root = editor.value;
  if (!root)
    return;
  const text = value.replace(/\r\n?/g, '\n');
  const selection = window.getSelection();
  const current = selection?.rangeCount ? selection.getRangeAt(0) : null;
  const range = current && root.contains(current.commonAncestorContainer)
    ? current
    : document.createRange();
  if (!current || !root.contains(current.commonAncestorContainer)) {
    range.selectNodeContents(root);
    range.collapse(false);
  }
  range.deleteContents();
  const textNode = document.createTextNode(text);
  range.insertNode(textNode);
  range.setStartAfter(textNode);
  range.collapse(true);
  selection?.removeAllRanges();
  selection?.addRange(range);
  root.normalize();
}

function handlePaste(event: ClipboardEvent) {
  event.preventDefault();
  event.stopPropagation();
  const clipboard = event.clipboardData;
  let text = clipboard?.getData('text/plain') ?? '';
  if (!text && Array.from(clipboard?.types ?? []).includes('text/html')) {
    const fallback = document.createElement('div');
    fallback.innerHTML = clipboard?.getData('text/html') ?? '';
    text = fallback.textContent ?? '';
  }
  insertPlainTextAtSelection(text);
  selectedMentionElement.value = null;
  emit('update:modelValue', serializeEditor());
  refreshTrigger();
}

function recordMentionHistory(entry: MentionHistoryEntry) {
  if (entry.before === entry.after)
    return;
  mentionUndoStack.push(entry);
  if (mentionUndoStack.length > 100)
    mentionUndoStack.shift();
  mentionRedoStack.length = 0;
}

function applyMentionHistory(direction: 'undo' | 'redo') {
  const source = direction === 'undo' ? mentionUndoStack : mentionRedoStack;
  const target = direction === 'undo' ? mentionRedoStack : mentionUndoStack;
  const entry = source.at(-1);
  const current = serializeEditor();
  const expected = direction === 'undo' ? entry?.after : entry?.before;
  if (!entry || current !== expected)
    return false;
  source.pop();
  target.push(entry);
  selectedMentionElement.value = null;
  trigger.value = null;
  pendingCaretOffset = direction === 'undo' ? entry.undoCaretOffset : entry.redoCaretOffset;
  emit('update:modelValue', direction === 'undo' ? entry.before : entry.after);
  return true;
}

function mentionHistoryDirection(event: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'shiftKey' | 'altKey'>) {
  if ((!event.ctrlKey && !event.metaKey) || event.altKey)
    return null;
  const key = event.key.toLocaleLowerCase();
  if (key === 'z')
    return event.shiftKey ? 'redo' : 'undo';
  if (key === 'y' && !event.shiftKey)
    return 'redo';
  return null;
}

function handleBeforeInput(event: InputEvent) {
  const direction = event.inputType === 'historyUndo'
    ? 'undo'
    : event.inputType === 'historyRedo' ? 'redo' : null;
  if (direction && applyMentionHistory(direction)) {
    event.preventDefault();
    event.stopPropagation();
  }
}

function adjacentMention(direction: 'backward' | 'forward') {
  const root = editor.value;
  const selection = window.getSelection();
  if (!root || !selection?.rangeCount || !selection.isCollapsed)
    return null;
  const range = selection.getRangeAt(0);
  let candidate: Node | null = null;
  if (range.startContainer === root) {
    candidate = root.childNodes[range.startOffset + (direction === 'backward' ? -1 : 0)] ?? null;
  }
  else if (range.startContainer.nodeType === Node.TEXT_NODE) {
    const textNode = range.startContainer;
    const atBoundary = direction === 'backward' ? range.startOffset === 0 : range.startOffset === (textNode.textContent?.length ?? 0);
    if (atBoundary)
      candidate = direction === 'backward' ? textNode.previousSibling : textNode.nextSibling;
  }
  return candidate instanceof HTMLElement && candidate.classList.contains('workbench-inline-mention') ? candidate : null;
}

function removeMentionElement(element: HTMLElement | null) {
  if (!element)
    return false;
  const before = serializeEditor();
  const undoCaretOffset = currentCaretOffset() ?? before.length;
  const next = element.nextSibling;
  const previous = element.previousSibling;
  element.remove();
  if (next?.nodeType === Node.TEXT_NODE && next.textContent?.startsWith(' '))
    next.textContent = next.textContent.slice(1);
  else if (previous?.nodeType === Node.TEXT_NODE && previous.textContent?.endsWith(' '))
    previous.textContent = previous.textContent.slice(0, -1);
  const after = serializeEditor();
  recordMentionHistory({
    before,
    after,
    undoCaretOffset,
    redoCaretOffset: Math.min(undoCaretOffset, after.length),
  });
  selectedMentionElement.value = null;
  emit('update:modelValue', after);
  return true;
}

function handleKeydown(event: KeyboardEvent) {
  // Keep editor keystrokes inside the editor. In particular, Escape followed
  // by Delete must never fall through to Vue Flow's selected-node shortcuts.
  event.stopPropagation();
  const historyDirection = mentionHistoryDirection(event);
  if (historyDirection && applyMentionHistory(historyDirection)) {
    event.preventDefault();
    return;
  }
  if ((event.key === 'Backspace' || event.key === 'Delete') && removeMentionElement(
    selectedMentionElement.value ?? adjacentMention(event.key === 'Backspace' ? 'backward' : 'forward'),
  )) {
    event.preventDefault();
    return;
  }
  if (!menuOpen.value)
    return;
  if (event.key === 'Escape') {
    cancelMentionSearch(event);
    return;
  }
  if (!filteredMaterials.value.length)
    return;
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    const offset = event.key === 'ArrowDown' ? 1 : -1;
    moveActiveOption(offset);
    return;
  }
  if (event.key === 'Enter' || event.key === 'Tab') {
    event.preventDefault();
    chooseMaterial(filteredMaterials.value[activeIndex.value]!);
  }
}

function handleCapturedKeydown(event: KeyboardEvent) {
  if ((event.key === 'Escape' || event.key === 'Esc') && menuOpen.value && document.activeElement === editor.value)
    cancelMentionSearch(event);
}

function handleCapturedPointerdown(event: PointerEvent) {
  if (container.value?.contains(event.target as Node))
    lastExternalPointerDownAt = 0;
  else
    lastExternalPointerDownAt = Date.now();
}

function cancelMentionSearch(event: KeyboardEvent) {
  const triggerEnd = trigger.value?.end ?? currentCaretOffset() ?? 0;
  event.preventDefault();
  event.stopImmediatePropagation();
  trigger.value = null;
  placeCaretAtOffset(triggerEnd);
  // Re-apply once after Chrome finishes the key event. This protects against
  // native contenteditable Escape behavior without exposing it to the canvas.
  window.setTimeout(placeCaretAtOffset, 0, triggerEnd);
}

function moveActiveOption(offset: 1 | -1) {
  const length = filteredMaterials.value.length;
  const previous = activeIndex.value;
  const next = (previous + offset + length) % length;
  activeIndex.value = next;
  const wrappedToStart = offset === 1 && next < previous;
  const wrappedToEnd = offset === -1 && next > previous;
  void nextTick(() => scrollActiveOptionIntoView(wrappedToStart ? 'start' : wrappedToEnd ? 'end' : undefined));
}

function scrollActiveOptionIntoView(edge?: 'start' | 'end') {
  const container = optionList.value;
  const option = container?.children[activeIndex.value] as HTMLElement | undefined;
  if (!container || !option)
    return;
  if (edge === 'start') {
    container.scrollTop = 0;
    return;
  }
  if (edge === 'end') {
    container.scrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
    return;
  }
  const top = option.offsetTop;
  const bottom = top + option.offsetHeight;
  if (top < container.scrollTop)
    container.scrollTop = top;
  else if (bottom > container.scrollTop + container.clientHeight)
    container.scrollTop = bottom - container.clientHeight;
}

function chooseMaterial(material: MaterialMentionOption) {
  if (material.disabledReason || !trigger.value)
    return;
  const currentPrompt = serializeEditor();
  const currentTrigger = trigger.value;
  const marker = `@{${material.name}}`;
  const nextPrompt = `${currentPrompt.slice(0, currentTrigger.start)}${marker} ${currentPrompt.slice(currentTrigger.end)}`;
  pendingCaretOffset = currentTrigger.start + marker.length + 1;
  recordMentionHistory({
    before: currentPrompt,
    after: nextPrompt,
    undoCaretOffset: currentTrigger.end,
    redoCaretOffset: pendingCaretOffset,
  });
  trigger.value = null;
  emit('add', material, nextPrompt);
}

function handleEditorClick(event: MouseEvent) {
  const token = (event.target as HTMLElement).closest<HTMLElement>('.workbench-inline-mention');
  editor.value?.querySelectorAll('.workbench-inline-mention.is-selected').forEach(item => item.classList.remove('is-selected'));
  token?.classList.add('is-selected');
  selectedMentionElement.value = token ?? null;
  trigger.value = null;
}

function closeAfterBlur() {
  const triggerEnd = trigger.value?.end ?? null;
  window.setTimeout(() => {
    focused.value = document.activeElement === editor.value;
    if (!focused.value) {
      const activeElement = document.activeElement;
      const escapedToPage = triggerEnd !== null
        && Date.now() - lastExternalPointerDownAt > 250
        && (activeElement === document.body || activeElement === document.documentElement);
      trigger.value = null;
      selectedMentionElement.value = null;
      if (escapedToPage)
        placeCaretAtOffset(triggerEnd);
    }
  }, 0);
}
</script>

<template>
  <div ref="container" class="workbench-mention-editor nodrag nowheel" :class="{ 'is-focused': focused }" @pointerdown.stop @wheel.stop>
    <div
      ref="editor"
      class="workbench-mention-editor__input workbench-shot-prompt workbench-scroll-region"
      role="textbox"
      contenteditable="true"
      :aria-label="label"
      :data-placeholder="placeholder"
      aria-multiline="true"
      aria-autocomplete="list"
      :aria-expanded="menuOpen"
      :aria-controls="menuOpen ? listboxId : undefined"
      :aria-activedescendant="activeOptionId"
      @focus="focused = true"
      @blur="closeAfterBlur"
      @beforeinput="handleBeforeInput"
      @input="handleInput"
      @paste="handlePaste"
      @click="handleEditorClick"
      @keydown="handleKeydown"
      @scroll="updateMentionMenuPosition"
    />
    <span v-if="showHint !== false" class="workbench-mention-editor__hint">{{ hint || '输入 @ 引用图片、视频、音频或文字素材' }}</span>

    <div v-if="menuOpen" :id="listboxId" class="workbench-mention-menu" :style="menuStyle" role="listbox" :aria-label="`${label}素材选择`">
      <div class="workbench-mention-menu__header">
        <Search :size="14" aria-hidden="true" />
        <span>{{ trigger?.query ? `搜索“${trigger.query}”` : '选择素材' }}</span>
        <small v-if="showReferenceCounts !== false">
          图片 {{ mentions.filter(item => item.mode === 'reference_image').length }}/{{ imageLimit ?? 9 }}
          <template v-if="(videoLimit ?? 3) > 0"> · 视频 {{ mentions.filter(item => item.mode === 'reference_video').length }}/{{ videoLimit ?? 3 }}</template>
          <template v-if="(audioLimit ?? 0) > 0"> · 音频 {{ mentions.filter(item => item.mode === 'reference_audio').length }}/{{ audioLimit ?? 3 }}</template>
        </small>
      </div>
      <div v-if="filteredMaterials.length" ref="optionList" class="workbench-mention-menu__options workbench-scroll-region">
        <button
          v-for="(material, index) in filteredMaterials"
          :id="`${listboxId}-option-${index}`"
          :key="material.mentionKey || material.nodeKey"
          type="button"
          role="option"
          :aria-selected="activeIndex === index"
          :aria-disabled="Boolean(material.disabledReason)"
          :disabled="Boolean(material.disabledReason)"
          :class="{ 'is-active': activeIndex === index }"
          @pointermove="activeIndex = index"
          @mousedown.prevent="chooseMaterial(material)"
        >
          <video v-if="material.mediaKind === 'video' && material.previewUrl" :src="material.previewUrl" muted preload="metadata" aria-hidden="true" />
          <img
            v-else-if="material.previewUrl && !failedPreviewUrls.has(material.previewUrl)"
            :src="material.previewUrl"
            alt=""
            :class="{ 'is-audio-avatar': material.mediaKind === 'audio' }"
            @error="markPreviewFailed(material.previewUrl)"
          >
          <span v-else class="workbench-mention-menu__type" :class="{ 'is-audio': material.mediaKind === 'audio' }" aria-hidden="true">
            <Film v-if="material.mediaKind === 'video'" :size="16" />
            <AudioLines v-else-if="material.mediaKind === 'audio'" :size="16" />
            <ImageIcon v-else-if="material.hasImage" :size="16" />
            <FileText v-else :size="16" />
          </span>
          <span class="workbench-mention-menu__copy">
            <strong>{{ material.name }}</strong>
            <small>{{ material.disabledReason || (material.mediaKind === 'video' ? '视频素材 · 默认作为参考视频' : material.mediaKind === 'audio' ? '音频素材 · 默认作为参考音频' : material.hasImage ? '图片素材 · 默认作为参考图' : '文字素材 · 注入提示词') }}</small>
          </span>
          <Film v-if="material.mediaKind === 'video'" :size="15" aria-hidden="true" />
          <AudioLines v-else-if="material.mediaKind === 'audio'" :size="15" aria-hidden="true" />
          <ImageIcon v-else-if="material.hasImage" :size="15" aria-hidden="true" />
        </button>
      </div>
      <p v-else>
        没有可引用的素材
      </p>
    </div>
  </div>
</template>
