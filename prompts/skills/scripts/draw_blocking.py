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


def blueprint(plan, layout, base_only=False):
    """Draw static geometry and a removable shot overlay in the same square coordinate space."""
    if layout["orientation"] != plan["orientation"]:
        raise ValueError("Shot and base layout must use the same orientation")
    if not layout["features"]:
        raise ValueError("Supply the scene footprint")
    svg = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", role="img")
    ET.SubElement(svg, "title").text = layout["name"]
    def shape(parent, tag, **attrs):
        return ET.SubElement(parent, tag, {k.replace("_", "-"): str(v) for k, v in attrs.items()})

    def xy(p):
        point(p)  # Same normalized coordinate contract as legacy plans.
        return 44 + 6.8*p["x"], 98 + 6.8*p["y"]

    def coords(points):
        return " ".join(f"{x:.1f},{y:.1f}" for x,y in points)

    def text(parent, x, y, value, size=16, **style):
        shape(parent, "text", x=x, y=y, font_size=size, font_family="sans-serif", **style).text = value

    def arrow(parent, a, b):
        shape(parent, "line", x1=a[0], y1=a[1], x2=b[0], y2=b[1], stroke="#232323",
              stroke_width=2.5, stroke_dasharray="7 5")
        theta = math.atan2(b[1]-a[1], b[0]-a[0])
        wings = [(b[0]-12*math.cos(theta+d), b[1]-12*math.sin(theta+d)) for d in (-.46,.46)]
        shape(parent, "polygon", points=coords([wings[0], b, wings[1]]), fill="#232323")

    background = shape(svg, "rect", fill="white")
    text(svg, 32, 44, layout["name"], 29, font_weight="bold")
    text(svg, 32, 70, layout["orientation"], 15, fill="#505050")
    base = shape(svg, "g", id="scene-layout")
    shape(base, "rect", x=32, y=86, width=704, height=704, fill="#fafafa", stroke="#bbbbbb")
    features = layout["features"]
    for kind in ("path", "footprint", "wall", "opening"):
        for f in features:
            if f["kind"] != kind:
                continue
            pts = [xy(p) for p in f["points"]]
            if len(pts) < (3 if kind in {"path","footprint"} else 2):
                raise ValueError("Incomplete layout geometry: " + f["name"])
            if kind in {"path", "footprint"}:
                shape(base, "polygon", points=coords(pts), fill="#eeeeea" if kind == "path" else "#d7d7d4", stroke="#aaa")
            else:
                shape(base, "polyline", points=coords(pts), fill="none", stroke="#353535",
                      stroke_width=5 if kind == "wall" else 2, stroke_dasharray="none" if kind == "wall" else "4 3")
    notes = shape(svg, "g", id="plan-notes")
    cursor = 106
    def note(value, size=17, bold=False):
        nonlocal cursor
        import unicodedata
        line, width = "", 0
        for ch in value:
            advance = size * (1 if unicodedata.east_asian_width(ch) in "WFA" else .6)
            if ch == "\n" or width + advance > 392:
                text(notes, 768, cursor, line, size, font_weight="bold" if bold else "normal")
                cursor += size+7
                line, width = "", 0
                if ch == "\n":
                    continue
            line += ch
            width += advance
        text(notes, 768, cursor, line, size, font_weight="bold" if bold else "normal")
        cursor += size+9

    occupied = []
    def map_label(parent, pos, value):
        w = max(24, sum(15 if ord(ch)>255 else 9 for ch in value)+10)
        for dx, dy in [(9,-13),(9,23),(-w-8,-13),(-w-8,23),(9,-38),(9,49)]:
            x = min(734-w,max(34,pos[0]+dx))
            y = min(782,max(107,pos[1]+dy))
            box = (x,y-16,x+w,y+3)
            if not any(box[0]<r[2] and box[2]>r[0] and box[1]<r[3] and box[3]>r[1] for r in occupied):
                break
        occupied.append(box)
        shape(parent,"rect",x=x,y=y-16,width=w,height=20,rx=3,fill="white",fill_opacity=".9")
        text(parent,x+4,y,value,15)

    for i,f in enumerate(features,1):
        pts = [xy(p) for p in f["points"]]
        center = (sum(p[0] for p in pts)/len(pts),sum(p[1] for p in pts)/len(pts))
        # The IDs identify fixed geometry even when two wall sections share a name.
        map_label(base,center,str(i))

    overlay = shape(svg, "g", id="shot-overlay")
    assets = plan["assets"]
    positions = {a["name"]: xy(a) for a in assets}
    if not base_only:
        note("摄影机", 22, True)
        for i,cam in enumerate(plan["cameras"],1):
            origin = xy(cam)
            sightline = positions[cam["target"]]
            if cam.get("frame"):
                left,right = map(xy,cam["frame"])
                if (left[0]-origin[0])*(right[1]-origin[1]) == (right[0]-origin[0])*(left[1]-origin[1]):
                    raise ValueError("Empty camera field of view")
                sightline = ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2)
                shape(overlay,"polygon",points=coords([origin,left,right]),fill="#89929a",fill_opacity=".12",
                      stroke="#697078",stroke_width=1.6,stroke_dasharray="none" if i%2 else "7 4")
            shape(overlay,"line",x1=origin[0],y1=origin[1],x2=sightline[0],y2=sightline[1],stroke="#606870",stroke_dasharray="2 5")
            shape(overlay,"rect",x=origin[0]-5,y=origin[1]-5,width=10,height=10,fill="#202020")
            map_label(overlay,origin,f"C{i}")
            note(f"C{i}  {cam.get('framing') or cam['target']}",18,True)
            if cam.get("beat"):
                note(cam["beat"])
            cursor += 8
        if plan.get("axis"):
            a,b = (positions[n] for n in plan["axis"])
            shape(overlay,"line",x1=a[0],y1=a[1],x2=b[0],y2=b[1],stroke="#373737",stroke_width=2,stroke_dasharray="12 4 2 4")
            note("动作轴 · " + " — ".join(plan["axis"]), 16)
        for asset in assets:
            x,y = positions[asset["name"]]
            route = [xy(p) for p in asset.get("route", [])]
            if asset.get("end") and (not route or route[-1] != xy(asset["end"])):
                route.append(xy(asset["end"]))
            last = (x,y)
            for stop in route:
                if stop != last:
                    arrow(overlay,last,stop)
                last = stop
            if asset.get("kind") in {"person","animal"}:
                group = shape(overlay,"g",transform=f"translate({x} {y}) rotate({asset.get('heading') or 0})")
                shape(group,"ellipse",cx=0,cy=0,rx=10,ry=7,fill="white",stroke="#181818",stroke_width=2)
                if asset.get("heading") is not None:
                    shape(group,"polygon",points="-4,-6 0,-13 4,-6",fill="#181818")
            else:
                shape(overlay,"circle",cx=x,cy=y,r=5,fill="#262626",stroke="white",stroke_width=1)
            map_label(overlay,(x,y),asset["name"])
        cursor += 14
    note("场地底图",22,True)
    for i,f in enumerate(features,1):
        note(f"{i}   {f['name']}",16)
    if not base_only:
        cursor += 12
        note("扇形为取景范围，点划线为动作轴，箭头为移动方向。",15)
    height = max(816, cursor+18)
    svg.attrib.update(width="1192",height=str(height),viewBox=f"0 0 1192 {height}")
    background.attrib.update(width="1192", height=str(height))
    return ET.tostring(svg,encoding="unicode")


def draw(plan, layout=None, base_only=False):
    embedded = plan.get("layout")
    if layout and embedded and embedded != layout:
        raise ValueError("Shot embeds a different layout")
    if layout or embedded:
        return blueprint(plan, layout or embedded, base_only)
    if base_only:
        raise ValueError("An empty base needs a layout")

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
    parser.add_argument("--layout", type=Path, help="reuse a saved empty scene layout")
    parser.add_argument("--base-only", action="store_true", help="render just the scene layout")
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        layout = json.loads(args.layout.read_text(encoding="utf-8")) if args.layout else None
        args.svg.write_text(draw(plan, layout, args.base_only), encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"{error}\n")
