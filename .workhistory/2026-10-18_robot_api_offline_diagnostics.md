# 로봇 API 시간 초과 비교 진단 개선

## 작업 범위

사용자가 최근 시간 초과 후 우선 개선 작업을 승인했다. 기존 결과·로봇 조건·동결
예산을 보존하기 위해 요청 전송 코드나 추론 강도·모델·시간 제한은 변경하지 않았다.
tools/audit_robot_api.py와 합성 테스트, 실행 문서를 추가했다. 이 도구는 fingerprint에
포함되는 로봇/탐색 src나 기존 고정 도구를 수정하지 않는다. 네트워크 호출·키 설정·
MuJoCo/GPU 실행 없이 아카이브를 읽고 별도 진단 보고서를 만든다.

OpenAI Docs 지침으로 공식 API request debugging 문서를 확인했다. 기존 transport는
이미 X-Client-Request-Id를 보냈다. 새 도구는 이 ID와 전송 실패 단계를 보고해 원격
지원 문의 근거를 제공한다. 출처: https://developers.openai.com/api/reference/overview
공식 문서의 ID 추적 안내는 제공자 원인을 입증하지 않는다.

## 진단 내용

manifest로 로그·관측·첫 goal context·카메라를 검증한다. 정책·관측계약·wire schema·
feedback·navigation·task 소스가 원본 hash와 맞을 때만 첫 호출을 재구성한다.
카메라/원문 요청은 출력하지 않고 HTTPX 형태의 재구성 바이트·hash·컨텍스트/이미지/
스키마 크기·추론 강도·이미지 detail·토큰 제한 존재 여부를 남긴다. 실제 전송 request
캡처나 토큰 측정으로 주장하지 않는다. 이후 호출은 전송 로그만 진단한다.

실패 전송 단계는 response_closed 정리 이벤트에 덮이지 않는다. 응답 헤더/본문/
전송/연결 단계를 구분하고 누락 정보는 unknown으로 남긴다. 같은 journal의 request ID,
버전 및 시간 순서를 검증한다. 출력 덮어쓰기와 입력 아카이브 내 출력도 거절한다.

실제 비교 대상:
- 실패: afs_autonomous/20261018T014205_556509Z_point_recovery/attempts/attempt_00000/rollout
- 성공: robot_goal_agent/20261018T004636_410637Z

실패 첫 요청 재구성82286bytes/context17311/PNG41817, 성공83343/context17312/PNG42608.
둘 다 high reasoning/high image/행동 이력0/로컬 출력토큰 cap 없음. 실패301.03초,
성공6.54초이므로 크기 폭증·누적 이력만으로 지연을 설명할 근거가 없다.
실패는 응답 헤더 대기이며 제공자/네트워크/중간 경로 원인은 미확정이다.

최종 보고서:
`/workspace/g1_failure/runtime/robot_api_audit/20261018T024723_577469Z/report.html`
같은 폴더 audit.json과 manifest.json에 도구/출력 hash 및 원본 manifest hash를 보존했다.
초기 보고서024520_640525Z도 보존한다. 추가 API/로봇 실행0, 재시도0, 과거 판정 변경0.

## 검증과 다음 실행

도구 테스트7개는 네트워크 클라이언트 사용 금지, 원본 hash 불변, 첫 호출 재구성,
단계 보존, 소스 불일치 거절, manifest 변조/출력 겹침/기존 폴더 거절을 확인했다.
최종 기존 타임아웃·복구·자율 탐색 회귀 결과는 아래에 기록한다.
ROBOT_API_DIAGNOSTICS.md에 무료 진단 명령과 별도의 유료 다음 후보 실행 명령을 분리했다.
제외 후 계속은 기존 기능으로 수동 검토 후 명시적으로 허용하며, 이 작업에서 실행하지 않았다.

최종 회귀 **61 passed, 1 skipped in 23.85s**. skip은 명시적 opt-in이 필요한
32초 GPU 지연 실험이며 실행하지 않았다. Ruff check/format --check와 git diff --check
통과. 복구 세션 protocol의 동결 environment와 현재 fingerprint를 비교해
`FROZEN_ENVIRONMENT_UNCHANGED=True`를 확인했다. 기존 DB/예산은 수정하지 않았다.
