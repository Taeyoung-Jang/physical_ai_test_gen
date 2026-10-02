# Physical AI Test Generation 작업 이력

이 폴더는 연구·개발 과정과 검증 근거를 추후 보고서 작성에 재사용할 수 있도록 보존한다.

## 기록 원칙

- 날짜별 Markdown 파일에 목표, 변경 사항, 문제 원인, 검증 결과와 산출물 경로를 기록한다.
- 성공 결과뿐 아니라 실패한 시도와 원인도 기록한다.
- 실험 수치는 실행 당시 생성된 job ID 및 산출물 경로와 함께 남긴다.
- 아직 검증하지 않은 기능은 완료된 것처럼 기록하지 않는다.
- 비밀키, 인증 토큰, 개인 정보는 기록하지 않는다.

## 이력 목록

| 날짜 (UTC) | 제목 | 기록 |
|---|---|---|
| 2026-09-03 | Server/Client 연동, 산출물 영상화, GR00T-WBC GPU 보행 통합 | [2026-09-03_server_client_gpu_locomotion.md](2026-09-03_server_client_gpu_locomotion.md) |

| 2026-09-03 | 20회 기준선, 명령 sweep, 보행 지표 및 dynamics failure sweep | [2026-09-03_locomotion_research_baseline.md](2026-09-03_locomotion_research_baseline.md) |

- 2026-09-06: [방향 편차 검토](2026-09-06_heading_drift_review.md)
- 2026-09-06: [평가 수정 및 경로 유지 검증](2026-09-06_heading_fixes.md)

- 2026-09-06: [프로젝트 통합 감사 및 로드맵](2026-09-06_project_integration_audit.md)

- 2026-09-06: [랜덤 환경·SceneGraph·이동 지도 구현](2026-09-06_procedural_world_implementation.md)

- 2026-09-06: [G1 환경 연결·내비게이션·GPU 주행 검증](2026-09-06_g1_navigation_integration.md)

- 2026-09-06: [SceneGraph 변형·Random/Sobol·적응형 AFS 파일럿](2026-09-06_scene_search_pilot.md)

- 2026-09-08: [다양한 지형 환경 생성 및 독립 GPU 검증 — 서버 연결 승인 대기](2026-09-08_terrain_scene_setup.md)

- 2026-09-26: [Failure Case 평가 지표·AFS 우선 탐색·행동 회귀 자산화 구현 계획](2026-09-26_failure_case_measurement_plan.md)

- 2026-09-26: [P0 실패 발견 측정기·최소 행동 reader 구현 및 136개 회귀 테스트](2026-09-26_failure_discovery_measures_p0.md)

- 2026-09-27: [P1 행동 시간선·failure memory·관측 경계 자산화 및 170개 테스트](2026-09-27_behavior_failure_memory_p1.md)

- 2026-09-27: [P2 행동 근거 AFS/Random 로컬 캠페인·동일 예산·중단 재개](2026-09-27_behavior_afs_campaign_p2.md)

- 2026-09-27: [AFS 프롬프트와 실제 후보 선택 방식 정합성 수정](2026-09-27_afs_selection_prompt_alignment.md)

- 2026-09-27: [AFS 전체 연결 자가 점검·중단 복구·실행 자원·예산 검증 보강](2026-09-27_afs_pipeline_self_audit.md)

- 2026-09-28: [AFS/Random 전체 파일럿 일괄 실행 스크립트](2026-09-28_afs_pilot_script.md)

- 2026-09-28: [README의 OpenAI API 키 설정·전체 실행 안내](2026-09-28_readme_api_key.md)

- 2026-09-28: [첫 live AFS 파일럿의 EGL 라이브러리 누락 진단](2026-09-28_afs_pilot_egl_diagnosis.md)

- 2026-09-28: [재개 파일럿의 API 크레딧 소진·로봇 행동·비용 집계 갭](2026-09-28_afs_pilot_quota_diagnosis.md)

- 2026-09-28: [AFS/Random 중간 8회 유효 FAIL·완화 탐색·네트워크 중단 분석](2026-09-28_afs_pilot_partial_results.md)

- 2026-09-28: [Luna 소규모 캠페인 설정·76개 테스트·밀기 외 AFS 확장 계획](2026-09-28_luna_pilot_setup.md)

- 2026-09-28: [통로 폭·상자 배치 5축 AFS·정적 지도·경계 메모리·Luna 실행 설정](2026-09-28_corridor_geometry_afs.md)

- 2026-09-28: [Luna 넓은 통로 유효 FAIL 분석·경로 추종 여유 부족·입력 비용](2026-09-28_luna_corridor_wide_result.md)

- 2026-09-28: [AFS 집중 검토·후반 행동 근거 누락 재현·가설/경계 탐색 개선안](2026-09-28_afs_search_review.md)

- 2026-09-28: [AFS v2 구현·가설 선택·행동 중복 억제·탐색 측정·294개 회귀 테스트](2026-09-28_afs_search_v2_implementation.md)

- 2026-09-28: [Luna 통로 파일럿 4회 유효 결과·첫 AFS 제안의 근거 ID 오타 중단 진단](2026-09-28_corridor_pilot_evidence_id_diagnosis.md)

- 2026-09-28: [AFS 근거 ID 출력 제한·원본/비용 보존 복구·321개 회귀 테스트](2026-09-28_afs_evidence_reference_recovery.md)

