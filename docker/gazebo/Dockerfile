# syntax=docker/dockerfile:1.7
ARG ROS_IMAGE=ros:jazzy-ros-base-noble@sha256:5147d3ae250ce754afd399f6bfec15b33dd4e473ca357e30432a3182031bfad6
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d

# hadolint ignore=DL3006
FROM ${UV_IMAGE} AS uv

# hadolint ignore=DL3006
FROM ${ROS_IMAGE} AS simulator
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]
COPY docker/gazebo/apt-pins.txt docker/gazebo/write_versions.py /tmp/
# The simulator stays on the measured ROS/Gazebo releases. distro packages retain Ubuntu updates.
# hadolint ignore=DL3008
RUN arch="$(dpkg --print-architecture)" \
 && case "$arch" in amd64) col=2 ;; arm64) col=3 ;; *) exit 1 ;; esac \
 && awk -v col="$col" '!/^#/ && NF { if (NF != 3 || $col == "") exit 1; print $1 "=" $col }' \
      /tmp/apt-pins.txt > /tmp/ros-pins \
 && apt-get update \
 && xargs apt-get install -y --no-install-recommends \
      python3-numpy python3-scipy python3-yaml ros-jazzy-rosbag2 libegl1 libgl1-mesa-dri \
      < /tmp/ros-pins \
 && rm -rf /var/lib/apt/lists/* \
 && source /opt/ros/jazzy/setup.bash \
 && install -d /opt/roboprobe \
 && python3 /tmp/write_versions.py /tmp/ros-pins /opt/roboprobe/ros_versions.json \
 && rm /tmp/apt-pins.txt /tmp/ros-pins /tmp/write_versions.py

# The isolated worker venv can use a different NumPy release from Jazzy's system Python.
# Arrow 26 requires NumPy 2, so the ROS recorder uses its Noble-compatible release range.
RUN --mount=type=bind,from=uv,source=/uv,target=/tmp/uv \
    --mount=type=cache,target=/root/.cache/uv \
    /tmp/uv pip install --system --break-system-packages --python /usr/bin/python3 \
      'pyarrow>=17,<26' 'pydantic>=2.7'

FROM simulator AS warehouse-fuel
COPY docker/gazebo/fuel-models.txt docker/gazebo/prefetch_fuel.sh /tmp/
RUN source /opt/ros/jazzy/setup.bash \
 && GZ_FUEL_CACHE_PATH=/opt/roboprobe/fuel bash /tmp/prefetch_fuel.sh /tmp/fuel-models.txt

FROM simulator AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/opt/roboprobe/venv
WORKDIR /src/backend
COPY backend/pyproject.toml backend/uv.lock ./
COPY plugins /src/plugins
# The installed shared CLI currently loads API and learning modules on import.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --extra worker --extra api --extra ml
COPY schemas /src/schemas
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --extra worker --extra api --extra ml
# Remove bundled development files without changing how the worker imports its dependencies.
RUN site="$(/opt/roboprobe/venv/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')" \
 && rm -rf "${site}/torch/include" "${site}/torch/test" "${site}/pyarrow/include" \
 && find "${site}/torch/bin" -mindepth 1 ! -name torch_shm_manager -exec rm -rf {} + \
 && for pkg in numpy pandas scipy sklearn pyarrow matplotlib sympy; do \
      find "${site}/${pkg}" -depth -type d -name tests -exec rm -rf {} +; \
    done

WORKDIR /src/ros_ws
COPY ros_ws/src ./src
RUN source /opt/ros/jazzy/setup.bash \
 && colcon build --packages-select roboprobe_ros --merge-install \
      --install-base /opt/roboprobe/ros_ws/install

FROM simulator AS runtime
ARG VERSION=dev
ARG REVISION=unknown
ARG APP_UID=10001
ARG APP_GID=10001
LABEL org.opencontainers.image.title="roboprobe-gazebo" \
      org.opencontainers.image.description="RoboProbe Gazebo Harmonic and ROS Jazzy worker" \
      org.opencontainers.image.source="https://github.com/CodewithJha/RoboProbe" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="MIT"

RUN groupadd --system --gid "${APP_GID}" roboprobe \
 && useradd --system --uid "${APP_UID}" --gid roboprobe --home-dir /tmp/roboprobe \
      --no-create-home --shell /usr/sbin/nologin roboprobe \
 && install -d -o roboprobe -g roboprobe /data/artifacts /data/workdirs \
 && install -d /app \
 && ln -s /data /app/data

COPY --from=builder /opt/roboprobe/venv /opt/roboprobe/venv
COPY --from=builder /opt/roboprobe/ros_ws/install /opt/roboprobe/ros_ws/install
COPY --from=warehouse-fuel /opt/roboprobe/fuel /opt/roboprobe/fuel
COPY configs /app/configs
COPY tasks /app/tasks
COPY ros_ws/src/roboprobe_ros/config /app/ros_ws/src/roboprobe_ros/config
COPY --chmod=755 docker/gazebo/entrypoint.sh /usr/local/bin/roboprobe-gazebo
COPY docker/gazebo/cyclonedds.xml /opt/roboprobe/cyclonedds.xml

ENV ROBOPROBE_GIT_SHA=${REVISION} \
    HOME=/tmp/roboprobe \
    ROS_HOME=/tmp/roboprobe/ros \
    XDG_RUNTIME_DIR=/tmp/roboprobe/runtime \
    MPLCONFIGDIR=/tmp/matplotlib \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ROBOPROBE_STORAGE__WORKDIR_ROOT=/tmp/roboprobe-workdirs \
    GZ_FUEL_CACHE_PATH=/opt/roboprobe/fuel \
    ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
    CYCLONEDDS_URI=file:///opt/roboprobe/cyclonedds.xml

WORKDIR /app
VOLUME ["/data/artifacts"]
USER ${APP_UID}:${APP_GID}
HEALTHCHECK --interval=5s --timeout=5s --start-period=20s \
  CMD ["/usr/local/bin/roboprobe-gazebo", "healthcheck"]
ENTRYPOINT ["/usr/local/bin/roboprobe-gazebo"]
CMD ["worker", "--backend", "gazebo_nav2", "--concurrency", "1", "--health"]
