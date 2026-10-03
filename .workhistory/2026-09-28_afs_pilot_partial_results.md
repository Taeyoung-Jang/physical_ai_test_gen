# AFS/Random live pilot 중간 결과: 8회 유효 FAIL, 완화 탐색, 네트워크 중단

날짜: 2026-09-28 UTC.

## 요청과 확인 범위

사용자가 재개 후 생성된 실험 결과의 분석을 요청했다. 코드를 수정하거나 API/GPU 실험을
재실행하지 않고, 저장된 보고서·proposal·decision·skill·state 기록을 대조했다.
원본 기록/평가/예산은 유지했다. 별도 유료 호출은 하지 않았다.
대표 카메라 이미지 1장을 확인했고 MP4 메타데이터를 조회했다. 모든 영상의 전체 재생 검토는 아니다.
기존 미커밋 변경을 보존했으며, 새 live 근거의 범위를 AGENTS.md에 갱신했다.

- 캠페인: `/workspace/g1_failure/runtime/afs_benchmark/20260928T033700_667656Z`
- 검토 보고서: `reports/20260928T054832_522126Z/`
- 새 유효 시도: attempt_00002 ~ attempt_00009.
- 최신 중단 시도: attempt_00010.

## 요약 및 지표 해석

| 항목 | AFS | Random |
|---|---:|---:|
| 선언된 유효 예산 | 8 | 8 |
| 현재 유효 실행 | 4 | 4 |
| goal PASS | 0 | 0 |
| goal FAIL | 4 | 4 |
| 전체 시도 | 6 | 5 |
| 인프라/불완전 제외 | 2 | 1 |
| 현재 관측 FDR | 100% | 100% |

8개 유효 실행은 모두 정책 호출 10회 예산 종료 BUDGET_EXHAUSTED이며, goal-only FAIL이다.
접촉/낙상/기술 실패를 목표 실패로 대체한 것이 아니다. 관측된 낙상 이벤트는 없으며,
유효 trace의 최소 base 높이는 약 0.725 m 이상, 최대 sampled tilt는 약 9.10도 이하이다.
정적 no_path는 물체 조작까지 포함한 장면 불가능성 증명이 아니다.

실행 계약에 따른 FAIL 데이터가 처음 확보되고, 행동 피드백 → LLM 제안 → 다음 실제 rollout
연결이 실행됐다는 점은 성과다. 그러나 단일 seed의 중간 4+4회만으로 연구 목표 달성을 주장하지 않는다.
모든 표본이 FAIL이므로 현재 두 방식의 발견률 차이는 없다. 보고서의 공식 비교 상태는
not_comparable / relative_gain null / unequal_or_incomplete_valid_budget이다.
양 arm의 현재 개수는 같지만 선언한 전체 8회씩이 미완료라 Gain을 아직 계산하지 않는 것이다.

FDR target flag는 관측 표본의 수치 비교일 뿐 통계적 우월성 판정이 아니다.
6-family detector가 없어 coverage는 not_measured/null이며, 8 failures가 8종 발견이라는 뜻이 아니다.
memory의 brackets는 빈 배열이다. 두 paired cold scenes는 각 arm에서 따로 실행했으므로
전체 유효 8회는 서로 다른 장면 설정 6개에 해당한다. 독립 실행을 중복 archive로 오인하지 않는다.

## 실제 실행 조건과 로봇 진행

| attempt | arm / 선택 | 질량 kg | 상자 마찰 | 바닥 마찰 | 최종 목표 거리 m | push 호출 수 |
|---|---|---:|---:|---:|---:|---:|
| 00002 | AFS cold | 9.7003 | 0.6552 | 0.7765 | 5.1694 | 0 |
| 00003 | Random cold | 9.7003 | 0.6552 | 0.7765 | 3.7706 | 2 |
| 00004 | AFS cold | 9.3354 | 1.1167 | 0.9225 | 3.8930 | 1 |
| 00005 | Random cold | 9.3354 | 1.1167 | 0.9225 | 5.6391 | 0 |
| 00006 | AFS success_probe | 1.0000 | 1.1167 | 0.9225 | 4.1538 | 0 |
| 00007 | Random uniform | 0.8357 | 1.3984 | 1.3637 | 5.3869 | 0 |
| 00008 | AFS success_probe | 1.0000 | 0.2000 | 0.9225 | 3.3420 | 1 |
| 00009 | Random uniform | 4.1613 | 1.2404 | 1.0680 | 3.9498 | 0 |

같은 장면의 paired cold 실행에서도 행동이 다르다. 예를 들어 9.70 kg에서는 한쪽이 push를
호출하지 않았고 다른 쪽은 두 번 호출했다. 로봇 추론/실행은 결정론적 반복 조건이 아니므로,
행동 차이를 질량만으로 설명하지 않는다. 표의 거리는 최종 목표 거리이며 직선 경로의
이동 가능성이나 성공 확률이 아니다.

### AFS가 실제 수행한 조건 완화 탐색

proposal_00000은 최신 AFS FAIL의 질량 9.335 kg과 마찰을 근거로 질량 [1, 3] kg의
success_probe를 첫 후보로 제안했다. host는 1 kg을 선택하고 나머지 두 축을 유지한 채
attempt_00006을 실행했다. 이 회차는 push_object를 선택하지 않고 접근 후 짧은 우회 이동으로
예산을 소진했다. 가볍게 해도 FAIL이었지만, 이를 "1 kg이어도 밀지 못한다"는 근거로 쓸 수 없다.

