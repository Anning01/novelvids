"""Recover an asset object whose named fields spilled into its enclosing JSON array."""


def unpack_asset_rows(rows, fields):
    if not isinstance(rows, list):
        return rows
    result = []
    index = 0
    while index < len(rows):
        item = rows[index]
        if isinstance(item, dict):
            result.append(dict(item))
            index += 1
            continue
        if not isinstance(item, str) or item not in fields or index + 1 >= len(rows):
            return rows
        if item == "name":
            result.append({})
        if not result or item in result[-1]:
            return rows
        result[-1][item] = rows[index + 1]
        index += 2
    for row in result:
        visual = row.get("visual_fields")
        if not isinstance(visual, str) or visual.count("':'") != 1:
            continue
        key, value = visual.split("':'")
        spill = {k: v for k, v in row.items() if k not in fields}
        if not key or key in spill or not all(isinstance(v, str) for v in spill.values()):
            continue
        for field in spill:
            del row[field]
        row["visual_fields"] = {key: value, **spill}
    return result
