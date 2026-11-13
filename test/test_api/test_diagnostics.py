import json
from types import SimpleNamespace

import pytest

from auth.deps import AuthContext
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from services.diagnostics import recent_tasks


@pytest.mark.asyncio
async def test_recent_limits_before_export_and_isolates_users_and_teams():
    params = {'user_id':4,'team_id':5,'novel_id':17,'prompt':'private-manuscript','api_key':'secret-key'}
    tasks = [await AiTask.create(task_type=6,status=4,request_params=params,
        error_message='第 5 个视频片段分析失败：增量修复 private-manuscript') for _ in range(101)]
    for user,team in [(9,5),(4,9),(4,None),(None,None)]:
        await AiTask.create(task_type=6,status=4,request_params={'user_id':user,'team_id':team})
    await AgentOperation.create(task=tasks[-1],key='diagnostic:failure',state='completed',
        result={'exception':'ValueError','file':'services/remake/gateway.py','line':120,'payload':'private-manuscript'})
    result = await recent_tasks(AuthContext(user=SimpleNamespace(id=4),team_id=5))
    assert [r['task_id'] for r in result] == [str(t.id) for t in reversed(tasks[1:])]
    assert result[0]['reason']=='validation' and result[0]['clip']==5
    assert result[0]['file']=='services/remake/gateway.py' and result[0]['line']==120
    assert 'private-manuscript' not in json.dumps(result) and 'secret-key' not in json.dumps(result)
    assert len(await recent_tasks(AuthContext(user=SimpleNamespace(id=4)))) == 1
    assert len(await recent_tasks(AuthContext())) == 1
