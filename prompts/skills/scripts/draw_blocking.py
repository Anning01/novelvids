"""Draw one shared overhead camera plan. Usage: python draw_blocking.py plan.json plan.svg"""

import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def point(item):
    x, y = item["x"], item["y"]
    if not all(type(value) is int and 0 <= value <= 100 for value in (x, y)):
        raise ValueError("Use integer coordinates from 0 to 100")
    return 68 + 6 * x, 64 + 3 * y


def draw(plan):
    svg = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", viewBox="0 0 736 420",
                     width="736", height="420", role="img")
    ET.SubElement(svg, "title").text = plan["orientation"]
    ET.SubElement(svg, "rect", width="736", height="420", fill="white")
    def label(x, y, text):
        node = ET.SubElement(svg, "text", x=str(x), y=str(y), fill="#222",
                             **{"font-size": "15", "font-family": "sans-serif", "text-anchor": "middle"})
        node.text = text

    def line(start, end, dashed=False):
        attrs = {"stroke-dasharray": "5 5"} if dashed else {}
        ET.SubElement(svg, "line", x1=str(start[0]), y1=str(start[1]), x2=str(end[0]), y2=str(end[1]),
                      stroke="#333", **attrs)
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length:
            ux, uy = dx / length, dy / length
            # Leave the asset marker visible at the end of a sightline.
            x, y = end[0] - 5 * ux, end[1] - 5 * uy
            left = (x - 9 * ux - 4 * uy, y - 9 * uy + 4 * ux)
            right = (x - 9 * ux + 4 * uy, y - 9 * uy - 4 * ux)
            ET.SubElement(svg, "polyline", points=f"{left[0]:.1f},{left[1]:.1f} {x:.1f},{y:.1f} {right[0]:.1f},{right[1]:.1f}",
                          stroke="#333", fill="none")

    label(368, 25, "↑ " + plan["orientation"])
    ET.SubElement(svg, "rect", x="20", y="36", width="696", height="364", fill="none", stroke="#999")
    assets = plan["assets"]
    positions = {asset["name"]: point(asset) for asset in assets}
    cameras = plan["cameras"]
    if not positions or len(assets) != len(positions) or not cameras:
        raise ValueError("Provide uniquely named assets and cameras in cut order")
    for camera in cameras:
        line(point(camera), positions[camera["target"]], dashed=True)
    for asset in assets:
        x, y = positions[asset["name"]]
        if asset.get("end"):
            line((x, y), point(asset["end"]))
        ET.SubElement(svg, "circle", cx=str(x), cy=str(y), r="4", fill="white", stroke="#222")
        label(x, y - 10, asset["name"] + (" · " + asset["facing"] if asset.get("facing") else ""))
    # A camera can stay in place for multiple cuts to different subjects.
    ids = {}
    for i, cam in enumerate(cameras, 1):
        ids.setdefault(point(cam), []).append(f"C{i}")
    for (x, y), names in ids.items():
        ET.SubElement(svg, "rect", x=str(x - 4), y=str(y - 4), width="8", height="8", fill="#333")
        label(x, y + 19, "/".join(names))
    return ET.tostring(svg, encoding="unicode")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("svg", type=Path)
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        args.svg.write_text(draw(plan), encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"{error}\n")
