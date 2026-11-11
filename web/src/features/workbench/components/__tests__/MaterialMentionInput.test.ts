import type { MaterialMention } from '../materialMentionTypes';
import { fireEvent, render, waitFor } from '@testing-library/vue';
import { describe, expect, it } from 'vitest';
import MaterialMentionInput from '../MaterialMentionInput.vue';

function mention(edgeKey: string, name: string): MaterialMention {
  return {
    edgeKey,
    nodeKey: edgeKey,
    name,
    prompt: '',
    previewUrl: '',
    hasImage: false,
    mediaKind: 'text',
    mode: 'prompt_injection',
  };
}

describe('material mention input', () => {
  it.each(['5s', '2.5s', ''])('renders persisted duration %s as a token without changing its serialized syntax', async duration => {
    const syntax = `@{镜头时长${duration ? ':' + duration : ''}}`;
    const prompt = `【镜头1·${syntax}·中景】`;
    const { container, emitted } = render(MaterialMentionInput, {
      props: { modelValue: prompt, materials: [], mentions: [], label: '视频 Prompt' },
    });
    await waitFor(() => expect(container.querySelector('.is-duration')).not.toBeNull());
    const token = container.querySelector<HTMLElement>('.is-duration')!;
    expect(token.textContent).toBe(duration || '请设置时长');
    expect(token.dataset.marker).toBe(syntax);
    expect(token.querySelector('svg')).not.toBeNull();
    const editor = container.querySelector<HTMLElement>('[contenteditable]')!;
    editor.append(document.createTextNode('继续'));
    editor.dispatchEvent(new InputEvent('input', { bubbles: true, data: '继续' }));
    expect(emitted()['update:modelValue']?.at(-1)).toEqual([prompt + '继续']);
  });

  it('renders an explicitly encoded first-frame marker using its resolved image URL', async () => {
    const syntax = '@{参考图片:uploads%2F1%2Flast-frame.png}';
    const reference = { ...mention('saved-first-frame', '分镜1生成尾帧.png'), syntax,
      previewUrl: 'https://cdn.example.com/last-frame.png?signature=resolved', hasImage: true,
      mediaKind: 'image' as const, mode: 'reference_image' as const };
    const { container, emitted } = render(MaterialMentionInput, {
      props: { modelValue: `首帧参考：${syntax}`, materials: [], mentions: [reference], label: '视频 Prompt' },
    });
    await waitFor(() => expect(container.querySelector('.workbench-inline-mention')).not.toBeNull());
    const token = container.querySelector<HTMLElement>('.workbench-inline-mention')!;
    expect(token.dataset.marker).toBe(syntax);
    expect(token.textContent).toContain('分镜1生成尾帧.png');
    expect(token.querySelector('img')?.src).toBe(reference.previewUrl);
    expect(container.textContent).not.toContain('uploads%2F');
    const editor = container.querySelector<HTMLElement>('[contenteditable]')!;
    editor.dispatchEvent(new InputEvent('input', { bubbles: true }));
    expect(emitted()['update:modelValue']?.at(-1)).toEqual([`首帧参考：${syntax}`]);
  });

  it('inserts a material after compact frame and duration tokens at the serialized caret position', async () => {
    const syntax = '@{参考图片:uploads%2F1%2Flast-frame.png}';
    const prompt = `首帧参考：${syntax}\n【镜头1·@{镜头时长:5s}】 @`;
    const reference = { ...mention('first-frame', '上一镜头尾帧'), syntax, mode: 'reference_image' as const };
    const view = render(MaterialMentionInput, {
      props: { modelValue: prompt, mentions: [reference], materials: [mention('hero', '新角色')], label: '视频 Prompt' },
    });
    await waitFor(() => expect(view.container.querySelectorAll('.workbench-inline-mention')).toHaveLength(2));
    const editor = view.container.querySelector<HTMLElement>('[contenteditable]')!;
    const previousGeometry = Object.getOwnPropertyDescriptor(Range.prototype, 'getBoundingClientRect');
    Object.defineProperty(Range.prototype, 'getBoundingClientRect', { configurable: true, value: () => new DOMRect(0, 0, 1, 20) });
    try {
      editor.focus();
      const range = document.createRange();
      range.selectNodeContents(editor); range.collapse(false);
      window.getSelection()?.removeAllRanges(); window.getSelection()?.addRange(range);
      editor.dispatchEvent(new InputEvent('input', { bubbles: true, data: '@' }));
      await fireEvent.mouseDown(await view.findByRole('option', { name: /新角色/ }));
      expect(view.emitted().add?.at(-1)).toEqual([
        expect.objectContaining({ name: '新角色' }), prompt.slice(0, -1) + '@{新角色} ',
      ]);
    }
    finally {
      view.unmount();
      if (previousGeometry) Object.defineProperty(Range.prototype, 'getBoundingClientRect', previousGeometry);
      else delete (Range.prototype as Partial<Range>).getBoundingClientRect;
    }
  });

  it('pastes clipboard HTML as plain text without carrying source styles', async () => {
    const { container, emitted } = render(MaterialMentionInput, {
      props: {
        modelValue: '',
        materials: [],
        mentions: [],
        label: '图片 Prompt',
      },
    });
    const editor = container.querySelector<HTMLElement>('.workbench-mention-editor__input')!;
    editor.focus();

    const clipboardData = {
      types: ['text/plain', 'text/html'],
      getData: (type: string) => type === 'text/plain'
        ? '身份特征：唐代僧人\n服饰装备：黄袍'
        : '<span style="color:#111;background:#fff;font-size:22px">身份特征：唐代僧人<br>服饰装备：黄袍</span>',
    };
    const pasteEvent = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(pasteEvent, 'clipboardData', { value: clipboardData });
    editor.dispatchEvent(pasteEvent);

    expect(editor.textContent).toBe('身份特征：唐代僧人\n服饰装备：黄袍');
    expect(editor.querySelector('[style]')).toBeNull();
    expect(editor.querySelector('span')).toBeNull();
    expect(emitted()['update:modelValue']?.at(-1)).toEqual([
      '身份特征：唐代僧人\n服饰装备：黄袍',
    ]);
  });

  it('updates the complete mention when a connected asset is renamed', async () => {
    const { emitted, rerender } = render(MaterialMentionInput, {
      props: {
        modelValue: '【@新资产2】出现在镜头中',
        materials: [],
        mentions: [mention('edge-2', '新资产2')],
        label: '镜头画面 Prompt',
      },
    });

    await rerender({ mentions: [mention('edge-2', '18岁漂亮女同学')] });

    await waitFor(() => expect(emitted()['update:modelValue']?.at(-1)).toEqual([
      '【@18岁漂亮女同学】出现在镜头中',
    ]));
  });

  it('does not partially remove a longer mention when a prefix-named asset changes', async () => {
    const { emitted, rerender } = render(MaterialMentionInput, {
      props: {
        modelValue: '【@新资产2】与@新资产',
        materials: [],
        mentions: [mention('edge-1', '新资产'), mention('edge-2', '新资产2')],
        label: '镜头画面 Prompt',
      },
    });

    await rerender({ mentions: [mention('edge-1', '女主'), mention('edge-2', '新资产2')] });

    await waitFor(() => expect(emitted()['update:modelValue']?.at(-1)).toEqual([
      '【@新资产2】与@女主',
    ]));
  });

  it('renders storyboard-style braced asset references as the same inline mention token', async () => {
    const reference = {
      ...mention('edge-building', '郊区小楼'),
      previewUrl: '/media/building.png',
      hasImage: true,
      mediaKind: 'image' as const,
      mode: 'reference_image' as const,
      assetCategory: 'scene' as const,
    };
    const { container } = render(MaterialMentionInput, {
      props: {
        modelValue: '镜头缓慢向 @{郊区小楼} 推近',
        materials: [reference],
        mentions: [reference],
        label: '镜头画面 Prompt',
      },
    });

    await waitFor(() => expect(container.querySelector('.workbench-inline-mention')).not.toBeNull());
    const token = container.querySelector<HTMLElement>('.workbench-inline-mention');
    expect(token?.dataset.marker).toBe('@{郊区小楼}');
    expect(token?.dataset.assetCategory).toBe('scene');
    expect(token).toHaveClass('is-asset-scene');
    expect(token?.textContent).toContain('@郊区小楼');
  });

  it('assigns distinct asset category classes independent of reference mode', async () => {
    const person = { ...mention('edge-person', '女主'), assetCategory: 'person' as const };
    const item = { ...mention('edge-item', '柠檬水'), assetCategory: 'item' as const };
    const { container } = render(MaterialMentionInput, {
      props: {
        modelValue: '@{女主}拿起@{柠檬水}',
        materials: [person, item],
        mentions: [person, item],
        label: '镜头画面 Prompt',
      },
    });

    await waitFor(() => expect(container.querySelectorAll('.workbench-inline-mention')).toHaveLength(2));
    expect(container.querySelector('[data-asset-category="person"]')).toHaveClass('is-asset-person');
    expect(container.querySelector('[data-asset-category="item"]')).toHaveClass('is-asset-item');
  });
});
