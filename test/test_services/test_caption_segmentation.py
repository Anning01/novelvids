import pytest
from unittest.mock import AsyncMock, patch
from auth.deps import AuthContext
from schemas.video_edit import EditDocument, SubtitleClip
from services.video_editor.recognition import split_document_subtitles

from services.video_editor.captions import split_utterance


def test_splits_long_chinese_utterances_without_losing_words():
    text='这是第一段需要按照时间拆分的说明文字，接下来是一段比较长的通用测试内容，希望每条字幕能够保持适合阅读的长度，同时保留前后句子的顺序以及所有文字，最后检查整段内容对应的结束时间是否正确'
    pieces=split_utterance({'text':text,'start_time':1000,'end_time':11000})
    assert len(pieces)>3
    assert ''.join(p.text for p in pieces)==text.replace('，','')
    assert all(len(p.text)<=20 for p in pieces)
    assert pieces[0].start==1 and pieces[-1].end==11
    assert all(a.end<=b.start for a,b in zip(pieces,pieces[1:]))


def test_uses_word_timestamps_instead_of_distributing_over_long_silence():
    text='这是前面的一句完整短字幕，这是后面的一句完整短字幕'
    left,_,right=text.partition('，')
    words=[{'text':c,'start_time':i*100,'end_time':(i+1)*100} for i,c in enumerate(left)]
    words += [{'text':c,'start_time':8000+i*100,'end_time':8000+(i+1)*100} for i,c in enumerate(right)]
    pieces=split_utterance({'text':text,'start_time':0,'end_time':10000,'words':words})
    assert pieces[0].end<2
    assert pieces[-1].start>=8


def test_english_splitting_keeps_words_and_all_text():
    text='This is a longer caption that should be split into readable phrases without chopping individual words apart.'
    pieces=split_utterance({'text':text,'start_time':0,'end_time':12000})
    assert ' '.join(p.text for p in pieces)==text.rstrip('.')
    assert len(pieces)>1


@pytest.mark.asyncio
async def test_splitting_existing_subtitles_is_local_preserves_style_and_respects_selection():
    long='这是一段用于字幕拆分的通用说明文字' * 3
    first=SubtitleClip(id='first',type='subtitle',start=0,duration=6,text=long,font_size=55,color='#ffff00',bold=True)
    second=SubtitleClip(id='second',type='subtitle',start=6,duration=6,text=long)
    doc=EditDocument(clips=[first,second])
    original=doc.model_dump()
    with patch('services.video_editor.recognition.chapter_scope',new=AsyncMock()), patch('services.video_editor.recognition.VolcSeedAsrClient.recognize',new=AsyncMock()) as recognize, patch('services.video_editor.recognition.billing_recorder.record_asr',new=AsyncMock()) as bill:
        result=await split_document_subtitles(1,AuthContext(),doc,['first'])
    recognize.assert_not_awaited()
    bill.assert_not_awaited()
    assert doc.model_dump()==original
    assert result['split_count']==1
    clips=result['document']['clips']
    assert clips[-1]['id']=='second' and clips[-1]['text']==long
    assert len(clips)>3
    assert all(c['font_size']==55 and c['color']=='#ffff00' and c['bold'] for c in clips[:-1])
    assert clips[0]['id']=='first' and clips[0]['start']==0
    assert clips[-2]['start']+clips[-2]['duration']==6


@pytest.mark.parametrize('item', [None, {}, {'text': 123}, {'text':'   '}])
def test_empty_or_invalid_utterances_do_not_create_captions(item):
    assert split_utterance(item)==[]
