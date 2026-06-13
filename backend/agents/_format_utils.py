from __future__ import annotations


def to_compact(data) -> str:
    """Convert dict/list-of-dicts to compact pipe-delimited string for LLM input.

    Reduces token count ~50% vs JSON/str() for tabular data.
    """
    if data is None:
        return "null"
    if isinstance(data, list):
        if not data:
            return "[]"
        if isinstance(data[0], dict):
            keys = list(data[0].keys())
            header = "|".join(str(k) for k in keys)
            rows = "\n".join(
                "|".join(str(row.get(k, "")) for k in keys) for row in data
            )
            return f"{header}\n{rows}"
        return "|".join(str(v) for v in data)
    if isinstance(data, dict):
        if not data:
            return "{}"
        lines: list[str] = []
        scalars: list[str] = []
        for k, v in data.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                lines.append(f"[{k}]\n{to_compact(v)}")
            elif isinstance(v, dict):
                lines.append(f"[{k}]\n{to_compact(v)}")
            elif isinstance(v, list):
                scalars.append(f"{k}={('|'.join(str(i) for i in v)) or '[]'}")
            else:
                scalars.append(f"{k}={v}")
        if scalars:
            lines.insert(0, "\n".join(scalars))
        return "\n\n".join(lines)
    return str(data)
