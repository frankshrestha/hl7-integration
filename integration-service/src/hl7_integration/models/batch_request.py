from pydantic import BaseModel, Field


class BatchRequestItem(BaseModel):
    item_id: int
    message_id: str = Field(min_length=1, max_length=64)


class BatchRequest(BaseModel):
    batch_id: str = Field(min_length=1, max_length=64)
    items: list[BatchRequestItem] = Field(min_length=1)
