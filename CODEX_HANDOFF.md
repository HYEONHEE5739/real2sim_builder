# Real2Sim Builder 인수인계

최신 재개 결과: `../soarm101_lab/SCENE_REFINEMENT_HANDOFF.md` 최상단 참조.
`so101-scene1-paired-layout-20261010-b9e9cc4d`의 `train_surface_colors`가
모든 holdout image nonregression을 통과해 promote됐다. canonical은 이제 색상 개선 Scene.
export는 같은 project ID의 폴더이며 기존 `-cups-review`와 별개, SO101은 v3로 import했다.
Geometry/contact는 미검증이고 v2 컵 배치는 채택하지 않았다.
Wrist optical pose만 수정하면 housing이 시점을 가릴 수 있다. mount frame과 외형도
같이 변경한 후보를 검사해야 한다. 실제 API는 이를 자동으로 동기화하지 않는다.
`wrist_mount_focal_coupled`도 holdout 영상 악화로 REJECTED; 조인트나 원본 q는 미수정.
아래 중단/인계 문구는 과거 시점이며 사용자가 명시적으로 재개를 요청했다.

2026-10-10 실제 source 확인 기준. SO-101 실행/Adapter 상세는 `../soarm101_lab/CODEX_HANDOFF.md`.
기존 상세문서는 아래 경로를 참조하며 복사된 오래된 설명보다 실제 코드를 우선한다.

## 목적과 구조

독립 offline evidence-driven scene fitter / agent toolkit이다. 사진에서 임의 scene을
자동 완성하는 내부 AI는 없다. 외부 VS Code Codex가 입력 해석·초기 geometry·hypothesis를 작성하고
Builder의 numerical calibration/render/compare/candidate/export를 실행한다.
`app/cli.py`가 CLI/UI 진입점. `app/core/scene.py` canonical validation,
core/editing.py candidate operations, reconstruction/pipeline.py deterministic run,
calibration/ FK·camera fitting·Snapshot import, blender/ author/render/sync,
validation/ metrics/acceptance, exporters/ MJCF/USD/package 책임.
상세 구조 `docs/ARCHITECTURE.md`, 명령/절차 `docs/AGENTIC_TOOLKIT.md`.

## Scene→SO101

canonical scene + workflow → XML/USD/shared assets/manifest/SCENE.md/validation report export
→ sibling SO101 `real2sim/workspaces/builder.py`가 immutable 실행 Workspace로 변환한다.
Builder reference_robot snapshot 자체는 제어 가능한 로봇이 아니다. Adapter가 기존 SO101 articulation에
visuals와 camera/task/physics/reset를 연결한다. SO101은 새 object/camera ID를 metadata로 소비한다.
지원은 SO101 world/gripper camera + 기존 pick/place recipe 범위. 임의 robot/task 알고리즘은 미지원.
소비 절차 `docs/CONSUMING_SCENES.md`, 최신 상세는 sibling docs/real2sim/BUILDER_WORKSPACE.md.

## 계약과 검증 상태

`real2sim.scene/1`: m, right-handed Z-up, column-vector transforms, optical camera X right/Y down/Z forward.
값은 value/provenance/evidence로 구분한다. measured/calibrated/derived/optimized/estimated/unknown.
workflow schema `so101.scene-workflow/1`은 core/scene.py:validate_workflow에서 검증,
core/editing.py:set_workflow로 candidate에 작성, package exporter에서 canonical/manifest에 보존한다.
Support surface, observation camera IDs, real bindings, object physics, tasks/pick/place/instruction,
reset/success metadata와 tasks/reset/success/physics provenance를 명시한다.
사용자 brief를 자동 NLP로 변환하지 않는다. Codex가 evidence를 근거로 작성한다.
실측 없이 mass/friction을 physical truth로 표시하지 않는다. dynamics system identification과
recorded-action articulated physics replay는 구현/검증되지 않았다.

Snapshot schema `real2sim.snapshot/1`은 SO101이 수집하며 shared robot_model/calibration과 shot별
side/wrist/state/metadata/COMPLETE를 가진다. measured q와 commands 분리, host clocks 사용.
legacy_unverified joint mapping은 acceptance 제한으로 보존한다.
FK는 Snapshot마다 measured q로 robot을 pose하고 wrist는 base×FK×mount로 계산한다.
상세 `docs/MULTIPOSE_CAPTURE.md`, `docs/INPUTS.md`.
예전 문서의 continuous capture/import-reference 예제는 historical이며 새 수집은 import-snapshots.
옛 captures/workspace_001 경로는 이미 삭제되었을 수 있으므로 실행하지 않는다.

