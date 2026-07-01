from enum import StrEnum


class BroadcastCampaignStatus(StrEnum):
    draft = "draft"
    queued = "queued"
    running = "running"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"


class BroadcastAudienceType(StrEnum):
    all_users = "all_users"


class BroadcastMessageStatus(StrEnum):
    pending = "pending"
    sending = "sending"
    sent = "sent"
    retry = "retry"
    failed = "failed"


class BroadcastFailureKind(StrEnum):
    permanent = "permanent"
    retry = "retry"
