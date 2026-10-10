# 입력 계약

CLI와 UI는 같은 importer를 사용합니다. 파일은 project/input에 복사하며 원본은 수정하지 않습니다. scene/asset SHA-256을 보존합니다. 모든 길이·XYZ/depth는 **m**, robot revolute 상태는 **rad**입니다. 세계는 오른손 +Z up, pose는 column vector의 `T_parent_child`, 카메라는 +X right/+Y down/+Z forward입니다.

## 이미지 / 동영상

```bash
python -m app.cli add PROJECT /data/side.png --camera side --split train
python -m app.cli add PROJECT /data/left.mp4 --kind video --camera left --split validation
```

EXIF orientation과 해상도를 확인합니다. 동영상은 기본 최대 12개 프레임을 균일 sampling하고 거의 같은 프레임을 건너뜁니다. 각 프레임 timestamp를 보존합니다. train/validation은 **동영상 전체 기준으로** 나눕니다. 같은 영상을 일부 train, 일부 validation으로 재등록하지 마세요. calibration resolution이 입력 resolution과 다르면 K를 명시적으로 조정해야 합니다.

아직 입력이 RGB뿐이면 색 영역을 inventory로 기록하지만, metric scale과 camera pose 및 숨은 물체 형상은 확정하지 않습니다. `NEEDS_MORE_DATA`에서 필요한 최소 측정/보정 데이터를 안내합니다.

## 측정 / calibration YAML

측정은 `--kind measurements`, 카메라 보정은 `--kind calibration`입니다. bare 숫자/행렬은 각각 measured/calibrated로 저장합니다. 추정값은 `{value: ..., provenance: estimated, evidence: [...]}`로 명시하세요. 허용 provenance는 measured/calibrated/derived/optimized/estimated/unknown이고 `value: null`은 unknown이어야 합니다.

측정 파일 예:

```yaml
units: m
objects:
  - id: table
    role: support_surface
    shape: box
    dimensions: [1.0, 0.8, 0.04]
    pose:
      - [1, 0, 0, 0]
      - [0, 1, 0, 0]
      - [0, 0, 1, -0.02]
      - [0, 0, 0, 1]
    color: [0.5, 0.5, 0.5]
  - id: bin
    role: receptacle
    dimensions: [0.20, 0.15, 0.10]
    pose:
      - [1, 0, 0, 0.20]
      - [0, 1, 0, 0]
      - [0, 0, 1, 0.05]
      - [0, 0, 0, 1]
    visual: {type: container, wall: 0.005}
    collision: {type: container, wall: 0.005}
```

상자 중심 pose/full dimensions를 사용합니다. table top은 위 예에서 Z=0입니다. container는 중심 pose, full dimensions, 벽 두께를 사용하며 열린 상단과 별도 floor/wall collision을 생성합니다. round cup은 geometry에 `round: true`, 선택적으로 `bottom_diameter_m`를 넣습니다.

카메라 파일 예(아래는 좌표 계약 예시이며 실제 calibration 값으로 바꿔야 합니다):

```yaml
units: m
cameras:
  - id: side
    frame: world
    resolution: [640, 480]
    K: [[500, 0, 320], [0, 500, 240], [0, 0, 1]]
    distortion: [0, 0, 0, 0, 0]
    pose:
      - [1, 0, 0, 0]
      - [0, -1, 0, 0]
      - [0, 0, -1, 1]
      - [0, 0, 0, 1]
```

`frames`는 key별 `{parent: world, transform: 4x4}`입니다. metadata는 객체 ID 기준 merge합니다. 완전한 canonical YAML은 `--kind scene`으로 넣습니다. 기본 K는 zero-skew OpenCV pinhole이고 4/5/8/12/14 distortion 계수를 지원합니다. 카메라 intrinsic이나 단위가 없는 데이터는 임의 fovy/scale로 채우지 않습니다.

## 랜드마크 / 마스크

동일 metadata에 아래 목록을 추가할 수 있습니다.

```yaml
units: m
landmarks:
  - camera: side
    frame: world
    point_m: [-0.5, -0.4, 0]
    uv: [123.0, 245.0]
    split: train
  - camera: left
    object: block
    point_m: [-0.03, -0.03, 0.03]
    uv: [178.0, 92.0]
    split: validation
masks:
  - image: left.png
    object: block
    path: left_block_mask.png
```

カメラ PnPには4点以上の非共線 metric world pointsが必要です。 `object`がある point_m は物体座標系です。既知寸法の measured/derived local cornersと校正済みカメラで未確定の object poseを求めます。URDF/FK link座標は `frame: robot_link_<link>` を使えます。

maskは入力と同解像度の白黒 PNG、非ゼロが対象物です。 `image`は metadata 相対パスで元の画像を指定するか、evidenceのproject内pathを指定します。先に画像を登録してください。マスクのtrain/validationは対応画像から決定します。

独立検証の物体ごとに1つの見えるmask、または4点以上非共線cornersを用意します。table/object/binの全体を global image scoreだけで承認しません。mask optimizerはtrainだけを使います。

## CAD / robot snapshot

meshはcanonical `assets`と`visual: {type: mesh, asset: ID}`で指定します。 assets entryは `{path: relative/to/scene/file.stl}`。 metadata importerではファイル基準相対パス、canonical importerではそのディレクトリ内だけを参照します。textureもassetsで指定しvisual.geometryの`texture: ASSET_ID`を使えます。PNG/JPEGに対応します。STLに単位metadataはないため**既にmであること**を確認し、異なる単位は明示的な mesh scaleを与えます。元のSTLを修正しません。

```bash
python -m app.cli add PROJECT /models/robot.urdf --kind robot --joints /data/joints.json --base /data/base.json
```

joints JSONはモデルjoint名→rad/mのmap。base JSONはworld→robot_baseの4×4です。URDFの全非fixed jointにstateが必要です。package:// meshは入力側で解決してください。MJCFはscalar hinge/slide jointsまたはstaticモデル、USDはbaked poseを対象とします。free/ball joint stateとUSD articulation drive実行は未対応です。外観のsnapshotを生成しcollisionは無効です。

## depth / point cloud / actions / passive motion

metadataに以下を追加できます。NPY/単一配列NPZ/text XYZを読み、有限値のみ使用します。点群は対象物だけにsegmentation済みである必要があります。

```yaml
units: m
point_clouds:
  - path: block_xyz.npy
    object: block
    frame: world
    split: train
    full_bounds: false
depths:
  - path: depth_m.npy
    camera: side
    object: block
    mask: block_mask.png
    split: train
    full_bounds: false
```

depthはカメラと同解像度、optical Z距離です。rectified RGB/Kと一致したdepthを使います。boundsは診断値として記録します。両側の外面を観測したことを示す `full_bounds: true` のboxだけ、unknown/estimated dimensionsをderivedに更新します。単一表面から隠れた厚みを推測しません。world object orientationが不明なら追加根拠を求めます。

`actions`の記録はtimestamp等のlineageとして保存するだけで、controllerやtaskを実行しません。物理比較は `motions`に object/support/times_s/positions_world_m/initial_velocity_m_s/split、任意の `fit_parameters: [friction]`を指定する受動的な滑りに限定します。known mass、known support friction、独立validation trajectoryが必要です。慣性・damping・任意action sequenceの逆同定は未対応です。


Multi-pose measured capture import, per-observation URDF/MJCF FK, shared calibration,
held-out candidate guards and portable export: [Capture workflow](MULTIPOSE_CAPTURE.md).
