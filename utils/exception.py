from fastapi import HTTPException
from tortoise.exceptions import DoesNotExist
from tortoise.models import Model
from tortoise.queryset import QuerySet


async def get_object_or_404(model: QuerySet | Model, **kwargs):
    """Helper to get an object or raise HTTPException 404."""
    try:
        return await model.get(**kwargs)
    except DoesNotExist:
        model_name = model.__name__
        # A simple way to build a detail message.
        # You might want a more robust way to pluralize/name models.
        raise HTTPException(status_code=404, detail=f"{model_name} not found")
