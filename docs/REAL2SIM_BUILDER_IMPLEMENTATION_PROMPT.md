# Real2Sim Builder — Implementation Prompt

You are building a new standalone project named `real2sim-builder`.

The purpose of this project is to turn real-world images/videos into a reusable simulation scene package for robotics.

This project must be independent from any specific SO-101 task, Isaac Lab task, Mimic pipeline, dataset pipeline, policy, or evaluation code.

The existing SO-101 project may be used as a reference implementation if it is accessible, but do not modify or delete that project in this phase.

---

## 1. Product Goal

Build a general-purpose **Real2Sim Builder** that accepts real-world visual evidence and produces a simulation-ready scene for:

- Isaac Sim / Isaac Lab
- MuJoCo

Typical usage:

```text
Real images / videos
+ optional measurements
+ optional camera calibration
+ optional robot model / joint states
        ↓
Real2Sim Builder
        ↓
Scene reconstruction
        ↓
Autonomous validation / refinement
        ↓
Exported Scene Package
        ↓
Used later by another robotics project
```

The Real2Sim Builder ends at **scene generation and validation**.

It must NOT implement:

- task logic
- robot control
- Mimic
- datagen
- teleoperation
- policy training
- policy evaluation
- task-specific rewards / reset logic

Those belong to downstream robotics projects.

---

## 2. Main Use Case

A user starts a completely new robotics project in a new real environment.

Example:

```text
Project B
- different table
- different object layout
- different camera positions
- different bins / fixtures
- different background
```

The user should be able to create a new Real2Sim project, provide images/videos and optional supporting data, then let the tool build the scene automatically.

The final exported scene should be usable by another AI agent or engineer to create an Isaac/MuJoCo environment without needing to reverse-engineer the scene manually.

---

## 3. Inputs

Required:

- one or more images and/or videos of the real workspace

Optional:

- camera intrinsics
- camera extrinsics
- known measurements
- CAD / meshes
- robot URDF / MJCF / USD
- robot joint states
- robot actions
- timestamps
- multiple camera views
- depth / point cloud data

Use available evidence in this priority:

```text
measured values
→ calibration data
→ known robot geometry / FK
→ synchronized multi-view observations
→ deterministic image measurements
→ numerical optimization
→ visual estimation
```

Do not guess values that can be calculated.

Every important reconstructed value should retain provenance such as:

- `measured`
- `calibrated`
- `derived`
- `optimized`
- `estimated`
- `unknown`

---

## 4. Canonical Scene Representation

Do not make USD or MJCF the single source of truth.

Create a simulator-independent canonical scene representation, for example:

```text
scene.yaml
```

It should describe:

- coordinate convention
- world frame
- units
- objects
- transforms
- dimensions
- semantic roles
- cameras
- visual geometry
- collision geometry
- physics properties
- provenance
- source assets

Example semantic roles:

```text
workspace
support_surface
manipulable_object
receptacle
fixture
background
reference_robot
camera
```

From this canonical scene representation, generate:

```text
scene.usd   → Isaac Sim
scene.xml   → MuJoCo
```

Do not force USD→MJCF or MJCF→USD conversion as the primary architecture.

Both should be exported from the same canonical scene description.

---

## 5. AI-Readable Metadata

Every final scene package must include metadata that allows another AI agent to understand and use the scene without manually inspecting simulator files.

At minimum generate:

```text
scene_manifest.yaml
SCENE.md
```

`scene_manifest.yaml` should include:

- scene name
- coordinate system
- units
- frame hierarchy
- object IDs
- semantic roles
- poses
- dimensions
- asset references
- collision representation
- cameras
- physics parameters
- provenance
- Isaac export mapping
- MuJoCo export mapping

`SCENE.md` should be a concise human/AI-readable summary containing:

- what the workspace represents
- important objects
- manipulable objects
- support surfaces
- receptacles / targets
- cameras
- coordinate convention
- important measurements
- uncertain / estimated parts
- intended simulator exports