- 2026-09-28: [통로 4m success_probe 유효 PASS·자율 우회·관측 경계 분석](2026-09-28_afs_success_probe_result.md)

- 2026-09-28: [다중 장애물 17축 AFS·G1 관측/물리 연결·390개 회귀 검사](2026-09-28_obstacle_geometry_afs.md)

- 2026-09-28: [다중 장애물 Luna/GPU 우회 PASS·종료 후 사용량/출처 보완점](2026-09-28_obstacle_slalom_live_result.md)

- 2026-09-28: [사용량·출처 보완, 3개 유형 규칙, 실행 가능한 고정 예산 회귀 suite](2026-09-28_measurement_taxonomy_regression.md)

- 2026-09-29: [Slalom 회귀 시작 전 EGL 누락 진단·사전 검사 한계·복구 명령](2026-09-29_regression_egl_startup_diagnosis.md)

- 2026-09-29: [Slalom 회귀 유효 FAIL·경로 추종/시작점 차단·제외 포함 완료 분석](2026-09-29_slalom_regression_valid_fail.md)

- 2026-09-29: [새 17축 Luna AFS 캠페인 준비·EGL 점검·고정 예산 및 실행 명령](2026-09-29_obstacle_afs_campaign_preparation.md)

- 2026-09-29: [17축 AFS 완화 탐색·5회 유효 FAIL·응답 출력 한도 제외·고정 예산 한계](2026-09-29_obstacle_afs_partial_result.md)

- 2026-09-29: [로봇·AFS 기본 출력 토큰 상한 제거·요청/프로토콜/회귀 검증](2026-09-29_remove_default_output_token_caps.md)

- 2026-09-29: [17축 Luna AFS 6+6 완료·관측 Gain 20%·근접 도달 FAIL과 체류시간 감사](2026-09-29_obstacle_afs_completed_result.md)

- 2026-10-02: [최종 이동 체류 처리 옵션·AFS 진행 근거·고정 예산 회귀 계획](2026-10-02_goal_navigation_completion.md)

- 2026-10-02: [새 도착 옵션 실험의 이동 정체·0속도 명령 반복·체류 미검증 분석](2026-10-02_goal_dwell_live_result.md)

- 2026-10-02: [경로점 선회 수정·수치 명령 피드백·AFS 측정 근거 연결](2026-10-02_navigation_tracking_feedback.md)

- 2026-10-02: [새 추종기 실제 전진·횡이동 확인과 발자국 여유 복구 한계](2026-10-02_navigation_followup_live_result.md)

- 2026-10-02: [경로 여유 추가·제한된 바깥 복구와 재계획·AFS 근거 전달](2026-10-02_navigation_clearance_recovery.md)

- 2026-10-02: [새 경로 추종기의 Luna와 CUDA 목표 PASS·5회 호출·복구 미사용 확인](2026-10-02_navigation_v3_live_pass.md)

- 2026-10-02: [동일 조건 재실행 PASS·6회 호출 이유·두 성공의 회귀 기준선 확인](2026-10-02_navigation_v3_repeat_pass.md)

- 2026-10-02: [성공 기준의 AFS 단일 축 대조·후속 경계와 LLM 선택·고정 예산 실행 준비](2026-10-02_anchored_contrasts.md)

- 2026-10-02: [AFS 폭 대조 기준 장면의 세 번째 PASS·긴 응답과 출력 비용 검토](2026-10-02_anchored_contrast_control_pass.md)

- 2026-10-02: [AFS 통로 폭 3.6m 유효 PASS·6회 이동·누적 사용량 구분](2026-10-02_anchored_contrast_width36_pass.md)

- 2026-10-02: [AFS 통로 폭 3.2m API 응답 중단·중간 지점 접근·미확정 경계와 비용](2026-10-02_anchored_contrast_width32_timeout.md)

- 2026-10-02: [폭 대조 실험 중단 결정·AFS 기준 장면과 환경 축 선택 확장 제안](2026-10-02_afs_next_development_plan.md)

- 2026-10-02: [전체 연구 개발 계획 리마인드·P0–P4 현황·다음 우선순위 미확정](2026-10-02_project_plan_reminder.md)

- 2026-10-02: [실패 유형과 장면 도메인 자동 점검·초기 목표 점유 공백·166개 회귀 검사](2026-10-02_failure_domain_readiness.md)

- 2026-10-02: [목표 주변 18축 장면·AFS 연결·작업자 근접 측정 계약과 오프라인 검증](2026-10-02_goal_region_afs_and_human_contract.md)

- 2026-10-02: [목표 주변 첫 실동작 준비·CUDA 추론 확인·에이전트 API 키 부재로 실행 대기](2026-10-02_goal_region_live_preflight.md)

- 2026-10-02: [목표 주변 빈 공간의 Luna CUDA 첫 PASS·4회 호출·성공 대조 근거 검증](2026-10-02_goal_region_clear_live_pass.md)

- 2026-10-02: [목표 부분 점유 한 회 준비·단일 축과 동일 소스 자산 확인·API 키 대기](2026-10-02_goal_region_partial_preparation.md)

- 2026-10-02: [목표 부분 점유 PASS·GPT 중간 목표와 직접 이동 선택·10회 호출과 미확정 경계](2026-10-02_goal_region_partial_live_pass.md)

- 2026-10-02: [두 성공 근거의 AFS 양쪽 배치 제안·1회 요청 잠금·세 장면 고정 예산과 행동 비교](2026-10-02_goal_region_paired_afs.md)
