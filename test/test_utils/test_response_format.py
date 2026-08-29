from pydantic import BaseModel, model_validator

from utils.response_format import ResponseSchema


class _NormalizedItem(BaseModel):
    value: str

    @model_validator(mode="after")
    def normalize_value(self):
        self.value = self.value.upper()
        return self


def test_typed_response_validates_nested_list_items():
    response = ResponseSchema[list[_NormalizedItem]](
        data=[{"value": "normalized by the response model"}],
    )

    assert response.data is not None
    assert isinstance(response.data[0], _NormalizedItem)
    assert response.model_dump()["data"] == [
        {"value": "NORMALIZED BY THE RESPONSE MODEL"},
    ]
