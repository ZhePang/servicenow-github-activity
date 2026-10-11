import copy
from datetime import datetime, timezone

import pytest

from app.domain import EventValidationError, TimeRange, normalize_event, parse_timestamp


def test_normalization_utc_and_preserved_payload(event):
    event['created_at'] = '2026-08-01T14:00:00+02:00'
    result = normalize_event(event)
    assert result.occurred_at == datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    assert result.occurred_at.utcoffset().total_seconds() == 0
    assert result.event_id == '100' and result.pr_number is None
    assert 'owner/project' in result.raw_json


def test_canonical_hash_ignores_key_order_but_detects_changes(event):
    assert normalize_event(event).content_hash == normalize_event(dict(reversed(list(event.items())))).content_hash
    altered = copy.deepcopy(event); altered['payload']['extra'] = 1
    assert normalize_event(event).content_hash != normalize_event(altered).content_hash


@pytest.mark.parametrize('field,value', [('id',''), ('repo',{}), ('actor',{}),
    ('payload',None), ('created_at','2026-08-01T12:00:00'), ('created_at','invalid')])
def test_invalid_envelopes(event, field, value):
    event[field] = value
    with pytest.raises(EventValidationError): normalize_event(event)


def test_numeric_identifiers_are_strict_and_positive(event):
    for value in (True, 0, -1, '10'):
        event['repo']['id'] = value
        with pytest.raises(EventValidationError): normalize_event(event)


def test_unknown_types_and_bot_heuristic(event):
    event['type'] = 'FutureEvent'; event['actor']['login'] = 'automation[bot]'
    value = normalize_event(event)
    assert value.event_type == 'FutureEvent' and value.is_bot


def test_pr_number_required_and_consistent(event):
    event['type'] = 'PullRequestEvent'
    with pytest.raises(EventValidationError): normalize_event(event)
    event['payload'] = {'action':'opened','pull_request':{'number':12}}
    assert normalize_event(event).pr_number == 12
    event['payload']['number'] = 13
    with pytest.raises(EventValidationError): normalize_event(event)


def test_range_normalizes_and_rejects_empty_or_naive():
    start = parse_timestamp('2026-08-01T12:00:00+02:00')
    end = parse_timestamp('2026-08-01T11:00:00Z')
    assert TimeRange(start,end).start.hour == 10
    with pytest.raises(EventValidationError): TimeRange(end,start)
    with pytest.raises(EventValidationError): TimeRange(end,end)
    with pytest.raises(EventValidationError): TimeRange(datetime(2026,8,1),end)


@pytest.mark.parametrize('value',[False,0,[], '',None])
def test_supplied_pr_object_must_be_an_object(event,value):
    event['type']='PullRequestEvent';event['payload']={'number':1,'pull_request':value}
    with pytest.raises(EventValidationError):normalize_event(event)


def test_nested_pr_number_cannot_be_boolean(event):
    event['type']='PullRequestEvent';event['payload']={'number':1,'pull_request':{'number':True}}
    with pytest.raises(EventValidationError):normalize_event(event)


def test_timestamp_edges_return_validation_errors(event):
    event['created_at']='9999-12-31T12:00:00Z'
    with pytest.raises(EventValidationError):normalize_event(event)
    with pytest.raises(EventValidationError):parse_timestamp('0001-01-01T00:00:00+01:00')
