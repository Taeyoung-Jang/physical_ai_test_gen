
import torch
from transformers import AutoModelForVision2Seq, AutoProcessor


def resolve_device_dtype(device: str = "auto"):
    """실행 환경에 맞는 (device, torch_dtype) 을 고른다.

    cuda → bf16, Apple Silicon MPS → fp32, cpu → fp32.
    MPS는 float64 미지원이므로 fp32 사용 (fp16보다 안정적).
    flash-attn 은 CUDA 전용이므로 어디서나 'eager' attention 을 쓴다.
    """
    if device == "auto":
        if torch.cuda.is_available():
            device = "cuda:0"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
    if device.startswith("cuda"):
        dtype = torch.bfloat16
    else:
        # MPS + CPU 모두 float32. MPS는 float64 미지원이므로 fp32로 고정.
        dtype = torch.float32
    return device, dtype


model_id = "openvla/openvla-7b"

processor = AutoProcessor.from_pretrained(
    model_id, trust_remote_code=True)

# CPU에 먼저 로드한 뒤 float64 버퍼를 패치하고 device로 이동
model = AutoModelForVision2Seq.from_pretrained(
    model_id,
    attn_implementation="eager",
    low_cpu_mem_usage=True, 
    trust_remote_code=True)

print(model)
