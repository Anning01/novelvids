import pytest
from pydantic import ValidationError

from schemas.video_edit import SubtitleClip, EditDocument, EditSave
from services.video_editor.subtitles import subtitle_styles, subtitle_ass, wrap_subtitle, escape_ass


def caption(**patch):
    return SubtitleClip(id='caption',type='subtitle',start=0,duration=1,text='文本\n字幕',**patch)


def test_exactly_thirteen_bounded_presets_plus_none():
    styles=subtitle_styles()
    assert len(styles)==14 and styles[0]['id']=='none'
    assert len({style['id'] for style in styles})==14
    for style in styles:
        clip=caption(**{key:value for key,value in style.items() if key not in {'id','name'}})
        assert clip.stroke_width <= 3
    assert caption().align=='center' and caption().opacity==1


@pytest.mark.parametrize('patch',[{'letter_spacing':-6},{'line_spacing':101},{'opacity':1.1},{'opacity':float('nan')},{'align':'justify'},{'stroke_color':'red'},{'stroke_width':11}])
def test_invalid_subtitle_styles_are_rejected(patch):
    with pytest.raises(ValidationError):caption(**patch)


def test_ass_layout_encodes_formatting_opacity_alignment_and_line_spacing():
    clip=caption(font_size=60,bold=True,italic=True,underline=True,letter_spacing=4,line_spacing=12,align='left',opacity=.5,stroke_color='#ff244a')
    text=subtitle_ass(clip,1920,1080)
    assert '&H80ffffff' in text and '&H804a24ff' in text
    assert ',-1,-1,-1,0,100,100,4.00000,' in text
    events=[line for line in text.splitlines() if line.startswith('Dialogue:')]
    assert len(events)==2
    assert r'\an7' in events[0]
    assert ',804.00000)' in events[0] and ',888.00000)' in events[1]
    assert wrap_subtitle('你好世界你好',100,30,20)=='你好\n世界\n你好'
    escaped=escape_ass(r'{\alpha&HFF&}\Nunsafe')
    assert r'{\alpha' not in escaped and r'\Nunsafe' not in escaped


@pytest.mark.asyncio
async def test_subtitle_style_draft_roundtrip_and_old_draft_defaults():
    from test.test_services.test_video_editor import project
    from services.video_editor.drafts import read_draft,save_draft
    from models.video_edit import ChapterEditDraft
    from auth.deps import AuthContext
    from tortoise import Tortoise
    _,chapter,_,_=await project()
    legacy={'version':1,'clips':[{'id':'s','type':'subtitle','start':0,'duration':1,'text':'旧字幕','bottom':10}]}
    draft=await ChapterEditDraft.create(chapter=chapter,document=legacy)
    for _ in range(2):
        await Tortoise.generate_schemas(safe=True)
        assert (await ChapterEditDraft.get(id=draft.id)).document==legacy
        data=(await read_draft(chapter.id,AuthContext()))['document']['clips'][0]
        assert data['opacity']==1 and not data['bold'] and data['letter_spacing']==0
    clip=caption(bold=True,italic=True,underline=True,opacity=.4,letter_spacing=3,line_spacing=10,align='right')
    await save_draft(chapter.id,EditSave(revision=draft.revision,document=EditDocument(clips=[clip])),AuthContext())
    saved=(await read_draft(chapter.id,AuthContext()))['document']['clips'][0]
    assert saved['bold'] and saved['italic'] and saved['underline']
    assert saved['opacity']==.4 and saved['align']=='right' and saved['line_spacing']==10


@pytest.mark.asyncio
async def test_rendered_subtitle_opacity_and_rich_formatting_reach_encoded_frames(tmp_path):
    from services.video_editor.render import EditRenderer
    from unittest.mock import AsyncMock
    from test.test_services.test_video_editor import ffmpeg
    async def cancelled():return False
    async def pixels(name,**patch):
        directory=tmp_path/name;directory.mkdir()
        clip=SubtitleClip(id='styled',type='subtitle',start=0,duration=1,text='Rich text\n字幕',font_size=120,**patch)
        renderer=EditRenderer(cancelled=cancelled,progress=AsyncMock())
        output=await renderer.render(EditDocument(width=320,height=180,clips=[clip]),{},directory)
        return ffmpeg('-ss','0.5','-i',output,'-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-')
    plain=await pixels('plain',stroke_width=0,shadow=0)
    styled=await pixels('styled',bold=True,underline=True,italic=True,letter_spacing=5,line_spacing=20,align='left',opacity=.5,stroke_color='#ff244a',stroke_width=3)
    invisible=await pixels('invisible',bold=True,underline=True,opacity=0)
    assert max(plain)>220 and max(invisible)<20
    assert 60<max(styled)<185
    assert styled!=plain


@pytest.mark.asyncio
async def test_capabilities_publish_the_same_thirteen_presets(client):
    from auth.deps import get_auth_context,AuthContext
    from main import app
    app.dependency_overrides[get_auth_context]=lambda:AuthContext()
    try:
        response=(await client.get('/api/video-editor/capabilities')).json()
        assert response['code']==0,response
        assert response['data']['subtitle_styles']==subtitle_styles()
    finally:
        app.dependency_overrides.pop(get_auth_context,None)
