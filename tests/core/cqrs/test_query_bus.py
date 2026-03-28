"""
Tests for QueryBus — the core CQRS query routing mechanism.
Verifies registration, execution, duplicate prevention, missing handler errors,
and error logging behavior.
"""
import pytest
from dataclasses import dataclass

from app.core.cqrs.query import Query
from app.core.cqrs.query_bus import QueryBus


# --- Test queries ---

@dataclass
class GetValueQuery(Query):
    key: str


@dataclass
class GetCountQuery(Query):
    pass


@dataclass
class UnregisteredQuery(Query):
    pass


# --- Tests ---

class TestQueryBusRegistration:

    def test_register_handler(self):
        bus = QueryBus()
        async def handler(q): return None
        bus.register(GetValueQuery, handler)
        assert bus.is_registered(GetValueQuery)

    def test_is_registered_returns_false_for_unknown(self):
        bus = QueryBus()
        assert bus.is_registered(GetValueQuery) is False

    def test_duplicate_registration_raises(self):
        bus = QueryBus()
        async def handler(q): return None
        bus.register(GetValueQuery, handler)
        with pytest.raises(ValueError, match="allerede registreret"):
            bus.register(GetValueQuery, handler)

    def test_register_multiple_different_queries(self):
        bus = QueryBus()
        async def handler_a(q): return "a"
        async def handler_b(q): return "b"
        bus.register(GetValueQuery, handler_a)
        bus.register(GetCountQuery, handler_b)
        assert bus.is_registered(GetValueQuery)
        assert bus.is_registered(GetCountQuery)


class TestQueryBusExecution:

    @pytest.mark.asyncio
    async def test_execute_returns_handler_result(self):
        bus = QueryBus()

        async def handler(q: GetValueQuery):
            return f"value-{q.key}"

        bus.register(GetValueQuery, handler)
        result = await bus.execute(GetValueQuery(key="abc"))
        assert result == "value-abc"

    @pytest.mark.asyncio
    async def test_execute_unregistered_query_raises(self):
        bus = QueryBus()
        with pytest.raises(ValueError, match="No handler registered"):
            await bus.execute(UnregisteredQuery())

    @pytest.mark.asyncio
    async def test_execute_routes_to_correct_handler(self):
        bus = QueryBus()

        async def value_handler(q: GetValueQuery):
            return q.key

        async def count_handler(q: GetCountQuery):
            return 42

        bus.register(GetValueQuery, value_handler)
        bus.register(GetCountQuery, count_handler)

        assert await bus.execute(GetValueQuery(key="x")) == "x"
        assert await bus.execute(GetCountQuery()) == 42

    @pytest.mark.asyncio
    async def test_execute_propagates_and_logs_handler_exception(self, caplog):
        bus = QueryBus()

        async def failing_handler(q: GetValueQuery):
            raise RuntimeError("query failed")

        bus.register(GetValueQuery, failing_handler)

        with caplog.at_level("ERROR", logger="app.core.cqrs.query_bus"):
            with pytest.raises(RuntimeError, match="query failed"):
                await bus.execute(GetValueQuery(key="bad"))

        # Verify the error was logged with exc_info
        assert "query failed" in caplog.text

    @pytest.mark.asyncio
    async def test_execute_returns_none_from_handler(self):
        bus = QueryBus()

        async def handler(q: GetValueQuery):
            return None

        bus.register(GetValueQuery, handler)
        result = await bus.execute(GetValueQuery(key="empty"))
        assert result is None
