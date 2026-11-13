"""Review or apply the temporary-media prefix's two-day OSS lifecycle rule."""
import argparse
import base64
from datetime import datetime, timezone
from email.utils import formatdate
import hashlib
import hmac
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from services.oss.lifecycle import TEMP_PREFIX, with_temporary_expiry
from services.platform.temporary_media import bucket_config


def lifecycle_request(client, bucket, method, body=None):
    date = formatdate(usegmt=True)
    checksum = base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode() if body else ""
    content_type = "application/xml" if body else ""
    resource = f"/{bucket.bucket}/?lifecycle"
    canonical = "\n".join([method, checksum, content_type, date, resource])
    signature = base64.b64encode(hmac.digest(bucket.secret.encode(), canonical.encode(), "sha1")).decode()
    headers = {"Date":date, "Authorization":f"OSS {bucket.access_id}:{signature}"}
    if body:
        headers.update({"Content-Type":content_type, "Content-MD5":checksum})
    response = client.request(method, f"https://{bucket.bucket}.oss-{bucket.region}.aliyuncs.com/?lifecycle",
                              headers=headers, content=body)
    if response.status_code == 404 and method == "GET" and ET.fromstring(response.content).findtext("Code") == "NoSuchLifecycle":
        return None
    response.raise_for_status()
    return response.content


def configure(*, apply=False):
    bucket = bucket_config()
    if bucket is None:
        raise ValueError("OSS configuration is incomplete")
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        old = lifecycle_request(client, bucket, "GET")
        merged = with_temporary_expiry(old)
        print(f"Temporary media rule: prefix={TEMP_PREFIX}, days=2")
        if not apply:
            print("Preview only. Use --apply to save this rule.")
            return
        backup = Path("data/oss-lifecycle-backups")
        backup.mkdir(parents=True, exist_ok=True, mode=0o700)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        file = backup / (timestamp + ".xml")
        with file.open("xb") as output:
            file.chmod(0o600)
            output.write(old or b"<LifecycleConfiguration/>")
        if lifecycle_request(client, bucket, "GET") != old:
            raise ValueError("Bucket lifecycle changed during review. Run again.")
        lifecycle_request(client, bucket, "PUT", merged)
        actual = lifecycle_request(client, bucket, "GET")
        if actual is None or ET.canonicalize(actual, strip_text=True) != ET.canonicalize(merged, strip_text=True):
            raise ValueError("Saved lifecycle rule does not match the reviewed document")
        print("Saved and verified. Previous rule configuration backed up.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    configure(apply=parser.parse_args().apply)
