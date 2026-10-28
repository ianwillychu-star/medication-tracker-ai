"""Conductivity GUI — Python 3.12.10"""

import csv
import io
import math
from pathlib import Path
from dataclasses import dataclass

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector


@dataclass(eq=False)
class Curve:
    name: str
    source: str
    x: np.ndarray
    y: np.ndarray
    lo: float
    hi: float
    thickness: float | None = None
    export: bool = True


def read_curves(text, source):
    """支援原始儀器格式，以及 V,J,V,J... 的一般格式。"""
    try:
        dialect = csv.Sniffer().sniff(
            text[:12000], delimiters=",;\t"
        )
        rows = list(csv.reader(io.StringIO(text), dialect))
    except csv.Error:
        rows = [line.split() for line in text.splitlines()]

    rows = [
        row for row in rows
        if any(cell.strip() for cell in row)
    ]

    if not rows:
        raise ValueError("沒有資料。")

    blocks = [
        i for i, cell in enumerate(rows[0])
        if cell.strip() == "No."
    ]

    if blocks:
        stop = next(
            (
                i for i, row in enumerate(rows)
                if row[0].startswith("==========")
            ),
            len(rows),
        )

        specs = [
            (f"No.{rows[0][b + 1]}", b + 2, b + 4)
            for b in blocks
        ]
        data_rows = rows[2:stop]

    else:
        if len(rows[0]) % 2:
            raise ValueError(
                "一般格式需依 V,J,V,J…排列成偶數欄。"
            )

        specs = [
            (f"Curve {i // 2 + 1}", i, i + 1)
            for i in range(0, len(rows[0]), 2)
        ]
        data_rows = rows

    result = []

    for label, a, b in specs:
        points = []
        started = False

        for row in data_rows:
            if len(row) <= b:
                if started and any(z.strip() for z in row):
                    raise ValueError(
                        f"{label} 有缺少欄位的資料列。"
                    )
                continue

            if not row[a].strip() and not row[b].strip():
                continue

            try:
                v = float(row[a])
                j = float(row[b])
            except ValueError:
                if started or blocks:
                    raise ValueError(
                        f"{label} 含無效數值：{row[a:b + 1]}"
                    )
                continue

            if not (math.isfinite(v) and math.isfinite(j)):
                raise ValueError(
                    f"{label} 含 NaN 或無限值。"
                )

            points.append((v, j))
            started = True

        if len(points) < 3:
            raise ValueError(
                f"{label} 至少需要三個點。"
            )

        x, y = np.asarray(points, dtype=float).T

        near = (x >= -0.1) & (x <= 0.1)

        if near.sum() >= 3 and np.ptp(x[near]) > 0:
            lo, hi = -0.1, 0.1
        else:
            lo, hi = float(x.min()), float(x.max())

        result.append(
            Curve(
                name=f"{Path(source).stem} / {label}",
                source=source,
                x=x,
                y=y,
                lo=lo,
                hi=hi,
            )
        )

    return result


