from app import repository


class _Result:
    def first(self):
        return (1,)


class _Connection:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _Result()


class _Transaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_):
        return False


class _Engine:
    def __init__(self):
        self.connection = _Connection()

    def begin(self):
        return _Transaction(self.connection)


def test_follow_up_uses_only_random_conversation_id(monkeypatch):
    fake_engine = _Engine()
    monkeypatch.setattr(repository, "engine", fake_engine)

    conversation_id = "8974866e-fc1d-4e8d-957d-2750f05f18d6"
    assert repository.save_conversation("bia", conversation_id) == conversation_id

    ownership_sql, ownership_params = fake_engine.connection.calls[0]
    assert "WHERE id=:id" in ownership_sql
    assert ownership_params == {"id": conversation_id}
