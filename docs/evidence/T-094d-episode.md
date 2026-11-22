# T-094d warehouse launch evidence

A CPU-rendered ARM64 Jazzy/Harmonic run completed its process lifecycle offline with
the pinned warehouse assets in the Fuel cache. The episode used a copied workdir made
by the T-096a materializer, seed `34987515`, and a 150-second startup timeout. The
container network was disabled and Gazebo used loopback.

```bash
ros2 launch roboprobe_ros episode.launch.py workdir:=/path/to/materialized/episode \
  headless:=true use_sim_time:=true
```

The spawned model published ground truth on `/model/turtlebot4/pose`. The bridge
forwarded that pose to the recorder. The robot travelled 3.746 m along the warehouse
axis and the recorder saved 293 samples over 14.697 simulated seconds. Clearance
ranged from 2.176 to 2.735 m. The Trace v1 reader and sampling validator accepted
the Parquet file (SHA-256
`a33f5e355d5990fc422eccc4da6b0ae5e878527ff6252102c88dc6d0e37a5803`).

Nav2 returned `ABORTED` (action result 6) after a planner acknowledgment timeout.
`episode_done.json` recorded 14.745 simulated seconds and 22.307 wall seconds.
The recorder flushed the complete trace and the launch shut down after the manager
exited. Gazebo and the manager both exited cleanly.

Run the same launch acceptance check in an installed Gazebo worker environment
with its pinned cached assets and a disposable materialized workdir.

```bash
cd backend
ROBOPROBE_GAZEBO_LAUNCH_WORKDIR=/path/to/materialized/episode \
  uv run pytest -o addopts= -m sim tests/sim/test_gazebo_launch.py
```
