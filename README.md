# Real2Sim Builder

실제 작업 공간의 이미지·동영상과 측정/보정 자료를 받아 **독립적인 시뮬레이션 장면 패키지**를 만드는 첫 버전입니다. 기존 SO-101 프로젝트의 실행 코드, task, policy를 import하지 않습니다. 로봇 제어·teleoperation·Mimic·datagen·학습·평가는 이 프로젝트의 범위 밖입니다.

하나의 `working/current_scene.yaml`에서 MuJoCo MJCF와 Isaac용 USD를 생성합니다. MuJoCo에서 직접 렌더하고 실제 영상과 비교한 뒤, 근거가 있는 카메라/물체 위치·색상·수동 운동 마찰만 보정합니다. 결과는 `ACCEPTED`, `NEEDS_MORE_DATA`, `FAILED` 중 하나입니다.

## 실행

Python 3.10 이상입니다. 이미 의존성이 있는 환경에서는 설치 없이 프로젝트 루트에서 실행할 수 있습니다.

```bash
cd /home/hyeonhee/soarm_isaaclab/real2sim-builder
python -m app.cli --help
python -m app.cli ui
```

UI의 **New Scene / Inputs → Run → Compare → Result**를 사용합니다. 영상과 보조 자료를 넣고 Start를 한 번 누르면 워커가 실행됩니다. Run의 Worker Python은 MuJoCo/NumPy 등이 설치된 Python 경로를 지정합니다. UI 프로세스는 시뮬레이터를 import하지 않습니다. Pause/Resume/Stop과 종료 후 재시작을 지원합니다.

기존 conda 패키지는 자동 설치하거나 변경하지 않습니다. 기본 라이브러리는 NumPy, SciPy, Pillow, PyYAML, OpenCV이고, 렌더에는 MuJoCo, UI에는 PyQt6, 승인된 양쪽 엔진 패키지의 USD 로딩 검증에는 `pxr`가 필요합니다. MJCF/USD 모델 입력과 STL 이외 mesh에는 trimesh가 필요합니다.

설치가 필요하다면 **별도 환경**을 권장합니다. 모든 선택 의존성은 `pyproject.toml`에 정의되어 있습니다. 기존 환경에 패키지 등록만 하는 명령은 아래와 같으며, 없는 라이브러리를 추가해 주지는 않습니다.

```bash
python -m pip install --no-deps --no-build-isolation -e .
```

이 컴퓨터의 기존 설치를 변경하지 않고 사용하는 정확한 명령은 [LOCAL_RUN.md](docs/LOCAL_RUN.md)에 있습니다.

## CLI로 새 장면 만들기

`new`가 출력하는 프로젝트 경로를 이후 명령에 사용합니다. `validation` 입력은 학습/보정에 쓰지 않는 독립적인 관측이어야 합니다.

```bash
python -m app.cli new "Factory B"
python -m app.cli add projects/factory-b-<id> /data/side.png --camera side --split train
python -m app.cli add projects/factory-b-<id> /data/left.png --camera left --split validation
python -m app.cli add projects/factory-b-<id> /data/cameras.yaml --kind calibration
python -m app.cli add projects/factory-b-<id> /data/measurements.yaml --kind measurements
python -m app.cli run projects/factory-b-<id> --renderer software-egl
python -m app.cli status projects/factory-b-<id>
```

동영상은 `--kind video`로 넣습니다. 로봇은 `--kind robot --joints joint_states.json`으로 추가하며, 주어진 상태의 **참조 형상/FK 스냅샷**으로만 사용합니다. Joint states는 모델 기준 rad/m입니다. 모델 actuator나 정책을 실행하지 않습니다. 입력 계약과 검증 마스크/랜드마크 작성 방법은 [INPUTS.md](docs/INPUTS.md)를 참조하세요.

렌더러는 `software-egl`(Mesa 소프트웨어), `egl`(설치된 EGL 장치), `osmesa`를 지원합니다. 모드 변경은 새 워커에서 수행합니다. OSMesa는 OS 라이브러리가 설치되어 있어야 합니다. GPU VRAM/FPS와 Isaac 렌더 품질을 보장하는 성능 벤치마크는 이 버전의 검사에 포함되지 않습니다.

## 결과와 폴더

