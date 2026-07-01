from dataclasses import dataclass


@dataclass
class DupGroup:
    lower_name: str
    variants: list[tuple[int, str, int]]  # (id, name, recipe_count)
