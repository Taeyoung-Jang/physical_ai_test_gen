"""lam_guided — LAM-Guided 3D Failure Case Generator.

기존 Active Failure Search 위에 얹는 행동 조건부(behavior-conditioned) 확장:
  LAM/정책 실행 관찰 → 행동 취약성 추정 → 그 약점을 찌르는 3D failure case 생성 → 재실행.

기존 pipeline(src/*.py)은 손대지 않으며, 모든 기능은 config flag로 on/off 한다.
"""
