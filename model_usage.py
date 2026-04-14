# Pricing per 1M tokens (USD) for recent OpenAI models, fetched December 29, 2025.
import sys

PRICING = {
    'gpt-5.2': {'input': 1.75, 'cached': 0.175, 'output': 14.00},
    'gpt-5.2-chat-latest': {'input': 1.75, 'cached': 0.175, 'output': 14.00},
    'gpt-5.2-pro': {'input': 21.00, 'cached': 0.0, 'output': 168.00},
    'gpt-5.1': {'input': 1.25, 'cached': 0.125, 'output': 10.00},
    'gpt-5.1-chat-latest': {'input': 1.25, 'cached': 0.125, 'output': 10.00},
    'gpt-5': {'input': 1.25, 'cached': 0.125, 'output': 10.00},
    'gpt-5-chat-latest': {'input': 1.25, 'cached': 0.125, 'output': 10.00},
    'gpt-5-mini': {'input': 0.25, 'cached': 0.025, 'output': 2.00},
    'gpt-5-nano': {'input': 0.05, 'cached': 0.005, 'output': 0.40},
    'gpt-4.1': {'input': 2.00, 'cached': 0.50, 'output': 8.00},
    'gpt-4.1-mini': {'input': 0.40, 'cached': 0.10, 'output': 1.60},
    'gpt-4.1-nano': {'input': 0.10, 'cached': 0.025, 'output': 0.40},
}


def _calculate_cost_usd(model, usage) -> float:
    rates = PRICING.get(model)
    if not rates:
        return 0.0
    input_cost = usage['input'] * rates['input']
    cached_cost = usage['cached'] * rates.get('cached', rates['input'])
    output_cost = usage['output'] * rates['output']
    # Prices are per 1M tokens.
    return (input_cost + cached_cost + output_cost) / 1_000_000


def _aggregate_usage(usages):
    total = {'input': 0, 'cached': 0, 'output': 0, 'reasoning': 0}
    for usage in usages:
        total['input'] += usage.input_tokens
        total['cached'] += usage.input_tokens_details.cached_tokens
        total['output'] += usage.output_tokens
        total['reasoning'] += usage.output_tokens_details.reasoning_tokens
    return total


def print_usage(model, usage, file=sys.stderr):
    print(' Usage '.center(30, '-'), file=file)
    print('Model:', model, file=file)

    if not isinstance(usage, list):
        usage = [usage]
    total = _aggregate_usage(usage)

    for key, value in total.items():
        print(f'{key.title()} (tokens):', value, file=file)

    cost = _calculate_cost_usd(model, total)
    if cost is not None:
        print(f'Total cost (USD): ${cost:.6f}', file=file)
    else:
        print('Total cost: n/a (pricing unavailable for model)', file=file)


def summarize_usage(model, usage) -> dict:
    if not isinstance(usage, list):
        usage = [usage]
    total = _aggregate_usage(usage)
    return {
        'model': model,
        'input_tokens': total['input'],
        'cached_tokens': total['cached'],
        'output_tokens': total['output'],
        'reasoning_tokens': total['reasoning'],
        'cost_usd': _calculate_cost_usd(model, total),
    }


def format_usage_markdown(model, usage) -> str:
    if not isinstance(usage, list):
        usage = [usage]
    total_usage = _aggregate_usage(usage)
    cost = _calculate_cost_usd(model, total_usage)
    token_table = '\n'.join(
        f"| {key.title()} | {value} |"
        for key, value in total_usage.items()
    )

    out = (
        "# Usage\n\n"
        f"**Model**: `{model}`\n\n"
        "|    | Tokens |\n"
        "|----|--------|\n"
        + token_table +
        f"\n\n**Total cost**: ${cost:.6f}\n"
    )
    print(out)
    return out
