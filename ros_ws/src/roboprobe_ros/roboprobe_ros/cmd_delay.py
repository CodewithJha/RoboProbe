"""Sim-time command latency relay for Jazzy Nav2 (T-093d, FR-SIM-003)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final

import rclpy
from geometry_msgs.msg import Twist, TwistStamped
from rclpy.clock import JumpThreshold
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException
from rclpy.parameter import Parameter
from std_msgs.msg import Float64

from roboprobe_ros._vendor.perturbation.delay import CommandDelayBuffer
from roboprobe_ros.base import RoboProbeNode

if TYPE_CHECKING:
    from rclpy.clock import TimeJump
    from rclpy.context import Context

__all__ = ["CommandDelay", "main"]

_DELAY_ACTUAL_TOPIC: Final = "/roboprobe/cmd_delay_actual"
_MS_PER_S: Final = 1000
_NS_PER_S: Final = 1_000_000_000

type Command = Twist | TwistStamped


def _number(values: dict[str, object], key: str) -> float:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"perturb_params.yaml must specify numeric {key}"
        raise TypeError(msg)
    if not math.isfinite(value):
        msg = f"{key} must be finite"
        raise ValueError(msg)
    return float(value)


class CommandDelay(RoboProbeNode):
    """Apply the shared FIFO model on the same clock as the simulation."""

    def __init__(
        self,
        *,
        context: Context | None = None,
        parameter_overrides: list[Parameter] | None = None,
    ) -> None:
        """Enable simulation time and configure the episode relay."""
        overrides = [*(parameter_overrides or ()), Parameter("use_sim_time", value=True)]
        super().__init__("cmd_delay", context=context, parameter_overrides=overrides)
        try:
            self._configure()
        except Exception:
            self.destroy_node()
            raise

    def _configure(self) -> None:
        self._delay_s = _number(self.perturbation, "cmd_delay_ms") / _MS_PER_S
        rate_hz = _number(self.perturbation, "rate_hz")
        if rate_hz <= 0.0:
            msg = "rate_hz must be positive"
            raise ValueError(msg)
        self._queue = CommandDelayBuffer[tuple[float, Command]](self._delay_s)
        raw = self.topic("cmd_vel_nav")
        output = self.topic("cmd_vel")
        if self.resolve_topic_name(raw) == self.resolve_topic_name(output):
            msg = "cmd_vel_nav and cmd_vel must resolve to distinct topics"
            raise ValueError(msg)

        message_type = TwistStamped if self.stamped_cmd_vel else Twist
        output_qos = self.qos("cmd_vel")
        self._command = self.create_publisher(message_type, output, output_qos)
        self._latency = self.create_publisher(Float64, _DELAY_ACTUAL_TOPIC, output_qos)
        self.create_subscription(message_type, raw, self._receive, self.qos("cmd_vel_nav"))
        if self._delay_s > 0.0:
            self.create_timer(1.0 / rate_hz, self._release)
            self._jump_handler = self.get_clock().create_jump_callback(
                JumpThreshold(
                    min_forward=None, min_backward=Duration(nanoseconds=-1), on_clock_change=True
                ),
                post_callback=self._reset_queue,
            )

    def _reset_queue(self, _jump: TimeJump) -> None:
        # The shared FIFO disallows clock regressions, so a new timeline gets a new FIFO.
        self._queue = CommandDelayBuffer[tuple[float, Command]](self._delay_s)

    def _receive(self, command: Command) -> None:
        if self._delay_s == 0.0:
            self._send(command, 0.0)
            return
        now = self.get_clock().now().nanoseconds / _NS_PER_S
        # ROS reports zero until the first simulation clock sample arrives.
        if now > 0.0:
            self._queue.push(now, (now, command))

    def _release(self) -> None:
        now = self.get_clock().now().nanoseconds / _NS_PER_S
        for enqueued, command in self._queue.pop_due(now):
            self._send(command, now - enqueued)

    def _send(self, command: Command, actual_s: float) -> None:
        self._command.publish(command)
        self._latency.publish(Float64(data=actual_s))


def main(args: list[str] | None = None) -> None:
    """Start the relay and release its resources on ROS shutdown."""
    rclpy.init(args=args)
    try:
        node = CommandDelay()
        try:
            rclpy.spin(node)
        finally:
            node.destroy_node()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        rclpy.try_shutdown()
