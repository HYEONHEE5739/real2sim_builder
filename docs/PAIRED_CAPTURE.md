# Paired evidence로 기존 Scene 개선

SO-101 UI는 관측만 저장하고 Builder는 기존 import/FK/candidate/render/evaluate를 재사용한다.
별도의 refinement engine이나 내부 LLM을 추가하지 않았다.

전체 계약·수집·명령·검증: `../soarm101_lab/docs/real2sim/PAIRED_CAPTURE.md`.
Builder의 기존 절차: `docs/AGENTIC_TOOLKIT.md`, `docs/MULTIPOSE_CAPTURE.md`.

`python -m app.cli import-paired PROJECT SESSION --scene-state STATE --validation SHOT_IDS`
은 기존 reconstructed project에 real2sim.snapshot/1 + hashed pair.json observation을 추가한다.
기존 import-snapshots는 유지한다. Real은 fitting evidence, saved Sim은 historical runtime baseline이다.
후보 렌더는 measured q를 사용해 반드시 새로 만든다. baseline 이미지 재사용을 후보 렌더로 표시하지 않는다.
Candidate metrics images[].paired_diagnostics는 Real↔Runtime/Candidate↔Runtime 차이와 provenance를 기록한다.
MAE만으로 Scene/Adapter 오류를 단정하지 않는다. agent가 camera/FK/geometry/material/renderer를 조사한다.
형상 fitting target은 Real이고 nonregression도 기존 train/heldout 비교를 유지한다.

runtime_baseline metadata는 export manifest observations와 reconstruction evidence에 보존된다.
새 export는 SO101 Adapter의 새 Workspace version으로 import한다. 기존 사용자의 데이터는 변경하지 않는다.
검증 결과는 SO101 outputs/workflow_validation/paired_capture/smoke_report.json 참조.
실제 하드웨어 및 새 실측 Candidate 개선은 미검증이다.
