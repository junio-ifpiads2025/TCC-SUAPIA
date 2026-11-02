import pytest

from services.shared import audit_service


@pytest.fixture(autouse=True)
def audit_rows(monkeypatch):
    """Auditoria nunca toca o Postgres nos testes; as linhas gravadas ficam nesta lista."""
    rows = []

    async def insert(row):
        rows.append(row)

    monkeypatch.setattr(audit_service, "_db_insert", insert)
    return rows
