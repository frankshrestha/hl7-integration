from enum import StrEnum


class MessageStatus(StrEnum):
    REJECTED = "rejected"
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    RETRYING = "retrying"
    DELIVERED = "delivered"
    DEAD_LETTERED = "dead_lettered"


class MessageEventType(StrEnum):
    RECEIVED = "received"
    VALIDATION_FAILED = "validation_failed"
    QUEUED = "queued"
    DUPLICATE_RECEIVED = "duplicate_received"
    DELIVERY_ATTEMPTED = "delivery_attempted"
    DELIVERY_SUCCEEDED = "delivery_succeeded"
    DELIVERY_FAILED = "delivery_failed"
    RETRY_SCHEDULED = "retry_scheduled"
    DEAD_LETTERED = "dead_lettered"
    REPLAYED = "replayed"
    BATCH_FETCHED = "batch_fetched"
