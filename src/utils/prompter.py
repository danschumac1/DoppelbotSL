'''
2025-03-09
Author: Dan Schumacher
How to run:
   python ./src/utils/prompter.py
'''
import base64
import os
import importlib
import json
from typing import List, Dict, Optional, Tuple, Type, Union
from abc import ABC, abstractmethod
import time
from pydantic import BaseModel
import yaml
from dotenv import load_dotenv
import torch
torch.cuda.empty_cache()
import re
from json_repair import repair_json
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from openai import OpenAIError


import openai
from transformers import (
    AutoTokenizer, 
    BitsAndBytesConfig, 
    AutoModelForCausalLM, 
    Gemma3ForConditionalGeneration, 
    AutoProcessor,
    # pipeline
    )

from utils.logging_utils import MasterLogger

from typing import Optional
from contextlib import suppress

def _load_hf_or_adapter(
    *,
    base_model_id: str,
    adapter_id: Optional[str],
    device_map,
    torch_dtype,
    trust_remote_code: bool = False,
    use_fast_tokenizer: Optional[bool] = None,
    quantization_config=None,
):
    """
    Load a full HF causal model from `base_model_id`.
    If `adapter_id` is given, apply a PEFT adapter on top (and try merging).
    Returns (model, tokenizer).
    """
    from transformers import AutoTokenizer, AutoModelForCausalLM
    tok_kwargs = {}
    if use_fast_tokenizer is not None:
        tok_kwargs["use_fast"] = use_fast_tokenizer
    if trust_remote_code:
        tok_kwargs["trust_remote_code"] = True

    tokenizer = AutoTokenizer.from_pretrained(base_model_id, **tok_kwargs)
    if tokenizer.pad_token is None and tokenizer.eos_token is not None:
        tokenizer.pad_token = tokenizer.eos_token

    model_kwargs = {
        "device_map": device_map,
        "torch_dtype": torch_dtype,
    }
    if trust_remote_code:
        model_kwargs["trust_remote_code"] = True
    if quantization_config is not None:
        model_kwargs["quantization_config"] = quantization_config

    model = AutoModelForCausalLM.from_pretrained(base_model_id, **model_kwargs)

    if adapter_id:
        # Apply LoRA adapter
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter_id)
        # Optional merge (saves VRAM at inference; skip if it fails)
        with suppress(Exception):
            model = model.merge_and_unload()

    return model, tokenizer
    

class QAs(BaseModel):
    question: Dict[str, str]  # Multiple inputs as a dictionary
    answer: Union[BaseModel, str]   # Allow both strings and BaseModel

