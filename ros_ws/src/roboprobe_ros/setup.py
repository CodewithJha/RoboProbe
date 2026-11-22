"""Build the RoboProbe ROS package and install its shared configuration."""

from pathlib import Path

from setuptools import find_packages, setup

PACKAGE = "roboprobe_ros"

setup(
    name=PACKAGE,
    version="0.0.1",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{PACKAGE}"]),
        (f"share/{PACKAGE}", ["package.xml"]),
        (f"share/{PACKAGE}/config", [str(path) for path in sorted(Path("config").glob("*.yaml"))]),
        (
            f"share/{PACKAGE}/launch",
            [str(path) for path in sorted(Path("launch").glob("*.launch.py"))],
        ),
    ],
    install_requires=["setuptools"],
    # Arrow 26 requires NumPy 2, while ROS Jazzy uses Ubuntu Noble's NumPy 1.26.
    extras_require={"recorder": ["pyarrow>=17,<26", "pydantic>=2.7"]},
    entry_points={
        "console_scripts": [
            "cmd_delay = roboprobe_ros.cmd_delay:main",
            "episode_recorder = roboprobe_ros.episode_recorder:main",
            "sensor_perturber = roboprobe_ros.sensor_perturber:main",
        ],
    },
    zip_safe=False,
    maintainer="CodewithJha",
    maintainer_email="155089480+CodewithJha@users.noreply.github.com",
    description="RoboProbe nodes for Gazebo and Nav2 episodes",
    license="MIT",
    tests_require=["pytest"],
)
