FROM ros:jazzy-ros-base-noble@sha256:5147d3ae250ce754afd399f6bfec15b33dd4e473ca357e30432a3182031bfad6
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-jazzy-navigation2 ros-jazzy-nav2-bringup ros-jazzy-nav2-minimal-tb4-sim \
    ros-jazzy-nav2-simple-commander ros-jazzy-ros-gz ros-jazzy-rmw-cyclonedds-cpp \
    libgl1-mesa-dri libegl-mesa0 mesa-utils \
    && rm -rf /var/lib/apt/lists/*