class Prompter(ABC):
    def __init__(
        self,
        prompt_path: Optional[str],
        prompt_headers: Dict[str, str],
        llm_model: str = "gpt-4o-mini",
        temperature: float = 0.1,
        show_prompt: bool = True,
        device_map: int = 0,  # Default to GPU0
        repetition_penalty: float = 1.1
    ):
        self.llm_model = llm_model
        self.prompt_path = prompt_path
        self.prompt_headers = prompt_headers
        self.temperature = temperature
        self.first_print = True
        self.show_prompt = show_prompt
        self.device_map = device_map
        self.repetition_penalty = repetition_penalty
        (
            self.output_format_class,
            self.examples,
            self.system_prompt,
            self.main_prompt_header,
            self.prompt_headers,
            self.is_structured_output  # ← add this line
        ) = self._load_yaml_examples_with_model()

        self.format_examples()


    def __repr__(self) -> str:
        return f"Prompter(model={self.llm_model}, examples={len(self.examples)})"

    def _load_yaml_examples_with_model(self) -> Tuple[Type[BaseModel], List[QAs], str, str, Dict[str, str], bool]:
        with open(self.prompt_path, "r") as f:
            raw = yaml.safe_load(f)

        meta = raw.get("__meta__", {})
        model_path = meta.get("output_model")
        if not model_path:
            raise ValueError("YAML file must contain __meta__.output_model")

        unstructured_aliases = {"simple_string", "string", "str"}
        if model_path in unstructured_aliases:
            model_class = str
            is_structured = False
        else:
            try:
                module_name, class_name = model_path.rsplit(".", 1)
                model_module = importlib.import_module(module_name)
                model_class = getattr(model_module, class_name)
                is_structured = True
            except (ValueError, ImportError, AttributeError) as e:
                raise ImportError(
                    f"Could not load output_model '{model_path}'. Either:\n"
                    f"  - Use one of: {unstructured_aliases}, or\n"
                    f"  - Provide a valid import path like 'my_module.MyModelClass'\n"
                    f"Full error: {e}"
                )

        system_prompt = raw.get("system_prompt", "You are a helpful assistant.")
        main_prompt_header = raw.get("main_prompt_header", "")
        prompt_headers = raw.get("prompt_headers", {})
        # print(raw.get("examples", []))
        examples = [
            QAs(
                question=ex["input"], 
                answer=model_class(**ex["output"]) if is_structured else ex["output"])
            for ex in raw.get("examples", [])
        ]

        return model_class, examples, system_prompt, main_prompt_header, prompt_headers, is_structured

    def format_q_as_string(self, question_dict: Dict[str, str]) -> str:
        """Formats multiple question fields for the LLM"""
        formatted_questions = "\n\n".join(
            f"{self.prompt_headers.get(key, key).upper()}: {value}" for key, value in question_dict.items()
        )

        if self.is_structured_output:
            prompt = (
                f"{formatted_questions}\n"
                f"Provide your response in JSON format using the schema below:\n"
                f"{self.output_format_class.model_json_schema()}\n"
                f"Do not include any extra text, explanations, or comments outside the JSON object."
            )
        else:
            prompt = (
                f"{formatted_questions}\n"
                f"Answer the question clearly and concisely. Do not include explanations unless asked."
            )

        return prompt

    def format_examples(self):
        """Formats few-shot examples by prepending prompt headers"""
        for qa in self.examples:
            qa.question = self.format_q_as_string(qa.question)
            if isinstance(qa.answer, BaseModel):
                qa.answer = qa.answer.model_dump_json()

    def add_examples_posthoc(self, examples: List[QAs]):
        """Allows adding examples after initialization."""
        self.examples.extend(examples)
        self.format_examples()
        

    @abstractmethod
    def parse_output(self, llm_output: str):
        """Extract response-text from the LLM output"""
        pass

    @abstractmethod
    def get_completion(self, user_inputs: Dict[str, str]) -> str:
        """Send the prompt to the LLM and get a response"""
        pass

