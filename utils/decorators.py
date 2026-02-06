from functools import wraps
from typing import Callable, Any
from tortoise.transactions import in_transaction

def atomic(connection_name: str = "default"):
    """
    通用事务装饰器。
    将异步函数包裹在 Tortoise ORM 事务中执行。
    如果函数执行过程中抛出异常，事务将自动回滚。

    参数:
        connection_name: 数据库连接名称，默认为 "default"

    使用示例:
        @atomic()
        async def create_user_with_profile(self, user_data, profile_data):
            user = await User.create(**user_data)
            await Profile.create(user=user, **profile_data)
            return user
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            async with in_transaction(connection_name):
                return await func(*args, **kwargs)
        return wrapper
    return decorator
