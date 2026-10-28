"""Python 3.12.10
請與原本的 conductivity_gui.py 放在同一個資料夾。
"""

import importlib.util
import math
import sys
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox


def load_original():
    path = Path(__file__).resolve().with_name(
        "conductivity_gui.py"
    )

    if not path.is_file():
        raise FileNotFoundError(
            "請將本檔與原本的 conductivity_gui.py "
            "放在同一個資料夾。"
        )

    spec = importlib.util.spec_from_file_location(
        "conductivity_original", path
    )
    module = importlib.util.module_from_spec(spec)

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return module


def set_ranges(curves, lo, hi, indices):
    """只更新 fitting 區間，不修改膜厚與輸出勾選。"""
    if not (
        math.isfinite(lo)
        and math.isfinite(hi)
        and lo < hi
    ):
        raise ValueError(
            "請輸入有限數字，且 Vmin 必須小於 Vmax。"
        )

    indices = list(indices)

    if any(
        i < 0 or i >= len(curves)
        for i in indices
    ):
        raise ValueError("選取的數據不存在。")

    for i in indices:
        curves[i].lo = lo
        curves[i].hi = hi

    return indices


base = load_original()


class AppV2(base.App):
    def __init__(self):
        super().__init__()

        self.title(
            "Conductivity GUI V2 — 共用／個別 fitting 區間"
        )

        self.new_data_range = None
        self.seen_count = len(self.curves)

        self.batch_lo = tk.StringVar(value="-0.1")
        self.batch_hi = tk.StringVar(value="0.1")

        self.range_status = tk.StringVar(
            value="輸入區間後，選擇要套用的對象。"
        )

        frame = ttk.LabelFrame(
            self,
            text="共用 fitting 區間（V）",
            padding=6,
        )

        pane = next(
            widget
            for widget in self.winfo_children()
            if isinstance(widget, ttk.Panedwindow)
        )

        frame.pack(
            fill="x",
            padx=6,
            pady=4,
            before=pane,
        )

        controls = ttk.Frame(frame)
        controls.pack(fill="x")

        for label, variable in [
            ("Vmin", self.batch_lo),
            ("Vmax", self.batch_hi),
        ]:
            ttk.Label(
                controls,
                text=label,
            ).pack(side="left", padx=4)

            ttk.Entry(
                controls,
                textvariable=variable,
                width=12,
            ).pack(side="left")

        for text, scope in [
            ("套用全部", "all"),
            ("套用已勾選", "checked"),
            ("僅套用目前這組", "current"),
        ]:
            ttk.Button(
                controls,
                text=text,
                command=lambda s=scope: self.apply_range(s),
            ).pack(side="left", padx=5)

        ttk.Button(
            controls,
            text="讀取目前這組區間",
            command=self.copy_current,
        ).pack(side="left", padx=5)

        ttk.Label(
            frame,
            textvariable=self.range_status,
        ).pack(fill="x", pady=(4, 0))

        ttk.Label(
            frame,
            text=(
                "「套用全部」會更新所有數據的區間；"
                "之後仍可個別調整。膜厚與輸出勾選不受影響；"
                "新匯入數據沿用最後一次套用全部的區間。"
            ),
        ).pack(fill="x")

    def refresh(self, redraw=True):
        # 新加入數據沿用共用區間，
        # 不覆蓋現有數據的個別設定。
        start = getattr(self, "seen_count", 0)
        bounds = getattr(
            self, "new_data_range", None
        )

        if (
            bounds is not None
            and len(self.curves) > start
        ):
            set_ranges(
                self.curves,
                *bounds,
                range(start, len(self.curves)),
            )

        self.seen_count = len(self.curves)

        super().refresh(redraw)

    def copy_current(self):
        if self.current is None:
            messagebox.showwarning(
                "尚未選擇",
                "請先在左側選擇一組數據。",
            )
            return

        curve = self.curves[self.current]

        self.batch_lo.set(
            f"{curve.lo:.12g}"
        )
        self.batch_hi.set(
            f"{curve.hi:.12g}"
        )

        self.range_status.set(
            "已讀取目前這組區間；"
            "尚未套用至其他數據。"
        )

    def apply_range(self, scope):
        try:
            lo = float(self.batch_lo.get())
            hi = float(self.batch_hi.get())

            if scope == "all":
                indices = list(
                    range(len(self.curves))
                )

            elif scope == "checked":
                indices = [
                    i
                    for i, curve in enumerate(self.curves)
                    if curve.export
                ]

            else:
                indices = (
                    []
                    if self.current is None
                    else [self.current]
                )

            if not indices and scope != "all":
                raise ValueError(
                    "請先勾選數據，"
                    "或選擇目前要調整的數據。"
                )

            affected = set_ranges(
                self.curves,
                lo,
                hi,
                indices,
            )

            if scope == "all":
                self.new_data_range = (lo, hi)

            self.refresh()
            self.populate()

            invalid = [
                i + 1
                for i in affected
                if self.stats(
                    self.curves[i]
                )["slope"] is None
            ]

            text = (
                f"已套用 {lo:g} ～ {hi:g} V "
                f"至 {len(affected)} 組；"
                "膜厚保持原設定。"
            )

            if not affected and scope == "all":
                text = (
                    "已設定新匯入數據的預設區間："
                    f"{lo:g} ～ {hi:g} V。"
                )

            if invalid:
                text += (
                    " 無法擬合的組別："
                    + ", ".join(map(str, invalid))
                    + "（請檢查區間內點數）。"
                )

            self.range_status.set(text)

        except ValueError as error:
            messagebox.showerror(
                "區間設定有誤",
                str(error),
            )


if __name__ == "__main__":
    AppV2().mainloop()