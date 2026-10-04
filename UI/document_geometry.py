"""Bounded backing resolution and independent screen-space instrument geometry."""
import math
from PySide6.QtCore import QPointF

MAX_BACKING_PIXELS = 12_000_000
MAX_BACKING_EDGE = 4096
MIN_BACKING_EDGE = 2048


def backing_scale(width, height, device_ratio=1.0, *, minimum_edge=MIN_BACKING_EDGE):
    """Physical pixels per logical pixel; never changes document display size."""
    width, height = max(1.0, float(width)), max(1.0, float(height))
    desired = max(1.0, float(device_ratio), minimum_edge / max(width, height))
    return min(desired, MAX_BACKING_EDGE / max(width, height),
               math.sqrt(MAX_BACKING_PIXELS / (width * height)))


def local_point(point, center, angle):
    delta = point - center
    radians = math.radians(angle)
    c, s = math.cos(radians), math.sin(radians)
    return QPointF(delta.x() * c + delta.y() * s, -delta.x() * s + delta.y() * c)


def snapped_angle(angle, force=False):
    nearest = round(angle / 45) * 45
    return (nearest if force or abs(nearest - angle) <= 5 else angle) % 360


def ruler_tick_step(pixels_per_mm):
    # Avoid overlapping labels at low zoom, while retaining true PDF units.
    return next((step for step in (1, 2, 5, 10, 20, 50, 100)
                 if step * pixels_per_mm >= 5), 100)
