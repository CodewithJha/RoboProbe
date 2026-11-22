#!/usr/bin/env bash
# Keep the worker venv separate from the ROS system interpreter. Colcon-generated
# executables and ros2 continue to use the system Python they were built with.
set -e

worker_python=/opt/roboprobe/venv/bin/python
if [[ "${1:-}" == healthcheck ]]; then
  exec "$worker_python" -c 'import os, urllib.request; port = os.environ.get("ROBOPROBE_WORKER__HEALTH_PORT", "9101"); urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=3).close()'
fi

install -d -m 700 "$HOME" "$ROS_HOME" "$XDG_RUNTIME_DIR"
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
# shellcheck disable=SC1091
source /opt/roboprobe/ros_ws/install/setup.bash

export RMW_IMPLEMENTATION="${ROBOPROBE_BACKENDS__GAZEBO_NAV2__RMW:-${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}}"
case "${ROBOPROBE_BACKENDS__GAZEBO_NAV2__SOFTWARE_RENDERING,,}" in
  1|true|yes|on) export LIBGL_ALWAYS_SOFTWARE=1 ;;
esac

case "${1:-}" in
  prefetch-fuel) exec bash /opt/roboprobe/prefetch_fuel.sh /opt/roboprobe/fuel-models.txt ;;
  ros2|gz) exec "$@" ;;
  *) exec /opt/roboprobe/venv/bin/roboprobe "$@" ;;
esac