def fit(
    curve,
    global_t=None,
    geometry="垂直",
    gap=None,
    width=None,
    area=None,
):
    """J = slope * V + intercept；膜厚用於換算 conductivity。"""
    mask = (
        (curve.x >= curve.lo)
        & (curve.x <= curve.hi)
    )

    x = curve.x[mask]
    y = curve.y[mask]

    t = (
        curve.thickness
        if curve.thickness is not None
        else global_t
    )

    out = {
        "n": len(x),
        "thickness": t,
        "slope": None,
        "intercept": None,
        "r2": None,
        "slope_se": None,
        "sigma": None,
        "sigma_se": None,
        "status": "",
    }

    if not (
        math.isfinite(curve.lo)
        and math.isfinite(curve.hi)
        and curve.lo < curve.hi
    ):
        out["status"] = "Vmin 必須小於 Vmax"
        return out

    if len(x) < 3 or np.ptp(x) == 0:
        out["status"] = "區間不足3點或電壓無變化"
        return out

    dx = x - x.mean()
    dy = y - y.mean()

    xx = dx @ dx
    xy = dx @ dy
    yy = dy @ dy

    m = float(xy / xx)
    b = float(y.mean() - m * x.mean())

    se = math.sqrt(
        float(
            np.sum((y - m * x - b) ** 2)
            / (len(x) - 2)
            / xx
        )
    )

    r2 = (
        float(np.clip(xy * xy / (xx * yy), 0, 1))
        if yy > 0
        else None
    )

    out.update(
        slope=m,
        intercept=b,
        r2=r2,
        slope_se=se,
    )

    if t is None or not math.isfinite(t) or t <= 0:
        out["status"] = "待填膜厚；擬合已完成"
        return out

    if geometry == "垂直":
        # m: mA/cm²/V；t: nm；sigma: S/cm
        factor = t * 1e-10

    else:
        dimensions = [gap, width, area]

        if any(
            value is None
            or not math.isfinite(value)
            or value <= 0
            for value in dimensions
        ):
            out["status"] = (
                "平面量測需有效間距、寬度與正規化面積"
            )
            return out

        # gap: μm；width: mm；t: nm；area: cm²
        factor = (
            1e-3
            * area
            * (gap * 1e-4)
            / ((width * 0.1) * (t * 1e-7))
        )

    out.update(
        sigma=m * factor,
        sigma_se=se * abs(factor),
    )

    out["status"] = "請確認歐姆區及幾何"

    if m <= 0:
        out["status"] = "非正斜率：檢查極性與物理"

    elif r2 is None or r2 < 0.99:
        out["status"] = "R²<0.99：檢查線性區"

    return out


