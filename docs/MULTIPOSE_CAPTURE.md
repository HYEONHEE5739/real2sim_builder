# Snapshot → offline reconstruction → dual export

2026-10-08. SO-101 UI captures **one complete measured observation per click**.
The independent Builder never commands hardware. VS Code Codex is the external
reconstruction agent; `run`/UI Start are deterministic tools, not LLM calls.
No dependency installation or environment change is required.

## Collect snapshots in SO-101

Run the existing desktop entry point from SO-101:

```bash
.venv-real2sim-ui/bin/python scripts/real2sim/real2sim_ui.py
```

1. The UI opens idle: no engine, cameras or robot connection starts automatically.
   In **Real2Sim Capture → 연결 설정**, choose the actual Profile, Leader/Follower
   ports, follower calibration ID/files and two distinct camera devices. Select the
   worker Python in Workspace Pipeline (this machine: the existing `lerobot-arena`
   Python). Connection fields are shared with Real/Sim; there is no second controller.
2. Click **Start · 카메라/로봇 연결** in Capture. This always uses the real-only worker,
   regardless of the Simulation backend or Pipeline Workspace selection. It does not
   import MuJoCo/Isaac/omni/pxr. Start releases leader torque after calibration checks
   but sends no new follower goal. **Start Teleop** retains the existing
   hold-before-torque activation and starts following. **Stop Teleop** stops new
   goals; Disconnect closes the devices/runtime.
3. Capture's Side/Wrist views use those exact streams. Changing tabs never reconnects
   devices or starts teleop. Choose scene name/output location.
4. Move using normal user-operated teleop, hold the pose still for at least ~0.6 s,
   then click **현재 상태 캡처**. No robot command is sent by Capture. One Side/Wrist
   pair, measured state, timestamps and metadata save automatically. Check Saved,
   path/count/warnings; a failed save is not counted and can be retried.
5. Keep the table, robot base and object layout fixed. Change only the robot pose.
   If objects move, restore them or change **Scene state**, e.g. `layout_002`.
   This label is a user's assertion, not automatic object-motion detection. Different
   scene states are reconstructed in separate Builder projects.
6. Start with 8–15 varied poses and reserve independent poses for held-out validation.
   This is a suggested scale, not a success guarantee. Split is selected at Builder
   import, not on every capture. Near-identical measured poses cannot cross splits.
7. One Start-to-Disconnect connection is one snapshot session. The output setting is
   the parent directory. The first Capture creates `snapshot_<start date/time>_<id>/`;
   later captures append numbered shots there without rewriting model/calibration.
   Stop Teleop and tab changes keep the same session. Disconnect closes it after any
   in-flight save; the next Start uses a new session. Output/name stay fixed after the
   first Capture; calibration/model changes require a new connection.
   Previously committed snapshots are never overwritten; crash remnants remain
   separate from the committed index. Old `snapshot_dataset_*` inputs remain readable.

Capture Start has no SIM frames. For four-view comparison, choose Isaac/MuJoCo at
**Real / Sim → Simulation backend** and explicitly click **Connect** with the existing
Profile/Workspace. Switching connection modes waits for the old runtime to exit
before starting the new one. An old engine status never selects or locks the UI
backend on startup. The runtime and Workspace Pipeline remain separate consumers.
Actual connected hardware remains **NOT_TESTED** by the automated regression suite.

## Versioned portable dataset

```text
snapshot_<connection-start-time>_<id>/
  capture_manifest.yaml             # real2sim.snapshot/1 (JSON is valid YAML)
  calibration/cameras.json
  calibration/sensors.json
  robot_model/robot.urdf
  robot_model/<mesh-hash>.stl
  snapshots/snapshot_000001/
    side.png
    wrist.png
    state.json
    metadata.json
    COMPLETE
  snapshots/snapshot_000002/...
  COMPLETE
  .capture.lock
```

The manifest's optional `session` records its ID and connection start/end Unix
nanoseconds. The folder is created lazily on first Capture; those wall-clock fields
are separate from image/feedback host-monotonic timestamps. Reader schema remains
`real2sim.snapshot/1`. Closed sessions are readable; the UI does not append a new
connection to an older session.

Model/calibration are shared once. The manifest holds schema/dataset ID, Profile hash,
joint names/order/model rad or m/native units/mapping and hash, clock conventions,
robot model/base provenance, camera K/distortion/original resolution/parent/mount,
scene-state records, committed snapshot index and common file hashes. Each indexed
snapshot binds metadata by SHA-256; metadata binds both PNGs and state.json. State
includes actual native follower feedback, model `q_measured`, separate `q_command`
(nullable), command timestamp, stability window and measured history. Each image
retains its own read start/end, sequence, aligned measured q, skew, blur, resolution
and eligibility. Commands never replace measurements. PNGs preserve sensor resolution;
JPEGs in the IPC directory are only UI previews and are never calibration inputs.

