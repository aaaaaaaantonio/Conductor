from collections import defaultdict
from collections.abc import Callable


def group_by[T, K](items: list[T], key_fn: Callable[[T], K]) -> dict[K, list[T]]:
    grouped: dict[K, list[T]] = defaultdict(list)
    for item in items:
        grouped[key_fn(item)].append(item)
    return grouped
