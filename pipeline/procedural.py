"""Procedural, slow flight through a 3D star field (rendered at half resolution, with glow)."""
import cv2
import numpy as np


class StarField:
    def __init__(self, W, H, seed=1, n=3400, speed=1.0):
        rng = np.random.default_rng(seed)
        self.W, self.H = W, H
        self.w, self.h = W // 2, H // 2
        self.n = n
        self.x = rng.uniform(-1, 1, n) * 1.6
        self.y = rng.uniform(-1, 1, n) * 0.9
        self.z0 = rng.uniform(0.05, 1.0, n)
        self.mag = rng.power(3.0, n)                       # few bright stars, many faint ones
        tint = rng.choice(4, n, p=[0.55, 0.2, 0.15, 0.1])
        palette = np.array([[255, 255, 255], [190, 210, 255], [255, 228, 196], [255, 205, 170]], np.float32)
        self.color = palette[tint] / 255.0
        self.speed = 0.018 * speed                          # depth units per second (slow)
        self.focal = 0.9
        hue = rng.uniform(0, 1)
        self.haze = self._haze(rng, hue)

    def _haze(self, rng, hue):
        """Very faint coloured nebulosity so empty space is never flat black."""
        small = rng.normal(0, 1, (9, 16)).astype(np.float32)
        small = cv2.resize(small, (self.w, self.h), interpolation=cv2.INTER_CUBIC)
        small = cv2.GaussianBlur(small, (0, 0), self.w / 10)
        small = (small - small.min()) / (np.ptp(small) + 1e-6)
        c1 = np.array([0.25 + 0.5 * hue, 0.2, 0.55 - 0.3 * hue], np.float32)
        c2 = np.array([0.1, 0.15 + 0.2 * hue, 0.35], np.float32)
        return (small[..., None] * c1 + (1 - small[..., None]) * c2) * (small[..., None] ** 2) * 60

    def render(self, t, base=None):
        z = (self.z0 - self.speed * t) % 1.0 + 0.02
        sx = (self.x / z * self.focal) * (self.h / 2) + self.w / 2
        sy = (self.y / z * self.focal) * (self.h / 2) + self.h / 2
        inside = (sx >= 0) & (sx < self.w - 1) & (sy >= 0) & (sy < self.h - 1)
        # brightness grows as the star approaches; fade in from far away and at near clip
        b = self.mag * np.clip((1 - z) * 1.4, 0, 1) * np.clip(z * 12, 0, 1)
        img = np.zeros((self.h, self.w, 3), np.float32)
        xi, yi = sx[inside], sy[inside]
        x0, y0 = np.floor(xi).astype(int), np.floor(yi).astype(int)
        fx, fy = xi - x0, yi - y0
        val = (b[inside, None] * self.color[inside]) * 255 * 3.2
        for dx, dy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)),
                          (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            np.add.at(img, (y0 + dy, x0 + dx), val * w[:, None])
        glow = cv2.GaussianBlur(img, (0, 0), 2.5) * 2.6
        img = img + glow + self.haze
        img = cv2.resize(img, (self.W, self.H), interpolation=cv2.INTER_LINEAR)
        if base is not None:
            img = img + base
        return np.clip(img, 0, 255).astype(np.uint8)