## CLI 실무 순서

Builder 디렉터리에서 기존 환경을 사용한다. `docs/LOCAL_RUN.md`는 GUI/USD 경로 설명이며
GPU 미지원 문구는 당시 검사 한정이다. SO101에서는 후속 실제 GPU/Isaac smoke가 통과했다.

```bash
export REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender
python -m app.cli capabilities
python -m app.cli inspect projects/so101-scene1-snapshot-reconstruction-2202744f
```

새 프로젝트: `new NAME`이 출력하는 실제 project 경로를 사용하고,
`add PROJECT /path/brief --kind brief`, `add ... --kind measurements`,
`import-snapshots PROJECT /path/session --scene-state static_001 --validation SHOT_IDS`.
서로 다른 scene-state를 정적 배치로 합치지 않는다. 가능하면 독립 session holdout.

기존 도구 반복 예:

```bash
python -m app.cli candidate "$PROJECT" create wrist_mount_next
python -m app.cli candidate "$PROJECT" edit wrist_mount_next --edits /absolute/edits.json
python -m app.cli candidate "$PROJECT" fit wrist_mount_next --target camera:wrist
python -m app.cli candidate "$PROJECT" render wrist_mount_next --engine blender
python -m app.cli candidate "$PROJECT" evaluate wrist_mount_next --engine blender --validation
python -m app.cli candidate "$PROJECT" evaluate wrist_mount_next --engine mujoco --renderer software-egl --validation
# 개선·nonregression·freshness 확인 후에만:
python -m app.cli candidate "$PROJECT" promote wrist_mount_next
python -m app.cli validate "$PROJECT" --engine blender
python -m app.cli export "$PROJECT"
```

Fit은 실제 landmarks·rank·train/holdout 조건이 있을 때만 가능하다. 임의 가짜 correspondence를
확정값으로 주지 않는다. 세부 edits schema와 blender-build/author/sync는 AGENTIC_TOOLKIT.md.
실패는 candidate reject, 필요하면 rollback. Promote는 DRAFT이지 ACCEPTED가 아니다.
`export --allow-unvalidated`는 명확히 UNVALIDATED 검토 package만 만든다.
UI Start/run은 deterministic loop. Agent 후보 도구는 run 없이 개별 실행 가능하다.

## 파일과 재개

실제 입력 `inputs/scene1/scene_info.md`와 참고사진.
실제 작업 `projects/so101-scene1-snapshot-reconstruction-2202744f/`.
기존 reference `projects/so101-reference-bb83b89f`는 보호한다.
current canonical `working/current_scene.yaml`; scratch/agent/<candidate>/candidate_scene.yaml,
candidate.json, fit.json, renders/<engine>/metrics.json,
previews/<index>_<camera>/{real,sim,overlay,difference}.png, posed/<index>/ 렌더 자료.
Blender workspace 위치는 candidate JSON/inspect에서 실제 경로를 확인한다.
package는 exports/<project-id>/scene.yaml, scene.xml, scene.usd, scene_manifest.yaml, SCENE.md,
shared assets, validation/report.json. Scene 수정 후 기존 export가 최신이라고 가정하지 않는다.
inspect/history/signature를 먼저 읽고 살아 있는 candidate부터 재개한다.

## 완료·미완료 및 다음 일

실측 SO101 scene1 제작·반복·export 및 SO101 import는 수행되어
sibling `outputs/real2sim/environments/scene1_builder/v1`에서 소비한다.
카메라 외형/컵 무늬와 wrist 정렬 개선이 있었으나 실물 완전 일치/물성 검증은 아니다.
사용자가 현재 Real/Sim 차이를 보고 추가 Snapshot을 수집하려는 단계다. 아직 새 세션 경로 미제공.
새 자료는 wrist 그리퍼 정렬을 우선하여 shared camera mount/side extrinsic/object pose를 순차 개선한다.
설치 변경으로 기존 extrinsic은 실제 검증 evidence 없으면 초기 추정이다. measured q는 고정한다.
원본 data/accepted scene을 덮어쓰기보다 candidate를 사용한다. validation 개선만 promote한다.

