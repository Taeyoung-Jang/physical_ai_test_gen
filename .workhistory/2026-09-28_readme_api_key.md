# README의 OpenAI API 키 설정 안내

날짜: 2026-09-28 UTC.

## 요청 및 변경 범위

- 사용자 요청: API 키 등록 방법을 루트 `README.md`에 작성.
- README 상단에 RunPod/Bash용 키 설정과 AFS 전체 실행 절차를 추가했다.
- 앞선 일괄 실행 스크립트 및 기타 미커밋 변경은 그대로 보존했다. 실행 코드는 변경하지 않았다.

## 확인 및 안내 내용

- OpenAI Docs 스킬로 공식 Quickstart를 검색·열람하고 환경 변수 설정 방식을 확인했다.
  출처: https://developers.openai.com/api/docs/quickstart
- 로컬 `run_afs_pilot.py`, AFS provider, 로봇 API transport에서 `OPENAI_API_KEY` 사용을 확인했다.
  local goal adapter의 자식 프로세스는 부모 환경을 상속한다.
- `set +x`, Bash `read -r -s`, `export`를 순서대로 안내한다. 실제 키를 코드/문서에 쓰거나
  셸 명령 인자에 넣지 않고 터미널 숨김 입력을 사용한다.
- 키 값을 노출하지 않는 SET/MISSING 확인 명령을 추가했다. 이 확인은 원격 인증이나 모델 접근
  검증이 아님을 명시했다. 세션 범위, `.env` 자동 로딩 없음, `unset` 의미도 안내했다.
- plan-only와 유료 `--live` 명령, 기본 유효 rollout/호출 상한, 출력 위치, 상세 문서 링크를 추가했다.
- 기존 Panda/ExtraTrees 설명과 현재 G1 LLM 실험을 구분했다. 기존 연구 결과나 기능을 재평가하지 않았다.

## 검증 범위

- 새 섹션의 Bash 코드 블록을 추출해 `bash -n` 구문 검사를 통과했다.
- README에서 키 입력/환경 변수 설정/확인/해제 명령만 추출해 합성 문자열로 실행했다.
  출력은 예상한 `OPENAI_API_KEY: SET`, 해제 후 `OPENAI_API_KEY: MISSING`과 일치했다.
- `git diff --check`를 통과했다.
- 실제 키를 조회·기록하거나 API/GPU 실험을 실행하지 않았다. 코드 변경이 없어 전체 회귀 검사는 재실행하지 않았다.
