import pytest


@pytest.fixture
def event():
    return {'id': '100', 'type': 'WatchEvent', 'created_at': '2026-08-01T12:00:00Z',
            'repo': {'id': 10, 'name': 'owner/project'},
            'actor': {'id': 20, 'login': 'alice'}, 'payload': {'action': 'started'}}