별도 synthetic metadata integration 실험은 sibling
`outputs/workflow_validation/metadata_adapter/paths.json`와 report.json.
새 fruit Builder project/export→SO101 import→MuJoCo/Isaac actual render/reset/success smoke,
UI camera/convert/head fixtures 검증. 실제 banana 사진 reconstruction 또는 성공 manipulation은 아니다.
Builder core/export/candidate/multipose 기록 30 pass/1 skip; 양 프로젝트 관련 합계144 pass/2 skip.
실물 Teleop/새 scene Source→성공 annotation/datagen→Qwen/ACT/SmolVLA 학습/rollout End-to-End 미검증.
Blender 검증 `docs/BLENDER_REGRESSION.json`; structural parity만으로 두 엔진 픽셀/contact 동일성 주장 금지.

## 환경·검사·인계

기존 Python `/home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python`, CPython3.11.
Blender `/home/hyeonhee/apps/blender/blender`. pip bpy 설치 불필요.
Qt는 sibling .venv-real2sim-ui, pxr는 기존 Isaac ext cache에 있으며 command-scoped 경로로만 연결한다.
정확한 LOCAL_RUN.md를 읽고 실제 설치 경로를 확인한다. 설치/버전 변경 없이 진행한다.

```bash
/home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python -B -m pytest tests/test_core.py tests/test_exporters.py tests/test_agent_toolkit.py tests/test_multipose.py -q -p no:cacheprovider
```

옵션 USD/Qt 검사는 기존 dependency 경로가 있어야 실행된다. skip을 PASS로 합치지 않는다.
SO101의 MuJoCo 검사는 pxr/Isaac import 프로세스와 분리한다. 최근 EGL developer 초기화 수정은
SO101 인수인계 참고; Builder source를 같은 이유로 무조건 바꾸지 않는다.

현재 이 Builder에는 Git 저장소가 없다. sibling SO101에는 113개 미커밋 status entry가 있었다.
Git clone만으로 두 프로젝트/ignored outputs를 복구할 수 없다. 두 폴더와 사용자 data를 통째로
안전하게 인계하고 현재 작업트리 diff/status를 보존한다. 임의 reset/clean/삭제/자동 commit 금지.
이 인수인계 작업은 문서만 작성하며 기존 코드·Scene·Snapshot·사용자 data를 바꾸지 않는다.

추가 기능(2026-10-10): import-paired는 기존 Snapshot importer를 확장하여 runtime_baseline을
보존하고 기존 Candidate 평가에 three-way diagnostics를 추가한다. `docs/PAIRED_CAPTURE.md` 참고.
SO101은 관측 저장만 수행한다. 최신 Source/프리뷰 변경은 sibling CODEX_HANDOFF.md의 추가 변경 절 참조.


## 최신 Scene 보정 인계 — 2026-10-10

현재 작업의 상세 인계는 `../soarm101_lab/SCENE_REFINEMENT_HANDOFF.md`이다.
위 본문의 “새 세션 미제공”은 과거 상태다. 최신 Pair 세션
`../soarm101_lab/outputs/real2sim/snapshots/snapshot_20261010_160851_00c94af5`
8쌍 모두 사용했다. 새 프로젝트는
`projects/so101-scene1-paired-layout-20261010-b9e9cc4d`.
`cups_latest_layout`, `cups_layout_white_paper`는 holdout nonregression 실패 후보다.
사용자가 UI에서 비교할 수 있게 후자의 candidate_scene.yaml을 명시적으로
UNVALIDATED review export했다. export ID는 project ID + `-cups-review`다.
`working/review_export.json`에서 정확한 source/export를 확인한다.
`working/current_scene.yaml`은 baseline이므로 검토 후보와 혼동하지 않는다.
SO101 Workspace는 `scene1_builder/v2`; v1/원본/기존 프로젝트는 보존했다.
XML/USD structural parity PASS, 실제 runtime 검사 범위는 SO101
`outputs/workflow_validation/paired_refinement_160851/layout_export_result.json`.
현재 사용자는 다른 계정으로 인계하므로 추가 fitting을 시작하지 않는다.
수치 fitting은 motor-to-URDF calibration 완료가 아니며 물성/실물 task는 미검증이다.

API 추가: core.capture.import_paired의 include_flagged_reason은 사용자가 명시적으로
모든 Pair를 쓰라고 한 경우 soft quality exclusion을 override하며 warnings/raw q/hash는
유지한다. 현재 CLI에는 이 옵션이 없다. 테스트는 SO101 test_snapshots.py에 있다.
/tmp 진단 scripts는 환경 재시작으로 소실될 수 있다. project/validation 결과를 기준으로
재개하며 placeholder correspondence를 measured로 쓰거나 검사를 우회하지 않는다.
