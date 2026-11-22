#!/usr/bin/env bash
# Capture the running Jazzy warehouse after Nav2 becomes active (T-091).
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 OUTPUT_DIRECTORY" >&2
    exit 2
fi

output="$(mkdir -p "$1" && cd "$1" && pwd)"
description="$(ros2 pkg prefix --share nav2_minimal_tb4_description)"
sim="$(ros2 pkg prefix --share nav2_minimal_tb4_sim)"

ros2 topic list -t >"$output/ros-topics.txt"
gz topic -l >"$output/gazebo-topics.txt"
cp "$sim/configs/tb4_bridge.yaml" "$output/stock-bridge.yaml"

{
    for topic in /scan /scan_raw /rgbd_camera/depth_image /rgbd_camera/points_raw \
        /cmd_vel_nav /cmd_vel_smoothed /cmd_vel /odom /amcl_pose /ground_truth_pose /behavior_tree_log; do
        printf '\n## %s\n' "$topic"
        # Raw and ground-truth topics are only present when the RoboProbe bridge is active.
        if grep -Fq "$topic [" "$output/ros-topics.txt"; then
            ros2 topic info -v "$topic" | sed '/^GID:/d'
        else
            printf '%s\n' 'Not published in this graph.'
        fi
    done
} >"$output/ros-topic-info.txt"

for node in controller_server velocity_smoother local_costmap/local_costmap \
    global_costmap/global_costmap amcl bt_navigator; do
    ros2 param dump "/$node" >"$output/params-${node##*/}.yaml"
done

timeout 20s ros2 run tf2_tools view_frames --wait-time 5 --output "$output/tf-frames" \
    >"$output/tf-frames.txt" 2>&1
# The console dump includes the same frame graph in a diffable text form.
rm -f "$output/tf-frames.pdf" "$output/tf-frames.gv"

{
    printf '%s\n' '# Lidar and camera declarations in the pinned robot Xacro'
    grep -n -E 'shell_z_offset|rplidar_[xyz]_offset|xacro:rplidar|xacro:oakd' \
        "$description/urdf/standard/turtlebot4.urdf.xacro"
    grep -n -E 'base_link_z_offset' "$description/urdf/icreate/create3.urdf.xacro"
    printf '\n%s\n' '# Live laser and depth frame IDs'
    for topic in /scan /rgbd_camera/depth_image; do
        printf '%s\n' "$topic"
        timeout 20s ros2 topic echo "$topic" --once --field header --qos-profile sensor_data |
            grep '^frame_id:'
    done
} >"$output/sensor-geometry.txt"