# === OpenAI Implementation ===
class OpenAIPrompter(Prompter):
    def __init__(self, llm_model="gpt-4o-mini", **kwargs):
        super().__init__(**kwargs)
        self.client = openai.Client(api_key=self._load_env())

    def _load_env(self) -> str:
        """Loads API key from .env"""
        load_dotenv("./resources/.env")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(f"API Key not found. Set OPENAI_API_KEY=xxxx in ./resources/.env")
        return api_key
    
    def parse_output(self, llm_output) -> Union[str, dict]:
        """Parses LLM output based on structured/unstructured mode"""
        content = llm_output.choices[0].message.content.strip()

        if self.is_structured_output:
            try:
                content = repair_json(content, return_objects=True)
                return content
            except json.JSONDecodeError:
                raise ValueError(f"Expected JSON but got invalid response:\n{content}")
        else:
            return content  # raw string
        
    def add_image(self, input_dict: Dict[str, str], image_path: str):
        with open(image_path, "rb") as img:
            base64_img = base64.b64encode(img.read()).decode("utf-8")
        input_dict["__image__"] = f"data:image/png;base64,{base64_img}"


    def _build_messages(self, input_texts: Dict[str, str], override_examples: List[QAs] | None = None):
        messages = [{"role": "system", "content": self.system_prompt}]
        examples = override_examples if override_examples is not None else self.examples

        # Add few-shot examples (already pre-formatted)
        for qa in examples:
            messages.append(
                {"role": "user", "content": f"{self.main_prompt_header}\n{qa.question}"}
                )
            messages.append(
                {"role": "assistant", "content": qa.answer}
                )


        # Format final user input
        user_input_prompt = self.format_q_as_string(input_texts)
        if "__image__" in input_texts:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_input_prompt},
                    {"type": "image_url", "image_url": {"url": input_texts["__image__"]}}
                ]
            })
        else:
            messages.append({"role": "user", "content": f"{self.main_prompt_header}\n{user_input_prompt}"})


        if self.show_prompt and self.first_print:
            self.first_print = False
            print("=" * 50)
            print("=" * 17, "EXAMPLE PROMPT", "=" * 17)
            print(json.dumps(messages, indent=4))
            print("=" * 50)

        return messages

    def format_examples_static(self, examples: List[QAs]) -> List[QAs]:
        """Return a formatted copy of examples without mutating self.examples."""
        from copy import deepcopy
        formatted = deepcopy(examples)
        for qa in formatted:
            qa.question = self.format_q_as_string(qa.question)
            if isinstance(qa.answer, BaseModel):
                qa.answer = qa.answer.model_dump_json()
        return formatted


    def get_completion(
        self,
        input_texts: Union[Dict[str, str], List[Dict[str, str]]],
        parse: bool = True,
        verbose: bool = False,
        max_workers: int = 10,
        sleep_between: float = 0.0,
        per_input_examples: Optional[List[List[QAs]]] = None,
        request_timeout: float = 60.0,
    ) -> Union[dict, List[Union[dict, str]]]:
        """
        Unified completion for single or batched OpenAI chat calls.

        Parameters
        ----------
        input_texts : dict | list[dict]
            A single input dict or a list of input dicts. Each dict is the fields your prompt expects,
            e.g. {"question": {"question": "...", "context": "..."}}
        parse : bool, default True
            If True, parse response via self.parse_output(). If False, return raw response object.
        verbose : bool, default False
            If True, pretty-print parsed outputs.
        max_workers : int, default 10
            Max threads for batched requests.
        sleep_between : float, default 0.0
            Optional sleep (seconds) before each request (useful for rate limiting).
        per_input_examples : list[list[QAs]] | None, default None
            Optional few-shot examples per input. If provided, length must equal len(input_texts).
            Each inner list is formatted into user/assistant pairs ONLY for that specific input.
        request_timeout : float, default 60.0
            Timeout (seconds) for each future.result() call.

        Returns
        -------
        dict | list[dict|str]
            Parsed result for single input, or a list of parsed results for batched inputs.
            On errors, an item may be a dict like {"error": "..."}.
        """

        # Normalize to list for a unified path
        if isinstance(input_texts, dict):
            input_texts = [input_texts]

        n = len(input_texts)

        # Validate per-input examples shape if provided
        if per_input_examples is not None and len(per_input_examples) != n:
            raise ValueError("per_input_examples must be the same length as input_texts.")

        # Helper: format examples without mutating self.examples (thread-safe)
        def _format_examples_static(examples: List[QAs]) -> List[QAs]:
            from copy import deepcopy
            formatted = deepcopy(examples)
            for qa in formatted:
                # qa.question is a Dict[str, str]
                qa.question = self.format_q_as_string(qa.question)
                if isinstance(qa.answer, BaseModel):
                    qa.answer = qa.answer.model_dump_json()
            return formatted

        # Worker to call API for a single input
        def call_single(i: int, input_dict: Dict[str, str], local_examples: Optional[List[QAs]]):
            if sleep_between > 0:
                time.sleep(sleep_between)

            # Format per-input examples if provided
            formatted_local_examples = _format_examples_static(local_examples) if local_examples else None

            # Build messages (use override examples when provided)
            messages = self._build_messages(input_dict, override_examples=formatted_local_examples)

            completion_kwargs = {
                "model": self.llm_model,
                "messages": messages,
                "temperature": self.temperature,
            }
            if self.is_structured_output:
                completion_kwargs["response_format"] = {"type": "json_object"}

            response = self.client.chat.completions.create(**completion_kwargs)
            parsed = self.parse_output(response) if parse else response

            if verbose:
                print(f"\n=== OUTPUT {i} ===")
                try:
                    print(json.dumps(parsed, indent=2))
                except TypeError:
                    # Fallback if parsed is not JSON-serializable (e.g., raw response object)
                    print(parsed)

            return i, parsed

        results: List[Optional[Union[dict, str]]] = [None] * n

        # Launch threaded batch
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for i, inp in enumerate(input_texts):
                local_ex = per_input_examples[i] if per_input_examples is not None else None
                futures.append(executor.submit(call_single, i, inp, local_ex))

            for future in as_completed(futures):
                try:
                    i, result = future.result(timeout=request_timeout)
                    results[i] = result
                except TimeoutError:
                    results[i] = {"error": "TimeoutError: request took too long"}
                except openai.OpenAIError as e:
                    results[i] = {"error": f"OpenAIError: {str(e)}"}
                except Exception as e:
                    results[i] = {"error": f"UnexpectedError: {type(e).__name__}: {str(e)}"}

        # Return single element or list
        return results[0] if n == 1 else results

