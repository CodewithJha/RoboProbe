# T-091 — TB4 Nav2 topic and geometry verification

## Outcome

Recorded the Jazzy `nav2_minimal_tb4_sim` topic graph, Nav2 MPPI speed parameter paths, TF frames, and lidar/pallet geometry used in `ros_ws/src/roboprobe_ros/config/topics.yaml` and `tasks/warehouse_delivery_v1.yaml`.

## Method

Upstream package sources (pinned to the same stack as `spikes/T-090/Dockerfile`):

- `ros-navigation/navigation2` `@jazzy` — `nav2_bringup/params/nav2_params.yaml`, `tb4_simulation_launch.py`
- `ros-navigation/nav2_minimal_turtlebot_simulation` `@main` — `nav2_minimal_tb4_sim/configs/tb4_bridge.yaml`, `spawn_tb4.launch.py`, `nav2_minimal_tb4_description/urdf/**`

Cross-checks from [`docs/evidence/T-090-gazebo-spike.md`](../T-090-gazebo-spike.md): `enable_stamped_cmd_vel=False`, depth on `/rgbd_camera/depth_image`.

Reproduce a live capture inside the T-090 image:

```bash
docker build -t roboprobe-t090-local:jazzy spikes/T-090
docker run --rm -v "$PWD:/repo" -w /repo -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
  roboprobe-t090-local:jazzy bash -lc 'source /opt/ros/jazzy/setup.bash && ./scripts/ros_introspect.sh docs/evidence/T-091/capture'
```

## Geometry

| Quantity | Value (m) | Derivation |
|----------|-----------|------------|
| Lidar plane | 0.194 | `base_link_z_offset` + `shell_z_offset` + `rplidar_z_offset` from minimal TB4 URDF + spawn `z_pose=0.01` |
| Dropped pallet height | 0.144 | EUR pallet; top ≈ 4.9 cm below lidar plane (OQ-2) |

## RoboProbe intercept topics

| Upstream (verified) | RoboProbe episode (T-093+) |
|---------------------|------------------------------|
| `/scan` from `tb4_bridge.yaml` | Bridge targets `/scan_raw`; perturber publishes `/scan` |
| `/cmd_vel` from velocity smoother | Smoother → `/cmd_vel_nav`; `cmd_delay` → `/cmd_vel` |
| `/rgbd_camera/depth_image` | `depth_image_proc` → `/rgbd_camera/depth/points`; degrader → `depth_points` |

`ground_truth_pose` (`/ground_truth/pose`) is bridged from the Gazebo model pose in `episode.launch.py` (T-094d).

## Artefacts

| File | Contents |
|------|----------|
| `tb4_bridge.yaml` | Copy of upstream bridge configuration |
| `nav2_speed_param_paths.txt` | MPPI `vx_max` and velocity-smoother keys |
| `nav2_controller_flags.txt` | `enable_stamped_cmd_vel` and `use_sim_time` |
| `tb4_lidar_offsets.txt` | URDF constants for lidar height |
