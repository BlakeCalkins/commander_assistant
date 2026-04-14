import argparse
import sys
from pathlib import Path
from time import time

from openai import OpenAI

from model_usage import print_usage


def read_prompt_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def main(prompt: str):
    client = OpenAI()
    model = "gpt-5-nano"

    start = time()
    response = client.responses.create(
        model=model,
        input=prompt,
        # reasoning={'effort': 'low'},
    )
    print(response.output_text)
    print(f"{round(time()-start, 2)} seconds elapsed", file=sys.stderr)
    print_usage(model, response.usage)


# Launch app
if __name__ == "__main__":
    parser = argparse.ArgumentParser("AI Response")
    parser.add_argument("prompt_file", type=Path)
    args = parser.parse_args()
    main(read_prompt_file(args.prompt_file))
