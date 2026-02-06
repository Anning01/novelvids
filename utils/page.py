import ast
from datetime import datetime
from typing import Optional, TypeVar, Dict, Any

from fastapi import Request, Query
from pydantic import BaseModel, field_validator
from tortoise import fields
from tortoise.expressions import Q

# 定义泛型类型
ModelType = TypeVar("ModelType")


# 查询参数类
class QueryParams(BaseModel):
    page: Optional[int] = Query(
        default=1, ge=1, description="页码：默认为1，必须为≥1的整数。示例：?page=2"
    )
    page_size: Optional[int] = Query(
        default=10,
        ge=1,
        le=100,
        description="每页条数：默认为10，范围1-100。示例：?page_size=20",
    )
    sort: Optional[str] = Query(
        default=None,
        description="""
        排序规则：格式为「字段名+符号」（无符号=升序，-=降序），多字段用逗号分隔。
        示例：?sort=create_time,-id → 按create_time升序、id降序排列
        """,
    )
    search: Optional[str] = (
        Query(
            default=None,
            description="""
        1. 搜索：直接传关键词（会对预设的可搜索字段进行模糊匹配）
           示例：?search=张三 → 搜索所有含"张三"的记录
           
        2. 过滤：按「字段__操作符=值」格式传参，支持多条件（用&连接）
           常用操作符：
           - __contains: 包含（字符串模糊匹配）
           - __lte: 小于等于（数字/日期）
           - __gte: 大于等于（数字/日期）
           - __gt: 大于（数字/日期）
           - __lt: 小于（数字/日期）
           
           示例：
           ?search=张三&age__gte=18 → 姓名含"张三"且年龄≥18
           ?create_time__gte=2023-01-01 → 创建时间在2023-01-01之后
        """,
        ),
    )

    filters: dict[str, Any] = {}

    @classmethod
    @field_validator("filters", mode="before")
    def extract_filters(cls, v, info):
        # 获取所有输入数据
        data = info.data

        # 排除已知字段
        known_fields = {"page", "page_size", "sort", "search"}

        # 提取过滤参数
        return {k: v for k, v in data.items() if k not in known_fields}


def get_list_params(
    request: Request,
    page: Optional[int] = Query(
        default=1, ge=1, description="页码：默认为1，必须为≥1的整数。示例：?page=2"
    ),
    page_size: Optional[int] = Query(
        default=10,
        ge=1,
        le=100,
        description="每页数量：默认为10，范围1-100。示例：?page_size=20",
    ),
    sort: Optional[str] = Query(
        default=None,
        description="""
        排序规则：格式为「字段名+符号」（无符号=升序，-=降序），多字段用逗号分隔。
        示例：?sort=create_time,-id → 按create_time升序、id降序排列
        """,
    ),
    search: Optional[str] = Query(
        default=None,
        description="""
        1. 搜索：直接传关键词（会对预设的可搜索字段进行模糊匹配）
           示例：?search=张三 → 搜索所有含"张三"的记录
           
        2. 过滤：按「字段__操作符=值」格式传参，支持多条件（用&连接）
           常用操作符：
           - __contains: 包含（字符串模糊匹配）
           - __lte: 小于等于（数字/日期）
           - __gte: 大于等于（数字/日期）
           - __gt: 大于（数字/日期）
           - __lt: 小于（数字/日期）
           
           示例：
           ?search=张三&age__gte=18 → 姓名含"张三"且年龄≥18
           ?create_time__gte=2023-01-01 → 创建时间在2023-01-01之后
        """,
    ),
) -> QueryParams:
    # 提取所有查询参数
    params = dict(request.query_params)
    # 过滤出已知参数
    known_params = {
        "page": page,
        "page_size": page_size,
        "sort": sort,
        "search": search,
    }

    # 过滤参数
    filter_params = {k: v for k, v in params.items() if k not in known_params}

    return QueryParams(
        page=page,
        page_size=page_size,
        sort=sort,
        search=search,
        filters=filter_params,
    )


