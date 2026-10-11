from fastapi.testclient import TestClient
from app.main import create_app


def test_dashboard_and_local_assets(tmp_path):
    with TestClient(create_app(tmp_path/'events.duckdb')) as client:
        page=client.get('/')
        assert page.status_code==200
        assert 'GitHub activity explorer' in page.text
        assert 'datetime-local' in page.text and 'UTC' in page.text
        assert client.get('/static/app.js').status_code==200
        assert client.get('/static/styles.css').status_code==200
        assert client.get('/static/vendor/chart.umd.min.js').status_code==200
