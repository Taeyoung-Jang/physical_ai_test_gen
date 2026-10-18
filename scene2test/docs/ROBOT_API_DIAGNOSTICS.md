# 로봇 API 응답 지연 오프라인 진단

`tools/audit_robot_api.py`는 보존된 실험 아카이브만 읽어 API 전송 단계와 첫 요청
구성을 비교한다. API 키·네트워크 호출·렌더러·로봇 실행이 필요하지 않으며, 실험 결과나
고정 세션을 변경하지 않는다. 원본 manifest를 검증하고 별도 JSON/HTML/manifest를 만든다.

## 비교 결과와 해석

2026-10-18 사람 모형 중앙 배치 실험의 첫 호출은 전송 완료 후 응답 헤더 대기에서
ReadTimeout으로 끝났다. 다음 값은 원본에 고정된 입력·정책 소스로 **재구성**한 첫
요청이며 실제 전송 바이트 캡처나 토큰 수가 아니다.

| 항목 | 중앙 배치 실험 | 앞선 가장자리 배치 성공 실험 |
|---|---:|---:|
| 첫 요청 결과 | 300초 HTTP 읽기 제한 초과 | HTTP 200 |
| 첫 호출 wall 시간 | 301.03초 | 6.54초 |
| 재구성 요청 바이트 | 82,286 | 83,343 |
| 컨텍스트 UTF-8 바이트 | 17,311 | 17,312 |
| PNG 바이트 | 41,817 | 42,608 |
| 추론 강도와 이미지 detail | high / high | high / high |
| 요청 시 행동 이력 개수 | 0 | 0 |

크기와 설정이 비슷하므로 이번 지연을 요청 크기나 high 설정만의 문제로 단정할 수
없다. 제공자·중간 경로·네트워크 내부 원인은 로컬 로그만으로 분리할 수 없다.
문제 요청의 client_request_id는 `f0068741-092a-4db2-b017-a79a46bc86b9`이다.
[OpenAI 공식 요청 디버깅 지침](https://developers.openai.com/api/reference/overview)에
따르면 응답 헤더를 받지 못한 경우에도 이 ID로 제공자 측 수신 여부를 문의할 수 있다.
클라이언트 전송 완료만으로 제공자 수신이나 과금 여부를 확정하지 않는다.

## 실행

`scene2test` 디렉터리에서 실행한다. `--run`을 반복해 여러 보존 결과를 비교할 수 있다.

```bash
uv run --no-sync python tools/audit_robot_api.py --run /workspace/g1_failure/runtime/afs_autonomous/20261018T014205_556509Z_point_recovery/attempts/attempt_00000/rollout --run /workspace/g1_failure/runtime/robot_goal_agent/20261018T004636_410637Z
```

출력 기본 경로는 `/workspace/g1_failure/runtime/robot_api_audit/<timestamp>`이다.
기존 출력 폴더나 입력 아카이브와 겹치는 경로는 거절한다. `audit.json`의 `calls`에서
실패 단계를 보고 `first_request`에서 요청 크기·이미지·스키마·추론 설정을 확인한다.
첫 요청 입력이 없거나 당시 정책 소스와 현재 소스가 다르면 재구성하지 않고
UNAVAILABLE로 표시한다. 현재는 0번 요청만 재구성하며 이후 요청의 이력을 추측하지 않는다.

## 실험 재개 시 유의점

진단 도구는 시간 초과를 재시도하지 않는다. 이번 실행은 INCONCLUSIVE로 남고, 시도
1회와 로봇 API1회를 소비한 기록을 유지한다. 미관측 토큰 비용은 0이 아니다.
추론 강도·모델·시간 제한을 바꾸면 새로운 로봇 조건의 기준선이 필요하므로 이번에는
변경하지 않았다. 검토 후 남은 예산으로 다음 후보를 진행하려면 다음을 사용할 수 있다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py run --live --session /workspace/g1_failure/runtime/afs_autonomous/20261018T014205_556509Z_point_recovery --continue-after-exclusion --max-new-attempts 1
```

이 명령은 **유료 실행**이며, 같은 중앙 배치를 자동 재시도하는 명령이 아니다.
제외된 시도도 축별 쿼터를 소비했으므로 다음 적격 축의 새 가설을 선택한다.
전체 예산은 늘어나지 않으며, 다음 유효/제외 결과를 확인한 뒤 나머지를 진행한다.
