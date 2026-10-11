"""Domain contracts; normalization is independent of HTTP and DuckDB."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping


class EventValidationError(ValueError):
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


class EventConflictError(ValueError):
    def __init__(self, message: str, source_lines=()):
        self.source_lines=tuple(source_lines)
        super().__init__(message)


EventEnvelope = Mapping[str, Any]


@dataclass(frozen=True)
class NormalizedEvent:
    event_id: str
    repo_id: int
    repo_name: str
    actor_id: int
    actor_login: str
    is_bot: bool
    event_type: str
    action: str | None
    occurred_at: datetime
    pr_number: int | None
    content_hash: str
    raw_json: str


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime

    def __post_init__(self):
        for name in ('start', 'end'):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise EventValidationError(name, 'Use a timestamp with a timezone.')
            object.__setattr__(self, name, value.astimezone(timezone.utc))
        if self.start >= self.end:
            raise EventValidationError('end', 'End must be after start.')


@dataclass(frozen=True)
class IngestResult:
    inserted: int
    duplicates: int
    revision: int


@dataclass(frozen=True)
class TrendRow:
    repo_id: int
    repo_name: str
    stars: int
    previous_stars: int | None
    momentum: int | None


@dataclass(frozen=True)
class RepositoryReport:
    repo_id: int
    repo_name: str
    activity: dict
    open_prs: dict
    merge_stats: dict
    contributors: list[dict]
    revision: int


def parse_timestamp(value: Any, field: str = 'created_at') -> datetime:
    if not isinstance(value, str):
        raise EventValidationError(field, 'Use an ISO timestamp with a timezone.')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise EventValidationError(field, 'Use an ISO timestamp with a timezone.') from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EventValidationError(field, 'A timezone is required.')
    try:
        return parsed.astimezone(timezone.utc)
    except OverflowError as error:
        raise EventValidationError(field, 'Timestamp is outside the supported UTC range.') from error


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EventValidationError(field, 'Use a nonempty string.')
    return value


def _positive_id(value: Any, field: str) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise EventValidationError(field, 'Use a positive 64-bit integer.')
    return value


def normalize_event(event: EventEnvelope) -> NormalizedEvent:
    if not isinstance(event, dict):
        raise EventValidationError('event', 'Use a JSON object.')
    repo, actor, payload = (event.get(key) for key in ('repo','actor','payload'))
    for name, value in (('repo',repo),('actor',actor),('payload',payload)):
        if not isinstance(value, dict):
            raise EventValidationError(name, 'Use a JSON object.')
    event_id = _text(event.get('id'), 'id')
    kind = _text(event.get('type'), 'type')
    repo_id = _positive_id(repo.get('id'), 'repo.id')
    actor_id = _positive_id(actor.get('id'), 'actor.id')
    repo_name = _text(repo.get('name'), 'repo.name')
    login = _text(actor.get('login'), 'actor.login')
    occurred = parse_timestamp(event.get('created_at'))
    if occurred >= datetime(9999,12,31,tzinfo=timezone.utc):
        raise EventValidationError('created_at','Timestamp must allow a coverage end at the next UTC midnight.')
    action = payload.get('action')
    if action is not None: action = _text(action, 'payload.action')
    number = None
    if kind == 'PullRequestEvent':
        pr = payload.get('pull_request', {})
        if not isinstance(pr, dict):
            raise EventValidationError('payload.pull_request', 'Use a JSON object.')
        number = payload.get('number', pr.get('number'))
        number = _positive_id(number, 'payload.number')
        if number >= 2**31:
            raise EventValidationError('payload.number', 'PR number exceeds the supported range.')
        if 'number' in pr:
            nested = _positive_id(pr['number'],'payload.pull_request.number')
            if nested != number:
                raise EventValidationError('payload.number', 'PR numbers must agree.')
    try:
        raw = json.dumps(event, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise EventValidationError('event', 'Use valid JSON values.') from error
    return NormalizedEvent(event_id,repo_id,repo_name,actor_id,login,login.lower().endswith('[bot]'),
                           kind,action,occurred,number,hashlib.sha256(raw.encode()).hexdigest(),raw)
