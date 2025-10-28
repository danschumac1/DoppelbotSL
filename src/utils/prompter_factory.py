from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional, Type, Tuple, Union

# import torch
from utils.prompter import (
    Prompter, 
    OpenAIPrompter,
    # HFPrompter,
    # GemmaPrompter,
    # _load_hf_or_adapter,
)

@dataclass(frozen=True)
class ModelSpec:
    name: str
    prompter_cls : Type[Prompter]
    default_model_id: str
    loader_kind: str


REGISTRY: Dict[str, ModelSpec] = {
    "gpt":     ModelSpec("gpt",     OpenAIPrompter, "gpt-4o-mini",                          "openai"),
    # "llama":   ModelSpec("llama",   HFPrompter,     "meta-llama/Llama-3.1-8B-Instruct",     "hf"),
    # "mistral": ModelSpec("mistral", HFPrompter,     "mistralai/Mistral-7B-Instruct-v0.3",   "hf"),
    # "gemma":   ModelSpec("gemma",   GemmaPrompter,  "google/gemma-3-12b-it",                "gemma"),
}

import ast

# def _bnb_8bit_config():
    # from transformers import BitsAndBytesConfig
    # return BitsAndBytesConfig(load_in_8bit=True, bnb_4bit_compute_dtype=torch.float16)


def _normalize_device_map(dm):
    # Accept ONLY single-GPU int or an explicit dict. No "auto".
    if isinstance(dm, int):
        return {"": dm}
    if isinstance(dm, dict):
        return dm
    raise ValueError(f"device_map must be an int GPU index or a dict mapping. Got: {type(dm)}")


# if you call it again with the same arguments, returns cached rather than creating new
@lru_cache(maxsize=16)
def _load_shared_handles(
    *, # this forces all subsequent parameters to be passesed as keywords, not positional
    loader_kind: str,
    model_id: str,
    device_map: str,
    torch_dtype_str: str,
    adapter_id: Optional[str],
    trust_remote_code: bool,
    use_fast_tokenizer: Optional[bool],
    quantize_8bit: bool,
) -> Dict[str, Any]:
    '''
    Returnas a dictionary of shared handles depending on loader kind
      - "openai" -> {}
      - "hf"     -> {"model", "tokenizer"}
      - "gemma"  -> {"model", "processor"}
    Cached by inputs to avoid reloading across multiple Prompters.

    '''
    # torch_dtype = getattr(torch, torch_dtype_str)
    # device_map = _normalize_device_map(device_map)

    if isinstance(device_map, str) and device_map not in ("auto",):
        raise ValueError(f"Invalid device_map string: {device_map}. Must be 'auto' or a repr(dict).")

    # OPENAI
    ################################################################################################
    if loader_kind == "openai":
        return {} # we don't need anything special.
    
    # HUGGING FACE
    ################################################################################################
    # if loader_kind == "hf":
    #     # ADAPTER
    #     ############################################################################################
    #     if adapter_id: # if we are loading a fine tuned model basically
    #         model, tokenizer = _load_hf_or_adapter(
    #             base_model_id=model_id,
    #             adapter_id=adapter_id,
    #             device_map=device_map,
    #             torch_dtype=torch_dtype,
    #             trust_remote_code=trust_remote_code,
    #             use_fast_tokenizer=use_fast_tokenizer,
    #             quantization_config=None if not quantize_8bit else _bnb_8bit_config(),
    #         )

        # BASE
        ############################################################################################
        # else: 
        #     from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
        #     tok_kwargs = {}
        #     if use_fast_tokenizer is not None:
        #         tok_kwargs["use_fast"] = use_fast_tokenizer
        #     if trust_remote_code:
        #         tok_kwargs["trust_remote_code"] = True

        #     tokenizer = AutoTokenizer.from_pretrained(model_id, **tok_kwargs)
        #     if tokenizer.pad_token is None and tokenizer.eos_token is not None:
        #         tokenizer.pad_token = tokenizer.eos_token

        #     model_kwargs = {
        #         "device_map": device_map,
        #         "torch_dtype": torch_dtype,
        #     }
        #     if trust_remote_code:
        #         model_kwargs["trust_remote_code"] = True
        #     if quantize_8bit:
        #         model_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)

        #     model = AutoModelForCausalLM.from_pretrained(model_id, **model_kwargs)

        # return {"model": model, "tokenizer": tokenizer}
    

    # GEMMA
    ################################################################################################
    # if loader_kind == "gemma":
    #     from transformers import AutoProcessor, Gemma3ForConditionalGeneration
    #     processor = AutoProcessor.from_pretrained(model_id, use_fast=True)
    #     if processor.tokenizer.pad_token is None and processor.tokenizer.eos_token is not None:
    #         processor.tokenizer.pad_token = processor.tokenizer.eos_token

    #     model = Gemma3ForConditionalGeneration.from_pretrained(
    #         model_id,
    #         device_map=device_map,
    #         torch_dtype=torch_dtype,
    #     )
    #     return {"model": model, "processor": processor}

    # ERROR!
    ################################################################################################
    # raise ValueError(f"Unknown loader_kind: {loader_kind}")

