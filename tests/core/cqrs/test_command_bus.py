"""
Tests for CommandBus — the core CQRS command routing mechanism.
Verifies registration, execution, duplicate prevention, and missing handler errors.
"""
import pytest
from dataclasses import dataclass

from app.core.cqrs.command import Command
from app.core.cqrs.command_bus import CommandBus


# --- Test commands ---

@dataclass
class DummyCommand(Command):
    value: int


@dataclass
class AnotherCommand(Command):
    name: str


@dataclass
class UnregisteredCommand(Command):
    pass


# --- Tests ---

class TestCommandBusRegistration:

    def test_register_handler(self):
        bus = CommandBus()
        async def handler(cmd): pass
        bus.register(DummyCommand, handler)
        assert bus.is_registered(DummyCommand)

    def test_is_registered_returns_false_for_unknown(self):
        bus = CommandBus()
        assert bus.is_registered(DummyCommand) is False

    def test_duplicate_registration_raises(self):
        bus = CommandBus()
        async def handler(cmd): pass
        bus.register(DummyCommand, handler)
        with pytest.raises(ValueError, match="allerede registreret"):
            bus.register(DummyCommand, handler)

    def test_register_multiple_different_commands(self):
        bus = CommandBus()
        async def handler_a(cmd): pass
        async def handler_b(cmd): pass
        bus.register(DummyCommand, handler_a)
        bus.register(AnotherCommand, handler_b)
        assert bus.is_registered(DummyCommand)
        assert bus.is_registered(AnotherCommand)


class TestCommandBusExecution:

    @pytest.mark.asyncio
    async def test_execute_calls_handler(self):
        bus = CommandBus()
        results = []

        async def handler(cmd: DummyCommand):
            results.append(cmd.value)

        bus.register(DummyCommand, handler)
        await bus.execute(DummyCommand(value=42))
        assert results == [42]

    @pytest.mark.asyncio
    async def test_execute_returns_handler_result(self):
        bus = CommandBus()

        async def handler(cmd: DummyCommand):
            return cmd.value * 2

        bus.register(DummyCommand, handler)
        result = await bus.execute(DummyCommand(value=5))
        assert result == 10

    @pytest.mark.asyncio
    async def test_execute_unregistered_command_raises(self):
        bus = CommandBus()
        with pytest.raises(ValueError, match="No handler registered"):
            await bus.execute(UnregisteredCommand())

    @pytest.mark.asyncio
    async def test_execute_routes_to_correct_handler(self):
        bus = CommandBus()
        calls = {"dummy": 0, "another": 0}

        async def dummy_handler(cmd: DummyCommand):
            calls["dummy"] += 1

        async def another_handler(cmd: AnotherCommand):
            calls["another"] += 1

        bus.register(DummyCommand, dummy_handler)
        bus.register(AnotherCommand, another_handler)

        await bus.execute(DummyCommand(value=1))
        await bus.execute(AnotherCommand(name="test"))

        assert calls == {"dummy": 1, "another": 1}

    @pytest.mark.asyncio
    async def test_execute_propagates_handler_exception(self):
        bus = CommandBus()

        async def failing_handler(cmd: DummyCommand):
            raise RuntimeError("boom")

        bus.register(DummyCommand, failing_handler)
        with pytest.raises(RuntimeError, match="boom"):
            await bus.execute(DummyCommand(value=1))
