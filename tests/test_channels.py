# channels/base.py
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BaseChannel:
    def __init__(self, channel_id: str):
        self.channel_id = channel_id

    def disconnect(self) -> Optional[bool]:
        """
        Disconnect a channel.

        Args:
        channel_id (str): The ID of the channel to disconnect.

        Returns:
        Optional[bool]: True if the channel was successfully disconnected, False otherwise.
        """
        try:
            # Implement actual disconnection logic
            # For example, close a socket or a database connection
            # For this example, we'll just log a message and return True
            logger.info(f"Disconnecting channel {self.channel_id}")
            # TO DO: implement actual disconnection logic
            return True
        except Exception as e:
            logger.error(f"Error disconnecting channel {self.channel_id}: {str(e)}")
            return False


# tests/test_channels.py
import logging

import pytest

from channels.base import BaseChannel

logger = logging.getLogger(__name__)


def test_disconnect_success():
    """
    Test that disconnecting a channel returns True.
    """
    channel_id = "test_channel"
    channel = BaseChannel(channel_id)
    result = channel.disconnect()
    assert result is True


def test_disconnect_failure():
    """
    Test that disconnecting a channel with an error returns False.
    """
    channel_id = "test_channel"
    channel = BaseChannel(channel_id)

    # Simulate an error by raising an exception
    def patched_disconnect(self) -> Optional[bool]:
        raise Exception("Simulated error")

    channel.disconnect = patched_disconnect.__get__(channel, type(channel))
    result = channel.disconnect()
    assert result is False


def test_disconnect_thread_safety():
    """
    Test that disconnecting a channel is thread-safe.
    """
    import threading

    channel_id = "test_channel"
    channel = BaseChannel(channel_id)
    results = []

    def disconnect_channel() -> None:
        result = channel.disconnect()
        results.append(result)

    threads = []
    for _ in range(10):
        thread = threading.Thread(target=disconnect_channel)
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    assert all(result is True for result in results)