class HFPrompter(Prompter):
    def __init__(
        self,
        llm_model: str,
        model=None,
        tokenizer=None,
        max_new_tokens: int = 2000,
        temperature: float = 0.1,
        quantize: bool = False,
        device_map: Union[int, List[int], dict, str] = 0,
        torch_dtype=torch.float16,
        # ⬇️ NEW: adapter support
        base_model_id: Optional[str] = None,   # e.g., "Qwen/Qwen2.5-7B-Instruct"
        adapter_id: Optional[str] = None,      # e.g., "Time-MQA/Qwen-2.5-7B"
        trust_remote_code: Optional[bool] = None,  # Qwen often needs True
        use_fast_tokenizer: Optional[bool] = None, # Llama typically True
        merge_adapter: bool = True,            # keep for API symmetry; we merge in helper
        **kwargs,
    ):
        super().__init__(llm_model=llm_model, temperature=temperature, **kwargs)

        self.max_new_tokens = max_new_tokens
        self.first_print = True

        # If a shared model/tokenizer is passed, honor it and bail early
        if model is not None and tokenizer is not None:
            self.model = model
            self.tokenizer = tokenizer
            if self.tokenizer.pad_token is None and self.tokenizer.eos_token is not None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            return

        # Build common kwargs
        model_device_map = device_map

        quantization_config = None
        if quantize:
            quantization_config = BitsAndBytesConfig(
                load_in_8bit=True,
                bnb_4bit_compute_dtype=torch.float16
            )

        # Decide loading path:
        # - If adapter_id is provided, we must have a base_model_id to load first.
        # - Else, treat llm_model as a full checkpoint and load normally.
        if adapter_id is not None:
            if not base_model_id:
                # Allow llm_model to be base if user forgot to pass base_model_id
                base_model_id = llm_model
            model, tokenizer = _load_hf_or_adapter(
                base_model_id=base_model_id,
                adapter_id=adapter_id,
                device_map=model_device_map,
                torch_dtype=torch_dtype,
                trust_remote_code=bool(trust_remote_code),
                use_fast_tokenizer=use_fast_tokenizer,
                quantization_config=quantization_config,
            )
            self.model, self.tokenizer = model, tokenizer
        else:
            # Regular full checkpoint
            tok_kwargs = {}
            if use_fast_tokenizer is not None:
                tok_kwargs["use_fast"] = use_fast_tokenizer
            if trust_remote_code:
                tok_kwargs["trust_remote_code"] = True

            self.tokenizer = AutoTokenizer.from_pretrained(llm_model, **tok_kwargs)
            if self.tokenizer.pad_token is None and self.tokenizer.eos_token is not None:
                self.tokenizer.pad_token = self.tokenizer.eos_token

            model_kwargs = {
                "device_map": model_device_map,
                "torch_dtype": torch_dtype,
            }
            if trust_remote_code:
                model_kwargs["trust_remote_code"] = True
            if quantization_config is not None:
                model_kwargs["quantization_config"] = quantization_config

            self.model = AutoModelForCausalLM.from_pretrained(llm_model, **model_kwargs)


    def parse_output(self, llm_output) -> Union[str, dict]:
        """Parses LLM output based on structured/unstructured mode"""
        
        content = llm_output.strip()

        if not self.is_structured_output:
            return content

        # Extract first JSON-like block
        match = re.search(r"\{.*", content, re.DOTALL)
        if not match:
            raise ValueError(f"Could not find a JSON object in output:\n{content}")
        
        json_candidate = match.group(0)

        try:
            return repair_json(json_candidate, return_objects=True)
        except Exception as e:
            raise ValueError(f"Output could not be repaired to valid JSON:\n{json_candidate}\nError: {e}")



    def _build_messages(self, input_texts: Dict[str, str]) -> List[Dict[str, str]]:
        messages = [{"role": "system", "content": self.system_prompt}]
        for qa in self.examples:
            messages.append({"role": "user", "content": f"{self.main_prompt_header}\n{qa.question}"})
            messages.append({"role": "assistant", "content": qa.answer})
        final_prompt = self.format_q_as_string(input_texts)
        messages.append({"role": "user", "content": f"{self.main_prompt_header}\n{final_prompt}"})

        if self.show_prompt and self.first_print:
            self.first_print = False
            print("=" * 50)
            print("=" * 17, "EXAMPLE PROMPT", "=" * 17)
            print(json.dumps(messages, indent=4))
            print("=" * 50)

        return messages

    def get_completion(
            self, 
            input_texts: Union[Dict[str, str],List[Dict[str, str]]], 
            parse=True
            ) -> Union[dict, List[dict], str]:
        if isinstance(input_texts, dict):
            input_texts = [input_texts]

        messages_list = [self._build_messages(item) for item in input_texts]

        prompts = [
            self.tokenizer.apply_chat_template(m, add_generation_prompt=True, tokenize=False)
            for m in messages_list
        ]
        inputs = self.tokenizer(
            prompts,
            return_tensors="pt",
            padding=True,
            truncation=True,
        )

        input_ids = inputs["input_ids"].to(self.model.device)
        attention_mask = inputs["attention_mask"].to(self.model.device)

        outputs = self.model.generate(
            input_ids=input_ids,
            attention_mask=attention_mask,
            max_new_tokens=self.max_new_tokens,
            repetition_penalty=self.repetition_penalty,
            return_dict_in_generate=True,
            pad_token_id=self.tokenizer.eos_token_id,
        )

        generated_sequences = outputs.sequences
        results = []
        for i in range(len(generated_sequences)):
            input_len = (input_ids[i] != self.tokenizer.pad_token_id).sum().item()
            gen_tokens = generated_sequences[i][input_len:]
            decoded = self.tokenizer.decode(gen_tokens, skip_special_tokens=True)
            results.append(self.parse_output(decoded) if parse else decoded)

        return results[0] if len(results) == 1 else results

