# Ground-truth clearance

`GroundTruthMonitor.from_episode(episode_file)` loads the workdir's map, footprint, and
pallets. The recorder calls `evaluate((x, y), (qx, qy, qz, qw))` in process using the Gazebo
ground-truth pose in map coordinates. Results are clearance in metres and roll, pitch, and yaw
in radians. Occupied and unknown map cells contribute to clearance.

For live diagnosis, the optional `ground_truth_monitor` executable accepts the same
`episode_file` and `topics_file` ROS parameters. It publishes clearance, roll, and pitch in
that order as `std_msgs/msg/Float64MultiArray` on `/roboprobe/ground_truth`.
