import type { MaterialMention } from '../materialMentionTypes';
import { fireEvent, render, screen } from '@testing-library/vue';
import { describe, expect, it } from 'vitest';
import PromptReferenceImageStrip from '../PromptReferenceImageStrip.vue';

const imageMention: MaterialMention = {
  nodeKey: 'asset-character',
  connectionKey: 'edge-character',
  edgeKey: 'edge-character:image:0',
  name: '将军-图1',
  sourceName: '将军',
  prompt: '古代将军',
  previewUrl: 'https://cdn.example.com/general.jpg',
  hasImage: true,
  mediaKind: 'image',
  mode: 'reference_image',
};

describe('promptReferenceImageStrip', () => {
  it('shows a numbered image preview and exposes focus and removal actions on hover', async () => {
    const view = render(PromptReferenceImageStrip, {
      props: { mentions: [imageMention] },
    });

    const thumbnail = screen.getByRole('button', { name: '参考图片 1：将军-图1，双击聚焦来源节点' });
    expect(thumbnail).toHaveTextContent('1');
    expect(screen.queryByLabelText('将军大图预览')).not.toBeInTheDocument();

    await fireEvent.mouseEnter(thumbnail.closest('li')!);
    const preview = screen.getByLabelText('将军大图预览');
    expect(preview).toBeInTheDocument();
    expect(preview.closest('.workbench-prompt-references-viewport')).toBeNull();
    expect(screen.getByText('将军')).toBeInTheDocument();
    expect(screen.getByText('双击可聚焦至节点')).toBeInTheDocument();

    await fireEvent.dblClick(thumbnail);
    expect(view.emitted().focus?.[0]).toEqual(['asset-character']);

    await fireEvent.keyDown(thumbnail, { key: 'Enter' });
    expect(view.emitted().focus?.[1]).toEqual(['asset-character']);

    await fireEvent.click(screen.getByRole('button', { name: '移除参考图片 1：将军-图1' }));
    expect(view.emitted().remove?.[0]).toEqual(['edge-character']);
  });

  it('keeps non-image references out of the image strip', () => {
    render(PromptReferenceImageStrip, {
      props: {
        mentions: [{
          ...imageMention,
          edgeKey: 'edge-audio',
          connectionKey: 'edge-audio',
          name: '旁白',
          mediaKind: 'audio',
          mode: 'reference_audio',
        }],
      },
    });

    expect(screen.queryByLabelText('Prompt 参考图片')).not.toBeInTheDocument();
  });
});