proposal_00001은 최신 1 kg 조건을 유지하고 box_friction [0.2, 0.6]의 success_probe를 제안했다.
host는 0.2를 선택해 attempt_00008을 실행했다. 실패를 더 강하게 만드는 것만이 아니라
성공 쪽으로 조건을 완화하는 탐색이라는 사용자 방침에 부합한다. 대안 가설과 관측 부족도
proposal에 기록됐다. 각 proposal에는 다른 space도 있었지만 모든 space/양 끝점을 실행한 것은 아니다.

### 주목할 실행: attempt_00008

- plan_path에서 목적지 경로 없음 확인 → 내부 계획기로 상자 앞 접근 → 동쪽으로 19 cm push 선택.
- 밀기 중 push frame의 전방 변위는 0.19213983051850536 m, 횡방향은 0.038649651761844636 m.
- skill status는 failed / DURATION_REACHED. 목표와의 차이는 0.03870884209015265 m다.
  19.2 cm 움직였다는 관측과 skill 성공 판정은 별개이며 handoff/release는 완료됐다.
- 재계획 결과는 여전히 no_path였고, 남쪽 좁은 틈으로 자세를 바꾸며 이동했지만 미도달했다.
- 최종 목표 거리 3.342 m. 접촉으로 강제 중단한 것이 아니라 10회 결정 예산을 소진했다.
- 무거운 조건00004의 push 변위는 약 5.11 mm였다. 단, 질량과 마찰이 모두 다르고,
  질량만 낮춘 1 kg 시험에서는 push를 선택하지 않았으며 접촉/실행도 달라 마찰만의 인과 효과로 단정하지 않는다.
- states 표본의 약 87.54%는 inference_wait다. 긴 영상의 상당 부분은 API 대기를 포함한다.
  누적 base 이동거리에는 대기 중 흔들림도 포함되므로 전체를 목표 방향 진전으로 해석하지 않는다.

代表動画: `attempts/attempt_00008/rollout/rollout.mp4`。
ffprobe: duration 363.5秒, size 13,865,756 bytes。
선택 이미지: 같은 rollout의 camera_004.png. 이미지의 외관만으로 기하학적 이동 가능성을 판정하지 않는다.

## 최신 중단: quota가 아니라 TCP 연결 실패

attempt_00010은 독립 탐색이며 질량4.78255 kg, box friction 0.85922, floor friction 0.31419다.
8번째 API 시도에서 다음 예외가 발생했다.

```text
api_transport_error
connection.connect_tcp.failed
ConnectError: [Errno 101] Network is unreachable
elapsed_wall_s: 4.365281242877245
```

HTTP 응답 이전 연결 오류로, 지난번 429/insufficient_quota나 300초 timeout이 아니다.
7회 정상 응답의 usage는 남지만 중도 중단이므로 INCONCLUSIVE로 제외한 것은 적절하다.
실패 시점에 어떤 네트워크 경로/장비에서 장애가 발생했는지는 저장 정보만으로 특정할 수 없다.

현재 읽기 전용 확인:

```bash
curl --connect-timeout 10 --max-time 15 -sS -o /dev/null -w 'NETWORK_PROBE_HTTP=%{http_code} total_s=%{time_total}\n' https://api.openai.com/v1/models
```

결과: HTTP401, 약0.245초. 키를 보내지 않는 연결 확인이므로 401은 예상된 응답이며,
현재 해당 연결에서 HTTP 응답을 얻을 수 있다는 뜻이다. 인증/잔액/장시간 통신 안정성이나
원래 경로의 복구까지 증명하지 않는다. OpenAI Docs 스킬로
[공식 오류 안내](https://developers.openai.com/api/docs/guides/error-codes)의 연결 오류 분류를 확인했다.
네트워크 설정/인증서/재시도 정책은 변경하지 않았다.

## 비용과 다음 연구 논점

전체 attempt의 decisions.jsonl에서 정상 응답 96회를 집계하면 입력2,512,913, 출력112,192,
합계2,625,105 tokens가 관측된다. 중단00001의 9회와 00010의 7회도 포함한다.
AFS proposer 별도 집계는 입력34,705, 출력1,872, 합계36,577 tokens다.
이는 과금액이 아니며 캐시 내역/단가/실패 요청 등을 포함한 완전한 청구 정보도 아니다.
INCONCLUSIVE의 usage가 보고서에서 빠지는 기존 importer 갭은 미수정 상태이므로,
보고서의 사용량을 실제 전체 사용량으로 간주하지 않는다.

다음 연구 우선순위는 확보된8 FAIL을 보존하고 현재 탐색 범위에 성공 관측이 가능한 조건과
충분한 행동 기회가 있는지 분리해서 확인하는 것이다. AFS 평가기가 로봇의 밀기 방향을 강제하는 것이 아니다.
현재 고정 조건에서 남은 예산을 완료할지, 별도 기준선 확인 캠페인을 둘지를 명확히 구분한다.
후자에서 task budget/geometry/policy/history 압축을 바꾸면 별도 조건으로 고정해야 한다.
현재 탐색은3개의 물성 축만 바꾸며 통로 폭/상자 위치 등 기하를 바꾼 실험은 아니다.
PASS 없이 모든 조건에서 실패가 계속되면 FDR만으로 AFS 우위를 측정하기 어렵다.
기존 목표/실패를 사후 변경하지 않고 성공 기준점, 반복, 성공과 실패 사이의 경계를 축적해야 한다.

## 保全

실행 코드, runtime archives, 기존 보고서, API 키, 계정 설정은 변경하지 않았다.
유료 재실행도 하지 않았다. 이번 신규 변경은 본 기록, 이력 색인, 검증 범위를 갱신한 AGENTS.md뿐이다.