The exported package should act as an interface between this tool and future AI-assisted robotics projects.

---

## 6. Autonomous Reconstruction Workflow

The tool should run this workflow autonomously:

```text
ANALYZE
↓
CAMERA & SCALE
↓
GEOMETRY
↓
VISUAL
↓
PHYSICS
↓
VALIDATION
↓
EXPORT
```

### ANALYZE

Inspect all available images/videos and supporting files.

Identify:

- workspace structure
- visible objects
- cameras
- scale anchors
- robot if present
- interaction-critical geometry
- ambiguous regions
- missing evidence

For videos, extract useful frames automatically.

Do not require the user to manually take repeated screenshots.

### CAMERA & SCALE

Estimate or calibrate:

- intrinsics
- extrinsics
- metric scale
- camera poses

When a robot model and joint states are available, use robot FK as a metric calibration reference.

Do not distort scene geometry to compensate for incorrect camera calibration.

### GEOMETRY

Reconstruct:

- work surfaces
- fixtures
- manipulation objects
- bins / receptacles
- major scene structure

Prioritize interaction-critical geometry.

Visual geometry and collision geometry may differ.

Prefer simple, robust collision primitives when appropriate.

### VISUAL

After geometry is stable, match:

- important materials
- colors
- textures
- dominant lighting
- visually important background structure

Photorealism is secondary to geometric correspondence and robot interaction.

### PHYSICS

When real motion/action evidence exists, compare real and simulated dynamics.

Tune only justified parameters such as:

- mass
- inertia
- friction
- damping
- contact parameters

Do not use physics parameters to hide geometry or timing errors.

### VALIDATION

Render the simulated scene from the reconstructed cameras.

Compare real vs sim using useful diagnostics such as:

- side-by-side
- overlay
- difference images
- landmark reprojection error
- object center/corner error
- silhouette overlap
- camera alignment
- multi-view consistency

Use hold-out views/frames when possible.

Do not rely only on subjective visual similarity.

---

## 7. Autonomous Iteration

The system must perform:

```text
render
→ compare
→ diagnose
→ modify
→ rerender
→ reevaluate
```

without requiring the user to repeatedly:

- open a simulator UI
- take screenshots
- manually compare images
- create new test files
- say "try again"

Do not stop after one improvement.

Continue automatically until one of these states is reached:

- `ACCEPTED`
- `NEEDS_MORE_DATA`
- `FAILED`

If more data is required, stop and request only the minimum missing evidence.

Example:

```text
NEEDS_MORE_DATA

Need:
- one additional left-side image

Reason:
- current views cannot distinguish object depth from camera translation
```

Do not request exploratory screenshots merely to inspect progress.

---

## 8. Project / Version Management

The UI should not expose many numbered profile files.

Avoid:

```text
profile_01.json
profile_02.json
profile_final.json
profile_final2.json
camera_fix_v3.py
scene_test_new.py
```

Prefer:

```text
working/current_scene.yaml
history.jsonl
scratch/
```

The current accepted state should be obvious.

Use Git history and a lightweight run history for iteration history.

Intermediate renders and temporary candidate outputs may be overwritten.

Create new source files only when they provide reusable functionality.

---

## 9. Proposed Project Structure

Use a clean architecture similar to:

```text
real2sim-builder/
├── app/
│   ├── core/
│   ├── reconstruction/
│   ├── calibration/
│   ├── validation/
│   ├── exporters/
│   └── ui/
│
├── projects/
│   └── <scene_project>/
│       ├── input/
│       ├── working/
│       ├── scratch/
│       ├── history.jsonl
│       └── exports/
│
├── tests/
├── docs/
└── README.md
```

Adjust this structure if the repository or framework suggests a better design, but preserve the separation between:

- reusable engine code
- individual Real2Sim projects
- temporary working state
- final exported scene packages

---

## 10. UI

Build the backend architecture first, then build the UI on top of it.

The UI is a **project manager and progress monitor**, not the reconstruction engine itself.

