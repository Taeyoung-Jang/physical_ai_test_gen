# 3D Object Generation 가이드

블루프린트 14장. 텍스트 프롬프트로 distractor/occluder 3D 메쉬를 생성해 asset bank 에
등록하고, failure case 에 삽입한다. **생성 모델이 없거나 실패하면 procedural default
객체로 자동 폴백**한다.

## 설계 (3단계 중 1·2 구현)

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | procedural primitive asset bank (box/cylinder) | ✅ |
| 2 | **offline generated mesh** (Shap-E → .obj → bank 등록) | ✅ |
| 3 | runtime 생성 모델 연동 | (느려서 미사용; offline 권장) |

**핵심 원칙: 생성은 offline 1회, 루프는 consume.** Shap-E 추론은 느리므로(스텝당 ~1s)
루프 실행 중 매번 생성하지 않는다. `tools/gen3d_asset.py` 로 미리 메쉬를 만들어
`index.json` 에 등록해 두면, LAM-Guided 루프가 그 asset 을 일반 asset 처럼 사용한다.

```
모듈:
  src/lam_guided/asset_gen.py   Asset3DGenerator / ShapEGenerator / NullGenerator / acquire_asset
  src/lam_guided/types.py       GeneratedAsset.mesh_path / shape="mesh"
  src/scene_builder.py          create_mesh() + _spawn_object 메쉬 분기(GEOM_MESH 시각 + box collision)
```

## 폴백 (모델 없을 때)

```python
acquire_asset(bank, family, spec, generator)
  → generator.available() and 생성 성공 ?  생성 메쉬 asset
  → 아니면                                  family 의 default procedural asset
```
생성기 미설치/추론 실패/오류 어느 경우든 **default 로 안전하게 폴백**한다(검증됨).

## 설치 (Apple Silicon)

```bash
uv sync --extra gen3d
```
- `diffusers==0.27.2`, `trimesh`, `huggingface-hub==0.23.4` (OpenVLA용 transformers 4.40.1 과 공존하도록 고정)
- ⚠️ **Shap-E 렌더러는 float64 를 쓰는데 Apple MPS 가 미지원** → `ShapEGenerator` 는 mps면 자동으로 **CPU** 사용.
- M4 Pro에서 16~24스텝 ≈ **20~30초** (모델 최초 1회 다운로드 ~1.3GB).

## 사용

```bash
# 실제 생성 → index.json 등록 + 스냅샷
PYBULLET_MODE=DIRECT uv run python tools/gen3d_asset.py \
    --prompt "a red soda can" --asset-id gen3d_red_can --family semantic_distractor \
    --tags red,can --steps 24

# 모델 없이(폴백 확인)
PYBULLET_MODE=DIRECT uv run python tools/gen3d_asset.py --no-model --family semantic_distractor
```
생성된 asset 은 `family_affinity` 가 설정되어 `bank.query(family=...)` 에 포함되므로,
이후 LAM-Guided 루프/generator 가 자동으로 후보에 넣는다.

## 메쉬 처리

- Shap-E mesh → PLY → trimesh 로 로드 → 원점 정렬 + 목표 size 로 스케일 + 바닥 z=0 정렬 → OBJ 저장
- PyBullet 스폰: **시각=GEOM_MESH(.obj), 충돌=AABB box proxy** (오목 메쉬 정확 충돌은 비싸고,
  kinematic clearance 테스트엔 box proxy 로 충분). 메쉬 로드 실패 시 box 시각으로 폴백.

## 검증

`tests/test_p13_asset_gen.py` (생성 모델 없이도 통과): 메쉬 to_object_node, `_spawn_object`
메쉬 로딩+collision proxy, no-model/NullGenerator → default 폴백.

> 실제 Shap-E 생성은 이 M4 Pro(CPU)에서 동작 확인됨: "a red soda can" → can 형상 메쉬
> (77k verts), `reports/gen3d_asset.png` 참고.

## 다른 생성 모델

`Asset3DGenerator` 인터페이스(`available`/`generate`)만 구현하면 교체 가능:
TripoSR(image→3D, 빠름), Point-E(경량), Hunyuan3D/TRELLIS(고품질, CUDA) 등.
어느 것이든 없으면 default 로 폴백하는 구조는 동일하다.
