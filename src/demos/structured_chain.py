#!/usr/bin/env python3
"""
Run with e.g.:
  echo "RUNNING GPT RUNNING GPT RUNNING GPT RUNNING GPT RUNNING GPT RUNNING GPT 
  python ./src/demos/structured_chain.py --model_type gpt --device_map 0 --show_prompt 0

  echo "RUNNING LLAMA RUNNING LLAMA RUNNING LLAMA RUNNING LLAMA RUNNING LLAMA RUNNING LLAMA 
  python ./src/structured_chain.py --model_type llama --device_map 2 --show_prompt 0

  echo "RUNNING MISTRAL RUNNING MISTRAL RUNNING MISTRAL RUNNING MISTRAL RUNNING MISTRAL RUNNING LLAMA 
  python ./src/structured_chain.py --model_type mistral --device_map 1  --show_prompt 0
  
  echo "RUNNING GEMMA RUNNING GEMMA RUNNING GEMMA RUNNING GEMMA RUNNING GEMMA RUNNING GEMMA 
  python ./src/structured_chain.py --model_type gemma --device_map 3 --show_prompt 0
"""
import sys; sys.path.append("./src")
import argparse
import json
import os
from utils.prompter_factory import make_prompter

def parse_args():
    parser = argparse.ArgumentParser(
        description="Run structured output demo with a single shared model instance."
    )
    parser.add_argument(
        "--model_type",
        type=str,
        default="gpt",
        choices=["gpt", "llama", "mistral", "gemma"],
    )
    parser.add_argument(
        "--device_map",
        type=int,               # force integers
        required=True,
        help="0, 1, 2, or 3 (on a four gpu server)." # on a four gpu server.
    )
    parser.add_argument("--show_prompt", type=int, default=0)
    parser.add_argument("--fatemeh_server", type=int, default=0)
    return parser.parse_args()


def main():
    args = parse_args()
    show_prompt = bool(args.show_prompt)

    # ---------- Build both prompters; weights are shared via factory cache ----------
    demo1 = make_prompter(
        model_name=args.model_type,
        device_map=args.device_map,  # <-- pass raw; factory normalizes
        prompt_path="./src/utils/prompts/demo/demo1.yaml",
        prompt_headers={"question": "HERE IS THE QUESTION:"},
        temperature=0.01,
        show_prompt=show_prompt,
    )

    demo2 = make_prompter(
        model_name=args.model_type,
        device_map=args.device_map,  # <-- pass raw; factory normalizes
        prompt_path="./src/utils/prompts/demo/demo2.yaml",
        prompt_headers={
            "question": "HERE IS THE QUESTION:",
            "brainstorm": "HERE IS THE BRAINSTORM:",
        },
        show_prompt=show_prompt,
    )

    # ---------- Run ----------
    question = "Who was the first major league baseball player to come out as gay?"
    out1 = demo1.get_completion({"question": question})
    brainstorm = out1.get("brainstorm") if isinstance(out1, dict) else ""
    out2 = demo2.get_completion({"question": question, "brainstorm": brainstorm or ""})
    print(json.dumps(out2, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()