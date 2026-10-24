# Random 유효 실험을 7회로 맞추기

완료된 AFS 7회에 맞추어 Random의 기존 유효 3회에 추가 4회를 실행합니다.
기존 결과와 DB는 그대로 두며, 새 폴더의 계획에는 원래 경로와 증거 ID만
참조합니다. 결과를 복사하거나 다른 경로로 재바인딩하지 않습니다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
set -o pipefail
bash tools/run_humanoid_random7.sh 2>&1 | tee zz_run_humanoid_random7.log
```

AFS와 기준 장면은 다시 실행하지 않습니다. 기존 seed 75002의 다음 Random
추출 인덱스 3~6을 그대로 사용하고, 변경 개수는 1/2/1/2입니다. 네 실행이
모두 유효하면 각 방법의 구성이 기준 1회, 변수 1개 변경 3회, 변수 2개 변경
3회로 같아집니다. 각 실행은 같은 기준 장면에서 시작하며 변경을 누적하지 않습니다.

Luna/OpenRouter, 에피소드당 로봇 호출 20회, HTTP 대기 600초, 실행기 마감
653초, 명시적 max_tokens128000을 유지합니다. 추가 로봇 호출 상한은 80회,
AFS 호출은 0회입니다. 원본 상태·소스·모델 리소스가 바뀌면 중단합니다.
오류·제외는 실패로 세지 않고 중단하며 자동 대체하지 않습니다. 완료 후 다시
실행해도 추가 실행하지 않습니다. 미완료 실행 intent는 재전송하지 않습니다.

새 경로는 `development/humanoid_luna_128k_random7_20261024_v6/`입니다.
`attempt_00003`~`attempt_00006`에 추가 결과와 영상을 저장하고, `summary.json`의
`value`에 원본 3회와 새 결과를 중복 없이 합산합니다. 안전 이벤트는 추가
실험에 대해 이 요약에서 집계하지 않으며, 목표 도달과 별도로 해석해야 합니다.
AFS 결과를 본 뒤 Random 예산을 늘린 개발용 비교라는 점을 계획에 기록합니다.