```text
app/
  core/           scene 계약, 입력 복사, 프로젝트 상태
  calibration/    카메라·물체 pose, 참조 FK, depth, 수동 운동 식별
  reconstruction/ 분석 및 자동 재시도
  validation/     렌더링, 비교 영상과 수치
  exporters/      canonical → MJCF / USD / 장면 패키지
  ui/             프로젝트 관리 및 워커 진행 표시
projects/<scene-id>/
  input/                  프로젝트 내부에 복사한 입력/asset
  working/current_scene.yaml
  working/state.json
  working/validation/
  scratch/                덮어쓸 수 있는 임시 산출물
  history.jsonl
  exports/<scene-id>/
    scene.yaml
    scene.xml
    scene.usd
    scene_manifest.yaml
    SCENE.md
    assets/
    validation/
    source/reconstruction.yaml
```

승인된 장면은 자동 export합니다. `NEEDS_MORE_DATA`이면 state의 `needs`에 다음에 필요한 근거와 이유가 표시됩니다. 완성된 형상이 있을 때만 검토용 후보를 `export --allow-unvalidated`로 내보낼 수 있으며, 그 패키지의 상태는 반드시 `UNVALIDATED`입니다. UI Result는 승인된 결과만 여는 경로를 제공합니다.

```bash
python -m app.cli verify projects/<id>/exports/<id>
python -m mujoco.viewer --mjcf projects/<id>/exports/<id>/scene.xml
```

Isaac Sim에서는 `scene.usd`를 엽니다. 소비자가 구현할 로봇 articulation, reset, observations/actions, task는 분리되어 있습니다. [패키지 사용 계약](docs/CONSUMING_SCENES.md)을 먼저 읽으세요.

## 검증 결과와 현재 한계

- 자동 테스트 **26개 통과**: 실제 소프트웨어 MuJoCo 렌더, USD 파서 로딩, 카메라/물체 보정, 자동 재시도, 프로젝트 재개, 패키지 이동/무결성, 로봇 모델 snapshot, 왜곡 보정, depth/cloud의 가려진 크기 처리, Qt UI.
- 알려진 합성 기준 장면은 `ACCEPTED`가 되고 두 엔진 패키지를 생성합니다. 합성 장면 검사는 실제 환경 정확도 검증을 대체하지 않습니다.
- 기존 SO-101 실제 side/wrist 캡처를 읽기 전용으로 가져와 두 엔진 파일과 비교 영상을 생성했습니다. **현재 `NEEDS_MORE_DATA`이며 실제 사진과 일치하는 장면으로 승인하지 않았습니다.** 필요한 추가 근거와 수치는 [VALIDATION.md](docs/VALIDATION.md)에 있습니다.
- USD는 `pxr.Usd.Stage.Open`으로 검증했습니다. 현재 실행 환경에서 NVIDIA 드라이버가 접근되지 않아 Isaac Sim 앱의 GPU 렌더/PhysX까지 검증하지 못했습니다.

첫 버전의 자동 복원은 측정된 primitive/mesh, 보정된 카메라, 대응점·마스크·명시적 depth 근거를 이용하는 결정론적 방식입니다. RGB 한 장으로 임의 물체의 의미·숨은 형상·실제 질량을 생성하는 학습 모델은 포함하지 않습니다. 관측으로 분리할 수 없는 값은 요청하거나 `estimated`/`unknown`으로 남깁니다. texture의 UV는 단순 투영이며, 원본 mesh UV 복원과 조명 역추정은 미지원입니다. 수동 운동 식별은 알려진 질량/지지면 물성과 시간·초기속도가 있는 미끄럼 마찰에 한정됩니다.

## 개발 검사

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

전체 검사는 MuJoCo, PyQt6, pxr, trimesh가 있는 환경에서 실행합니다. Qt/pxr가 없으면 해당 입력/로더 검사는 skip되며, 승인 패키지 생성에는 실제 USD 로더가 필요합니다. 구조와 상태 흐름은 [ARCHITECTURE.md](docs/ARCHITECTURE.md)에 정리했습니다.

## Codex agent toolkit

See [agent workflow and CLI](docs/AGENTIC_TOOLKIT.md) for candidate editing,
optional Blender background authoring/rendering, explicit canonical synchronization,
MuJoCo/ USD structural parity, promotion/rollback, and final validation/export.
`python -m app.cli capabilities` reports the existing environment without installing
anything. Blender runtime integration is not validated on a machine without Blender;
see [actual SO-101 regression results](docs/AGENTIC_REGRESSION.json).


Snapshot-based measured capture import (real2sim.snapshot/1), per-observation URDF/MJCF FK, shared calibration,
held-out candidate guards and portable export: [Capture workflow](docs/MULTIPOSE_CAPTURE.md).
