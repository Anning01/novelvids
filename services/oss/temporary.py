"""Short-lived OSS V4 URLs for one exact object and operation."""
import logging
import httpx
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from hmac import digest
from urllib.parse import quote, urlencode


@dataclass(frozen=True)
class TemporaryBucket:
    bucket: str
    region: str
    access_id: str = field(repr=False)
    secret: str = field(repr=False)

    def sign(self, method: str, key: str, now: datetime, seconds: int, headers: dict | None = None) -> str:
        time = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        day = time[:8]
        host = f"{self.bucket}.oss-{self.region}.aliyuncs.com"
        scope = f"{day}/{self.region}/oss/aliyun_v4_request"
        signed = {"host": host, **(headers or {})}
        additional = ";".join(sorted(k for k in signed if k not in {"content-type", "content-md5"} and not k.startswith("x-oss-")))
        params = {"x-oss-additional-headers": additional, "x-oss-credential": f"{self.access_id}/{scope}",
                  "x-oss-date": time, "x-oss-expires": str(seconds), "x-oss-signature-version": "OSS4-HMAC-SHA256"}
        query = urlencode(sorted(params.items()), quote_via=quote, safe="")
        canonical_headers = "".join(f"{k}:{signed[k]}\n" for k in sorted(signed))
        path = quote(key, safe="/")
        canonical = f"{method}\n/{self.bucket}/{path}\n{query}\n{canonical_headers}\n{additional}\nUNSIGNED-PAYLOAD"
        string = f"OSS4-HMAC-SHA256\n{time}\n{scope}\n{sha256(canonical.encode()).hexdigest()}"
        signing = ("aliyun_v4" + self.secret).encode()
        for component in (day, self.region, "oss", "aliyun_v4_request"):
            signing = digest(signing, component.encode(), "sha256")
        signature = digest(signing, string.encode(), "sha256").hex()
        return f"https://{host}/{path}?{query}&x-oss-signature={signature}"


# httpx normally includes the entire request URL in its INFO log. A presigned
# query is a bearer credential even when the URL never passes through our API.
def redact_signed_urls(record):
    if isinstance(record.args, tuple):
        record.args = tuple(arg.copy_with(query=None) if isinstance(arg, httpx.URL)
                            and "x-oss-signature" in arg.params else arg for arg in record.args)
    return True


def suppress_signed_queries():
    logging.getLogger("httpx").addFilter(redact_signed_urls)
