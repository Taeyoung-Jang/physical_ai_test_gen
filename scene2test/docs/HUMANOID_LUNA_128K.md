# Luna 출력 상한 명시

OpenRouter `openai/gpt-6-luna`의 로봇 및 AFS 요청에 `max_tokens: 128000`을
명시합니다. 내부 요청의 `max_output_tokens`가 공통 어댑터에서 `max_tokens`로
변환됩니다. 로봇 추론 강도 high와 AFS 추론 강도 medium은 유지합니다.
다른 모델 및 직접 OpenAI 요청 설정은 변경하지 않습니다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
set -o pipefail
bash tools/run_humanoid_luna_128k.sh both 2>&1 | tee zz_run_humanoid_luna_128k.log
```

에피소드당 로봇 호출 20회, HTTP 대기 600초, 실행기 마감 653초입니다.
이전과 같은 환경 시험 AFS 6회·Random 2회와 기준 확인 3회를 새로 실행하며,
이전 결과를 가져오거나 저장된 실패 요청을 다시 전송하지 않습니다. 총 상한은
11개 에피소드·220회 로봇 호출·9회 AFS 제안입니다. 새 기준 실행에서 명시적
128000 요청 기록과 VALID PASS를 확인한 뒤 방법별 실험을 준비합니다.

결과 폴더: `development/humanoid_luna_128k_20261023_v5/`.
기존 실험 폴더는 보존합니다. 이전 동결 준비본을 직접 live 재개하지 마십시오.
출력 상한 변경은 AFS 증거 참조 불일치 오류를 수정하지 않으며, timeout 또는
새로운 불완전 응답의 발생을 배제하지 않습니다. 자동 재시도는 추가하지 않습니다.
