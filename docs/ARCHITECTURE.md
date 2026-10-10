# 구조와 실행 책임

진입점은 `app.cli:main` 하나입니다. `python -m app.cli`와 설치된 `real2sim-builder` 명령은 같은 함수를 실행합니다. UI는 동일 CLI를 별도 Python 워커로 실행합니다. 특정 장면용 launcher, 기존 SO 작업별 script, 별도 엔진별 profile 계열은 없습니다.

```text
CLI / Qt 프로젝트 관리자
 → core.Project: 입력/상태/history, pause/resume/stop
 → core.evidence: 원본을 읽고 프로젝트 내부에 content hash로 복사
 → reconstruction.pipeline.run
    ANALYZE          영상 sampling / 색 영역 inventory
    CAMERA & SCALE   metric 랜드마크 카메라 PnP + bounded least squares
                     calibrated camera + measured corners → unknown object pose
                     segmented metric depth/cloud → 관측 bounds
    GEOMETRY         scene schema / frame graph / collision 검증
    VISUAL           canonical에서 실제 offscreen rendering
    PHYSICS          finite passive step, 조건을 만족한 운동의 friction fit
    VALIDATION       real/sim 비교 + 독립 관측의 corners/masks/motion
      RETRY          train-only object color response 수정 → 재렌더
      NEEDS_MORE_DATA 최소 부족 근거와 이유 기록
      FAILED         예외/반복 예산 소진 기록
    EXPORT           package 작성 + MJCF compile + USD loader 검증
      ACCEPTED       상대 export 경로와 검증 범위 기록
```

`core.scene`이 단일 계약입니다. `exporters.geometry.parts`에서 box/sphere/cylinder/mesh/open container의 공통 형상을 분해하고 각 exporter가 같은 결과를 사용합니다. USD에서 MJCF로 변환하지 않습니다. 엔진 이름은 manifest의 mapping에만 구체적으로 나타납니다.

`calibration.robot`은 URDF FK 또는 MJCF/USD의 주어진 pose를 참조 mesh로 복사합니다. articulation/control을 생성하지 않습니다. import 시 joint state의 의미와 source 단위가 필요합니다. `core.evidence.import_reference`는 이전 published profile/URDF/STL/실제 capture의 scene 관련 필드만 읽습니다. task.json, policy, Mimic config를 읽지 않습니다.

## 보정과 검증 경계

- metric scale을 pixel-only 관측으로 임의 결정하지 않습니다.
- measured/calibrated object pose는 object fitting으로 덮어쓰지 않습니다.
- uncertain object pose는 camera anchor에 쓰지 않아 camera/object 동시 이동의 gauge를 피합니다.
- 렌즈 왜곡은 원본 media/K/계수를 보존하고 deterministic rectification으로 비교 영상·마스크·랜드마크에 동일 적용합니다.
- 깊이의 관측 bounding box는 전체 물체 bounding box가 아닙니다. opposing-face coverage가 명시된 box만 unknown dimension을 derived로 채웁니다.
- validation 이미지/마스크/랜드마크/운동은 optimizer 입력에 쓰지 않습니다. candidate 선택은 train MAE 개선만으로 합니다.
- support/manipulable/receptacle마다 독립 물체 mask 또는 4개 이상 비공선 corner가 있어야 합니다. 화면 전체의 색이 비슷하다는 이유만으로 승인하지 않습니다.
- unknown mass는 static으로 export합니다. default friction은 측정된 물성으로 기록하지 않습니다.
- ACCEPTED는 보고서에 명시된 기하/영상 및 제공된 수동 운동 범위입니다. 실제 robot task 성공이나 정책 성능을 뜻하지 않습니다.

현재 영상 프레임은 기록된 로봇 reference pose/물체 pose 한 장면에 대응해야 합니다. 움직이는 물체의 서로 다른 timestamp pose 추적 및 automatic multi-view feature matching은 구현하지 않았습니다. 동영상에서 자동 추출한 timestamp와 추가 actions는 입력 lineage로 보존되며, actions를 실제 제어로 실행하지 않습니다.

## 저장과 복구

JSON/YAML은 임시 파일에 fsync 후 atomic replace합니다. current_scene 하나를 저장하고 history.jsonl에는 stage/iteration/decision/metrics를 append합니다. run.lock은 PID로 동시 reconstruction을 차단하며, 죽은 프로세스의 lock만 재사용합니다. Pause/Stop은 worker checkpoint에서 적용됩니다. 복귀 시 같은 current_scene에서 다시 단계 검증을 수행합니다.

scratch와 중간 비교 영상은 덮어쓸 수 있습니다. export는 임시 package 디렉터리에서 검증 후 교체합니다. 원본 입력과 기존 reference repository는 변경하지 않습니다. `source`의 원래 경로는 lineage이며 package 실행에 필요하지 않습니다. 런타임 asset 참조는 전부 package 상대 경로입니다.

## API 근거

엔진 바인딩의 최상위 import는 rendering/model snapshot/export loader 내부에 한정합니다.

- [MuJoCo XML reference](https://mujoco.readthedocs.io/en/3.3.1/XMLreference.html): optical→OpenGL 카메라 변환, focalpixel/principalpixel/sensorsize 및 collision geom.
- [OpenUSD transforms](https://openusd.org/dev/tut_xforms.html): USD row-vector transform 변환.
- [OpenUSD rendering guide](https://openusd.org/dev/user_guides/render_user_guide.html): USD camera/material 표현.

Isaac Sim용 산출물은 표준 USD Physics schema입니다. simulator가 제공한 기본 contact/inertia 처리의 엔진 간 물리 일치는 검증되지 않았습니다.

## Agent toolkit extension (2026-10-08)

`core/candidates.py` owns proposal isolation, asset promotion and rollback;
`core/editing.py` owns schema-aware inferred edits. `blender/backend.py` is the
optional executable/JSON bridge; `blender/worker.py` runs only inside bpy.
`core/cameras.py` shares the optical/render frame conversion and clipping.
`validation/parity.py` reads MJCF/USD back and checks against canonical geometry.
The single existing CLI exposes these tools. The UI only monitors their outputs.

Codex selects hypotheses externally. No LLM framework or dependency installer was
added. The legacy deterministic `run` remains available and its acceptance/export
now also runs structural parity. Unvalidated exports require fresh signatures too.
Detailed commands, supported Blender synchronization scope, unavailable capability
behavior and recovery limitations: [AGENTIC_TOOLKIT.md](AGENTIC_TOOLKIT.md).


Snapshot-based measured capture import (real2sim.snapshot/1), per-observation URDF/MJCF FK, shared calibration,
held-out candidate guards and portable export: [Capture workflow](MULTIPOSE_CAPTURE.md).
