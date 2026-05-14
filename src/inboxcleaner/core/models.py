from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Sender(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int | None = None
    email: str
    display_name: str | None
    domain: str
    group_id: int | None = None


class SenderGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int | None = None
    name: str
    created_by: Literal["auto", "manual"]
    notes: str | None = None


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    account_id: int
    thread_id: str
    sender_id: int
    subject: str | None
    internal_date: int  # ms since epoch
    size_estimate: int | None
    category: str | None
    labels: list[str]
    list_unsubscribe: str | None
    is_trashed: bool = False


class Account(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int | None = None
    email: str
    history_id: str | None = None
    last_sync_at: datetime | None = None


ActionType = Literal["trash", "archive", "label", "unsubscribe", "merge", "split"]
TargetKind = Literal["sender", "group"]


class ActionLogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int | None = None
    performed_at: datetime | None = None
    action_type: ActionType
    target_kind: TargetKind
    target_id: int
    message_count: int
    details: dict | None = None
