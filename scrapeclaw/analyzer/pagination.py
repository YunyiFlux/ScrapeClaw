"""Pagination Parameter & Stepping Inferencer."""
from typing import Dict, Any, Tuple, Optional

def infer_pagination_diff(
    base_params: Dict[str, Any],
    next_params: Dict[str, Any]
) -> Tuple[Optional[str], int, str]:
    """
    Infer pagination parameter by diffing two query parameter dictionaries.
    Returns: (param_name, step, kind)
    """
    for key, val in next_params.items():
        if key in base_params:
            base_val = base_params[key]
            try:
                b_int = int(base_val)
                n_int = int(val)
                if n_int > b_int:
                    diff = n_int - b_int
                    kind = "offset_limit" if diff > 1 else "page_number"
                    return key, diff, kind
            except (ValueError, TypeError):
                if str(val) != str(base_val):
                    return key, 1, "cursor"
    return None, 1, "none"
