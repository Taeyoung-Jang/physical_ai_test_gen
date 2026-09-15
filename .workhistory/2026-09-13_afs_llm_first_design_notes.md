# AFS 논의 문서화 및 LLM-first 방향 기록

일시: 2026-09-13 UTC.
요청: 지금까지 AFS에 관해 논의한 내용을 문서로 저장. 사용자는 LLM을 사용하는 방식부터
시작하는 것을 선호한다고 명시했다.

## 작업

- 시작 시 git status --short 출력 없음: 깨끗한 작업 트리 확인.
- 현재 G1_SCENE_SEARCH.md를 다시 읽고, 실제 파일럿 범위와 확장 논의를 구분.
- scene2test/docs/AFS_LLM_FIRST_DESIGN.md 새 파일 작성.
- 목적, SceneGraph 입력 계약, 숫자 특징 인코딩, ExtraTrees 파일럿의 정확한 동작,
  LLM 대리 모델/후보 생성/평가기/LAM 구분, 미확정 항목, 비교 원칙과 참고 연구를 정리.
- LLM-first를 다음 설계의 출발점으로 기록. 특정 모델·API·비용·프롬프트·획득 함수·
  지형 변수·평가 목표를 확정한 것처럼 기록하지 않음.
- 수동 경사/계단 성능 대조 실험은 AFS 구현의 필수 선행 작업이 아니라는 범위 유지.

## 변경 및 검증 범위

apply_patch로 새 문서 두 개만 생성. 기존 코드·AGENTS.md·실험 결과는 수정하지 않음.
유료 API 호출, GPU 실험, 서버 변경, Git 커밋/push를 수행하지 않음.
문서화만 수행했으므로 테스트나 LLM 구현이 완료됐다는 주장은 하지 않음.
관련 링크와 파일 내용을 읽기 전용으로 확인하고 git diff --check로 공백 오류 검사 예정.

주 문서: [AFS_LLM_FIRST_DESIGN.md](../scene2test/docs/AFS_LLM_FIRST_DESIGN.md).
