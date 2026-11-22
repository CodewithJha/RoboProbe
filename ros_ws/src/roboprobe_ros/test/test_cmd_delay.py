"""Exercise command delivery against a deterministic fake Jazzy clock (T-093d)."""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import TYPE_CHECKING
from unittest import TestCase

import launch
import launch_testing
import pytest
import rclpy
import yaml
from geometry_msgs.msg import Twist, TwistStamped
from launch_ros.actions import Node as LaunchNode
from launch_testing.actions import ReadyToTest
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, qos_profile_sensor_data
from rosgraph_msgs.msg import Clock
from std_msgs.msg import Float64

if TYPE_CHECKING:
    from collections.abc import Callable

_DELAY_MS = 65.0
_RATE_HZ = 20.0
_CLOCK_STEP_MS = 10
_CONTROL_QUEUE_DEPTH = 10
_CLOCK_SETTLE_S = 0.050
_NANOSECONDS_PER_MILLISECOND = 1_000_000
_ZERO = "zero"
_PLAIN = "plain"
_STAMPED = "stamped"
_CASES = {_PLAIN: Twist, _STAMPED: TwistStamped, _ZERO: Twist}


def _topic(case: str, kind: str) -> str:
    return f"/cmd_delay_test/{case}/{kind}"


@pytest.mark.launch_test
def generate_test_description() -> tuple[launch.LaunchDescription, dict[str, object]]:
    """Start installed command relays for both ROS message types and zero delay."""
    files = TemporaryDirectory(prefix="roboprobe-cmd-delay-")
    root = Path(files.name)
    nodes = []
    for case, message in _CASES.items():
        topics = root / f"{case}_topics.yaml"
        perturb = root / f"{case}_perturb.yaml"
        topics.write_text(
            yaml.safe_dump(
                {
                    "stamped_cmd_vel": message is TwistStamped,
                    "topics": {
                        "cmd_vel_nav": {"name": _topic(case, "in"), "qos": "default"},
                        "cmd_vel": {"name": _topic(case, "out"), "qos": "default"},
                    },
                }
            ),
            encoding="utf-8",
        )
        perturb.write_text(
            yaml.safe_dump(
                {"cmd_delay_ms": 0.0 if case == _ZERO else _DELAY_MS, "rate_hz": _RATE_HZ}
            ),
            encoding="utf-8",
        )
        nodes.append(
            LaunchNode(
                package="roboprobe_ros",
                executable="cmd_delay",
                name=f"test_cmd_delay_{case}",
                parameters=[{"topics_file": str(topics), "perturb_file": str(perturb)}],
                remappings=[
                    ("/clock", _topic(case, "clock")),
                    ("/roboprobe/cmd_delay_actual", _topic(case, "delay")),
                ],
            )
        )
    return launch.LaunchDescription([*nodes, ReadyToTest()]), {"test_files": files}


def _spin_until(executor: SingleThreadedExecutor, ready: Callable[[], bool]) -> None:
    deadline = monotonic() + 10.0
    while not ready():
        assert monotonic() < deadline, "Timed out waiting for command relay DDS"
        executor.spin_once(timeout_sec=0.05)


def _advance(executor: SingleThreadedExecutor, duration: float) -> None:
    deadline = monotonic() + duration
    while monotonic() < deadline:
        executor.spin_once(timeout_sec=max(0.0, deadline - monotonic()))


def _command(msg_type: type[Twist] | type[TwistStamped], speed: float) -> Twist | TwistStamped:
    if msg_type is TwistStamped:
        stamped = TwistStamped()
        stamped.header.frame_id = "base_link"
        stamped.header.stamp.sec = 3
        stamped.twist.linear.x = speed
        return stamped
    plain = Twist()
    plain.linear.x = speed
    return plain


class TestCommandDelay(TestCase):
    """Test FIFO delivery, message preservation, and latency in simulation time."""

    def test_twist(self) -> None:
        """Release two unstamped commands in FIFO order."""
        self._check(_PLAIN)

    def test_twist_stamped(self) -> None:
        """Preserve the TwistStamped header and release in FIFO order."""
        self._check(_STAMPED)

    def test_zero_delay(self) -> None:
        """Forward commands immediately while the simulation clock is frozen."""
        self._check(_ZERO)

    def _check(self, case: str) -> None:
        context = Context()
        rclpy.init(context=context)
        node = Node(f"probe_{case}", context=context)
        executor = SingleThreadedExecutor(context=context)
        executor.add_node(node)
        msg_type = _CASES[case]
        clock = node.create_publisher(Clock, _topic(case, "clock"), qos_profile_sensor_data)
        control_qos = QoSProfile(depth=_CONTROL_QUEUE_DEPTH)
        source = node.create_publisher(msg_type, _topic(case, "in"), control_qos)
        messages: list[Twist | TwistStamped] = []
        latencies: list[float] = []
        output = node.create_subscription(
            msg_type, _topic(case, "out"), messages.append, control_qos
        )
        delay = node.create_subscription(
            Float64,
            _topic(case, "delay"),
            lambda value: latencies.append(value.data),
            control_qos,
        )

        def clock_to(elapsed_ms: int) -> None:
            stamp = Clock()
            stamp.clock.sec = 10
            stamp.clock.nanosec = elapsed_ms * _NANOSECONDS_PER_MILLISECOND
            clock.publish(stamp)
            _advance(executor, _CLOCK_SETTLE_S)

        try:
            _spin_until(
                executor,
                lambda: all(
                    (
                        clock.get_subscription_count(),
                        source.get_subscription_count(),
                        output.get_publisher_count(),
                        delay.get_publisher_count(),
                    )
                ),
            )
            for _ in range(3):
                clock_to(0)
            expected = [_command(msg_type, 0.10), _command(msg_type, 0.20)]
            for command in expected:
                source.publish(command)
                _advance(executor, _CLOCK_SETTLE_S)
            if case == _ZERO:
                _spin_until(executor, lambda: bool(messages and latencies))
            else:
                _advance(executor, 0.150)
                assert not messages
                for instant in range(_CLOCK_STEP_MS, int(_DELAY_MS), _CLOCK_STEP_MS):
                    clock_to(instant)
                    assert not messages
                for instant in range(70, 121, _CLOCK_STEP_MS):
                    clock_to(instant)
            _spin_until(executor, lambda: len(messages) == len(latencies) == len(expected))
            assert messages == expected
            if case == _ZERO:
                assert latencies == [0.0] * len(expected)
            else:
                expected_sec = _DELAY_MS / 1000.0
                assert all(
                    expected_sec - 1e-9 <= actual <= expected_sec + 1.0 / _RATE_HZ
                    for actual in latencies
                )
        finally:
            executor.shutdown()
            node.destroy_node()
            rclpy.shutdown(context=context)


@launch_testing.post_shutdown_test()
class TestCommandDelayShutdown(TestCase):
    """The installed relays handle launch teardown cleanly."""

    def test_exit_codes(self, proc_info: object) -> None:
        """Require every command relay to exit normally."""
        launch_testing.asserts.assertExitCodes(proc_info)
