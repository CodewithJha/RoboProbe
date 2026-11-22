"""Record Trace v1 and MCAP against ROS Jazzy simulation time (T-094b)."""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, NamedTuple

import pyarrow.parquet as pq
import pytest
import rclpy
import yaml
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, Twist
from nav2_msgs.msg import BehaviorTreeLog, BehaviorTreeStatusChange
from nav_msgs.msg import Odometry
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from roboprobe_ros._vendor.trace_enums import NavStatus
from roboprobe_ros._vendor.trace_io import TRACE_SCHEMA, read_trace, validate_trace
from roboprobe_ros.episode_recorder import EpisodeRecorder
from rosgraph_msgs.msg import Clock
from std_msgs.msg import Float64, String
from std_srvs.srv import SetBool, Trigger

if TYPE_CHECKING:
    from collections.abc import Callable

_RATE_HZ = 20
_DURATION_S = 10
_EXPECTED_ROWS = _RATE_HZ * _DURATION_S
_NS_PER_S = 1_000_000_000
_WAIT_S = 12.0
_QUEUE_DEPTH = 10
_MCAP_MAGIC = b"\x89MCAP0\r\n"
_TRACE_AND_BAG_SUBSCRIBERS = 2
_SHARED_TRACES = Path(__file__).resolve().parents[4] / "backend/tests/fixtures/traces"


class _Sample(NamedTuple):
    clearance_m: float = 1.2
    roll_rad: float = 0.1
    pitch_rad: float = 0.2
    yaw_rad: float = 0.3


class _Monitor:
    def evaluate(
        self, position: tuple[float, float], quaternion: tuple[float, float, float, float]
    ) -> _Sample:
        assert position == (2.0, 3.0)
        assert quaternion == (0.0, 0.0, 0.0, 1.0)
        return _Sample()


def _wait(executor: SingleThreadedExecutor, ready: Callable[[], bool]) -> None:
    deadline = monotonic() + _WAIT_S
    while not ready():
        assert monotonic() < deadline, "Timed out waiting for recorder DDS traffic"
        executor.spin_once(timeout_sec=0.01)


def test_vendored_reader_accepts_the_backend_golden_fixture() -> None:
    """Share the same Parquet vector with the backend oracle tests."""
    trace = read_trace(_SHARED_TRACES / "straight_pass.parquet")
    assert validate_trace(trace, min_hz=10.0, max_gap_s=0.2) == ()
    assert trace.nav_status[-1] == NavStatus.SUCCEEDED