Keep it simple.

### Home

Show:

```text
Real2Sim Builder

Projects

SO101 Workspace     ACCEPTED
Factory B           RUNNING
Shelf Test          DRAFT

[ + New Scene ]
```

### New Scene

Allow:

```text
Scene Name

Required:
[ Add Images ]
[ Add Videos ]

Optional:
[ Robot Model ]
[ Joint States ]
[ Camera Calibration ]
[ Measurements ]

[ Start Reconstruction ]
```

### Run View

Show:

```text
Status
Current Stage
Iteration
Current task
Current metrics
Agent decision

ANALYZE      ✓
CAMERA       ✓
GEOMETRY     ●
VISUAL       ○
PHYSICS      ○
VALIDATION   ○
```

Controls:

- Start
- Pause
- Resume
- Stop

The system should resume from saved working state after interruption.

### Compare View

Show useful validation outputs:

```text
Real | Sim
Overlay
Difference
Metrics
```

This is primarily for inspection, not for manual iteration.

### Result View

When accepted:

```text
ACCEPTED

scene.usd
scene.xml
scene_manifest.yaml
SCENE.md

Validation: PASS
```

Provide simple actions such as:

- Open export folder
- Open in Isaac Sim, if supported
- Open in MuJoCo, if supported

---

## 11. Final Scene Package

A successful export should look similar to:

```text
exports/
└── <scene_name>/
    ├── scene.usd
    ├── scene.xml
    ├── scene_manifest.yaml
    ├── SCENE.md
    │
    ├── assets/
    │   ├── meshes/
    │   └── textures/
    │
    ├── validation/
    │   ├── report.json
    │   └── previews/
    │
    └── source/
        └── reconstruction.yaml
```

This folder is the final product of Real2Sim Builder.

A downstream robotics project should be able to consume this package and then separately implement:

- robot integration
- task logic
- observations/actions
- reset logic
- Mimic/datagen
- policy training/evaluation

---

## 12. Existing SO-101 Project

If the existing SO-101 Real2Sim implementation is available:

- inspect it for reusable concepts and code
- use the current SO-101 workspace as the first real test case
- migrate only generic Real2Sim functionality into this new project
- do not copy task-specific Mimic/datagen/policy code
- do not modify or delete the existing SO-101 project during this implementation phase

The goal is to prove:

```text
SO-101 real references
        ↓
Real2Sim Builder
        ↓
scene.usd
scene.xml
scene_manifest.yaml
SCENE.md
```

Once this new builder works reliably, cleanup of the old SO-101-specific Real2Sim code can be handled separately.

---

## 13. Implementation Order

Proceed in this order:

1. inspect the new repository and available reference project
2. define the canonical scene schema
3. define project/run state management
4. implement import of images/videos and optional metadata
5. implement deterministic rendering/export interfaces
6. implement validation / comparison tools
7. implement the autonomous reconstruction loop
8. implement USD exporter
9. implement MuJoCo exporter
10. implement metadata / `SCENE.md` generation
11. use the existing SO-101 workspace as the first end-to-end test
12. build the minimal UI on top of the working backend
13. document how another robotics project consumes an exported scene package

Do not begin by recreating the old UI.

Do not create unnecessary frameworks or duplicated scene-specific code.

Prefer a small, understandable, reusable architecture.

---

## 14. Completion Criteria

The first version is complete when a user can:

1. create a new Real2Sim project
2. add real images/videos
3. optionally add robot/calibration/measurement data
4. start reconstruction once
5. let the system iterate without repeated manual screenshots or prompts
6. inspect progress
7. receive an `ACCEPTED`, `NEEDS_MORE_DATA`, or `FAILED` result
8. export a self-contained scene package
9. load the exported USD in Isaac Sim
10. load the exported MJCF/XML in MuJoCo
11. give the same scene package to another AI agent and have that agent understand the scene from its metadata

Start by inspecting the project and designing the minimal architecture needed to support this workflow, then proceed with implementation.
