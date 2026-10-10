# 다른 robotics project에서 패키지 사용하기

export 디렉터리 전체를 복사합니다. 원래 SO-101 repo나 builder의 working/scratch/input은 실행에 필요하지 않습니다. `scene.yaml`은 canonical, `scene_manifest.yaml`은 engine mapping과 provenance 계약, `SCENE.md`는 설명입니다.

1. manifest의 `status`를 확인합니다. `UNVALIDATED`를 검증 완료 환경으로 취급하지 마세요.
2. `validation/report.json`의 camera·임계값·holdout·engine loader 결과·물리 비교 범위를 확인합니다.
3. `uncertainties`와 physics_defaults를 확인합니다. unknown mass는 static이고 friction default는 미검증입니다.
4. `python -m app.cli verify PACKAGE`로 파일 hash/상대 asset/schema를 확인합니다.
5. object ID·semantic role·pose·frame·치수와 engine mapping을 사용해 소비하는 프로젝트에서 robot/task를 구현합니다.

## MuJoCo

```python
import mujoco
model = mujoco.MjModel.from_xml_path('/path/to/package/scene.xml')
data = mujoco.MjData(model)
mujoco.mj_forward(model, data)
```

mapping은 canonical object ID→body name입니다. camera는 canonical ID와 같은 이름입니다. physics timestep은 scene.xml의 option에 있습니다. visual과 collision은 별도 geom group이며 reference_robot collision은 비활성입니다. 양의 질량이 있는 manipulable object만 freejoint를 가집니다. robot reference는 주어진 상태의 mesh snapshot이며 제어 가능한 robot이 아닙니다.

## Isaac Sim / Isaac Lab

Isaac Sim에서 `/path/to/package/scene.usd`를 열거나, 소비하는 stage의 Xform에 reference합니다. defaultPrim은 `/Scene`, metersPerUnit=1, upAxis=Z입니다. object mapping은 `/Scene/<object-id>`, camera는 `/Scene/<camera-id>`입니다. 표준 USD Physics의 rigid body/mass/collision/material을 생성합니다.

```python
from pxr import Usd, UsdGeom
stage = Usd.Stage.Open('/path/to/package/scene.usd')
assert stage.GetDefaultPrim()
assert UsdGeom.GetStageMetersPerUnit(stage) == 1.0
```

이 코드는 USD parser 검사입니다. Isaac renderer/PhysX/robot articulation 실행은 소비하는 환경에서 확인해야 합니다. builder는 Isaac Lab EnvCfg/task/reward/reset을 생성하지 않습니다.

## 좌표와 asset 계약

길이는 m, world는 오른손 +Z입니다. canonical transform은 `T_parent_child`, column vector입니다. 부모 frame을 따라 world pose를 구합니다. optical camera는 X right/Y down/Z forward이고, USD/MuJoCo의 OpenGL camera axes로 exporter에서 이미 변환했습니다. engine camera에 다시 같은 변환을 적용하지 마세요.

asset은 상대 path와 SHA-256입니다. source의 원래 경로는 출처 기록이며 runtime 의존성이 아닙니다. asset을 변경하면 package hash도 달라집니다. 변경된 asset/model을 별도 검증 없이 원래 ACCEPTED 결과로 배포하지 마세요.

container는 열린 상단과 별도 floor/wall의 primitive collision입니다. 화면 오차를 맞추기 위해 collision 치수를 수정하지 않습니다. USD와 MuJoCo의 default contact/inertia, renderer lighting/UV 대응까지 동일한 것은 아닙니다.


Multi-pose measured capture import, per-observation URDF/MJCF FK, shared calibration,
held-out candidate guards and portable export: [Capture workflow](MULTIPOSE_CAPTURE.md).
