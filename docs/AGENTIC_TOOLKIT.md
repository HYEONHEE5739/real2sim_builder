# Codex reconstruction toolkit

Canonical `working/current_scene.yaml` remains the source of truth. Codex supplies
visual reasoning; no embedded LLM API or agent framework is used. The original
`run` command remains the deterministic calibration/color-fitting fallback.

## Environment and capabilities

Use an existing Python with NumPy/SciPy/OpenCV/Pillow/YAML/MuJoCo. USD structural
parity requires existing `pxr` bindings, not the Isaac Sim application. No command
installs dependencies. Blender is an external executable selected by
`REAL2SIM_BLENDER=/absolute/path/to/blender`, otherwise PATH lookup.

```
python -m app.cli capabilities
python -m app.cli inspect projects/<id>
```

Blender 5.2.2 LTS is now available at `/home/hyeonhee/apps/blender/blender`.
Set `REAL2SIM_BLENDER` to this existing executable. Actual headless build, author,
render, sync and dual-export checks are recorded in `BLENDER_REGRESSION.json`.
The earlier MuJoCo-only baseline remains in `AGENTIC_REGRESSION.json`.

## Candidate loop (no UI required)

```
python -m app.cli candidate projects/<id> create trial_001
python -m app.cli candidate projects/<id> edit trial_001 --edits edits.json
python -m app.cli candidate projects/<id> blender-build trial_001
python -m app.cli candidate projects/<id> blender-author trial_001 --path author.py
python -m app.cli candidate projects/<id> evaluate trial_001 --engine blender
python -m app.cli candidate projects/<id> blender-sync trial_001
python -m app.cli candidate projects/<id> evaluate trial_001 --engine blender
python -m app.cli candidate projects/<id> evaluate trial_001 --engine mujoco
python -m app.cli candidate projects/<id> promote trial_001
# or: candidate projects/<id> reject trial_001
python -m app.cli rollback projects/<id>
```

`render` only renders train observations; `evaluate` also compares. `--validation`
uses the existing held-out geometric/photometric checks. Default candidate
comparison is train-only: do not adaptively tune against held-out evidence.
`promote` is an explicit agent decision; it requires a fresh evaluation, not an
invented automatic quality threshold. It does NOT declare the scene ACCEPTED.
The agent must compare a baseline and refuse regressing proposals.

All edits and evaluations hold the same project lock as the original run worker.
Do not manually edit YAML while a worker holds the lock. A stale candidate base,
stale evaluation, unsynchronized blend, or protected-field overwrite is rejected.

Blender author scripts execute through `bpy` in the existing candidate blend.
Use `obj['r2s_id']` and `obj['r2s_role']` for new mesh objects. Cameras also need
`r2s_resolution=[width,height]` and `r2s_pixel_aspect=[x,y]`. Visible untagged
objects are rejected during sync. Use one Principled BSDF material per canonical
object; image textures are supported, procedural materials must be baked by the
authoring script. Point/area/sun lights and constant world ambient are supported.
Complex environment node graphs must be baked or simplified explicitly.

Blender render after authoring reads the blend, not a regenerated unedited scene.
Synchronization exports evaluated mesh geometry as OBJ, preserving UV seams and
baking scale. Collision remains separate and unchanged. New objects have unknown
collision until an explicit `set_collision` edit. Negative scale/shear are rejected.
Changes to calibrated/measured geometry/camera/color are rejected; use genuinely
new evidence rather than relabeling measured fields as inferred.

## Schema-aware edit operations

`--edits` takes a JSON list. No YAML string substitution is necessary.

```json
[
  {"op":"add_object","id":"cup_new","role":"receptacle",
   "dimensions":[0.07,0.07,0.065],"visual":{"type":"container","round":true,
   "wall":{"value":0.002,"provenance":"estimated","evidence":["visual hypothesis"]}},
   "collision":{"type":"container","round":true,
   "wall":{"value":0.002,"provenance":"estimated","evidence":["provisional collision"]}}},
  {"op":"set_material","id":"cup_new","color":[0.8,0.8,0.75],"roughness":0.6}
]
```

