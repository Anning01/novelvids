from tortoise import Model, fields


class AbstractBaseModel(Model):
    """抽象基类模型，不会被创建为数据库表"""

    id = fields.IntField(primary_key=True, description="ID")
    created_at = fields.DatetimeField(auto_now_add=True, description="创建时间")
    updated_at = fields.DatetimeField(auto_now=True, description="更新时间")

    class Meta:
        # 关键配置：将该模型标记为抽象模型
        abstract = True
