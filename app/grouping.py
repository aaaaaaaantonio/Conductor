from collections import defaultdict
from typing import Callable, TypeVar

T = TypeVar("T")
K = TypeVar("K")


def group_by(items: list[T], key_fn: Callable[[T], K]) -> dict[K, list[T]]:
    grouped: dict[K, list[T]] = defaultdict(list)
    for item in items:
        grouped[key_fn(item)].append(item)
    return grouped
