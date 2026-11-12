import xml.etree.ElementTree as ET
import pytest
from services.oss.lifecycle import RULE_ID, TEMP_PREFIX, with_temporary_expiry


def test_prefix_cleanup_preserves_existing_rules_and_is_idempotent():
    before = b'<LifecycleConfiguration><Rule><ID>original</ID><Prefix>another/</Prefix><Status>Enabled</Status><Expiration><Days>365</Days></Expiration></Rule></LifecycleConfiguration>'
    updated = with_temporary_expiry(before)
    root=ET.fromstring(updated)
    assert ET.tostring(root[0])==ET.tostring(ET.fromstring(before)[0])
    assert len(root)==2 and root[1].findtext('Prefix')==TEMP_PREFIX
    assert root[1].findtext('Expiration/Days')=='2'
    assert with_temporary_expiry(updated)==updated
    with pytest.raises(ValueError):
        with_temporary_expiry(f'<LifecycleConfiguration><Rule><ID>{RULE_ID}</ID><Prefix>originals/</Prefix></Rule></LifecycleConfiguration>'.encode())


def test_same_bucket_configuration_requires_no_extra_bucket(monkeypatch):
    from config import settings
    from services.platform.temporary_media import bucket_config
    for key,value in {"STUDIO_TEMP_BUCKET":"","STUDIO_TEMP_REGION":"","OSS_BUCKET":"test-bucket",
                      "OSS_ENDPOINT":"oss-cn-guangzhou.aliyuncs.com","OSS_ACCESS_KEY_ID":"test","OSS_ACCESS_KEY_SECRET":"test"}.items():
        monkeypatch.setattr(settings,key,value)
    result=bucket_config()
    assert result.bucket=="test-bucket" and result.region=="cn-guangzhou"


def test_configuration_previews_then_backups_merges_and_verifies(tmp_path, monkeypatch):
    import httpx
    from types import SimpleNamespace
    from scripts import configure_oss_temp_lifecycle as command
    from services.oss.temporary import TemporaryBucket
    bucket=TemporaryBucket("test-bucket","cn-guangzhou","test-id","test-secret")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(command,"bucket_config",lambda:bucket)
    state={"body":None,"puts":0}
    real=httpx.Client
    def api(req):
        if req.method=="GET":
            return httpx.Response(200,content=state["body"]) if state["body"] else httpx.Response(404,content=b"<Error><Code>NoSuchLifecycle</Code></Error>")
        assert req.method=="PUT" and req.headers["content-md5"]
        state["body"]=req.content
        state["puts"]+=1
        return httpx.Response(200)
    monkeypatch.setattr(httpx,"Client",lambda **kw:real(**kw,transport=httpx.MockTransport(api)))
    command.configure()
    assert state["puts"]==0 and not list(tmp_path.iterdir())
    command.configure(apply=True)
    assert state["puts"]==1
    backups=list(tmp_path.glob("data/oss-lifecycle-backups/*.xml"))
    assert len(backups)==1 and backups[0].read_bytes()==b"<LifecycleConfiguration/>"
    assert ET.fromstring(state["body"]).findtext("Rule/Expiration/Days")=="2"
