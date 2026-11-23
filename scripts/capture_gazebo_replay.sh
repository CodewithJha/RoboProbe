#!/usr/bin/env bash
# Capture a supplemental media replay without changing the headless research datasets.
set -euo pipefail
: "${MEDOID_ID:?}"
output=/results
capture_pid=
replay_pid=
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp >/results/xvfb.log 2>&1 &
display_pid=$!
cleanup() {
    [[ -z "$capture_pid" ]] || kill -INT "$capture_pid" 2>/dev/null || true
    [[ -z "$replay_pid" ]] || kill -TERM "$replay_pid" 2>/dev/null || true
    kill -TERM "$display_pid" 2>/dev/null || true
}
trap cleanup EXIT
export DISPLAY=:99 QT_X11_NO_MITSHM=1
for ((i=0; i<50; i++)); do
    xdpyinfo >/dev/null 2>&1 && break
    sleep 0.2
done
xdpyinfo >/dev/null
# The worker uses the standard launch file. Enable only its existing GUI launch flag.
mkdir -p /tmp/replay-bin
cat >/tmp/replay-bin/ros2 <<'SH'
#!/bin/sh
set -eu
real=/opt/ros/jazzy/bin/ros2
if [ "${1:-}" = launch ] && [ "${2:-}" = roboprobe_ros ] && [ "${3:-}" = episode.launch.py ]; then
    exec "$real" "$@" headless:=false
fi
exec "$real" "$@"
SH
chmod 755 /tmp/replay-bin/ros2
export PATH="/tmp/replay-bin:$PATH"
/opt/roboprobe/venv/bin/roboprobe --json replay --repeats 1 "$MEDOID_ID" >"$output/gui-replay.json" 2>"$output/replay.log" &
replay_pid=$!
visible=0
for ((i=0; i<150; i++)); do
    if xwininfo -root -tree >"$output/windows.txt" 2>/dev/null && grep -Eiq '"Gazebo[^"]*"' "$output/windows.txt"; then
        visible=1
        break
    fi
    kill -0 "$replay_pid" 2>/dev/null || break
    sleep 1
done
if [[ $visible == 1 ]]; then
    ffmpeg -hide_banner -loglevel error -f x11grab -video_size 1280x720 -framerate 15 -i :99.0 \
        -c:v libx264 -preset ultrafast -pix_fmt yuv420p -movflags +faststart -t 110 "$output/gazebo-replay.mp4" \
        >"$output/ffmpeg.log" 2>&1 &
    capture_pid=$!
fi
wait "$replay_pid"
replay_pid=
if [[ -n "$capture_pid" ]]; then
    kill -INT "$capture_pid" 2>/dev/null || true
    wait "$capture_pid" || true
    capture_pid=
fi
test -s "$output/gazebo-replay.mp4"
ffprobe -v error -show_format -show_streams -of json "$output/gazebo-replay.mp4" >"$output/video-metadata.json"
