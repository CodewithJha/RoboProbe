# T-090 — Headless TurtleBot 4 warehouse spike

## Outcome

Proceed with the Gazebo/Nav2 integration on this laptop using one software-rendered worker. TurtleBot 4 completed the warehouse navigation goal and published depth frames without a display. Cold startup exceeded the current 60 s setting in every successful trial, so start with `backends.gazebo_nav2.startup_timeout_s = 150` s for this setup and retain `max_parallel_per_host = 1`. Keep cold-start latency and variable navigation throughput under [risk R-01](../23-risks-and-mitigations.md).

## Environment and versions

The host was an Apple Silicon Mac with macOS 26.5.2. Docker Engine 29.9.2 exposed a Linux arm64 VM with 10 vCPUs and 7.75 GiB RAM. The container had no `/dev/dri` device. Both rendering settings therefore ran without access to the laptop GPU. [Docker Desktop GPU passthrough documentation](https://docs.docker.com/desktop/features/gpu/)

| Component | Installed version |
|-----------|-------------------|
| Ubuntu | 24.04.5 LTS (Noble) |
| ROS 2 | Jazzy |
| Gazebo Harmonic (`gz sim --versions`) | 8.15.0 |
| `ros-jazzy-navigation2` | `1.3.14-1noble.20261109.092250` |
| `ros-jazzy-nav2-bringup` | `1.3.14-1noble.20261109.092853` |
| `ros-jazzy-nav2-minimal-tb4-sim` | `1.0.1-1noble.20261106.055525` |
| `ros-jazzy-nav2-simple-commander` | `1.3.14-1noble.20261106.010112` |
| `ros-jazzy-ros-gz` | `1.0.25-1noble.20261106.093604` |
| `ros-jazzy-rmw-cyclonedds-cpp` | `2.2.4-1noble.20261105.131809` |
| Mesa DRI | `25.2.8-0ubuntu0.24.04.5` |

## Procedure

Run the [spike harness](../../spikes/T-090/run.py) from the repository root. Each output directory must be new.

```bash
docker build -t roboprobe-t090-local:jazzy spikes/T-090
out="$(mktemp -d)"
python3 spikes/T-090/run.py --count 1 --software --output "$out/single-software"
python3 spikes/T-090/run.py --count 1 --output "$out/single-default"
python3 spikes/T-090/run.py --count 2 --software --output "$out/pair-software"
python3 spikes/T-090/run.py --count 2 --software --synchronize --timeout 240 --output "$out/pair-synchronized"
```

The harness uses the packaged warehouse world and map and starts the robot at `(2.12, -21.30)` facing north. It runs with `headless:=True`, `use_rviz:=False`, and Gazebo's `--headless-rendering` flag for EGL. Nav2 receives a `NavigateToPose` goal at `(2.12, -19.30)`. Each instance uses its own ROS domain and Gazebo partition. The optional barrier submits goals after both instances are ready.

Startup measures ROS launch to Nav2 ACTIVE using a monotonic wall clock. Goal wall time covers submission through the terminal action response. The launch also records both the median of Gazebo `/stats` RTF samples and the amount of ROS `/clock` time elapsed during the goal divided by the corresponding wall time. The Gazebo sample window starts at ACTIVE and can include time before the action. Docker CPU and working-set memory are point samples with a two-second pause between Docker CLI calls. Docker CPU can exceed 100% when the container uses several cores. The harness writes ROS package versions, per-instance results, launch logs, and raw Docker statistics in the output directory.

## Results

| Rendering and instance | Nav2 ACTIVE (s) | Goal wall (s) | Gazebo median RTF | Goal clock RTF | Observed depth frames | Peak CPU | Peak memory (MiB) |
|------------------------|----------------:|--------------:|------------------:|---------------:|-------------:|---------:|------------------:|
| Forced software, one | 74.49 | 10.74 | 0.987 | 0.415 | 45 | 459.4% | 1761.3 |
| Software flag unset, one | 92.23 | 4.40 | 1.000 | 1.002 | 44 | 300.5% | 1534.0 |
| Forced software, parallel startup 1 | 96.18 | 4.57 | 1.000 | 0.994 | 46 | 286.9% | 1281.0 |
| Forced software, parallel startup 2 | 78.49 | 4.77 | 1.000 | 0.949 | 45 | 331.5% | 1468.4 |
| Forced software, overlapping goals 1 | 76.21 | 10.00 | 0.999 | 0.433 | 186 | 354.8% | 1492.0 |
| Forced software, overlapping goals 2 | 94.70 | 9.88 | 0.906 | 0.438 | 44 | 360.3% | 1350.7 |

All six goals shown succeeded. In the first parallel startup trial, the instances became ready about 18 s apart and their goals did not overlap. The synchronized retry started the two goals about 2 ms apart, with 9.88 s of overlap. Both goal-clock ratios then fell below 0.5. The depth subscription starts before the barrier, so the earlier ready instance recorded more frames while waiting. Across all six successful episodes, Nav2's controller reported `enable_stamped_cmd_vel=False` and `use_sim_time=True`. The robot published real images on `/rgbd_camera/depth_image`.

## Problems and workarounds

- Bringup can wait on localization and the `odom` transform while the warehouse and robot initialize. Allow at least 150 s for this VM and preserve the Gazebo log when startup fails.
- An initial synchronized launch did not reach the action barrier within the 180 s budget. The retry completed both goals, with goal-clock ratios of 0.433–0.438. Keep one worker on this VM.
- The 40 s V1 overhead target was exceeded before a goal could start. Gazebo's near-real-time median also hid the 0.415 goal-window ratio from the slowest successful single-instance trial.

## Follow-up

Use the one-worker setting for T-091 and check startup again when the production image pre-stages world assets. Compare GPU and forced software rendering on a GPU-enabled Linux host in [#331](https://github.com/CodewithJha/RoboProbe/issues/331).
