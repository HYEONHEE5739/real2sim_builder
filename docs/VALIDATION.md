# 구현 검사 결과

검사일: 2026-10-07. 기존 conda/Qt/USD 설치를 읽기 전용으로 사용했으며 dependency 설치/업데이트를 수행하지 않았습니다.

## 자동 검사

`QT_QPA_PLATFORM=offscreen python -m pytest -q`: **26 passed**.

| 검사 | 확인 내용 |
|---|---|
| canonical / project | metre frame graph, 불완전 근거 거절, 경로 탈출 차단, atomic state, pause/stop/resume |
| camera / geometry | measured landmark로 카메라 위치 오차 보정, holdout 오차, calibrated corners로 unknown object pose 복원 |
| physics | 합성 passive sliding에서 마찰 회복, 독립 trajectory 오차, mass 미관측 거절 |
| exporters | 열린 bin collision, 실제 MJCF compile, USD pose/camera/단위 파서 로딩 |
| autonomous pipeline | 알려진 기준 장면 ACCEPTED, 색상 오류 자동 반복 보정, train-only candidate 선택 |
| independent validation | global similarity만으로는 ACCEPTED 불가 |
| package | 전체 패키지 이동 후 재로딩, 원본 CAD 제거 후 asset 로딩, hash 변조 감지 |
| inputs | 영상 frame/timestamp 추출, 측정/보정 provenance, mask 등록, URDF FK, MJCF/USD snapshot |
| depth / rectification | partial point cloud의 hidden extent 추정 금지, full bounds로 derived dimensions, 원본 보존/재개 중복 보정 방지 |
| Qt | 4개 화면, 별도 worker 경로, 실행 중 프로젝트 전환 차단 |

합성 기준 장면의 실제 MuJoCo 렌더를 관측 fixture로 사용합니다. 이는 pipeline/좌표/export/optimizer 동작 검사이며 **새로운 실제 장면의 복원 정확도를 입증한 것은 아닙니다.**

## SO-101 실제 reference

기존 published workspace `workspace_001/v2`와 실제 `capture_000001` side/wrist를 읽었습니다. URDF/STL/FK와 profile의 scene 관련 필드만 가져왔고 task/policy 코드는 사용하지 않았습니다.

프로젝트: `projects/so101-reference-bb83b89f`.

| camera | RGB MAE [0,1] | edge IoU |
|---|---:|---:|
| side | 0.13344 | 0.04654 |
| wrist | 0.15076 | 0.00082 |

현재 상태는 **NEEDS_MORE_DATA**입니다. 상속한 calibration 및 FK를 독립적인 실제 ground truth로 간주하지 않았습니다. table, cube_red/green/blue, cup_a_visual/b_visual 각각의 holdout 물체 mask 또는 측정된 비공선 corner가 필요합니다. 현재 비교는 위치/투영/배경·재질의 오차를 포함하며, 장면을 실물과 일치한다고 승인하지 않았습니다.

- 실제 MuJoCo software EGL에서 side/wrist RGB와 비교/overlay/difference를 생성했습니다.
- 후보 MJCF: 실제 compile 성공, **555 geoms**.
- 후보 USD: 실제 `pxr.Usd.Stage.Open` 성공, **649 prims**.
- 후보 package status: **UNVALIDATED**. UI의 승인 결과 경로로 표시하지 않습니다.
- profile/state/real image 원본 SHA-256이 import 전후 같았습니다.
- source hashes와 수치 증거: [so101_validation.json](so101_validation.json).
- 비교 이미지: `projects/so101-reference-bb83b89f/working/validation/previews/`.
- 후보 결과: `projects/so101-reference-bb83b89f/exports/so101-reference-bb83b89f/`.

## 미검증 범위

NVIDIA-SMI는 이 실행 환경에서 driver 접근 오류를 반환했습니다. **Isaac Sim 앱에서의 실제 GPU 렌더/PhysX, EGL GPU 경로, OSMesa 경로는 아직 검증되지 않았습니다.** USD parser 로딩을 Isaac Sim 런타임 검사로 대체했다고 주장하지 않습니다. 문서의 consuming 절차로 실환경에서 열어 확인해야 합니다.

실제 수동 운동의 마찰 식별, 원본 texture UV 복원, 자동 조명 역추정, 움직이는 multi-frame pose tracking, 임의 물체의 학습 기반 semantic/3D mesh 생성은 현재 지원하지 않습니다. robot 모델은 reference snapshot이므로 downstream 환경은 articulation/control을 별도로 추가해야 합니다.
