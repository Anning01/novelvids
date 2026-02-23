from typing import (
    Any,
    Dict,
    Generic,
    NewType,
    Type,
    TypeVar,
    Union,
    Optional,
)

from pydantic import BaseModel
from tortoise.models import Model
from tortoise.queryset import QuerySet

from utils.page import QueryParams, QueryBuilder
from utils.exception import get_object_or_404

T = TypeVar("T")
Total = NewType("Total", int)
ModelType = TypeVar("ModelType", bound=Model)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: Type[ModelType]):
        self.model = model

    async def get(
        self, id: int, base_query: Optional[QuerySet] = None, **kwargs
    ) -> ModelType:
        query_source = base_query if base_query is not None else self.model
        return await get_object_or_404(query_source, id=id, **kwargs)

    async def list(
        self,
        params: QueryParams,
        response_model: Type[BaseModel],
        search_fields: Optional[list[str]] = None,
        base_query: Optional[QuerySet] = None,
    ) -> dict[str, dict[str, int | Any] | Any]:
        if base_query is None:
            query = self.model.all()
        else:
            query = base_query
        #  应用过滤
        query = await QueryBuilder.apply_filters(
            query, self.model, params.filters or {}
        )

        # 应用搜索
        query = await QueryBuilder.apply_search(
            query, params.search, search_fields or []
        )

        # 计算总数
        total = await query.count()

        # 应用排序
        query = await QueryBuilder.apply_sorting(query, params.sort)

        # 应用分页
        paginated_query = await QueryBuilder.apply_pagination(
            query, params.page, params.page_size
        )

        # 执行查询
        items = await paginated_query

        # 计算分页信息
        pages = (total + params.page_size - 1) // params.page_size if total > 0 else 0

        items_pydantic = [response_model.model_validate(item) for item in items]

        results = {
            "items": items_pydantic,
            "pagination": {
                "total": total,
                "page": params.page,
                "page_size": params.page_size,
                "pages": pages,
            },
        }

        return results

    async def create(self, obj_in: CreateSchemaType, **kwargs) -> ModelType:
        if isinstance(obj_in, Dict):
            obj_dict = obj_in
        else:
            obj_dict = obj_in.model_dump(exclude_unset=True)
        obj = self.model(**obj_dict, **kwargs)
        await obj.save()
        return obj

    async def update(
        self, instance: ModelType, obj_in: Union[UpdateSchemaType, Dict[str, Any]]
    ) -> ModelType:
        if isinstance(obj_in, Dict):
            obj_dict = obj_in
        else:
            obj_dict = obj_in.model_dump(exclude_unset=True, exclude={"id"})
        obj = instance.update_from_dict(obj_dict)
        await obj.save()
        return obj

    async def patch(
            self, instance: ModelType, obj_in: Union[UpdateSchemaType, Dict[str, Any]]
    ) -> ModelType:
        # 1. 统一转换为字典
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            # exclude_unset=True 确保没传的字段不会出现在字典里
            update_data = obj_in.model_dump(exclude_unset=True, exclude={"id"})

        # 2. 这里的 update_from_dict 会根据字典内容只覆盖 instance 上的对应属性
        instance.update_from_dict(update_data)

        # 3. 获取待更新的字段列表，传给 save() 提高性能并防止竞态条件
        update_fields = list(update_data.keys())
        await instance.save(update_fields=update_fields)

        return instance


    async def remove(self, obj: ModelType) -> None:
        await obj.delete()
