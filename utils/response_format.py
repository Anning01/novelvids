import datetime
import random
import string
from typing import TypeVar, Generic, Optional, Union, List

from pydantic import BaseModel, ConfigDict

from config import settings

DataT = TypeVar("DataT")


class ResponseSchema(BaseModel, Generic[DataT]):
    """统一API响应格式

    属性:
        code (int): 响应状态码，0表示成功，非0表示异常
        data (T): 响应数据，泛型类型
        message (str): 响应消息
    """
    model_config = ConfigDict(json_schema_extra={"example": {"code": 0, "data": {}, "message": "操作成功"}})

    code: int = 0
    data: Optional[Union[DataT, list, dict]] = None  # 明确支持list和dict
    message: str = "操作成功"


# 统一响应格式
class Pagination(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int


class PaginationResponse(BaseModel, Generic[DataT]):
    items: Optional[List[DataT]] = None
    pagination: Optional[Pagination] = None


def generate_random_filename(extension=".png"):
    # 生成当前时间的时间戳
    timestamp = datetime.datetime.now(settings.tz).strftime("%Y%m%d_%H%M%S")

    # 生成随机字符串
    random_str = "".join(random.choices(string.ascii_letters + string.digits, k=8))

    # 组合文件名
    filename = f"{timestamp}_{random_str}{extension}"
    return filename
