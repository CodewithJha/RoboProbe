# ADR-0002: Primary simulator: Gazebo Harmonic + ROS 2 Jazzy + Nav2 (TurtleBot 4, warehouse world)

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context
RoboProbe needs one established simulator that (a) runs on a student laptop without a large GPU, (b) has a realistic, maintained autonomous-navigation stack to test, (c) has a warehouse-like world matching the concept's use case, (d) is free, and (e) can be scripted headless. Candidates: Gazebo (Harmonic/Jetty), Webots, MuJoCo, NVIDIA Isaac Sim, CARLA. As of Nov 2026, Jazzy+Harmonic (LTS to May 2029) is the most widely documented ROS 2 combination; Lyrical+Jetty (LTS to 2031) is newer, with Nav2 1.5.x binaries released Aug 2026.

## Decision
Use **Gazebo Harmonic + ROS 2 Jazzy + Nav2 1.3.x** on Ubuntu 24.04 inside Docker, with the **TurtleBot 4** model and the **`warehouse.sdf`** world from `nav2_minimal_tb4_sim`, launched via `nav2_bringup/tb4_simulation_launch.py` headless. All simulator access goes through the `SimulatorBackend` port so Lyrical+Jetty (or another simulator) is a new adapter/image, not a redesign.

## Alternatives considered
| Option | Assessment |
|--------|-----------|
| Gazebo Harmonic + Jazzy (chosen) | Native Nav2 bringup + warehouse world; CPU-capable; huge community; LTS |
| Lyrical + Jetty | Newest LTS but younger ecosystem and fewer tutorials; kept as migration path |
| Webots | Good ROS 2 support, but Nav2 TB4 warehouse assets are Gazebo-native; would need re-creating worlds |
| MuJoCo | Excellent physics speed, but no sensor/rendering stack or Nav2 integration out of the box |
| Isaac Sim | Requires RTX-class NVIDIA GPU; heavy; not laptop-friendly |
| CARLA | Automotive, not indoor mobile robots |

## Consequences
- + Tests a *real* robot software stack (Nav2), credible for industry
- + Warehouse world fits the concept use case
- + Free, headless, containerised
- − 60–150 s per episode ⇒ need sample-efficient selection (ADR-0005) and a fast dev backend (ADR-0003)
- − Non-deterministic timing ⇒ reproducibility measured, not assumed (MET-06)
- − Lidar/depth sensors ignore lighting ⇒ explicit perception-degradation model (06 §3.3)

## Verification / compliance
T-090 (spike) must demonstrate one headless episode with RTF ≥ 1.0 on the owner's laptop; if it fails, fall back to TurtleBot 3 (`nav2_minimal_tb3_sim`) with fewer sensors before considering another simulator.
