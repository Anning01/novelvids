import type { WorkbenchPromptEditor } from '../../types/workbenchTypes';
import { fireEvent, render, waitFor } from '@testing-library/vue';
import { describe, expect, it, vi } from 'vitest';
import { ref } from 'vue';
import { createWorkbenchPromptActionRegistry, workbenchPromptActionRegistryKey } from '../../prompt/promptActionRegistry';
import ImageGenerationParameterPanel, { type ImageGenerationParameters } from '@/components/ImageGenerationParameterPanel.vue';
import MediaGenerationModelSelector from '../MediaGenerationModelSelector.vue';
import WorkbenchPromptEditorPanel from '../WorkbenchPromptEditorPanel.vue';

const config: WorkbenchPromptEditor = {
  editorKey: 'asset_prompt',
  nodeKind: 'asset',
  fieldKey: 'prompt',
  label: '图片 Prompt',
  placeholder: '描述画面',
  hint: '',
  allowedAssetTypes: null,
  excludedAssetTypes: null,
  referenceLimits: { image: 10, video: 0, audio: 0 },
  allowPromptInjection: false,
};

describe('workbenchPromptEditorPanel positioning', () => {
  it('stays anchored below the node while the canvas pans', async () => {
    vi.spyOn(window, 'innerWidth', 'get').mockReturnValue(1280);
    vi.spyOn(window, 'innerHeight', 'get').mockReturnValue(768);
    const anchor = document.createElement('div');
    anchor.className = 'vue-flow__node';
    anchor.dataset.id = 'asset-1';
    let anchorRect = DOMRect.fromRect({ x: 700, y: 100, width: 350, height: 300 });
    vi.spyOn(anchor, 'getBoundingClientRect').mockImplementation(() => anchorRect);
    document.body.append(anchor);

    const view = render(WorkbenchPromptEditorPanel, {
      props: {
        open: true,
        nodeKey: 'asset-1',
        config,
        modelValue: '人物设定',
        materials: [],
        mentions: [],
      },
    });
    const panel = await waitFor(() => view.getByRole('dialog', { name: '图片 Prompt编辑器' }));
    await waitFor(() => expect(panel).toHaveStyle({ top: '406px', left: '619px', width: '512px', height: '320px' }));

    anchorRect = DOMRect.fromRect({ x: 200, y: 150, width: 350, height: 300 });
    await waitFor(() => expect(panel).toHaveStyle({ top: '456px', left: '119px' }));

    view.unmount();
    anchor.remove();
  });

  it('renders registered node actions in the extensible bottom action bar', async () => {
    const registry = createWorkbenchPromptActionRegistry();
    const run = vi.fn();
    const modelConfigId = ref<number | null>(7);
    const imageParameters = ref<ImageGenerationParameters>({
      clarity: 'high',
      aspectRatio: '16:9',
      outputFormat: 'png',
      generationCount: 1,
    });
    registry.register('asset-1', {
      id: 'asset-image-generation',
      label: '生成资产图片',
      enabled: ref(true),
      busy: ref(false),
      progress: ref(null),
      controls: [
        {
          id: 'asset-image-generation-model',
          component: MediaGenerationModelSelector,
          props: ref({
            options: [{ value: 7, label: 'Seedream 5.0 Pro' }],
            label: '图片模型',
          }),
          modelValue: modelConfigId,
          updateModelValue(value) {
            modelConfigId.value = Number(value);
          },
        },
        {
          id: 'asset-image-generation-parameters',
          component: ImageGenerationParameterPanel,
          props: ref({
            capabilities: {
              clarities: ['high'],
              aspect_ratios: ['16:9'],
              output_formats: ['png'],
              generation_counts: [1],
              default_clarity: 'high',
              default_aspect_ratio: '16:9',
              default_output_format: 'png',
              default_generation_count: 1,
            },
            compact: true,
          }),
          modelValue: imageParameters,
          updateModelValue(value) {
            imageParameters.value = value as ImageGenerationParameters;
          },
        },
      ],
      run,
    });
    const view = render(WorkbenchPromptEditorPanel, {
      props: {
        open: true,
        nodeKey: 'asset-1',
        config,
        modelValue: '人物设定',
        materials: [],
        mentions: [],
      },
      global: {
        provide: {
          [workbenchPromptActionRegistryKey as symbol]: registry,
        },
      },
    });

    const modelSelector = await view.findByRole('button', { name: '图片模型' });
    const parameterTrigger = view.getByRole('button', { name: '设置图片生成参数' });
    expect(modelSelector.closest('.workbench-prompt-panel__footer-start')).toBeInTheDocument();
    expect(parameterTrigger.closest('.workbench-prompt-panel__footer-start')).toBeInTheDocument();
    expect(parameterTrigger).toHaveTextContent('16:9 · 高 · 1张 · PNG');
    await fireEvent.click(await view.findByRole('button', { name: '生成资产图片' }));

    expect(run).toHaveBeenCalledOnce();
    expect(view.getByText('4 字')).toBeInTheDocument();
    view.unmount();
  });
});