def make_prompter(
    *, 
    model_name:str,
    device_map: Union[int, List[int], Dict[str, Any], str],
    llm_model: Optional[str] = None,
    prompt_path: Optional[str] = None,
    prompt_headers: Optional[Dict[str, str]] = None,
    temperature: float = 0.1,
    show_prompt: bool = False,
    repetition_penalty: float = 1.1,

    # HF / adapter options
    adapter_id: Optional[str] = None,
    trust_remote_code: bool = False,
    use_fast_tokenizer: Optional[bool] = None,
    torch_dtype: str = "float16",            # "float16" | "bfloat16" | etc.
    quantize_8bit: bool = False,

    # Extra kwargs passed through to Prompter subclasses if needed
    **extra_kwargs: Any, # (for later implimentation)
) -> Prompter:
    
    if model_name not in REGISTRY:
        valid = ", ".join(REGISTRY.keys())
        raise ValueError(f"Invalid model_name: {model_name}. Choose one of: {valid}")
    
    spec = REGISTRY[model_name]
    model_id = llm_model or spec.default_model_id
    # if spec.loader_kind == "gemma" and torch_dtype == "float16":
    #     try:
    #         gpu_idx = (device_map if isinstance(device_map, int)
    #                 else (device_map.get("", 0) if isinstance(device_map, dict) else 0))
    #         major, _ = torch.cuda.get_device_capability(gpu_idx)
    #         if major >= 8:  # Ampere+ supports bf16 well
    #             torch_dtype = "bfloat16"
    #     except Exception:
    #         torch_dtype = "bfloat16"

    
    # Normalize and cache-load shared handles

    # handles = _load_shared_handles(
    #     loader_kind=spec.loader_kind,
    #     model_id=model_id,
    #     device_map=device_map,
    #     torch_dtype_str=torch_dtype,
    #     adapter_id=adapter_id,
    #     trust_remote_code=trust_remote_code,
    #     use_fast_tokenizer=use_fast_tokenizer,
    #     quantize_8bit=quantize_8bit,
    # )
    # Common kwargs to Prompter subclasses
    base_kwargs = dict(
        prompt_path=prompt_path,
        prompt_headers=prompt_headers or {},
        llm_model=model_id,
        temperature=temperature,
        show_prompt=show_prompt,
        device_map=device_map,  # pass through
        repetition_penalty=repetition_penalty,
        **extra_kwargs,
    )

    if spec.loader_kind == "openai":
        # OpenAI client is created inside OpenAIPrompter
        return spec.prompter_cls(**base_kwargs)

    # if spec.loader_kind == "hf":
    #     return spec.prompter_cls(
    #         model=handles["model"],
    #         tokenizer=handles["tokenizer"],
    #         **base_kwargs,
    #     )

    # if spec.loader_kind == "gemma":
    #     # GemmaPrompter expects 'model' and 'processor'
    #     # torch_dtype is controlled by loader, but you can still pass it for logging or later use
    #     return spec.prompter_cls(
    #         model=handles["model"],
    #         processor=handles["processor"],
    #         torch_dtype=getattr(torch, torch_dtype),
    #         **base_kwargs,
    #     )

    raise RuntimeError("Unreachable")