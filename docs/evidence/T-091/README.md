# T-091 — TurtleBot 4 ROS and Gazebo interfaces

## Environment and repeatable capture

The live warehouse used the [T-090 image](../T-090-gazebo-spike.md) on arm64 with ROS 2 Jazzy, Gazebo Harmonic 8.15.0, Nav2 1.3.14 and `nav2_minimal_tb4_sim` 1.0.1. Capture from the same ROS domain and Gazebo partition after Nav2 reaches ACTIVE. Mount the checkout in the container, start the warehouse as in T-090, and run the capture script in a second shell with the same ROS environment.

```bash
source /opt/ros/jazzy/setup.bash
ros2 lifecycle get /bt_navigator
bash scripts/ros_introspect.sh /tmp/t091
```

The committed capture in [default](default/ros-topics.txt) records the stock endpoints, verbose QoS, six parameter dumps, the TF frame graph and the sensor declarations. Its [stock bridge config](default/stock-bridge.yaml) is from the installed Apache-2.0 Nav2 simulation package. Live timestamps and DDS participant IDs vary by capture. [Upstream Nav2 packages](https://github.com/ros-navigation/navigation2)

## Sensor geometry

The laser scan's ROS header names `rplidar_link`. The TF chain is `map → odom → base_link → shell_link → rplidar_link`. The pinned Xacro gives 0.030 m for the shell offset, 0.0642 m for the chassis offset and 0.098715 m for the sensor's offset from the shell, for a base-to-laser z offset of 0.192915 m. Live TF showed 0.193 m when rounded. The settled robot's world z was −0.00445 m, with pitch −0.004396 rad, so the scan plane was about 0.188 m above the floor at the sensor.

The stock depth image and the Gazebo point cloud both use `oakd_rgb_camera_optical_frame`. The project's [dropped pallet](../../../ros_ws/src/roboprobe_ros/models/dropped_pallet/model.sdf) uses a 0.8 × 0.6 × 0.135 m collision box. It spawned in the live warehouse with its center at z = 0.0675 m, putting its top 0.053 m below the measured scan plane. The stock world includes its own warehouse assets. The injected pallet uses this repository's simpler box geometry as specified in the [task](../../../tasks/measured/warehouse_delivery_measured_v1.yaml).

The regenerated demo fixture pins the measured task file so its scenario version and pallet geometry remain available after later warehouse revisions.

## ROS endpoint and bridge contract

The [topic contract](../../../ros_ws/src/roboprobe_ros/config/topics.yaml) uses the pinned ROS types and routes the custom inputs separately from the outputs produced by RoboProbe. The following mappings were verified with a real Jazzy bridge.

| Gazebo topic and type | ROS topic and type | Direction |
|-----------------------|--------------------|-----------|
| `/scan`, `gz.msgs.LaserScan` | `/scan_raw`, `sensor_msgs/msg/LaserScan` | Gazebo to ROS |
| `/rgbd_camera/points`, `gz.msgs.PointCloudPacked` | `/rgbd_camera/points_raw`, `sensor_msgs/msg/PointCloud2` | Gazebo to ROS |
| `/model/turtlebot4/pose`, `gz.msgs.Pose` | `/ground_truth_pose`, `geometry_msgs/msg/PoseStamped` | Gazebo to ROS |
| `/cmd_vel`, `gz.msgs.Twist` | `/cmd_vel`, `geometry_msgs/msg/Twist` | ROS to Gazebo |

Use the model-scoped Gazebo `PosePublisher` with `publish_model_pose=true`, `publish_link_pose=false` and `use_pose_vector_msg=false` for the ground-truth row. The global pose vector also contains other entities. Preserve the stock `/clock`, `/tf`, `/odom`, joint state and IMU bridges. [Gazebo PosePublisher](https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1systems_1_1PosePublisher.html)

Stock Nav2 sends controller and behavior commands through `/cmd_vel_nav` to the velocity smoother, then through `/cmd_vel_smoothed` to the collision monitor. Route the collision monitor's output and docking commands to `/roboprobe/cmd_vel_nav` before the RoboProbe delay node. The delay node publishes `/cmd_vel` for the robot bridge. Sensor and point inputs use the sensor-data profile, velocity and odometry use reliable volatile delivery, and AMCL pose uses reliable transient-local delivery.

The stock Jazzy graph used plain `Twist`. A separate bridge probe verified that the installed bridge also accepted a `TwistStamped` message and emitted its linear and angular components as `gz.msgs.Twist`. When enabling stamped velocity, use the same message type through the entire Nav2 velocity pipeline and the bridge. [Jazzy Nav2 configuration](https://docs.nav2.org/jazzy/configuration_and_development/migration_guides/iron/Iron/)

## Nav2 parameters

The [controller dump](default/params-controller_server.yaml) identifies the MPPI plugin and `FollowPath.vx_max=0.5`. The [smoother dump](default/params-velocity_smoother.yaml) records `max_velocity=[0.5, 0.0, 2.0]`. P1 updates the controller limit and the first smoother component through the [shipped profile](../../../configs/sut_profiles/tb4_nav2_default.yaml). The pinned bringup package's alternative DWB parameter files use `FollowPath.max_vel_x` (0.26 m/s in its multirobot example). The warehouse profile uses MPPI.
