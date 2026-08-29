from utils.enums import AiTaskTypeEnum


def test_remake_is_a_standalone_ai_task_type():
    capability = AiTaskTypeEnum.remake_decomposition

    assert capability.value == 6
    assert capability.nickname == "重制"
