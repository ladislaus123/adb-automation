import re
import time
import xml.etree.ElementTree as ET

from .adb import run_adb
from .errors import AutomationError

DUMP_REMOTE_PATH = "/sdcard/window_dump.xml"
BOUNDS_PATTERN = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def dump_ui_xml(serial, run_adb_command=run_adb):
    run_adb_command(["shell", "uiautomator", "dump", DUMP_REMOTE_PATH], serial=serial)
    return run_adb_command(["shell", "cat", DUMP_REMOTE_PATH], serial=serial)


def parse_bounds(bounds):
    match = BOUNDS_PATTERN.match(bounds or "")
    if not match:
        return None
    x1, y1, x2, y2 = (int(value) for value in match.groups())
    return (x1, y1, x2, y2)


def bounds_center(bounds):
    parsed = parse_bounds(bounds)
    if not parsed:
        return None
    x1, y1, x2, y2 = parsed
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def parse_ui_dump(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise AutomationError(f"Could not parse uiautomator dump: {exc}") from exc

    elements = []
    for node in root.iter("node"):
        elements.append(
            {
                "resource_id": node.get("resource-id") or "",
                "text": node.get("text") or "",
                "content_desc": node.get("content-desc") or "",
                "class_name": node.get("class") or "",
                "clickable": node.get("clickable") == "true",
                "bounds": node.get("bounds") or "",
            }
        )
    return elements


def element_matches(element, selector):
    kind, value = selector
    if kind == "id":
        return element["resource_id"] == value
    if kind == "accessibility":
        return element["content_desc"] == value
    if kind == "text":
        return element["text"] == value
    return False


def find_first(elements, selectors):
    for selector in selectors:
        for element in elements:
            if element_matches(element, selector):
                return element
    return None


def tap_point(serial, x, y, run_adb_command=run_adb):
    run_adb_command(
        ["shell", "input", "tap", str(int(x)), str(int(y))],
        serial=serial,
    )


def tap_element(serial, element, run_adb_command=run_adb):
    center = bounds_center(element.get("bounds"))
    if not center:
        raise AutomationError(f"Element has no usable bounds: {element}")
    tap_point(serial, center[0], center[1], run_adb_command=run_adb_command)
    return center


def wait_for_first(
    serial,
    selectors,
    timeout=6,
    interval=0.3,
    run_adb_command=run_adb,
    sleep=time.sleep,
):
    deadline = time.monotonic() + timeout
    while True:
        xml_text = dump_ui_xml(serial, run_adb_command=run_adb_command)
        elements = parse_ui_dump(xml_text)
        found = find_first(elements, selectors)
        if found is not None:
            return found
        if time.monotonic() >= deadline:
            return None
        sleep(interval)


def click_first(
    serial,
    selectors,
    timeout=6,
    interval=0.3,
    run_adb_command=run_adb,
    sleep=time.sleep,
):
    element = wait_for_first(
        serial,
        selectors,
        timeout=timeout,
        interval=interval,
        run_adb_command=run_adb_command,
        sleep=sleep,
    )
    if element is None:
        return False
    tap_element(serial, element, run_adb_command=run_adb_command)
    return True
