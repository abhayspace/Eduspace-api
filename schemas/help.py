"""Help chat schemas — in-app messaging between users and the developer."""
from typing import List, Optional

from pydantic import BaseModel, Field


class HelpSendIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class HelpMessageOut(BaseModel):
    id: str
    user_id: str = Field(alias="userId")
    sender: str  # 'user' | 'developer'
    sender_label: str = Field(alias="senderLabel")
    message: str
    created_at: str = Field(alias="createdAt")

    model_config = {"populate_by_name": True}


class HelpConversationOut(BaseModel):
    """A user's conversation summary, used in the developer inbox."""
    user_id: str = Field(alias="userId")
    sender_label: str = Field(alias="senderLabel")
    last_message: str = Field(alias="lastMessage")
    last_at: str = Field(alias="lastAt")
    unread: int = 0
    messages: List[HelpMessageOut] = []

    model_config = {"populate_by_name": True}


class HelpReplyIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