def write_results(
    path,
    curves,
    global_t,
    geometry,
    gap,
    width,
    area,
):
    selected = [c for c in curves if c.export]

    if not selected:
        raise ValueError("請先勾選要匯出的數據。")

    headers = [
        "Name",
        "Source",
        "Geometry",
        "Vmin_V",
        "Vmax_V",
        "Thickness_nm",
        "Thickness_setting",
        "Gap_um",
        "Width_mm",
        "J_normalization_cm2",
        "N",
        "Slope_mA_cm-2_V-1",
        "Intercept_mA_cm-2",
        "R_squared",
        "Slope_SE",
        "Conductivity_S_cm-1",
        "Conductivity_S_m-1",
        "Conductivity_SE_S_cm-1",
        "Status",
    ]

    separator = (
        "\t"
        if Path(path).suffix.lower() == ".txt"
        else ","
    )

    with open(
        path,
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.writer(
            file, delimiter=separator
        )
        writer.writerow(headers)

        for c in selected:
            r = fit(
                c, global_t, geometry,
                gap, width, area,
            )

            writer.writerow([
                c.name,
                c.source,
                geometry,
                c.lo,
                c.hi,
                r["thickness"],
                (
                    "individual"
                    if c.thickness is not None
                    else "global"
                ),
                gap if geometry == "平面" else "",
                width if geometry == "平面" else "",
                area if geometry == "平面" else "",
                r["n"],
                r["slope"],
                r["intercept"],
                r["r2"],
                r["slope_se"],
                r["sigma"],
                (
                    r["sigma"] * 100
                    if r["sigma"] is not None
                    else ""
                ),
                r["sigma_se"],
                r["status"],
            ])


class App(tk.Tk):
    def __init__(self):
        global FigureCanvasTkAgg

        from matplotlib.backends.backend_tkagg import (
            FigureCanvasTkAgg,
            NavigationToolbar2Tk,
        )

        super().__init__()

        self.title(
            "Conductivity GUI — Python 3.12.10"
        )
        self.geometry("1500x900")

        self.curves = []
        self.current = None

        self.global_t = None
        self.geometry_mode = "垂直"
        self.gap = None
        self.width = None
        self.area = None

        self.global_var = tk.StringVar()
        self.mode = tk.StringVar(value="垂直")
        self.gap_var = tk.StringVar()
        self.width_var = tk.StringVar()
        self.area_var = tk.StringVar(value="0.09")

        # 頂部操作按鈕
        bar = ttk.Frame(self, padding=6)
        bar.pack(fill="x")

        buttons = [
            (
                "匯入 CSV／TXT（可多選）",
                self.load,
            ),
            ("貼上 V–J 數據", self.paste),
            (
                "全部勾選",
                lambda: self.check_all(True),
            ),
            (
                "取消勾選",
                lambda: self.check_all(False),
            ),
            (
                "匯出 CSV",
                lambda: self.export(".csv"),
            ),
            (
                "匯出 TXT",
                lambda: self.export(".txt"),
            ),
        ]

        for text, command in buttons:
            ttk.Button(
                bar,
                text=text,
                command=command,
            ).pack(side="left", padx=3)

        # 共用膜厚及量測幾何
        settings = ttk.Frame(
            self, padding=6
        )
        settings.pack(fill="x")

        entries = [
            ("全域膜厚 nm", self.global_var),
            ("間距 μm", self.gap_var),
            ("導電寬度 mm", self.width_var),
            (
                "J正規化面積 cm²",
                self.area_var,
            ),
        ]

        for label, variable in entries:
            ttk.Label(
                settings, text=label
            ).pack(side="left", padx=3)

            ttk.Entry(
                settings,
                textvariable=variable,
                width=9,
            ).pack(side="left")

        ttk.Combobox(
            settings,
            textvariable=self.mode,
            values=["垂直", "平面"],
            state="readonly",
            width=6,
        ).pack(side="left", padx=5)

        ttk.Button(
            settings,
            text="套用共用設定",
            command=self.apply_global,
        ).pack(side="left", padx=4)

        ttk.Button(
            settings,
            text="全部改用全域膜厚",
            command=self.reset_thickness,
        ).pack(side="left")

        ttk.Label(
            self,
            text=(
                "J 單位：mA/cm²。"
                "垂直 σ = slope × t(nm) × 1E−10 S/cm。"
                "共用膜厚更新不覆蓋單組設定；"
                "初始 fitting 區間只是示範。"
            ),
        ).pack(fill="x", padx=10)

        pane = ttk.Panedwindow(
            self, orient="horizontal"
        )
        pane.pack(
            fill="both",
            expand=True,
            padx=6,
            pady=6,
        )

        left = ttk.Frame(pane)
        right = ttk.Frame(pane)

        pane.add(left, weight=1)
        pane.add(right, weight=2)

        # 左側數據表
        columns = [
            "export", "name", "range",
            "t", "r2", "sigma",
        ]

        self.table = ttk.Treeview(
            left,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        titles = [
            "輸出", "數據", "區間 V",
            "膜厚 nm", "R²", "σ S/cm",
        ]
        widths = [
            45, 180, 120, 80, 85, 100,
        ]

        for column, title, width in zip(
            columns, titles, widths
        ):
            self.table.heading(
                column, text=title
            )
            self.table.column(
                column,
                width=width,
                stretch=(column == "name"),
            )

        scroll = ttk.Scrollbar(
            left,
            orient="vertical",
            command=self.table.yview,
        )

        self.table.configure(
            yscrollcommand=scroll.set
        )

        self.table.pack(
            side="left",
            fill="both",
            expand=True,
        )
        scroll.pack(
            side="left", fill="y"
        )

        self.table.bind(
            "<<TreeviewSelect>>",
            self.select,
        )
        self.table.bind(
            "<Button-1>",
            self.toggle,
        )

        # 右側：全部預覽與單組操作
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(
            fill="both", expand=True
        )

        detail = ttk.Frame(self.tabs)
        overview = ttk.Frame(self.tabs)

        self.tabs.add(
            overview,
            text="全部曲線預覽（點圖選取）",
        )
        self.tabs.add(
            detail,
            text="單組 fitting／膜厚",
        )

        controls = ttk.Frame(
            detail, padding=5
        )
        controls.pack(fill="x")

        self.lo = tk.StringVar()
        self.hi = tk.StringVar()
        self.local_t = tk.StringVar()
        self.use_global = tk.BooleanVar(
            value=True
        )

        local_entries = [
            ("Vmin", self.lo),
            ("Vmax", self.hi),
            ("單組膜厚 nm", self.local_t),
        ]

        for label, variable in local_entries:
            ttk.Label(
                controls, text=label
            ).pack(side="left", padx=3)

            ttk.Entry(
                controls,
                textvariable=variable,
                width=9,
            ).pack(side="left")

        ttk.Checkbutton(
            controls,
            text="使用全域膜厚",
            variable=self.use_global,
        ).pack(side="left")

        ttk.Button(
            controls,
            text="套用至此組",
            command=self.apply_local,
        ).pack(side="left", padx=4)

        self.result = ttk.Label(
            detail,
            text=(
                "匯入後，選擇數據。"
                "可在圖上水平拖曳選取擬合區間。"
            ),
            wraplength=850,
        )
        self.result.pack(
            fill="x", padx=6
        )

        fig = Figure(
            figsize=(8, 5), dpi=100
        )

        self.ax = fig.add_subplot(211)
        self.res_ax = fig.add_subplot(212)

        fig.tight_layout(pad=3)

        self.detail_canvas = FigureCanvasTkAgg(
            fig, detail
        )

        NavigationToolbar2Tk(
            self.detail_canvas,
            detail,
        )

        self.detail_canvas.get_tk_widget().pack(
            fill="both", expand=True
        )

        self.span = SpanSelector(
            self.ax,
            self.drag,
            "horizontal",
            useblit=False,
            props={
                "alpha": 0.2,
                "facecolor": "orange",
            },
        )

        # 可捲動的全部曲線預覽
        self.over_canvas = tk.Canvas(
            overview
        )

        vs = ttk.Scrollbar(
            overview,
            orient="vertical",
            command=self.over_canvas.yview,
        )
        hs = ttk.Scrollbar(
            overview,
            orient="horizontal",
            command=self.over_canvas.xview,
        )

        self.over_canvas.configure(
            yscrollcommand=vs.set,
            xscrollcommand=hs.set,
        )

        vs.pack(
            side="right", fill="y"
        )
        hs.pack(
            side="bottom", fill="x"
        )
        self.over_canvas.pack(
            fill="both", expand=True
        )

        self.over_frame = ttk.Frame(
            self.over_canvas
        )

        self.over_canvas.create_window(
            (0, 0),
            window=self.over_frame,
            anchor="nw",
        )

        self.over_frame.bind(
            "<Configure>",
            lambda event: self.over_canvas.configure(
                scrollregion=self.over_canvas.bbox(
                    "all"
                )
            ),
        )

        self.over_plot = None
        self.axis_map = {}

    @staticmethod
    def positive(text, optional=False):
        if not text.strip() and optional:
            return None

        value = float(text)

        if (
            not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(
                "尺寸與面積需為大於零的有限數字。"
            )

        return value

    @staticmethod
    def fmt(value):
        return (
            ""
            if value is None
            else f"{value:.6g}"
        )

    def stats(self, curve):
        return fit(
            curve,
            self.global_t,
            self.geometry_mode,
            self.gap,
            self.width,
            self.area,
        )

    def apply_global(self):
        try:
            thickness = self.positive(
                self.global_var.get(),
                True,
            )

            mode = self.mode.get()

            gap, width, area = (
                self.positive(
                    variable.get(), True
                )
                for variable in [
                    self.gap_var,
                    self.width_var,
                    self.area_var,
                ]
            )

            if mode == "平面" and any(
                value is None
                for value in [gap, width, area]
            ):
                raise ValueError(
                    "平面量測請填寫間距、"
                    "導電寬度與 J 正規化面積。"
                )

            self.global_t = thickness
            self.geometry_mode = mode

            self.gap = gap
            self.width = width
            self.area = area

            self.refresh()

        except ValueError as error:
            messagebox.showerror(
                "設定有誤", str(error)
            )

    def reset_thickness(self):
        confirmed = messagebox.askyesno(
            "確認",
            "將清除所有單組膜厚設定，"
            "全部改用已套用的全域膜厚？",
        )

        if confirmed:
            for curve in self.curves:
                curve.thickness = None

            self.refresh()
            self.populate()

    def load(self):
        paths = filedialog.askopenfilenames(
            filetypes=[
                ("Data", "*.csv *.txt"),
                ("All", "*.*"),
            ]
        )

        pending = []

        try:
            for path in paths:
                raw = Path(path).read_bytes()

                try:
                    text = raw.decode(
                        "utf-8-sig"
                    )
                except UnicodeDecodeError:
                    text = raw.decode(
                        "cp950"
                    )

                pending.extend(
                    read_curves(text, path)
                )

            self.curves.extend(pending)
            self.refresh()

        except Exception as error:
            messagebox.showerror(
                "匯入失敗（本批未加入）",
                str(error),
            )

    def paste(self):
        win = tk.Toplevel(self)

        win.title(
            "貼上 V–J：兩欄，"
            "以 Tab、逗號或空白分隔"
        )

        name = ttk.Entry(
            win, width=50
        )
        name.insert(
            0,
            f"Pasted_{len(self.curves) + 1}",
        )
        name.pack(fill="x")

        text = tk.Text(
            win, width=70, height=24
        )
        text.pack(
            fill="both", expand=True
        )

        def add():
            try:
                curves = read_curves(
                    text.get("1.0", "end"),
                    name.get() or "Pasted",
                )

                self.curves.extend(curves)
                self.refresh()
                win.destroy()

            except Exception as error:
                messagebox.showerror(
                    "貼上失敗",
                    str(error),
                    parent=win,
                )

        ttk.Button(
            win,
            text="加入數據",
            command=add,
        ).pack()

    def refresh(self, redraw=True):
        for i, curve in enumerate(self.curves):
            result = self.stats(curve)

            thickness_label = self.fmt(
                result["thickness"]
            )

            if curve.thickness is not None:
                thickness_label += "*"

            values = [
                "☑" if curve.export else "☐",
                curve.name,
                f"{curve.lo:.5g} ~ {curve.hi:.5g}",
                thickness_label,
                self.fmt(result["r2"]),
                self.fmt(result["sigma"]),
            ]

            if self.table.exists(str(i)):
                self.table.item(
                    str(i), values=values
                )
            else:
                self.table.insert(
                    "",
                    "end",
                    iid=str(i),
                    values=values,
                )

        if redraw:
            self.draw_overview()

        self.draw_detail()

    def check_all(self, value):
        for curve in self.curves:
            curve.export = value

        self.refresh(False)

    def toggle(self, event):
        row = self.table.identify_row(
            event.y
        )
        column = self.table.identify_column(
            event.x
        )

        if row and column == "#1":
            curve = self.curves[int(row)]
            curve.export = not curve.export

            self.refresh(False)

    def select(self, event=None):
        selection = self.table.selection()

        if selection:
            self.current = int(
                selection[0]
            )
            self.populate()
            self.draw_detail()

    def populate(self):
        if self.current is None:
            return

        curve = self.curves[
            self.current
        ]

        self.lo.set(
            f"{curve.lo:.10g}"
        )
        self.hi.set(
            f"{curve.hi:.10g}"
        )
        self.local_t.set(
            ""
            if curve.thickness is None
            else f"{curve.thickness:.10g}"
        )
        self.use_global.set(
            curve.thickness is None
        )

    def apply_local(self):
        if self.current is None:
            return

        try:
            lo = float(self.lo.get())
            hi = float(self.hi.get())

            if not (
                math.isfinite(lo)
                and math.isfinite(hi)
                and lo < hi
            ):
                raise ValueError(
                    "需要有限數值 Vmin < Vmax。"
                )

            thickness = (
                None
                if self.use_global.get()
                else self.positive(
                    self.local_t.get()
                )
            )

            curve = self.curves[
                self.current
            ]

            curve.lo = lo
            curve.hi = hi
            curve.thickness = thickness

            self.refresh()

        except ValueError as error:
            messagebox.showerror(
                "設定有誤", str(error)
            )

    def drag(self, lo, hi):
        if (
            self.current is None
            or hi <= lo
        ):
            return

        curve = self.curves[
            self.current
        ]

        curve.lo = float(lo)
        curve.hi = float(hi)

        self.populate()
        self.refresh()

    def paint(self, ax, curve, short=False):
        result = self.stats(curve)

        ax.plot(
            curve.x,
            curve.y,
            lw=0.9,
            color="#2878b5",
            label="Measured",
        )

        ax.axvspan(
            curve.lo,
            curve.hi,
            alpha=0.12,
            color="orange",
        )

        if result["slope"] is not None:
            x = np.array([
                max(
                    curve.lo,
                    curve.x.min(),
                ),
                min(
                    curve.hi,
                    curve.x.max(),
                ),
            ])

            ax.plot(
                x,
                result["slope"] * x
                + result["intercept"],
                color="red",
                lw=2,
                label="Fit",
            )

        ax.set_xlabel("Voltage (V)")
        ax.set_ylabel("J (mA/cm²)")
        ax.grid(alpha=0.2)

        title = (
            f"#{self.curves.index(curve) + 1}"
            if short
            else f"Curve #{self.current + 1}"
        )

        ax.set_title(title)

        return result

    def draw_detail(self):
        self.ax.clear()
        self.res_ax.clear()

        if self.current is not None:
            curve = self.curves[
                self.current
            ]

            result = self.paint(
                self.ax, curve
            )
            self.ax.legend(
                loc="best"
            )

            if result["slope"] is not None:
                mask = (
                    (curve.x >= curve.lo)
                    & (curve.x <= curve.hi)
                )

                residual = (
                    curve.y[mask]
                    - result["slope"] * curve.x[mask]
                    - result["intercept"]
                )

                self.res_ax.plot(
                    curve.x[mask],
                    residual,
                    ".-",
                    ms=3,
                )

            self.res_ax.axhline(
                0,
                color="gray",
                lw=0.8,
            )
            self.res_ax.set_xlabel(
                "Voltage (V)"
            )
            self.res_ax.set_ylabel(
                "Residual (mA/cm²)"
            )
            self.res_ax.grid(
                alpha=0.2
            )

            text = (
                f"{curve.name}\n"
                f"N={result['n']}  "
                f"slope={self.fmt(result['slope'])}  "
                f"intercept={self.fmt(result['intercept'])}  "
                f"R²={self.fmt(result['r2'])}  "
                f"t={self.fmt(result['thickness'])} nm  "
                f"σ={self.fmt(result['sigma'])} S/cm\n"
                f"{result['status']}"
            )

            self.result.config(
                text=text
            )

        self.detail_canvas.draw_idle()

    def draw_overview(self):
        if self.over_plot is not None:
            self.over_plot.get_tk_widget().destroy()

        self.axis_map = {}

        if not self.curves:
            self.over_plot = None
            return

        rows = math.ceil(
            len(self.curves) / 3
        )

        fig = Figure(
            figsize=(10, 2.8 * rows),
            dpi=100,
        )

        for i, curve in enumerate(self.curves):
            ax = fig.add_subplot(
                rows, 3, i + 1
            )

            self.paint(
                ax, curve, True
            )

            self.axis_map[ax] = i

        fig.tight_layout()

        self.over_plot = FigureCanvasTkAgg(
            fig, self.over_frame
        )

        self.over_plot.get_tk_widget().pack()

        self.over_plot.mpl_connect(
            "button_press_event",
            self.pick_plot,
        )

        self.over_plot.draw()

    def pick_plot(self, event):
        if event.inaxes in self.axis_map:
            index = self.axis_map[
                event.inaxes
            ]

            self.table.selection_set(
                str(index)
            )
            self.table.see(
                str(index)
            )

            self.current = index
            self.populate()
            self.draw_detail()

            self.tabs.select(1)

    def export(self, extension):
        if not any(
            curve.export
            for curve in self.curves
        ):
            messagebox.showwarning(
                "無輸出資料",
                "請勾選左側「輸出」欄。",
            )
            return

        path = filedialog.asksaveasfilename(
            defaultextension=extension,
            filetypes=[
                (
                    extension[1:].upper(),
                    "*" + extension,
                )
            ],
            initialfile=(
                "conductivity_results"
                + extension
            ),
        )

        if not path:
            return

        try:
            write_results(
                path,
                self.curves,
                self.global_t,
                self.geometry_mode,
                self.gap,
                self.width,
                self.area,
            )

            messagebox.showinfo(
                "已匯出",
                "輸出包含已勾選數據的擬合結果、"
                "膜厚、conductivity 與狀態。\n"
                "尚未填厚度或無法擬合的數據，"
                "會保留空白結果與原因。",
            )

        except Exception as error:
            messagebox.showerror(
                "匯出失敗",
                str(error),
            )


if __name__ == "__main__":
    App().mainloop()