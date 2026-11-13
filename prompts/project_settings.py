"""Default project-wide audiovisual direction, shared by display and generation."""


def default_audiovisual_guidance(language: str = 'zh') -> str:
    if language == 'en':
        return ('Keep character identities, costumes, props, lighting and spatial continuity consistent. '
                'Use clear cinematic composition and natural performances; let the story guide camera movement and editing. '
                'Preserve dialogue, speakers and speech order; distinguish offscreen voices and inner thoughts from visible speakers. '
                'Use scene-appropriate ambience and sound effects; add music only when it serves the scene. '
                'No unrequested subtitles, text, logos or watermarks.')
    return ('保持人物身份、服装、道具、光线与空间关系连续一致；采用清晰的电影化构图和自然表演，运镜与剪辑服务于剧情。'
            '完整保留对白、说话者与台词顺序，区分画外声音、内心独白和画面中开口说话。'
            '按场景配置环境声与动作音效，配乐仅在剧情需要时使用；不添加未要求的字幕、文字、标识或水印。')


def audiovisual_guidance(value: str | None, language: str = 'zh') -> str:
    if not value or not value.strip() or value == default_audiovisual_guidance():
        return default_audiovisual_guidance(language)
    return value.strip()