class GemmaPrompter(Prompter):
    def __init__(
        self,
        llm_model: str = "google/gemma-3-12b-it",
        model=None,
        processor=None,
        max_new_tokens: int = 2000,
        temperature: float = 0.1,
        device_map: Union[int, List[int], dict, str] = 0,
        torch_dtype=torch.bfloat16,
        **kwargs,
    ):
        super().__init__(llm_model=llm_model, temperature=temperature, **kwargs)

        self.max_new_tokens = max_new_tokens
        self.temperature = temperature

        # SDP settings
        torch.backends.cuda.enable_mem_efficient_sdp(False)
        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_math_sdp(True)

        # Use shared model if provided
        if model is not None and processor is not None:
            self.model = model
            self.processor = processor
        else:
            self.processor = AutoProcessor.from_pretrained(llm_model, use_fast=True)
            self.processor.tokenizer.pad_token = self.processor.tokenizer.eos_token  # ✅ Required
            device_map = device_map

            self.model = Gemma3ForConditionalGeneration.from_pretrained(
                llm_model,
                device_map=device_map,
                torch_dtype=torch_dtype,
            )

    def _build_messages(self, input_texts: Dict[str, str]) -> List[Dict[str, Union[str, List[Dict[str, str]]]]]:
        messages = []

        # ✅ System message
        messages.append({
            "role": "system",
            "content": [{"type": "text", "text": str(self.system_prompt)}]
        })

        # ✅ Few-shot examples
        for example in self.examples:
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": str(example.question)}]
            })
            messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": str(example.answer)}]
            })

        # ✅ Actual question
        user_input = self.format_q_as_string(input_texts)
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": str(user_input)}]
        })

        return messages

    def parse_output(self, generated_text: str) -> Union[str, dict]:
        cleaned = generated_text.strip().split("<|file_separator|>")[0].strip()

        if not self.is_structured_output:
            return cleaned

        match = re.search(r"\{.*", cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"Could not find a JSON object in output:\n{cleaned}")

        json_candidate = match.group(0)
        try:
            return repair_json(json_candidate, return_objects=True)
        except Exception as e:
            raise ValueError(f"Output could not be repaired to valid JSON:\n{json_candidate}\nError: {e}")

    def get_completion(
        self,
        input_texts: Union[Dict[str, str], List[Dict[str, str]]],
        parse: bool = True
    ) -> Union[dict, List[dict], str]:
        if isinstance(input_texts, dict):
            input_texts = [input_texts]

        # Step 1: Build prompts from messages
        all_messages = [self._build_messages(entry) for entry in input_texts]

        raw_prompts = []
        for i, messages in enumerate(all_messages):
            prompt = self.processor.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=False
            )
            if not isinstance(prompt, str):
                raise ValueError(f"apply_chat_template returned invalid prompt at index {i}")
            raw_prompts.append(prompt)

        # Step 2: Tokenize batch
        self.processor.tokenizer.pad_token = self.processor.tokenizer.eos_token  # ✅ Ensure padding works
        tokenized = self.processor(
            text=raw_prompts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=8192 
        ).to(self.model.device, dtype=self.model.dtype)

        input_ids = tokenized["input_ids"]
        attention_mask = tokenized["attention_mask"]
        input_lengths = (input_ids != self.processor.tokenizer.pad_token_id).sum(dim=1)

        # Step 3: Generate
        with torch.inference_mode():
            outputs = self.model.generate(
                input_ids=input_ids,
                attention_mask=attention_mask,
                max_new_tokens=self.max_new_tokens,
                do_sample=True,
                temperature=self.temperature,
                top_p=0.95,
                top_k=50,
                pad_token_id=self.processor.tokenizer.pad_token_id,
            )

        # Step 4: Decode + parse
        results = []
        for i in range(outputs.shape[0]):
            generated_tokens = outputs[i][input_lengths[i]:]
            decoded = self.processor.decode(generated_tokens, skip_special_tokens=True)
            parsed = self.parse_output(decoded) if parse else decoded
            results.append(parsed)

        return results[0] if len(results) == 1 else results
