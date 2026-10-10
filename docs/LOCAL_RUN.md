# 현재 컴퓨터에서 설치 변경 없이 실행

구현/검사에 사용한 Python은 기존 `lerobot-arena` 환경입니다. 새 패키지를 설치하거나 conda 버전을 변경하지 않았습니다. Qt와 USD 바인딩은 이미 설치된 라이브러리의 경로만 추가했습니다. 기존 프로젝트의 Python source나 launcher는 실행하지 않습니다.

```bash
cd /home/hyeonhee/soarm_isaaclab/real2sim-builder

# 기존 안내를 따라 export한 값이 남았다면 이 터미널에서 제거합니다.
unset PYTHONPATH PYTHONHOME

# Qt/USD bindings의 경로는 아래 GUI 명령에만 적용합니다. shell에 export하지 않습니다.
env \
  REAL2SIM_WORKER_PYTHON=/home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python \
  REAL2SIM_USD_PYTHONPATH=/home/hyeonhee/miniconda3/envs/lerobot-arena/lib/python3.11/site-packages/isaacsim/extscache/omni.usd.libs-1.0.1+69cbf6ad.lx64.r.cp311 \
  PYTHONPATH="$PWD:/home/hyeonhee/soarm_isaaclab/soarm101_lab/.venv-real2sim-ui/lib/python3.11/site-packages" \
  LD_LIBRARY_PATH="/home/hyeonhee/miniconda3/envs/lerobot-arena/lib/python3.11/site-packages/isaacsim/extscache/omni.usd.libs-1.0.1+69cbf6ad.lx64.r.cp311/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  /home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python -m app.cli ui
```

GUI의 PYTHONPATH에 넣은 외부 venv의 site-packages는 worker에 전달하지 않습니다. worker는 선택한 Python의 NumPy/Pinocchio 등을 사용하고, `REAL2SIM_USD_PYTHONPATH`가 있을 때만 명시적인 pxr 바인딩 경로를 추가합니다. 기존 Workflow UI를 같은 터미널에서 실행해도 위 `env` 설정은 남지 않습니다. 기존 conda의 NumPy를 downgrade/upgrade할 필요가 없습니다.


다른 컴퓨터나 독립 환경에서 설치된 PyQt6/pxr가 있다면 이 경로 설정은 필요 없습니다. 위 경로는 엔진 라이브러리가 CPython 3.11용이므로 다른 Python 버전에 그대로 적용하지 마세요. GUI를 사용하려면 실제 desktop display가 필요합니다.

재검사 명령:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q  # 자체 환경에 PyQt6/pxr가 설치된 경우
python -m app.cli status projects/so101-reference-bb83b89f
python -m app.cli verify projects/so101-reference-bb83b89f/exports/so101-reference-bb83b89f
```

기존 SO 실제 캡처를 다시 가져올 때만 reference 경로를 사용합니다. 프로젝트에는 이미 복사된 입력과 패키지가 들어 있어 재-import는 필수가 아닙니다.

```bash
python -m app.cli import-reference projects/so101-reference-bb83b89f \
  --workspace /home/hyeonhee/soarm_isaaclab/soarm101_lab/outputs/real2sim/environments/workspace_001/v2 \
  --capture /home/hyeonhee/soarm_isaaclab/soarm101_lab/outputs/real2sim/captures/session_20260919_121858_8945750b43f24e6e8ccc79854fd84182/capture_000001
python -m app.cli run projects/so101-reference-bb83b89f --renderer software-egl
```

이 사례의 현재 상태는 `NEEDS_MORE_DATA`입니다. 실제 검증 mask/corners를 추가해 재실행하면 같은 current_scene에서 이어갑니다. 승인되지 않은 후보를 수동 검토하려면 아래 명령으로 export합니다.

```bash
python -m app.cli export projects/so101-reference-bb83b89f --allow-unvalidated
```

`egl` GPU rendering과 Isaac Sim 런타임은 이 검사 환경에서 NVIDIA 드라이버가 접근되지 않아 실행을 보증하지 않습니다. `software-egl`은 실제 두 카메라 RGB로 검증했습니다. OSMesa는 선택 경로만 제공하며 이 컴퓨터에서 별도 실행 검증하지 않았습니다.

Agent toolkit commands: `python -m app.cli capabilities`, `inspect`, `candidate`,
`validate`, `rollback`. Blender selection is `REAL2SIM_BLENDER=/path/to/blender`.
No automatic installation takes place. For direct CLI USD parity, add the existing
USD binding path above to `PYTHONPATH` (the GUI-only REAL2SIM_USD_PYTHONPATH variable
is not a Python interpreter search path). See [AGENTIC_TOOLKIT.md](AGENTIC_TOOLKIT.md).


Blender is installed at `/home/hyeonhee/apps/blender/blender`:

```bash
export REAL2SIM_BLENDER=/home/hyeonhee/apps/blender/blender
python -m app.cli capabilities
```

The Blender subprocess isolates host Python/USD library paths. No `pip install bpy`
is required. See `BLENDER_REGRESSION.json` for actual reference integration results.