@pytest.mark.parametrize(
    ("policy", "complete", "rows"),
    [
        ("never", True, _EXPECTED_ROWS),
        ("failures", False, 5),
        ("always", True, 6),
        ("never", True, 1),
    ],
)
def test_simulation_trace_and_bag(  # noqa: PLR0915 - keep DDS setup and teardown together
    tmp_path: Path, policy: str, complete: bool, rows: int
) -> None:
    """Drive the real ROS timer and service contracts, then read the written Parquet."""
    episode = tmp_path / "episode.yaml"
    episode.write_text(
        yaml.safe_dump(
            {
                "goal": {"x": 4.0, "y": 5.0, "yaw": 0.0},
                "sample_hz": _RATE_HZ,
                "record_bag": policy,
                "teardown_grace_s": 5.0,
            }
        ),
        encoding="utf-8",
    )
    context = Context()
    rclpy.init(context=context)
    recorder = EpisodeRecorder(
        monitor=_Monitor(),
        context=context,
        parameter_overrides=[Parameter("episode_file", value=str(episode))],
    )
    source = Node("test_recorder_source", context=context)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(recorder)
    executor.add_node(source)
    gt_pub = source.create_publisher(
        PoseStamped, recorder.topic("ground_truth_pose"), recorder.qos("ground_truth_pose")
    )
    amcl_pub = source.create_publisher(
        PoseWithCovarianceStamped, recorder.topic("amcl_pose"), recorder.qos("amcl_pose")
    )
    odom_pub = source.create_publisher(Odometry, recorder.topic("odom"), recorder.qos("odom"))
    cmd_pub = source.create_publisher(Twist, recorder.topic("cmd_vel"), recorder.qos("cmd_vel"))
    nav_pub = source.create_publisher(String, "/roboprobe/nav_status", _QUEUE_DEPTH)
    delay_pub = source.create_publisher(Float64, "/roboprobe/cmd_delay_actual", _QUEUE_DEPTH)
    lidar_stats_pub = source.create_publisher(String, "/roboprobe/perturber_stats", _QUEUE_DEPTH)
    bt_pub = source.create_publisher(
        BehaviorTreeLog, recorder.topic("bt_log"), recorder.qos("bt_log")
    )
    clock_pub = source.create_publisher(Clock, "/clock", qos_profile_sensor_data)
    start = source.create_client(Trigger, "/episode_recorder/start")
    stop = source.create_client(SetBool, "/episode_recorder/stop")
    data_pubs = (gt_pub, amcl_pub, odom_pub, cmd_pub, nav_pub, delay_pub, lidar_stats_pub, bt_pub)

    def clock_at(step: int) -> None:
        instant = _NS_PER_S + step * (_NS_PER_S // _RATE_HZ)
        msg = Clock()
        msg.clock.sec, msg.clock.nanosec = divmod(instant, _NS_PER_S)
        clock_pub.publish(msg)
        _wait(executor, lambda: recorder.get_clock().now().nanoseconds == instant)

    try:
        _wait(
            executor, lambda: all(pub.get_subscription_count() for pub in (*data_pubs, clock_pub))
        )
        _wait(executor, lambda: start.service_is_ready() and stop.service_is_ready())
        premature = stop.call_async(SetBool.Request(data=False))
        _wait(executor, premature.done)
        assert not premature.result().success
        clock_at(0)
        started = start.call_async(Trigger.Request())
        _wait(executor, started.done)
        assert started.result().success
        repeated_start = start.call_async(Trigger.Request())
        _wait(executor, repeated_start.done)
        assert repeated_start.result().success
        if policy == "always":

            def bag_discovered() -> bool:
                clock_at(0)  # The recorder discovers sensor topics after its first /clock.
                return gt_pub.get_subscription_count() == _TRACE_AND_BAG_SUBSCRIBERS

            _wait(executor, bag_discovered)
        gt = PoseStamped()
        gt.pose.position.x, gt.pose.position.y = 2.0, 3.0
        gt.pose.orientation.w = 1.0
        estimate = PoseWithCovarianceStamped()
        estimate.pose.pose.position.x, estimate.pose.pose.position.y = 2.1, 3.1
        estimate.pose.pose.orientation.w = 1.0
        odom = Odometry()
        odom.twist.twist.linear.x = 0.3
        command = Twist()
        command.linear.x = 0.4
        gt_pub.publish(gt)
        amcl_pub.publish(estimate)
        odom_pub.publish(odom)
        cmd_pub.publish(command)
        nav_pub.publish(String(data="ACTIVE"))
        delay_pub.publish(Float64(data=0.065))
        lidar_stats_pub.publish(String(data="{"))
        lidar_stats_pub.publish(String(data='{"count": 12, "dropped": 2}'))
        recovery = BehaviorTreeStatusChange(
            node_name="Spin", previous_status="IDLE", current_status="RUNNING"
        )
        bt_pub.publish(BehaviorTreeLog(event_log=[recovery]))
        _wait(executor, lambda: recorder.ready_to_sample)
        for step in range(1, rows + 1):
            clock_at(step)
            _wait(executor, lambda step=step: recorder.sample_count == step)
        result = stop.call_async(SetBool.Request(data=complete))
        _wait(executor, result.done)
        assert result.result().success, result.result().message
    finally:
        try:
            recorder.flush(complete=False)
        finally:
            executor.shutdown()
            recorder.destroy_node()
            source.destroy_node()
            rclpy.try_shutdown(context=context)

    output = tmp_path / "trace.parquet"
    trace = read_trace(output)
    assert pq.read_schema(output).remove_metadata().equals(TRACE_SCHEMA, check_metadata=True)
    assert pq.ParquetFile(output).metadata.row_group(0).column(0).compression == "ZSTD"
    problems = validate_trace(trace, min_hz=10, max_gap_s=0.2)
    assert bool(problems) == (rows == 1)
    assert abs(trace.n_samples - rows) <= 1
    assert trace.meta["complete"] is (complete and not problems)
    assert trace.meta["n_recoveries"] == 1
    assert trace.meta["cmd_delay_max_s"] == pytest.approx(0.065)
    assert trace.meta["lidar_perturber_stats"] == {"count": 12, "dropped": 2}
    assert (trace.goal_x, trace.goal_y) == pytest.approx((4.0, 5.0))
    assert trace.gt_x[0] == pytest.approx(2.0)
    assert trace.est_x[0] == pytest.approx(2.1)
    assert trace.cmd_v[0] == pytest.approx(0.4)
    assert trace.meas_v[0] == pytest.approx(0.3)
    assert trace.nav_status[0] == NavStatus.ACTIVE
    assert trace.min_obstacle_dist[0] == pytest.approx(1.2)
    assert trace.roll[0] == pytest.approx(0.1)
    assert trace.pitch[0] == pytest.approx(0.2)
    assert not trace.contact[0]
    if policy == "always":
        [bag] = (tmp_path / "bag").glob("*.mcap")
        assert bag.read_bytes().startswith(_MCAP_MAGIC)
        data = yaml.safe_load((tmp_path / "bag/metadata.yaml").read_text(encoding="utf-8"))
        assert data["rosbag2_bagfile_information"]["message_count"] > 0
    else:
        assert not (tmp_path / "bag").exists()