def validate_field_path(model: ModelType, field_path: str) -> bool:
    """验证字段路径有效性（支持关联字段）"""
    parts = field_path.split("__")
    current_model = model

    for part in parts:
        if part not in current_model._meta.fields_map:
            return False

        field_obj = current_model._meta.fields_map[part]
        if hasattr(field_obj, "related_model"):
            current_model = field_obj.related_model

    return True


# 查询构建器
class QueryBuilder:

    @staticmethod
    async def apply_pagination(query, page: int, page_size: int):
        offset = (page - 1) * page_size
        return query.offset(offset).limit(page_size)

    @staticmethod
    async def apply_sorting(query, sort: Optional[str]):
        if not sort:
            return query

        sort_fields = sort.split(",")
        for field in sort_fields:
            field = field.strip()
            direction = "-" if field.startswith("-") else ""
            column_name = field[1:] if direction else field

            # 验证字段路径有效性
            if not validate_field_path(query.model, column_name):
                continue
            query = query.order_by(f"{direction}{column_name}")
        return query

    @staticmethod
    async def apply_search(query, search: Optional[str], search_fields: list[str]):
        if not search or not search_fields:
            return query
        # 构建OR条件
        conditions = []
        for field in search_fields:
            # 支持json字段搜索
            if "." in field:
                json_field, json_key = field.split(".", 1)  # 拆分字段名和 JSON 键
                conditions.append(Q(**{f"{json_field}__contains": {json_key: search}}))
                continue
            conditions.append(Q(**{f"{field}__icontains": search}))

        # 应用OR条件
        if conditions:
            query = query.filter(Q(*conditions, join_type="OR"))
        return query

    @staticmethod
    async def apply_filters(query, model: ModelType, filters: Dict[str, Any]):
        if not filters:
            return query

        # 支持的操作符映射
        OPERATOR_MAPPING = {
            "gte": "__gte",  # 大于等于
            "lte": "__lte",  # 小于等于
            "gt": "__gt",  # 大于
            "lt": "__lt",  # 小于
        }

        for field_expr, value in filters.items():
            # 解析字段名和操作符（如 "created_at__gte" → ["created_at", "gte"]）
            parts = field_expr.split("__")
            field_name = parts[0]
            operator = parts[1] if len(parts) > 1 else "eq"  # 默认等于操作

            # 跳过无效字段
            if field_name not in model._meta.fields_map:
                continue

            # 获取字段对象
            field_obj = model._meta.fields_map[field_name]

            # 转换值类型
            try:
                processed_value = QueryBuilder._convert_value(field_obj, value)
            except (ValueError, TypeError):
                continue  # 类型转换失败，跳过此条件

            # 构建过滤条件
            if operator == "eq":
                query = query.filter(**{field_name: processed_value})
            elif operator in OPERATOR_MAPPING:
                # 使用 Tortoise ORM 的操作符语法（如 field__gte=value）
                query = query.filter(
                    **{f"{field_name}{OPERATOR_MAPPING[operator]}": processed_value}
                )

        return query

    @staticmethod
    def _convert_value(field_obj, value):
        """根据字段类型转换值"""
        # 处理字符串类型
        if isinstance(field_obj, fields.CharField) or isinstance(
            field_obj, fields.TextField
        ):
            return str(value)

        # 处理整数类型
        elif isinstance(field_obj, fields.IntField) or isinstance(
            field_obj, fields.SmallIntField
        ):
            return int(value)

        # 处理布尔类型
        elif isinstance(field_obj, fields.BooleanField):
            if isinstance(value, str):
                return value.lower() in ["true", "1", "yes"]
            return bool(value)

        # 处理日期时间类型
        elif isinstance(field_obj, fields.DatetimeField):
            if isinstance(value, str):
                # 支持 ISO 格式日期时间
                dt = datetime.fromisoformat(value)
                # 如果是 naive datetime，添加系统时区
                if dt.tzinfo is None:
                    from config import settings

                    dt = dt.replace(tzinfo=settings.tz)
                return dt
            return value

        # 处理 JSON 类型
        elif isinstance(field_obj, fields.JSONField):
            if isinstance(value, str):
                return ast.literal_eval(value)
            return value

        # 默认作为字符串处理
        return str(value)
