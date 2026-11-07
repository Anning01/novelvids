import pytest

from config import settings
from models.ai_task import AiTask
from models.asset import Asset
from test.test_auth.test_rbac_matrix import rbac_world

pytestmark = pytest.mark.skipif(not settings.AUTH_ENABLED, reason='Requires team authorization')


@pytest.mark.asyncio
@pytest.mark.parametrize('actor,foreign,code', [('rbac_viewer', False, 403), ('rbac_creator', True, 404)])
async def test_batch_keeps_existing_role_and_project_access(client, rbac_world, actor, foreign, code):
    novel = rbac_world['novel_b' if foreign else 'novel_a']
    asset = await Asset.create(novel=novel, canonical_name='Scoped image', asset_type=1)
    response = await client.post('/api/asset/reference-batch', headers={
        'Authorization': 'Bearer ' + rbac_world['tokens'][actor],
    }, json={'novel_id': novel.id, 'asset_ids': [asset.id], 'model_config_id': 1,
             'clarity': 'medium', 'aspect_ratio': '1:1', 'output_format': 'png'})
    assert response.json()['code'] == code, response.text
    assert await AiTask.filter(task_type=2).count() == 0