Other operations: `remove_object`, `update_pose` (4×4 `value`),
`update_dimensions` (`value` in metres), `set_visual_mesh` (`asset`, optional
`scale`/`texture`), `set_collision` (`value` geometry), `set_camera`
(`id`, optional `pose`, `K`, `resolution`, `distortion`), `set_lighting`
(`ambient`, optional `sources`). Sources have id/type/pose/color/energy/size;
the edit API marks their values estimated. Import assets first:

```
python -m app.cli candidate projects/<id> asset trial_001 --path cup.obj --kind visual
```

Use the returned asset ID. OBJ/STL require no new mesh library; other legacy
formats retain the existing optional trimesh dependency. Compound collisions are
explicit primitive parts with local 4×4 pose and full dimensions.

## Files and recovery

```
working/current_scene.yaml           current canonical (atomic file replacement)
working/blender/current.blend        last promoted packed authoring workspace
working/assets/{visual,collision,textures}/<hash>.<ext>
scratch/agent/<id>/candidate_scene.yaml
scratch/agent/<id>/candidate.blend
scratch/agent/<id>/blender/           requests, log, sync assets and signatures
scratch/agent/<id>/renders/<engine>/  images and metrics.json
scratch/agent/<id>/metrics.json      latest evaluation
scratch/agent/rollback.json          one-step promotion recovery record
```

Promotion copies assets to immutable content-addressed working paths before
switching canonical. Python exceptions restore prior canonical/state; an OS crash
is not a cross-file database transaction. Rollback refuses to overwrite changes
made after promotion. Rejected candidates remain inspectable in scratch; delete
their directory explicitly only when no retained record needs it. No v1/v2 scene
files are created. `history.jsonl` is event history, not a full scene backup.

## Final validation and export

```
python -m app.cli validate projects/<id> --engine blender
python -m app.cli export projects/<id>
python -m app.cli verify projects/<id>/exports/<id>
```

Final validation performs held-out comparison, 20 passive MuJoCo steps and
read-back MJCF/USD structural parity. It does not identify unknown physics or
execute an Isaac controller. The USD scene and MJCF share geometry/collision,
object IDs/roles, world transforms and calibrated cameras. Frame hierarchies are
baked to equal world transforms and retained as canonical frame-graph metadata.
Lighting/material response differs between engines and is recorded in manifest.

Missing evidence remains NEEDS_MORE_DATA. `export --allow-unvalidated` produces an
explicit UNVALIDATED package, and now also requires a fresh input signature.
Neither package load nor structural parity alone confers reconstruction accuracy.
CLI `validate` exits 2 for non-passing validation; unavailable Blender exits 3.
The legacy `run` exit contract is unchanged: read its JSON status, not just exit 0.

For new image-only projects, provide estimated geometry/cameras through the edit
API or calibrated evidence through the existing importer. The toolkit does not
magically infer metric scale. For nonzero distortion, run the existing calibrated
undistortion preprocessor before pinhole rendering; never silently drop distortion.
Video frame extraction is retained, but moving-frame scene tracking is not added.

## Human UI

The existing Compare tab selects final validation or candidate engine results.
It displays the same saved PNG/JSON files the agent reads. Start still means the
legacy deterministic pipeline; there is no fake AI prompt box or hidden LLM loop.

## Initial implementation verification

The final available-environment suite passed **43 tests**, with **1 Blender runtime
integration test skipped** because no Blender executable was found. Tests cover CLI
candidate round-trips, measurement protection, stale base/report rejection, failure
rollback, OBJ/compound geometry, actual MJCF/USD read-back parity, package metadata,
original deterministic pipeline and UI regressions. This is not evidence that the
bpy worker has run successfully on this machine.

SO-101 regression preserved the original canonical scene and existing package.
A trial robot-color adjustment improved train MAE from 0.1335808611 to 0.1302392557
under shared clipping conventions; 4,157 structural checks passed. The test promoted
and rolled back the trial to verify lifecycle integrity. Its export was UNVALIDATED
because held-out object geometry evidence is absent. The clipping convention change
means this newly rendered baseline slightly differs from the old stored MAE.


## Installed Blender verification

Use `export REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender` before starting
Builder. Its child process removes host PYTHONPATH/PYTHONHOME/LD_LIBRARY_PATH/
LD_PRELOAD so the existing Isaac USD/MaterialX libraries cannot shadow Blender's
bundled libraries. This does not change the parent conda environment.

