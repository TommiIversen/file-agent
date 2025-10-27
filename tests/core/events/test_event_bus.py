"""
Tests for the DomainEventBus.
"""

import asyncio
from unittest.mock import Mock, patch

import pytest

from app.core.events.domain_event import DomainEvent
from app.core.events.event_bus import DomainEventBus


# Define some simple test events
@pytest.fixture
def TestEventA():
    return DomainEvent()


@pytest.fixture
def TestEventB():
    return DomainEvent()


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    """Test that a handler is called when its subscribed event is published."""
    bus = DomainEventBus()
    handler_mock = Mock()

    async def async_handler(event: DomainEvent):
        handler_mock(event)

    await bus.subscribe(DomainEvent, async_handler)

    event_to_publish = DomainEvent()
    await bus.publish(event_to_publish)

    # Assert that the handler was called once with the correct event
    handler_mock.assert_called_once_with(event_to_publish)


@pytest.mark.asyncio
async def test_publish_to_correct_handlers_only():
    """Test that only handlers for the specific event type are called."""
    bus = DomainEventBus()

    # Mocks for two different event types
    handler_a_mock = Mock()
    handler_b_mock = Mock()

    class EventA(DomainEvent):
        pass

    class EventB(DomainEvent):
        pass

    async def handler_a(event: EventA):
        handler_a_mock(event)

    async def handler_b(event: EventB):
        handler_b_mock(event)

    await bus.subscribe(EventA, handler_a)
    await bus.subscribe(EventB, handler_b)

    event_a_instance = EventA()
    await bus.publish(event_a_instance)

    # Assert that only handler_a was called
    handler_a_mock.assert_called_once_with(event_a_instance)
    handler_b_mock.assert_not_called()


@pytest.mark.asyncio
async def test_multiple_handlers_for_one_event():
    """Test that all subscribed handlers for an event are called."""
    bus = DomainEventBus()
    handler1_mock = Mock()
    handler2_mock = Mock()

    async def async_handler1(event: DomainEvent):
        handler1_mock(event)

    async def async_handler2(event: DomainEvent):
        handler2_mock(event)

    await bus.subscribe(DomainEvent, async_handler1)
    await bus.subscribe(DomainEvent, async_handler2)

    event_to_publish = DomainEvent()
    await bus.publish(event_to_publish)

    handler1_mock.assert_called_once_with(event_to_publish)
    handler2_mock.assert_called_once_with(event_to_publish)


@pytest.mark.asyncio
async def test_publish_with_no_subscribers():
    """Test that publishing an event with no subscribers does not raise an error."""
    bus = DomainEventBus()
    event_to_publish = DomainEvent()

    try:
        await bus.publish(event_to_publish)
    except Exception as e:
        pytest.fail(f"Publishing with no subscribers raised an exception: {e}")


@pytest.mark.asyncio
async def test_failing_handler_does_not_stop_others(caplog):
    """Test that if one handler fails, other handlers are still executed."""
    bus = DomainEventBus()

    handler_success_mock = Mock()
    handler_fail_mock = Mock()

    async def success_handler(event: DomainEvent):
        handler_success_mock(event)
        await asyncio.sleep(0.01)  # ensure it runs as a task

    async def failing_handler(event: DomainEvent):
        handler_fail_mock(event)
        raise ValueError("Handler failed intentionally")

    await bus.subscribe(DomainEvent, failing_handler)
    await bus.subscribe(DomainEvent, success_handler)

    event_to_publish = DomainEvent()

    with patch("logging.error") as mock_log_error:
        await bus.publish(event_to_publish)

        # Assert that both handlers were called
        handler_fail_mock.assert_called_once_with(event_to_publish)
        handler_success_mock.assert_called_once_with(event_to_publish)

        # Assert that the error was logged
        mock_log_error.assert_called_once()
        log_args, _ = mock_log_error.call_args
        assert "Unhandled exception in handler 'failing_handler'" in log_args[0]
        assert "Handler failed intentionally" in log_args[0]
