from utils.crud import CRUDBase
from models.scene import Scene
from schemas.scene import SceneCreate, SceneUpdate


class SceneController(CRUDBase[Scene, SceneCreate, SceneUpdate]):
    def __init__(self):
        super().__init__(model=Scene)

    async def update(self, ncene_id: int, obj_in: SceneUpdate) -> Scene:
        instance = await self.get(ncene_id)
        return await super().update(instance, obj_in)

    async def patch(self, ncene_id: int, obj_in: SceneUpdate) -> Scene:
        instance = await self.get(ncene_id)
        return await super().patch(instance, obj_in)

    async def remove(self, ncene_id: int) -> None:
        instance = await self.get(ncene_id)
        await super().remove(instance)


scene_controller = SceneController()
