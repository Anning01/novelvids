import type { MaterialMention } from '../materialMentionTypes';
import { render, waitFor } from '@testing-library/vue';
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
