import asyncio
import json
import sys
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_two_processes_and_restart_reuse_content_even_with_different_request_ids(tmp_path):
    script = r'''
import asyncio,json,sys,os
from pathlib import Path
root,mode=Path(sys.argv[1]),sys.argv[2]
os.environ['DATABASE_URL']='sqlite://'+str(root/'race.db')
os.environ['MEDIA_PATH']=str(root)
os.environ['AUTH_ENABLED']='false'
from main import tortoise_config
from tortoise import Tortoise
from models.novel import Novel
from models.chapter import Chapter
from models.chapter_export import ChapterExport
from models.config import AiModelConfig
from models.creation_agent import AgentSettings
from models.ai_task import AiTask
from controllers.chapter_export import chapter_exports
from services.video_enhancement.contract import ENHANCEMENT_PRESET
from services.video_enhancement.media import file_digest
from schemas.video_export import ExportEnhanceIn
from auth.deps import AuthContext
async def main():
 await Tortoise.init(config=tortoise_config)
 try:
  if mode=='setup':
   await Tortoise.generate_schemas(safe=True)
   n=await Novel.create(name='Process test');c=await Chapter.create(novel=n,number=1,name='One',content='Fixture')
   await AgentSettings.create(id=1,configuration={'enabled':True})
   await AiModelConfig.create(task_type=7,name='assistant',model='fake',base_url='https://example.invalid',api_key='fake',is_active=True,supports_tool_calls=True)
   await AiModelConfig.create(task_type=8,name='enhancement',api_key='fake',is_active=True,**ENHANCEMENT_PRESET)
   path=root/'source.mp4';path.write_bytes(b'Frozen source')
   await ChapterExport.create(novel_id=n.id,chapter_id=c.id,identity_key='a'*64,source_version='b'*64,
     source_sha256=file_digest(path),source_media_ref='/media/source.mp4',source_probe={'duration':'5','width':864,'height':496,'fps':'24'})
   print('{}');return
  if mode!='replay':
   (root/('ready-'+mode)).touch()
   for _ in range(500):
    if (root/'ready-1').exists() and (root/'ready-2').exists():break
    await asyncio.sleep(.01)
   else:raise RuntimeError('process barrier timeout')
  source=await ChapterExport.get(id=1);cfg=await AiModelConfig.get(task_type=8)
  quote=await chapter_exports.quote(source,cfg.id,AuthContext())
  export,task=await chapter_exports.enhance(source.id,ExportEnhanceIn(model_config_id=cfg.id,
      source_sha256=quote['source_sha256'],quote_version=quote['quote_version']),AuthContext())
  print(json.dumps({'export':export.id,'task':str(task.id),'count':await AiTask.filter(task_type=8).count()}))
 finally:await Tortoise.close_connections()
asyncio.run(main())
'''
    async def run(mode):
        process=await asyncio.create_subprocess_exec(sys.executable,'-c',script,str(tmp_path),mode,
            cwd=Path(__file__).resolve().parents[2],stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        stdout,stderr=await asyncio.wait_for(process.communicate(),30)
        assert process.returncode==0,stderr.decode()
        return json.loads(stdout)
    await run('setup')
    first,second=await asyncio.gather(run('1'),run('2'))
    replay=await run('replay')
    assert first['export']==second['export']==replay['export']
    assert first['task']==second['task']==replay['task']
    assert first['count']==second['count']==replay['count']==1
