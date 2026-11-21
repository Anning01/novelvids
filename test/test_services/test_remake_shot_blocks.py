import asyncio
import pytest

from services.remake.shot_blocks import confirmed_blocks


@pytest.mark.asyncio
@pytest.mark.parametrize('capacity', [1, 2, 4])
async def test_parallel_drafts_recheck_the_seam_and_propagate_only_changed_context(capacity):
    seen, adopted, progress = [], [], []
    active = peak = 0
    async def run(i, previous, draft):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.002)
        active -= 1
        seen.append((i, draft, previous))
        return {'actions': [f'{i}-corrected' if i == 4 and not draft else str(i)]}
    async def promote(i, data):
        adopted.append(i)
        return data
    async def report(i, n):
        progress.append((i, n))
    result = await confirmed_blocks(12, 3, capacity=capacity, language='zh', confirmed={}, drafts={},
                                    run=run, promote=promote, report=report)
    assert peak == capacity
    assert len(result) == 12
    assert result[3]['actions'] == ['4-corrected']
    assert (5, False, result[3]) in seen
    assert all((i, False, result[i - 2]) in seen for i in (4, 7, 10))
    assert set(adopted) == {6, 8, 9, 11, 12}
    assert progress == [(i, 12) for i in range(1, 13)]


@pytest.mark.asyncio
async def test_partial_drafts_are_drained_and_reused_on_retry():
    confirmed, drafts, calls = {}, {}, []
    fail = True
    async def run(i, prev, draft):
        calls.append((i, draft))
        await asyncio.sleep(.001)
        if i == 4 and draft and fail:
            raise TimeoutError()
        return {'actions':[str(i)]}
    async def promote(_, value):
        return value
    args = dict(capacity=2, language='en', confirmed=confirmed, drafts=drafts, run=run, promote=promote, report=None)
    with pytest.raises(TimeoutError):
        await confirmed_blocks(6, 3, **args)
    saved = set(confirmed)
    calls.clear()
    fail = False
    result = await confirmed_blocks(6, 3, **args)
    assert len(result) == 6
    assert not any(i in saved for i, _ in calls)


@pytest.mark.asyncio
async def test_accepted_boundary_keeps_original_draft_and_avoids_cascading_paid_rewrites():
    audits, rewrites = [], []
    async def run(i, previous, draft):
        if not draft:
            rewrites.append(i)
        return {'actions': [str(i)]}
    async def audit(i, previous, candidate):
        audits.append(i)
        assert previous['actions'] == [str(i-1)] and candidate['actions'] == [str(i)]
        return True
    async def keep(_, data):
        return data
    values = await confirmed_blocks(12, 4, capacity=3, language='zh', confirmed={}, drafts={},
                                   run=run, promote=keep, report=None, audit=audit)
    assert len(values) == 12 and audits == [5,9] and rewrites == [1,2,3,4]


@pytest.mark.asyncio
async def test_first_seam_is_checked_while_a_later_block_is_still_generating():
    reached_seam = asyncio.Event()
    events = []
    async def run(i, previous, draft):
        if i == 9:
            await asyncio.wait_for(reached_seam.wait(), 2)
        await asyncio.sleep(0)
        events.append(('draft' if draft else 'final', i))
        return {'actions':[str(i)]}
    async def audit(i, previous, candidate):
        events.append(('audit', i))
        if i == 4:
            reached_seam.set()
        return True
    async def promote(_, data):
        return data
    result = await confirmed_blocks(9, 3, capacity=4, language='zh', confirmed={}, drafts={}, run=run,
                                    promote=promote, report=None, audit=audit)
    assert events.index(('audit',4)) < events.index(('draft',9))
    assert [x['actions'] for x in result] == [[str(i)] for i in range(1,10)]


@pytest.mark.asyncio
async def test_pressure_in_one_block_preserves_later_independent_drafts():
    from services.remake.gateway import RemakeVideoAnalysisError
    confirmed,drafts = {},{}
    async def run(i, previous, draft):
        await asyncio.sleep(.001)
        if i == 4:
            raise RemakeVideoAnalysisError("busy",error_code="REMAKE_ANALYSIS_RATE_LIMITED")
        return {'actions':[str(i)]}
    async def promote(_, value):
        return value
    with pytest.raises(RemakeVideoAnalysisError):
        await confirmed_blocks(9,3,capacity=2,language='en',confirmed=confirmed,drafts=drafts,
                               run=run,promote=promote,report=None)
    assert set(confirmed)=={1,2,3} and set(drafts)=={7,8,9}
