# AFS RuntimeError 원인 조사

대상: runtime/llm_afs_expanded/20260915T140138_975489Z.
사용자 요청: 키를 제공했는데 호출이 실패하는 정확한 원인 조사.

저장 요청의 model은 gpt-6-astra이고 Responses input/instructions/reasoning/text
형식이며, JSON schema의 객체 필드는 required/additionalProperties=false로 구성됨.
공식 모델 및 Structured Outputs 문서와 대조했으나 이것만으로 실제 API의 요청
수락이나 해당 계정의 접근 권한을 증명하지는 못함.

비인증 GET https://api.openai.com/v1/models 조회에서 HTTP 401 확인.
현재 도구 실행 경로에서 서버까지 도달한다는 증거이며, 과거 요청 시점의 네트워크
정상이나 사용자가 설정한 키의 인증 성공 증거는 아님.
현재 agent 프로세스 OPENAI_API_KEY 존재 여부만 검사: False. 값은 출력하지 않음.
사용자 터미널 환경과 별개이므로 사용자가 키를 제공하지 않았다고 해석하지 않음.

기존 provider는 비-200 응답을 상태 코드 포함 RuntimeError로 바꾸고 응답 본문을
버림. CLI는 다시 error_type만 저장하므로 이전 HTTP 상태 코드/오류 코드는 복구
불가. 저장된 RuntimeError만으로 키 오류/권한/한도/요청 오류/통신 실패를 확정할 수 없음.

생성 POST 재시도, 계정 인증 요청, 로봇 실행, 코드 수정은 하지 않음. 다음 진단은
키가 설정된 사용자 터미널에서 해당 모델의 읽기 전용 조회. HTTP 상태와 오류 코드만
공유하고 키/전체 헤더/전체 오류 본문은 공유하지 않도록 안내. 모델 조회 성공도 기존
Responses 요청 전체의 정상 작동을 보장하지는 않음.

공식 참고:
https://developers.openai.com/api/docs/models/gpt-6-astra
https://developers.openai.com/api/docs/guides/structured-outputs
