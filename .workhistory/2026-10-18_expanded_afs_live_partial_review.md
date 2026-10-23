# 10종 AFS 실제 탐색 첫 분류와 API 제외 검토

## 결과와 해석

사용자 실행 `/workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z`는
신규2시도 중 VALID FAIL1개, API 오류 제외1개로 NEEDS_ATTENTION/excluded_rollout,
pending=null이다. 유효6개 목표 중1개만 완료했다. 신규 FDR은1/1=100%지만 유효 표본이
하나인 중간 관측이며 일반화된 성능·공동 목표 달성이나 Random Gain이 아니다.
신규 대표 유형은 goal_occupied1종으로, 미분류 실패0개다.

최종 보고서: `reports/20261018T140348_151301Z/report.html`.
이번 검토는 기록 읽기·문서 기록만 수행했으며 코드·분류기·기존 DB·판정·예산은 바꾸지 않았다.

## 첫 번째 실험

unmixed PASS 기준 `4cf81f6f8dbc1570a37da4db9a0a0da1a21659747cf72bb982c6f80b59e82839`,
에피소드 `a783c4f15e330fc8ba1d68db0d1df3d513c18afa09925b67d0f9a8ad21fd88b2`에서
box_lateral_fraction .5→0만 바꾼 challenge다. 목표·로봇·나머지 파라미터는 고정이다.
예측 goal_occupied와 실제 대표 goal_occupied가 일치했지만 인과성은 UNCONFIRMED다.

로봇은 navigate8/move1/push1의10개 행동과10개 API 호출을 사용했다. 최종 full-rate
goal distance1.044812m/dwell0, BUDGET_EXHAUSTED다. 종료5초 상태는 완전하며,
거리 변화 .012524m·base excursion .028541m로 stalled=true다. 그 창 전체에서
clear_box_geom이 목표 원판을 완전히 덮었다. 기존 goal-behavior-v1/goal_occupied 규칙을
그대로 충족했으며 새 임계값 완화나 LLM 예측을 이용한 라벨 부여가 아니다.

마지막 push는 alignment_out_of_range로 거절됐다. forward gap1.044284m, heading
-.400234rad, box face 약-1.570796rad가 허용 범위 밖이었다. push distance .18m 자체는
유효했다. 정렬 attempted=false로 실제 밀기 운동이나 물리적 힘 부족이 확인된 것은 아니다.
조작 거절은 확장 프로필의 보조 진단이며 기존 유일 goal_occupied 대표를 유지해1종만 센다.

## 두 번째 실험과 제외 원인

첫 실패를 누적하지 않고 위와 같은 PASS 기준에서 obstacle_2_lateral_fraction0→-.7만
바꿨다. 목표 유형은 아직 관측되지 않은 obstacle_interference다.

첫 로봇 API 호출 observation0이 HTTP 응답 헤더를 기다리다가 ReadTimeout으로 중단됐다.
로그의 failed_transport_event는 http11.receive_response_headers.failed, 설정 read timeout은
300초, api_failed elapsed301.046641초다. 정책 행동은0개이며 실패 유형은 부여하지 않는다.
모델이 잘못 행동했다거나 환경이 로봇을 실패시켰다는 결과가 아니고, API·전송 계층 오류다.
서비스·네트워크 등 세부 근본 원인은 이 로그만으로 확정할 수 없다. 자동 재시도는 없었다.
사용량 응답이 없어 해당 호출의 token usage는 unknown이며0으로 대신하지 않는다.

## 피드백 연결 확인

저장된 proposal1 context에서 실제 관측 유형은 입력 이력의 goal_completion_failure와
신규 goal_occupied 두 개였다. 미발견 지원 목록은 collision, obstacle_interference,
human_safety_risk, fall, locomotion_stall, manipulation_failure였다.
최근 예측 결과에 첫 실험의 예상/실제 goal_occupied와 VALID FAIL이 함께 기록돼 있었다.
즉 실측→다음 요청 연결은 live에서도 확인됐다. 하지만 새 실험의 발견 실적은1종이며
입력 이력1종을 새 실적에 더하지 않는다. 두 번째 target은 예측일 뿐 발견 실적이 아니다.

## 무결성 비용 영상

신규 rollout의 선언 artifact101개와 최종 보고서305개 해시가 일치했다.
소스 drift0개이며 전체 source/resources/runtime 환경 fingerprint가 동결값과 일치한다.
저장 MP4는2개, GIF0개이며 두 영상 모두 ffmpeg로 끝까지 정상 디코딩됐다.

새 로봇11호출/실제 행동10개, usage 관측10호출+미상1호출이다. 알려진 사용량은
327955 input/34055 output tokens다. AFS2요청139222 input/10015 output tokens는
관측됐고, 입력 로봇 이력57호출1796453 input/128011 output은 별도다.
과거 AFS 비용은 unknown 상태를 유지한다. 신규 로봇+AFS의 전체 금액을 추정하지 않는다.

## 다음 실행 판단

새로 코드를 수정하거나 timeout을 임의로 늘리기보다, 제외 원인을 확인한 상태에서
동일 세션의 남은 범위를 이어가는 것이 다음 단계다. 현 시점 동결 환경이 일치하므로
source 검사를 우회할 필요가 없다. 로봇 시도6개·AFS6요청이 남았고 유효 표본5개가
더 필요하다. 추가 제외도 고정 예산을 소모하며 자동 유료 대체·재시도하지 않는다.

키가 설정된 사용자 터미널에서 아래 명령은 새 유료 호출을 수행한다. 검토 과정에서는
실행하지 않았다. 다음 장면으로 진행하는 것이지 제외된 두 번째 장면의 재시도가 아니다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py run --live --session /workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z --continue-after-exclusion
```

원래 config/--run 명령을 다시 실행하면 별도 새 세션이므로 위 재개 명령과 구분한다.
이번 검토는 새 API·GPU·로봇·시뮬레이션·세션·runtime 진단 출력·commit/push를 만들지 않았다.
문서 작성 스킬 지침에 따라 관측·판정 근거·원인 미확정·남은 예산을 작업 이력에 기록했다.