Camera/Joints share host monotonic nanoseconds, **not hardware exposure timestamps**.
Arm interpolation uses measured samples bracketing the image within 100 ms; gripper
uses last measured sample. Missing streams, incompatible units/mapping/resolution,
moving/unstable feedback, stale >200 ms or skew >100 ms reject the snapshot. Blur
variance <10 is saved with warning and excluded from fitting; textureless images can
trigger this heuristic. Quality is assessed at observation acquisition, before disk
encoding, so a slow save does not shift the captured pose/time.

The bounded background writer receives frozen arrays/state; no repeated recording
occurs. PNG/state/metadata are flushed, a complete folder is renamed, then an atomic
manifest index publishes it. Only indexed complete snapshots are valid. Failed index
publication leaves the prior committed prefix; a process crash can leave unindexed
folders which are preserved for diagnosis. The shared import lock prevents a changing
index while copying. After import, Builder's copy is immutable even if collection
continues in the producer dataset. Re-import only adds new snapshot IDs.

SO-101's current mapper is **legacy_unverified**, including the gripper percentage
coordinate; it is not a measurement of physical jaw angle. Geometry acceptance is
blocked until physical/model correspondence is verified. Record real calibration
values/evidence rather than relabeling the status to pass validation.

## Builder input and CLI

In Builder's directory and the existing environment described in LOCAL_RUN.md:

```bash
export REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender
python -m app.cli new 'Workspace snapshots'
# Use the actual directory printed above.
PROJECT='projects/workspace-snapshots-REPLACE_ID'
DATASET='/absolute/path/to/snapshot_dataset_...'
python -m app.cli add "$PROJECT" /data/scene_brief.md --kind brief
python -m app.cli add "$PROJECT" /data/reference_side.jpg /data/reference_overview.jpg --kind reference
python -m app.cli add "$PROJECT" /data/measurements.yaml --kind measurements
python -m app.cli import-snapshots "$PROJECT" "$DATASET" \
  --scene-state static_001 --validation snapshot_000009 snapshot_000012
python -m app.cli inspect "$PROJECT"
```

Replace paths/IDs with actual observations. Include previously held-out IDs again when
appending; existing splits cannot be reassigned. Same pose (<0.01 in model-joint
coordinates) across train/validation is rejected; same-split repetitions share a group.
This guard does not replace Jacobian rank/pose-diversity checks. A dataset with several
scene states requires explicit --scene-state; a project accepts only one static layout.
Import itself can accept a single valid snapshot, but calibration/acceptance needs
more data. `import-capture` autodetects the new schema; use `import-snapshots` to choose
holdout IDs. Legacy real2sim.capture/1 still uses read-only `import-capture`.

An import generates known robot reference geometry and cameras, **not automatically
inferred tables/objects**. Add real measurements or use candidate edit/Blender author/sync
for initial scene geometry. Reference photos and brief are agent-readable evidence;
there is no internal semantic vision/LLM model or automatic 2D detector.
`--kind reference` stores phone photos as context-only evidence: unknown camera views
are available to Codex but excluded from pixel fitting and calibration rectification.

## Codex reconstruction loop

Codex reads reference photos, the brief, measurements, inspect output and all saved
snapshot images. It selects a mismatch hypothesis and modifies one parameter group
within available evidence; the CLI alone does not perform this visual reasoning.

```bash
python -m app.cli add "$PROJECT" /data/correspondences.yaml --kind measurements
python -m app.cli candidate "$PROJECT" create wrist_mount_01
python -m app.cli candidate "$PROJECT" fit wrist_mount_01 --target camera:wrist
python -m app.cli candidate "$PROJECT" render wrist_mount_01 --engine mujoco
python -m app.cli candidate "$PROJECT" evaluate wrist_mount_01 --engine mujoco --validation
python -m app.cli candidate "$PROJECT" evaluate wrist_mount_01 --engine blender --validation
# If candidate has a .blend workspace, rebuild/sync it after changing canonical parameters.
# Promote only when the persisted nonregression gate passes:
python -m app.cli candidate "$PROJECT" promote wrist_mount_01
python -m app.cli validate "$PROJECT" --engine blender
python -m app.cli export "$PROJECT"
```

