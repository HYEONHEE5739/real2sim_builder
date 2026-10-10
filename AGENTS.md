# Codex 작업 규칙

- `CODEX_HANDOFF.md`와 관련 docs를 읽고 실제 source를 확인한다. SO-101 인수인계는 sibling `../soarm101_lab/CODEX_HANDOFF.md`.
- Builder는 offline reconstruction toolkit이다. 실제 로봇을 연결·구동하지 않는다. 내부 LLM 없이 외부 Codex가 가설을 선택한다.
- 입력 사진/Snapshot, reference project, 기존 사용자 scene/export를 임의로 변경·삭제하지 않는다. 새 실험은 새 project 또는 candidate로 한다.
- measured q·geometry·calibration은 evidence 없이 수정하지 않는다. estimated/unknown과 verified를 구분하고 provenance를 유지한다.
- candidate→render→evaluate(train/독립 validation)→promote/reject를 사용한다. 악화나 stale signature 검사를 우회하지 않는다. 불충분하면 NEEDS_MORE_DATA.
- 정상 export는 fresh validation을 요구한다. allow-unvalidated는 검토용이고 성공/물성 검증을 주장하지 않는다.
- 기존 CLI/calibration/Blender/exporter를 재사용하며 중복 시스템을 만들지 않는다. SO-101 Adapter는 sibling 프로젝트 책임이다.
- dependency 설치·conda 버전 변경은 임의로 하지 않는다. 실제 설치된 Blender와 격리된 subprocess 환경을 사용한다.
- 이 디렉터리는 현재 Git 저장소가 아니다. 사용자 파일을 보호하고 변경 범위를 기록한다.
- 관련 테스트와 실제 렌더를 구분하여 보고한다. structural parity가 Isaac pixel/contact parity를 증명하지 않는다.
