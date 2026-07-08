from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class SourceObject(BaseModel):
    source_system: str
    source_type: str
    external_id: str
    title: str
    url: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    owner: Optional[str] = None
    owner_team: Optional[str] = None
    account_name: Optional[str] = None
    project_key: Optional[str] = None
    component: Optional[str] = None
    environment: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    source_authority: float = 0.70
    acl: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    body: str

class IngestObjectsRequest(BaseModel):
    source_name: str = "api-ingest"
    source_system: str = "synthetic"
    objects: List[SourceObject]

class SearchRequest(BaseModel):
    query: str
    source_systems: Optional[List[str]] = None
    source_types: Optional[List[str]] = None
    statuses: Optional[List[str]] = None
    priorities: Optional[List[str]] = None
    project_key: Optional[str] = None
    account_name: Optional[str] = None
    component: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    limit: int = Field(10, ge=1, le=50)

class AgentAnswerRequest(BaseModel):
    question: str
    limit: int = Field(8, ge=1, le=20)

class SourceCreateRequest(BaseModel):
    source_system: str
    source_name: str
    auth_mode: str = "synthetic"
    config: Dict[str, Any] = Field(default_factory=dict)