SO-101 actual Blender build → author → render → compare → sync → MuJoCo render →
validation → dual export → rollback completed. Structural parity passed 2,388
checks after primitive visual parts were joined into reusable OBJ meshes.
The color trial worsened Blender train MAE (0.240627 → 0.241465), so it was not
retained: promotion was tested only to exercise the transaction, then rolled back.
The original reference remains unchanged and the exported trial is UNVALIDATED.
This checks the toolkit data flow, not reconstruction quality acceptance.

Restricted Codex sandbox execution produced a PulseAudio mainloop permission error
and timed out after saving the blend, even with `-noaudio`. The successful Blender
integration checks ran outside that sandbox; normal terminal execution is the tested
path. Do not count the timed-out attempt as a successful integration test.

Installed-Blender full suite: **45 passed, 0 skipped** after environment isolation.


Multi-pose measured capture import, per-observation URDF/MJCF FK, shared calibration,
held-out candidate guards and portable export: [Capture workflow](MULTIPOSE_CAPTURE.md).


## SO-101 workflow authoring contract

The external Codex agent translates the user's task description into declarative
`scene.workflow` using schema `so101.scene-workflow/1`. Builder does not call an LLM
or infer a task from an image. Use the existing candidate edit operation:

```json
[{"op":"set_workflow","value":{
  "schema":"so101.scene-workflow/1",
  "support_surface":"bench",
  "observation_cameras":["front"],
  "real_camera_bindings":{"front":"front_camera"},
  "reset":{"support_object":"spawn_region","mode":"uniform","seed":0,
           "margin_m":0.01,"clearance_m":0.003,"separation_m":0.01,"yaw_rad":[0,0]},
  "physics":{"mass_kg":0.02,"static_friction":0.8,"dynamic_friction":0.8,
             "restitution":0,"provenance":"provisional"},
  "tasks":[{"id":"sort_apple","pick":"apple","place":"basket",
            "instruction":"Place the apple in the basket.",
            "success":{"relation":"inside_region_and_settled",
                       "bounds_m":[[-0.06,-0.05,-0.035],[0.06,0.05,0.055]],"max_speed_m_s":0.03}}],
  "provenance":{
    "tasks":{"source":"derived","status":"UNVALIDATED","evidence":["user task brief"]},
    "reset":{"source":"estimated","status":"UNVALIDATED","evidence":["candidate hypothesis"]},
    "success":{"source":"estimated","status":"UNVALIDATED","evidence":["candidate hypothesis"]},
    "physics":{"source":"unknown","status":"UNVALIDATED","evidence":[]}
  }
}}]
```

Replace every ID and numerical example from actual scene/task evidence. All IDs
must resolve to canonical objects/cameras. `pick` must be manipulable_object,
`place` receptacle, support_surface support_surface. One horizontal workspace-role
box defines the spawn region. Success bounds are in target-local metres. The
legacy `contained_and_settled` relation is only for round container collision.
Optional `object_physics` maps logical object IDs to mass_kg/static_friction/
dynamic_friction/restitution overrides and provenance. Optional `roles` opts
static objects into STATIC_SUPPORT/STATIC_GEOMETRY/VISUAL_ONLY collision semantics.
Unknown values stay unknown in canonical physics; provisional runtime overrides
must be explicitly labelled. Provenance groups tasks/reset/success/physics are
required; source is measured/calibrated/derived/optimized/estimated/unknown,
status UNVALIDATED/VALIDATED/NOT_APPLICABLE, evidence is a list of references.
Geometry acceptance never implies task or physics acceptance.

Procedure: import images/snapshots and brief → author geometry and role IDs →
create candidate → write these operations to edits.json →
`python -m app.cli candidate PROJECT edit NAME --edits edits.json` → render/evaluate
and promote with the existing gates → validate → export. Workflow changes are
included in scene signatures, so export requires a fresh validation report.
Schema validation runs during edit, render and export; manifest and SCENE.md now
include workflow metadata. The downstream adapter performs runtime-specific reset,
robot/controller and task contract validation. Hardware paths stay in SO-101 UI.
The package contains intent, not source demonstrations or a trained policy. New
objects require real successful demonstrations before annotation/datagen/training
can be validated. Never fabricate them or relabel synthetic smoke as real data.
