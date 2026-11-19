# 24 — Glossary

| Term | Definition |
|------|-----------|
| **Â12 (Vargha–Delaney)** | Effect size: probability that a random value from group A exceeds one from group B (ties count half). |
| **Acquisition function** | Function scoring how useful evaluating a candidate scenario would be, given the surrogate model (07 §5). |
| **ADR** | Architecture Decision Record (docs/adr). |
| **AMCL** | Adaptive Monte-Carlo Localisation, Nav2's particle-filter localiser. |
| **Anchor** | Fixed values of the non-plotted parameters in a 2-D risk slice. |
| **Artefact** | Large file produced by a run/analysis (trace, bag, figure), stored content-addressed. |
| **AST (Adaptive Stress Testing)** | RL/MCTS-based search for likely failure trajectories in sequential systems; future strategy `S-AST`. |
| **Backend** | Implementation of `SimulatorBackend` (`kinematic2d`, `gazebo_nav2`, `replay`). |
| **BoTorch / GPyTorch** | PyTorch libraries for Bayesian optimisation / Gaussian processes. |
| **Budget (B)** | Max number of runs a campaign may execute (excluding confirm/replay runs). |
| **Campaign** | One budgeted search over a scenario space with one strategy and seed. |
| **Case** | UI name for a failure mode (Casebook). |
| **Common random numbers** | Using identical random streams across compared strategies to reduce variance. |
| **Composition root** | The one place per process where concrete implementations are instantiated and injected. |
| **Condition strip** | RoboProbe's signature glyph showing a scenario's normalised parameter values as bars. |
| **Confirmatory run** | Extra run planned by the interaction tester; tagged `confirm`. |
| **DDS** | Data Distribution Service, ROS 2 middleware. |
| **Discovery curve** | Cumulative unique failure modes vs. number of simulations. |
| **DoR / DoD** | Definition of Ready / Done (32). |
| **Episode** | One simulator execution of one scenario (= one run). |
| **EV (expected violation)** | `E[max(0, −ρ)]` under the GP posterior (07 §5.2). |
| **Experiment** | Set of campaigns comparing strategies across seeds. |
| **Failure class** | Category `F-*` of a failure (08 §2). |
| **Failure mode** | Cluster of failing runs with similar conditions and failure behaviour (09 §3). |
| **Falsification** | Searching for inputs that violate a specification. |
| **GP** | Gaussian process — probabilistic regression model giving mean and uncertainty. |
| **GT mode** | Ground-truth failure mode of the kinematic2d backend (10 §7.2). |
| **HDBSCAN** | Hierarchical density-based clustering, finds clusters of varying density and labels noise. |
| **Interaction failure** | Failure that requires ≥ 2 parameters jointly; no single one suffices (09 §6). |
| **INVALID** | Verdict for runs with infrastructure problems; excluded from learning. |
| **kinematic2d (k2d)** | RoboProbe's fast deterministic 2-D test-double simulator. |
| **Kriging Believer** | Batch heuristic: pretend a selected point returned its predicted mean, then select the next. |
| **Level set / boundary** | Set of scenarios where expected robustness equals 0 (pass/fail boundary). |
| **LHS** | Latin Hypercube Sampling. |
| **LogEI / qLogNEI** | Numerically stable (noisy, batch) Expected Improvement acquisition. |
| **Manifest** | Provenance record for a run (21 §4). |
| **MCAP** | Container file format for rosbag2 recordings. |
| **Medoid** | Actual member of a cluster minimising distance to all others. |
| **Minimal reproducing scenario** | Failing scenario closest to nominal for a mode. |
| **MoSCoW** | Must/Should/Could/Won't prioritisation (26). |
| **Nav2** | ROS 2 navigation stack under test. |
| **Nominal** | Default "normal operations" value of each parameter. |
| **OFAT** | One-factor-at-a-time testing. |
| **Oracle** | Function deciding from a trace whether a property was violated (08). |
| **Orchestrator** | Service running campaign loops, proposals and analysis. |
| **Outbox** | Table of events written in the same transaction as state changes, then published. |
| **p_fail** | GP-estimated probability that a scenario fails: `Φ(−μ/σ)`. |
| **Phase** | S-PROBE sub-behaviour that produced a proposal (warmup, falsify, mode_search, boundary, refine, explore). |
| **Pin** | Fixing a parameter to a value for a campaign. |
| **Port / adapter** | Interface / implementation in hexagonal architecture. |
| **Proposal** | A scenario suggested by a strategy plus rationale. |
| **Reference set (REF)** | Dense k2d sample (20 000 runs) used as ground truth for evaluation. |
| **Risk map / atlas** | Classification of the space into SAFE, UNCERTAIN, FAILURE regions. |
| **Robustness (ρ)** | Continuous score in [−1,1]; negative ⇔ failure (08). |
| **ROS 2 Jazzy** | ROS 2 LTS distribution (May 2024–May 2029). |
| **RTF** | Real-time factor = sim time / wall time. |
| **Run** | One execution of a scenario with a seed (a row in `runs`). |
| **Scenario** | Concrete assignment of values to all parameters. |
| **Scenario space** | Parameters, ranges, priors, constraints and task (06). |
| **SHAP** | Shapley-value-based feature attributions. |
| **SKIP LOCKED** | PostgreSQL row-locking clause enabling concurrent queue consumers. |
| **Sobol sequence** | Low-discrepancy quasi-random sequence. |
| **SSE** | Server-Sent Events (one-way HTTP streaming). |
| **STL** | Signal Temporal Logic — specification language with quantitative robustness semantics. |
| **Straddle** | Level-set acquisition `1.96σ − |μ|`. |
| **Strategy** | Test-selection algorithm `S-*` (07). |
| **SUT / SUT profile** | System under test (robot stack) / its configuration set. |
| **Surrogate** | Cheap model approximating the expensive simulator response (GP). |
| **TaskSpec** | Start, goal, obstacles and time limit of the robot task (06 §7). |
| **Trace** | Time series recorded during an episode (11 §6.2). |
| **TurtleBot 4 (TB4)** | Differential-drive research robot model used in Gazebo. |
| **UoW** | Unit of Work (transaction boundary pattern). |
| **Verdict** | PASS, FAIL or INVALID. |
| **Worker** | Process that claims and executes runs on one backend. |