Candidate edit, asset, blender-build/blender-author/blender-sync, reject and rollback
remain in AGENTIC_TOOLKIT.md. A fit returning NEEDS_MORE_DATA is not a successful fit.
Codex reads its reason and asks for missing evidence or changes hypothesis; no automatic
hardware motion, guessed measurement promotion, policy training or task generation.
Promotion is DRAFT; final fresh validation is required for accepted export.

Per observation, URDF/scalar-joint MJCF FK applies that camera's time-aligned measured q:

`T_world_wrist = T_world_base * FK_base_mount(q_measured) * T_mount_camera`.

Both Blender and MuJoCo render the posed robot and camera for each observation. Measured
q is frozen. The fitter uses train-only weighted soft-L1 reprojection least squares,
bounded camera/mount, K, robot base, object pose or dimension groups, and Jacobian rank.
Calibrated/measured values remain locked. Require >=2 varied training poses, >=8 training
correspondences and independent held-out observations; reject no train improvement or
held-out reprojection regression. Evaluation additionally gates held-out MAE/silhouette
IoU/center error. Silhouettes are evaluated, not differentiably optimized.

FK automatically provides 3D robot link frames/known local landmark positions. It does
**not** locate those landmarks in real images. Actual 2D uv/masks/corners and measured
object dimensions/intrinsics need evidence. Codex can suggest pixels/geometry from images
but must label them estimated, not measured. No automatic correspondence detector was added.

```yaml
units: m
landmarks:
  - observation: snapshot_dataset_REPLACE_ID_snapshot_000001_wrist
    frame: world
    point_m: [0.1, 0.2, 0.0]
    uv: [312.0, 227.0]
    weight: 1.0
    visible: true
```

Use actual observation IDs from inspect. Existing object-local point_m/point_fraction and
mask schemas remain in INPUTS.md. An unknown/estimated object dimension cannot serve as
an absolute metric anchor. Snapshot inputs require no grasp/place/reset events.

Outputs: `scratch/agent/<candidate>/renders/<engine>/metrics.json`,
`previews/<index>_<camera>/{real,sim,overlay,difference}.png`, per-pose render files
under `posed/<index>/`; candidate_scene.yaml/candidate.json/fit.json and input signatures
persist. Resume by inspecting and reopening the same candidate. Reject retains diagnostics;
failed candidates never change current_scene; rollback restores canonical/Blender/validation.

## Export and current SO-101 loader limit

The same canonical recipe emits scene.yaml, scene.xml, scene.usd, shared visual/collision
assets, scene_manifest.yaml, SCENE.md, validation/report.json and comparison previews.
Manifest includes frames, camera K/mount, IDs/roles/dimensions, engine mappings, portable
robot model, snapshot IDs/splits/pose/time/hash provenance, static scene state, uncertainty,
validation scope and PHYSICS_NOT_VALIDATED. Structural MJCF/USD parity is checked.
Isaac runtime appearance/contact is **NOT_TESTED**; pixel-identical engines are not claimed.

The current SO-101 Real/Sim loader consumes **so101.real2sim/2 Profile or
so101.workspace/1**, not a generic Builder scene package. Direct scene.xml/scene.usd
selection in that UI is **not implemented**. The exported reference robot is a posed
geometry snapshot, without a ready-made articulated controller. A downstream adapter
must map its static assets/cameras/frames into the SO-101 workspace and retain the existing
controllable robot/calibration/task contracts. That separate integration was not silently
implemented in this UI-focused change. Existing Profile/Workspace four-view operation remains.

Insufficient evidence makes validate exit 2 with needs. Review-only export:
`python -m app.cli export "$PROJECT" --allow-unvalidated`; its package is explicitly
UNVALIDATED and still requires a fresh report. Geometry success does not prove grasp/contact.

## Legacy compatibility and removals

Existing COMPLETE continuous sessions, paired captures, Builder projects and reference
files are unchanged. SO-101 `real2sim.legacy_capture` retains the old recorder/explicit
convert_paired API for tools/tests; `capture_dataset` lazily forwards old imports.
Builder applies old event exclusions only to legacy captures. Snapshot paths do not read
or require events. Active `physics-replay` CLI/stub and SO Record/Stop Recording/Save,
event handlers, Inspect/reference-fitting UI and paired Capture button were removed.
Calibration/profile/reference/paired-capture backend APIs used by old tools remain.
Generic LeRobot parquet/video-to-snapshot conversion is not implemented; explicit clocks,
feedback units/model/calibration are required rather than guessed.
