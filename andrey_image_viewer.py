"""
Copyright (c) 2026 Wahyu A. All rights reserved.
Distribution or modification without expressed permission is prohibited.

@author: Wahyu A.
@email: wahyu.andrey@gmail.com
"""

import glob
import os
import queue
import re
import math
import sys
import gc
import threading
import tkinter as tk
from tkinter import ttk
import traceback

# Pengaturan batas piksel
os.environ["OPENCV_IO_MAX_IMAGE_PIXELS"] = str(2**31 - 1)

import cv2
from PIL import Image, ImageColor, ImageTk, ImageFile
from tkinter import colorchooser, filedialog, messagebox
import numpy as np

# Coba muat pustaka industri pyvips
try:
    import pyvips
    HAS_PYVIPS = True
except ImportError:
    HAS_PYVIPS = False

try:
    import tifffile
    HAS_TIFFFILE = True
except ImportError:
    HAS_TIFFFILE = False

Image.MAX_IMAGE_PIXELS = None
ImageFile.LOAD_TRUNCATED_IMAGES = True


class AndreyImageViewerApp:

    def __init__(self, root):
        self.root = root
        self.root.title("Andrey Image Viewer - © 2026 Wahyu A.")
        self.root.geometry("1100x750")

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.layers = []
        self.zoom_scale = 1.0
        self.tk_image = None
        self.canvas_img_id = None
        self._canvas_buffer = None
        self._debounce_job = None

        self.solo_layer_idx = None
        self.layers_backup = []

        self.active_tool = None
        self.measure_start_pt = None
        self.measure_end_pt = None
        self.image_dpi = 300.0

        self.zoom_select_start = None
        self.zoom_rect_id = None

        self.render_request_queue = queue.Queue()
        self.render_result_queue = queue.Queue()
        self.is_rendering = False
        self.is_dragging = False

        self.rotation_angle = 0
        self.is_flipped_h = False

        self.img_width = 0
        self.img_height = 0

        self.opacity_var = tk.DoubleVar(value=1.0)
        self.threshold_var = tk.IntVar(value=0)

        # UI Initialization
        self.status_bar_frame = tk.Frame(root, bg="#e0e0e0", bd=1, relief=tk.SUNKEN)
        self.status_bar_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.lbl_status = tk.Label(
            self.status_bar_frame, text="Ready.", bg="#e0e0e0", fg="#333333", anchor="w", font=("Arial", 9)
        )
        self.lbl_status.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=2)

        self.progress_bar = ttk.Progressbar(
            self.status_bar_frame, orient="horizontal", mode="indeterminate", length=150
        )
        self.progress_bar.pack(side=tk.RIGHT, padx=5, pady=2)

        self.preview_panel = tk.Frame(root, bg="#ffffff")
        self.preview_panel.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

        self.right_panel = tk.Frame(root, width=450, bg="#f0f0f0")
        self.right_panel.pack_propagate(False) # Kunci ukuran agar tidak menyusut mengikuti isi
        self.right_panel.pack(side=tk.RIGHT, fill=tk.Y)

        ctrl_frame = tk.LabelFrame(
            self.right_panel, text="Tools", bg="#f0f0f0", font=("Arial", 9, "bold")
        )
        ctrl_frame.pack(fill=tk.X, padx=10, pady=5, ipady=5)

        tk.Label(ctrl_frame, text="Open Job Ticket:", bg="#f0f0f0", font=("Arial", 8, "bold")).grid(
            row=0, column=0, sticky="w", padx=5, pady=(2, 5)
        )
        tk.Button(
            ctrl_frame,
            text="🗁 (TIF/TIFF)",
            command=self.add_folder,
            bg="#e0e0e0",
            font=("Arial", 9, "bold"),
        ).grid(row=0, column=1, columnspan=2, sticky="ew", padx=5, pady=(2, 5))

        tk.Label(ctrl_frame, text="Opacity:", bg="#f0f0f0", font=("Arial", 8, "bold")).grid(
            row=1, column=0, sticky="w", padx=5
        )
        self.slider_opacity = tk.Scale(
            ctrl_frame,
            from_=0.0,
            to=1.0,
            resolution=0.01,
            orient=tk.HORIZONTAL,
            variable=self.opacity_var,
            command=self._on_opacity_slider_change,
            bg="#f0f0f0",
            highlightthickness=0,
            showvalue=False,
        )
        self.slider_opacity.grid(row=1, column=1, sticky="ew", padx=2)

        self.txt_opacity = tk.Entry(ctrl_frame, width=5, font=("Arial", 9), justify="center")
        self.txt_opacity.insert(0, "1.00")
        self.txt_opacity.grid(row=1, column=2, padx=5)
        self.txt_opacity.bind("<Return>", self._on_opacity_text_change)
        self.txt_opacity.bind("<FocusOut>", self._on_opacity_text_change)

        tk.Label(ctrl_frame, text="Threshold:", bg="#f0f0f0", font=("Arial", 8, "bold")).grid(
            row=2, column=0, sticky="w", padx=5, pady=(5, 0)
        )
        self.slider_threshold = tk.Scale(
            ctrl_frame,
            from_=100,
            to=0,
            orient=tk.HORIZONTAL,
            variable=self.threshold_var,
            command=self._on_threshold_slider_change,
            bg="#f0f0f0",
            highlightthickness=0,
            showvalue=False,
        )
        self.slider_threshold.grid(row=2, column=1, sticky="ew", padx=2, pady=(5, 0))

        self.txt_threshold = tk.Entry(ctrl_frame, width=5, font=("Arial", 9), justify="center")
        self.txt_threshold.insert(0, "0")
        self.txt_threshold.grid(row=2, column=2, padx=5, pady=(5, 0))
        self.txt_threshold.bind("<Return>", self._on_threshold_text_change)
        self.txt_threshold.bind("<FocusOut>", self._on_threshold_text_change)

        tk.Label(ctrl_frame, text="Zoom:", bg="#f0f0f0", font=("Arial", 8, "bold")).grid(
            row=3, column=0, sticky="w", padx=5, pady=(8, 0)
        )

        zoom_btn_frame = tk.Frame(ctrl_frame, bg="#f0f0f0")
        zoom_btn_frame.grid(row=3, column=1, columnspan=2, sticky="w", pady=(8, 0))

        tk.Button(zoom_btn_frame, text="➕", font=("Arial", 11), width=3, bd=1, relief=tk.RAISED, bg="#e0e0e0", command=self.zoom_in).pack(side=tk.LEFT, padx=1)
        tk.Button(zoom_btn_frame, text="➖", font=("Arial", 11), width=3, bd=1, relief=tk.RAISED, bg="#e0e0e0", command=self.zoom_out).pack(side=tk.LEFT, padx=1)
        tk.Button(zoom_btn_frame, text="⛶", font=("Arial", 11), width=3, bd=1, relief=tk.RAISED, bg="#e0e0e0", command=self.zoom_to_fit).pack(side=tk.LEFT, padx=1)
        tk.Button(zoom_btn_frame, text="100%", font=("Arial", 11), width=4, bd=1, relief=tk.RAISED, bg="#e0e0e0", command=self.reset_zoom).pack(side=tk.LEFT, padx=1)

        self.txt_zoom = tk.Entry(zoom_btn_frame, width=5, font=("Arial", 9), justify="center")
        self.txt_zoom.insert(0, "100%")
        self.txt_zoom.pack(side=tk.LEFT, padx=(5, 0))
        self.txt_zoom.bind("<Return>", self._on_zoom_text_change)
        self.txt_zoom.bind("<FocusOut>", self._on_zoom_text_change)

        tk.Label(ctrl_frame, text="Transform:", bg="#f0f0f0", font=("Arial", 8, "bold")).grid(
            row=4, column=0, sticky="w", padx=5, pady=(8, 0)
        )

        transform_btn_frame = tk.Frame(ctrl_frame, bg="#f0f0f0")
        transform_btn_frame.grid(row=4, column=1, columnspan=2, sticky="w", pady=(8, 0))

        tk.Button(transform_btn_frame, text="△", font=("Arial", 11), width=3, bd=1, relief=tk.RAISED, bg="#e0e0e0", command=self.rotate_normal).pack(side=tk.LEFT, padx=1)
        tk.Button(transform_btn_frame, text="◁", font=("Arial", 11), width=3, bd=1, relief=tk.RAISED, bg="#e0e0e0", command=self.rotate_left).pack(side=tk.LEFT, padx=1)
        tk.Button(transform_btn_frame, text="▽", font=("Arial", 11), width=3, bd=1, relief=tk.RAISED, bg="#e0e0e0", command=self.rotate_180).pack(side=tk.LEFT, padx=1)
        tk.Button(transform_btn_frame, text="▷", font=("Arial", 11), width=3, bd=1, relief=tk.RAISED, bg="#e0e0e0", command=self.rotate_right).pack(side=tk.LEFT, padx=1)
        tk.Button(transform_btn_frame, text="◧", font=("Arial", 11), width=3, bd=1, relief=tk.RAISED, bg="#e0e0e0", command=self.flip_horizontal).pack(side=tk.LEFT, padx=1)
        tk.Button(transform_btn_frame, text="🔄", font=("Arial", 11), width=3, bd=1, relief=tk.RAISED, bg="#e0e0e0", command=self.reset_transform).pack(side=tk.LEFT, padx=1)

        tk.Label(ctrl_frame, text="Measure:", bg="#f0f0f0", font=("Arial", 8, "bold")).grid(
            row=5, column=0, sticky="w", padx=5, pady=(8, 0)
        )

        measure_btn_frame = tk.Frame(ctrl_frame, bg="#f0f0f0")
        measure_btn_frame.grid(row=5, column=1, columnspan=2, sticky="w", pady=(8, 0))

        self.btn_densitometer = tk.Button(
            measure_btn_frame, text="⯐", font=("Arial", 11), width=3, bd=1, relief=tk.RAISED, bg="#e0e0e0", command=self.toggle_densitometer
        )
        self.btn_densitometer.pack(side=tk.LEFT, padx=1)

        self.btn_distance = tk.Button(
            measure_btn_frame, text="📏", font=("Arial", 11), width=3, bd=1, relief=tk.RAISED, bg="#e0e0e0", command=self.toggle_distance_tool
        )
        self.btn_distance.pack(side=tk.LEFT, padx=1)

        ctrl_frame.columnconfigure(1, weight=1)

        self.size_frame = tk.LabelFrame(
            self.right_panel, text="Size", bg="#f0f0f0", font=("Arial", 9, "bold")
        )

        self.size_var = tk.StringVar(value="Height x Width = - mm")
        self.lbl_size = tk.Label(
            self.size_frame, textvariable=self.size_var, bg="#f0f0f0", font=("Arial", 8, "bold"), fg="#333333", anchor="w"
        )
        self.lbl_size.pack(fill=tk.X, padx=5, pady=2)

        self.layer_container = tk.Frame(self.right_panel, bg="#f0f0f0")
        self.layer_container.pack(side="top", fill="both", expand=True, padx=5, pady=(5, 0))

        self.layer_canvas = tk.Canvas(self.layer_container, bg="#f0f0f0", highlightthickness=0)
        self.layer_scrollbar = tk.Scrollbar(self.layer_container, orient="vertical", command=self.layer_canvas.yview)
        self.layer_frame = tk.Frame(self.layer_canvas, bg="#f0f0f0")

        self.layer_frame.bind(
            "<Configure>",
            lambda e: self.layer_canvas.configure(scrollregion=self.layer_canvas.bbox("all")),
        )
        self.layer_canvas.create_window((0, 0), window=self.layer_frame, anchor="nw")
        self.layer_canvas.configure(yscrollcommand=self.layer_scrollbar.set)

        self.layer_canvas.pack(side="left", fill="both", expand=True)
        self.layer_scrollbar.pack(side="right", fill="y")

        self.lbl_legend_m = tk.Label(self.right_panel, text="[M] = Mirrored", bg="#f0f0f0", fg="#000000", font=("Arial", 8, "normal"), anchor="w")
        self.lbl_legend_n = tk.Label(self.right_panel, text="[N] = Not mirrored", bg="#f0f0f0", fg="#FF0000", font=("Arial", 8, "normal"), anchor="w")

        self.preview_panel_canvas = tk.Canvas(self.preview_panel, bg="#ffffff", highlightthickness=0)
        self.canvas = self.preview_panel_canvas

        self.v_scrollbar = tk.Scrollbar(self.preview_panel, orient=tk.VERTICAL, command=self._on_v_scroll)
        self.h_scrollbar = tk.Scrollbar(self.preview_panel, orient=tk.HORIZONTAL, command=self._on_h_scroll)

        self.canvas.configure(xscrollcommand=self.h_scrollbar.set, yscrollcommand=self.v_scrollbar.set)

        self.v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

        self.canvas.bind("<Configure>", lambda e: self.schedule_render())
        self.canvas.bind("<MouseWheel>", self._on_vertical_scroll)
        self.canvas.bind("<Button-4>", self._on_vertical_scroll)
        self.canvas.bind("<Button-5>", self._on_vertical_scroll)

        self.canvas.bind("<ButtonPress-1>", self._on_canvas_click)
        self.canvas.bind("<B1-Motion>", self._on_left_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_drag_release)

        self.canvas.bind("<ButtonPress-3>", self._on_drag_start)
        self.canvas.bind("<B3-Motion>", self._on_drag_motion)
        self.canvas.bind("<ButtonRelease-3>", self._on_drag_end)

        self.default_colors = [
            "#FF0000", "#00FF00", "#0000FF", "#FFFF00",
            "#FF00FF", "#00FFFF", "#FF5722", "#E91E63",
            "#9C27B0", "#3F51B5", "#009688", "#8BC34A",
        ]

        self.worker_thread = threading.Thread(target=self._persistent_render_worker, daemon=True)
        self.worker_thread.start()

    def apply_tiff_orientation(self, np_arr, orientation_value):
        if np_arr is None:
            return None
        img = np_arr.copy()
        if orientation_value == 1:
            return img
        elif orientation_value == 2:
            return cv2.flip(img, 1)
        elif orientation_value == 3:
            return cv2.rotate(img, cv2.ROTATE_180)
        elif orientation_value == 4:
            img = cv2.rotate(img, cv2.ROTATE_180)
            return cv2.flip(img, 1)
        elif orientation_value == 5:
            img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
            return cv2.flip(img, 1)
        elif orientation_value == 6:
            return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        elif orientation_value == 7:
            img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
            return cv2.flip(img, 1)
        elif orientation_value == 8:
            return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return img

    def update_size_info(self):
        if self.img_width == 0 or self.img_height == 0:
            self.size_var.set("Height x Width = - mm")
            return

        eff_w, eff_h = self.get_effective_dimensions()
        w_mm = (eff_w / self.image_dpi) * 25.4
        h_mm = (eff_h / self.image_dpi) * 25.4
        self.size_var.set(f"Height x Width = {h_mm:.2f} x {w_mm:.2f} mm")

    def set_status(self, text, is_busy=False):
        self.lbl_status.config(text=text)
        if is_busy:
            self.progress_bar.start(10)
        else:
            self.progress_bar.stop()

    def toggle_densitometer(self):
        if self.active_tool == "densitometer":
            self.active_tool = None
            self.btn_densitometer.config(bg="#e0e0e0", fg="#000000", relief=tk.RAISED)
            self.canvas.config(cursor="")
            self.set_status("Ready.")
        else:
            self.active_tool = "densitometer"
            self.btn_densitometer.config(bg="#333333", fg="#ffffff", relief=tk.SUNKEN)
            self.btn_distance.config(bg="#e0e0e0", fg="#000000", relief=tk.RAISED)
            self.canvas.config(cursor="crosshair")
            self.set_status("Densitometer Mode")

    def toggle_distance_tool(self):
        if self.active_tool == "distance":
            self.active_tool = None
            self.measure_start_pt = None
            self.measure_end_pt = None
            self.btn_distance.config(bg="#e0e0e0", fg="#000000", relief=tk.RAISED)
            self.canvas.config(cursor="")
            self.schedule_render(0)
            self.set_status("Ready.")
        else:
            self.active_tool = "distance"
            self.measure_start_pt = None
            self.measure_end_pt = None
            self.btn_distance.config(bg="#333333", fg="#ffffff", relief=tk.SUNKEN)
            self.btn_densitometer.config(bg="#e0e0e0", fg="#000000", relief=tk.RAISED)
            self.canvas.config(cursor="tcross")
            self.set_status("Distance Mode")

    def _get_image_coords(self, event):
        eff_w, eff_h = self.get_effective_dimensions()
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        img_x = int(canvas_x / self.zoom_scale)
        img_y = int(canvas_y / self.zoom_scale)
        return img_x, img_y, eff_w, eff_h

    def _on_canvas_click(self, event):
        if self.active_tool == "densitometer":
            self.measure_dot_percentage(event)
        elif self.active_tool == "distance":
            self.measure_distance(event)
        else:
            if self.layers and self.img_width > 0 and self.img_height > 0:
                self.zoom_select_start = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
                if self.zoom_rect_id:
                    self.canvas.delete(self.zoom_rect_id)
                self.zoom_rect_id = self.canvas.create_rectangle(
                    self.zoom_select_start[0], self.zoom_select_start[1],
                    self.zoom_select_start[0], self.zoom_select_start[1],
                    outline="red", width=2, dash=(4, 4), tags="overlay"
                )

    def _on_left_drag_motion(self, event):
        if not self.active_tool and self.zoom_select_start:
            cur_x = self.canvas.canvasx(event.x)
            cur_y = self.canvas.canvasy(event.y)
            self.canvas.coords(self.zoom_rect_id, self.zoom_select_start[0], self.zoom_select_start[1], cur_x, cur_y)

    def _on_left_drag_release(self, event):
        if not self.active_tool and self.zoom_select_start:
            end_x = self.canvas.canvasx(event.x)
            end_y = self.canvas.canvasy(event.y)

            c_x1, c_x2 = min(self.zoom_select_start[0], end_x), max(self.zoom_select_start[0], end_x)
            c_y1, c_y2 = min(self.zoom_select_start[1], end_y), max(self.zoom_select_start[1], end_y)

            if self.zoom_rect_id:
                self.canvas.delete(self.zoom_rect_id)
                self.zoom_rect_id = None
            self.zoom_select_start = None

            sel_w = c_x2 - c_x1
            sel_h = c_y2 - c_y1

            if sel_w > 10 and sel_h > 10:
                canvas_w = max(1, self.canvas.winfo_width())
                canvas_h = max(1, self.canvas.winfo_height())

                center_img_x = (c_x1 + (sel_w / 2.0)) / self.zoom_scale
                center_img_y = (c_y1 + (sel_h / 2.0)) / self.zoom_scale

                img_sel_w = max(1.0, sel_w / self.zoom_scale)
                img_sel_h = max(1.0, sel_h / self.zoom_scale)

                scale_w = canvas_w / img_sel_w
                scale_h = canvas_h / img_sel_h

                self.zoom_scale = max(0.05, min(10.0, min(scale_w, scale_h)))
                self._apply_centered_scroll(center_img_x, center_img_y)

    def _apply_centered_scroll(self, center_img_x, center_img_y):
        eff_w, eff_h = self.get_effective_dimensions()
        total_w = eff_w * self.zoom_scale
        total_h = eff_h * self.zoom_scale

        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()

        self.canvas.config(scrollregion=(0, 0, total_w, total_h))
        target_left_px = (center_img_x * self.zoom_scale) - (canvas_w / 2.0)
        target_top_px = (center_img_y * self.zoom_scale) - (canvas_h / 2.0)

        fraction_x = max(0.0, min(1.0, target_left_px / total_w))
        fraction_y = max(0.0, min(1.0, target_top_px / total_h))

        self.canvas.xview_moveto(fraction_x)
        self.canvas.yview_moveto(fraction_y)
        self.schedule_render(0)

    def measure_distance(self, event):
        if not self.layers or self.img_width == 0 or self.img_height == 0:
            return
        img_x, img_y, eff_w, eff_h = self._get_image_coords(event)
        if not (0 <= img_x < eff_w and 0 <= img_y < eff_h):
            self.set_status("📏 out of area.")
            return

        if self.measure_start_pt is None or (self.measure_start_pt and self.measure_end_pt):
            self.measure_start_pt = (img_x, img_y)
            self.measure_end_pt = None
            self.set_status(f"Point 1: ({img_x}, {img_y})")
            self.schedule_render(0)
        else:
            self.measure_end_pt = (img_x, img_y)
            x1, y1 = self.measure_start_pt
            x2, y2 = self.measure_end_pt
            dx, dy = x2 - x1, y2 - y1
            dist_px = math.sqrt(dx * dx + dy * dy)
            dist_mm = (dist_px / self.image_dpi) * 25.4
            self.set_status(f"Distance: {dist_px:.2f} px ({dist_mm:.2f} mm)")
            self.schedule_render(0)

    def measure_dot_percentage(self, event):
        if not self.layers or self.img_width == 0 or self.img_height == 0:
            return
        img_x, img_y, eff_w, eff_h = self._get_image_coords(event)
        if not (0 <= img_x < eff_w and 0 <= img_y < eff_h):
            return

        fx, fy = img_x, img_y
        if self.rotation_angle == 90:
            fx, fy = img_y, self.img_height - 1 - img_x
        elif self.rotation_angle == 180:
            fx, fy = self.img_width - 1 - img_x, self.img_height - 1 - img_y
        elif self.rotation_angle == 270:
            fx, fy = self.img_width - 1 - img_y, img_x

        if self.is_flipped_h:
            ox = self.img_width - 1 - fx
            oy = fy
        else:
            ox, oy = fx, fy

        ox = max(0, min(self.img_width - 1, ox))
        oy = max(0, min(self.img_height - 1, oy))

        for layer in self.layers:
            if not layer.get("visible", True):
                layer["dot_value"] = "OFF"
                continue
            try:
                pixel_val = layer["np_arr"][oy, ox]
                dot_percentage = ((255.0 - float(pixel_val)) / 255.0) * 100.0
                layer["dot_value"] = f"{dot_percentage:.1f}%"
            except Exception:
                layer["dot_value"] = "ERR"

        self.update_layer_list_ui()
        self.set_status(f"⊕ X={img_x}, Y={img_y}")

    def draw_measurement_overlay(self, render_x1, render_y1):
        self.canvas.delete("overlay")
        if self.active_tool != "distance" or not self.measure_start_pt:
            return

        def to_canvas_pos(pt):
            return pt[0] * self.zoom_scale, pt[1] * self.zoom_scale

        cx1, cy1 = to_canvas_pos(self.measure_start_pt)
        self.canvas.create_oval(cx1 - 5, cy1 - 5, cx1 + 5, cy1 + 5, fill="#FF0000", outline="#FFFFFF", width=2, tags="overlay")

        if self.measure_end_pt:
            cx2, cy2 = to_canvas_pos(self.measure_end_pt)
            self.canvas.create_oval(cx2 - 5, cy2 - 5, cx2 + 5, cy2 + 5, fill="#FF0000", outline="#FFFFFF", width=2, tags="overlay")
            self.canvas.create_line(cx1, cy1, cx2, cy2, fill="#00E676", width=2, dash=(4, 2), tags="overlay")
            dx, dy = self.measure_end_pt[0] - self.measure_start_pt[0], self.measure_end_pt[1] - self.measure_start_pt[1]
            dist_px = math.sqrt(dx * dx + dy * dy)
            dist_mm = (dist_px / self.image_dpi) * 25.4
            label_text = f"{dist_px:.1f} px ({dist_mm:.1f} mm)"
            mid_x, mid_y = (cx1 + cx2) / 2, (cy1 + cy2) / 2
            self.canvas.create_rectangle(mid_x - 55, mid_y - 22, mid_x + 55, mid_y - 4, fill="#000000", outline="#FFFFFF", tags="overlay")
            self.canvas.create_text(mid_x, mid_y - 13, text=label_text, fill="#FFFFFF", font=("Arial", 8, "bold"), anchor="center", tags="overlay")

    def get_layer_histogram_total(self, layer_idx):
        if layer_idx < 0 or layer_idx >= len(self.layers):
            return [], 0.0
        layer = self.layers[layer_idx]
        if "ink_coverage" in layer:
            return [], layer["ink_coverage"]
        return [], 0.0

    def check_metadata_info(self, meta_path):
        is_mirror = False
        screen_ruling = "N/A"
        screen_angle = "N/A"
        gradation = "N/A"
        if not os.path.exists(meta_path):
            return is_mirror, screen_ruling, screen_angle, gradation
        
        # Kompilasi pola regex sebelum membaca file
        grv_pattern = re.compile(r'(\d+)_(\d+)_(\d+)_(\d+)\.GRV', re.IGNORECASE)

        try:
            with open(meta_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_lower = line.lower().replace(" ", "")
                    # 1. Pengecekan Mirroring
                    if "orientation=-" in line_lower or "mirror=true" in line_lower or "mirrored=true" in line_lower:
                        is_mirror = True

                    # 2. Pengecekan Pola GRV per Baris
                    match = grv_pattern.search(line)
                    if match:
                        screen_ruling = match.group(1)
                        screen_angle = match.group(2)
                        # stylus_angle = match.group(3)
                        # min_dot = match.group(4)

            with open(meta_path, "rb") as f:
                content = f.read()

                if b"GR11" in content:
                    gradation = "GR11"
                elif b"GR10" in content:
                    gradation = "GR10"
                elif b"Xtreme" in content:
                    gradation = "Xtreme"

        except Exception as e:
            print(e)
        return is_mirror, screen_ruling, screen_angle, gradation

    def update_layer_list_ui(self):
        for widget in self.layer_frame.winfo_children():
            widget.destroy()

        for idx, layer in enumerate(self.layers):
            row = tk.Frame(self.layer_frame, bg="#e0e0e0", bd=1, relief=tk.RAISED)
            row.pack(fill=tk.X, pady=2, ipady=2)

            is_visible = layer["visible"]
            vis_btn = tk.Button(
                row, text="👁" if is_visible else "🚫", bg="#e0e0e0",
                fg="#333333" if is_visible else "#888888", font=("Arial", 11),
                width=3, bd=1, relief=tk.RAISED, command=lambda i=idx: self.toggle_layer_visibility(i),
            )
            vis_btn.pack(side=tk.LEFT, padx=(3, 2))

            is_solo_active = (self.solo_layer_idx == idx)
            bw_btn = tk.Button(
                row, text="◐", bg="#333333" if is_solo_active else "#e0e0e0",
                fg="#ffffff" if is_solo_active else "#000000", font=("Arial", 11),
                width=3, bd=1, relief=tk.SUNKEN if is_solo_active else tk.RAISED,
                command=lambda i=idx: self.toggle_solo_black_and_white(i),
            )
            bw_btn.pack(side=tk.LEFT, padx=2)

            hex_color = f"#{layer['color'][0]:02x}{layer['color'][1]:02x}{layer['color'][2]:02x}"
            color_btn = tk.Button(row, bg=hex_color, width=2, bd=1, relief=tk.RAISED, command=lambda i=idx: self.change_layer_color(i))
            color_btn.pack(side=tk.LEFT, padx=3)

            is_mirror_label = layer.get("is_mirror_label", False)
            tag = "M" if is_mirror_label else "N"

            ruling = layer.get("screen_ruling", "N/A")
            angle = layer.get("screen_angle", "N/A")
            gra = layer.get("gradation", "N/A")
            
            # print(gra)

            _, total_hist = self.get_layer_histogram_total(idx)
            ink_str = f"{total_hist * 100:.2f}%" if "ink_coverage" in layer else "Hitung..."
            display_text = f"{layer['name'][:14]}  [{tag}]  [{ruling}∠{angle}, {gra}]  [{ink_str}]"
            font_color = "#333333" if is_visible and is_mirror_label else "#FF0000" if is_visible else "#888888"

            lbl_name = tk.Label(row, text=display_text, fg=font_color, bg="#e0e0e0", anchor="w", font=("Arial", 8))
            lbl_name.pack(side=tk.LEFT, fill=tk.X, expand=True)
            layer["lbl_widget"] = lbl_name
            
            dot_text = layer.get("dot_value", "-")
            lbl_dot = tk.Label(row, text=dot_text, font=("Arial", 8, "bold"), fg="#212121" if is_visible else "#888888", bg="#ffffff" if is_visible else "#e0e0e0", width=6, relief=tk.SUNKEN if dot_text != "-" else tk.FLAT, bd=1)
            lbl_dot.pack(side=tk.LEFT, padx=4)

            del_btn = tk.Button(row, text="✕", fg="#FF5252", bg="#e0e0e0", bd=1, relief=tk.RAISED, font=("Arial", 9, "bold"), width=2, command=lambda i=idx: self.remove_layer(i))
            del_btn.pack(side=tk.RIGHT, padx=3)

    def cleanup_resources(self):
        if hasattr(self, "layers") and self.layers:
            for layer in self.layers:
                layer["np_arr"] = None
                layer["transformed_cache"] = None
            self.layers.clear()
            
        self.solo_layer_idx = None
        self.layers_backup = []
        self.canvas_img_id = None
        self._canvas_buffer = None
        
        # Hancurkan widget di dalam layer_frame jika masih ada yang tersisa
        if hasattr(self, "layer_frame"):
            for widget in self.layer_frame.winfo_children():
                widget.destroy()
                
        gc.collect()

    def on_closing(self):
        self.cleanup_resources()
        self.root.destroy()

    def extract_color_from_meta(self, meta_path):
        if not os.path.exists(meta_path): return None
        color_data = {}
        try:
            with open(meta_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    match = re.search(r"(C|M|Y|K)ForPantoneColorSim=(\d+)", line)
                    if match:
                        channel, value = match.groups()
                        color_data[channel] = int(value)

            if {"C", "M", "Y", "K"}.issubset(color_data.keys()):
                c = (255 - color_data["C"]) / 255.0
                m = (255 - color_data["M"]) / 255.0
                y = (255 - color_data["Y"]) / 255.0
                k = (255 - color_data["K"]) / 255.0

                r = max(0, min(255, round(255 * (1 - c) * (1 - k))))
                g = max(0, min(255, round(255 * (1 - m) * (1 - k))))
                b = max(0, min(255, round(255 * (1 - y) * (1 - k))))
                return (r, g, b)
        except Exception: pass
        return None

    def rotate_normal(self):
        if not self.layers: return
        self.rotation_angle = 0
        self.schedule_render(0)

    def rotate_left(self):
        if not self.layers: return
        self.rotation_angle = 270
        self.schedule_render(0)

    def rotate_180(self):
        if not self.layers: return
        self.rotation_angle = 180
        self.schedule_render(0)

    def rotate_right(self):
        if not self.layers: return
        self.rotation_angle = 90
        self.schedule_render(0)

    def flip_horizontal(self):
        if not self.layers: return
        self.is_flipped_h = not self.is_flipped_h
        self.schedule_render(0)

    def reset_transform(self):
        if not self.layers: return
        self.rotation_angle = 0
        self.is_flipped_h = False
        self.schedule_render(0)

    def get_effective_dimensions(self):
        if self.rotation_angle in (90, 270):
            return self.img_height, self.img_width
        return self.img_width, self.img_height

    def schedule_render(self, delay=20):
        if self._debounce_job:
            self.root.after_cancel(self._debounce_job)
        self._debounce_job = self.root.after(delay, self._start_async_render)

    def _start_async_render(self):
        if not self.layers or self.img_width == 0 or self.img_height == 0:
            self.canvas.delete("all")
            self.canvas_img_id = None
            return

        eff_w, eff_h = self.get_effective_dimensions()
        canvas_w = max(800, self.canvas.winfo_width())
        canvas_h = max(600, self.canvas.winfo_height())

        x_left, _ = self.canvas.xview()
        y_top, _ = self.canvas.yview()

        req = {
            "eff_w": eff_w, "eff_h": eff_h, "zoom_scale": self.zoom_scale,
            "canvas_w": canvas_w, "canvas_h": canvas_h,
            "x_left": x_left, "y_top": y_top,
            "threshold_val": self.threshold_var.get(),
            "opacity_val": self.opacity_var.get(),
            "is_dragging": self.is_dragging,
            "rotation_angle": self.rotation_angle,
            "is_flipped_h": self.is_flipped_h,
            "layers": [{"np_arr": l["np_arr"], "inv_color": l.get("inv_color", (1.0 - (l["color_arr"] / 255.0)).reshape(1, 1, 3)), "visible": l.get("visible", True)} for l in self.layers if l.get("visible", True)]
        }

        while not self.render_request_queue.empty():
            try: self.render_request_queue.get_nowait()
            except queue.Empty: break

        self.is_rendering = True
        self.set_status("Rendering...", is_busy=True)
        self.render_request_queue.put(req)
        self.root.after(10, self._check_render_queue)

    def _persistent_render_worker(self):
        while True:
            req = self.render_request_queue.get()
            if req is None: break
            try:
                eff_w, eff_h = req["eff_w"], req["eff_h"]
                zoom_scale = req["zoom_scale"]
                canvas_w, canvas_h = req["canvas_w"], req["canvas_h"]

                new_w = max(1, int(eff_w * zoom_scale))
                new_h = max(1, int(eff_h * zoom_scale))

                view_x1 = int(req["x_left"] * new_w)
                view_y1 = int(req["y_top"] * new_h)
                view_x2 = min(new_w, view_x1 + canvas_w)
                view_y2 = min(new_h, view_y1 + canvas_h)

                pad_px = 120 if not req["is_dragging"] else 30
                padded_x1 = max(0, view_x1 - pad_px)
                padded_y1 = max(0, view_y1 - pad_px)
                padded_x2 = min(new_w, view_x2 + pad_px)
                padded_y2 = min(new_h, view_y2 + pad_px)

                crop_x1 = max(0, min(eff_w - 1, int(padded_x1 / zoom_scale)))
                crop_y1 = max(0, min(eff_h - 1, int(padded_y1 / zoom_scale)))
                crop_x2 = max(crop_x1 + 1, min(eff_w, int(padded_x2 / zoom_scale) + 1))
                crop_y2 = max(crop_y1 + 1, min(eff_h, int(padded_y2 / zoom_scale) + 1))

                display_w = max(1, min(canvas_w + (pad_px * 2), int((crop_x2 - crop_x1) * zoom_scale)))
                display_h = max(1, min(canvas_h + (pad_px * 2), int((crop_y2 - crop_y1) * zoom_scale)))

                render_x1 = int(crop_x1 * zoom_scale)
                render_y1 = int(crop_y1 * zoom_scale)

                actual_threshold = int((100 - req["threshold_val"]) / 100.0 * 255)
                opacity_factor = req["opacity_val"]

                if self._canvas_buffer is None or self._canvas_buffer.shape != (display_h, display_w, 3):
                    self._canvas_buffer = np.full((display_h, display_w, 3), 255.0, dtype=np.float32)
                else:
                    self._canvas_buffer.fill(255.0)

                canvas_float = self._canvas_buffer
                cv_interp = cv2.INTER_NEAREST if req["is_dragging"] else cv2.INTER_LINEAR

                rot_global = req["rotation_angle"]
                flip_h_global = req["is_flipped_h"]

                W_eff = self.img_width
                H_eff = self.img_height

                if rot_global == 0:
                    fx1, fx2, fy1, fy2 = crop_x1, crop_x2, crop_y1, crop_y2
                elif rot_global == 90:
                    fx1, fx2 = crop_y1, crop_y2
                    fy1, fy2 = max(0, H_eff - crop_x2), min(H_eff, H_eff - crop_x1)
                elif rot_global == 180:
                    fx1, fx2 = max(0, W_eff - crop_x2), min(W_eff, W_eff - crop_x1)
                    fy1, fy2 = max(0, H_eff - crop_y2), min(H_eff, H_eff - crop_y1)
                elif rot_global == 270:
                    fx1, fx2 = max(0, W_eff - crop_y2), min(W_eff, W_eff - crop_y1)
                    fy1, fy2 = crop_x1, crop_x2

                if flip_h_global:
                    ox1, ox2 = max(0, W_eff - fx2), min(W_eff, W_eff - fx1)
                    oy1, oy2 = fy1, fy2
                else:
                    ox1, ox2, oy1, oy2 = fx1, fx2, fy1, fy2

                ox1 = max(0, min(W_eff - 1, ox1))
                oy1 = max(0, min(H_eff - 1, oy1))
                ox2 = max(ox1 + 1, min(W_eff, ox2))
                oy2 = max(oy1 + 1, min(H_eff, oy2))

                visible_layers = req["layers"]
                if visible_layers:
                    for layer in reversed(visible_layers):
                        raw_crop = layer["np_arr"][oy1:oy2, ox1:ox2]
                        if raw_crop.size == 0: continue

                        if flip_h_global: raw_crop = np.fliplr(raw_crop)
                        if rot_global == 90: raw_crop = cv2.rotate(raw_crop, cv2.ROTATE_90_CLOCKWISE)
                        elif rot_global == 180: raw_crop = cv2.rotate(raw_crop, cv2.ROTATE_180)
                        elif rot_global == 270: raw_crop = cv2.rotate(raw_crop, cv2.ROTATE_90_COUNTERCLOCKWISE)

                        gray_resized = cv2.resize(raw_crop, (display_w, display_h), interpolation=cv_interp)
                        gray_np = gray_resized.astype(np.float32)

                        if np.min(gray_np) >= actual_threshold: continue
                        alpha = np.where(gray_np < actual_threshold, (255.0 - gray_np) * (opacity_factor / 255.0), 0.0)[:, :, np.newaxis]
                        canvas_float *= (1.0 - (alpha * layer["inv_color"]))

                canvas_np = np.clip(canvas_float, 0, 255).astype(np.uint8)
                base_crop = Image.fromarray(canvas_np)
                self.render_result_queue.put((base_crop, render_x1, render_y1, new_w, new_h))
            except Exception as e:
                self.render_result_queue.put(e)

    def _check_render_queue(self):
        try:
            result = self.render_result_queue.get_nowait()
            self.is_rendering = False
            if result is None:
                self.canvas.delete("all")
                self.canvas_img_id = None
                return
            if isinstance(result, Exception): raise result

            final_scaled, render_x1, render_y1, new_w, new_h = result
            self.canvas.config(scrollregion=(0, 0, new_w, new_h))
            self.tk_image = ImageTk.PhotoImage(final_scaled)

            if self.canvas_img_id is None or not self.canvas.find_withtag(self.canvas_img_id):
                self.canvas.delete("all")
                self.canvas_img_id = self.canvas.create_image(render_x1, render_y1, anchor=tk.NW, image=self.tk_image)
            else:
                self.canvas.itemconfig(self.canvas_img_id, image=self.tk_image)
                self.canvas.coords(self.canvas_img_id, render_x1, render_y1)

            self.txt_zoom.delete(0, tk.END)
            self.txt_zoom.insert(0, f"{int(self.zoom_scale * 100)}%")
            self.draw_measurement_overlay(render_x1, render_y1)

            if not self.active_tool: self.set_status(f"Ready. {len(self.layers)} layer(s) loaded.")
        except queue.Empty:
            self.root.after(10, self._check_render_queue)
        except Exception as e:
            self.set_status("Rendering failed.")
            messagebox.showerror("Error", str(e))

    def _on_opacity_slider_change(self, val):
        self.txt_opacity.delete(0, tk.END)
        self.txt_opacity.insert(0, f"{float(val):.2f}")
        self.schedule_render(10)

    def _on_opacity_text_change(self, event=None):
        try:
            val = max(0.0, min(1.0, float(self.txt_opacity.get())))
            self.opacity_var.set(val)
            self.txt_opacity.delete(0, tk.END)
            self.txt_opacity.insert(0, f"{val:.2f}")
            self.schedule_render()
        except ValueError:
            self.txt_opacity.delete(0, tk.END)
            self.txt_opacity.insert(0, f"{self.opacity_var.get():.2f}")

    def _on_threshold_slider_change(self, val):
        self.txt_threshold.delete(0, tk.END)
        self.txt_threshold.insert(0, str(int(float(val))))
        self.schedule_render(10)

    def _on_threshold_text_change(self, event=None):
        try:
            val = max(0, min(100, int(self.txt_threshold.get())))
            self.threshold_var.set(val)
            self.txt_threshold.delete(0, tk.END)
            self.txt_threshold.insert(0, str(val))
            self.schedule_render()
        except ValueError:
            self.txt_threshold.delete(0, tk.END)
            self.txt_threshold.insert(0, str(self.threshold_var.get()))

    def _on_drag_start(self, event):
        self.is_dragging = True
        self.canvas.scan_mark(event.x, event.y)

    def _on_drag_motion(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_drag_end(self, event):
        self.is_dragging = False
        self.schedule_render(0)

    def _on_vertical_scroll(self, event):
        if event.num == 4 or event.delta > 0: self.canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0: self.canvas.yview_scroll(1, "units")
        self.schedule_render(0)

    def _on_v_scroll(self, *args):
        self.canvas.yview(*args)
        self.schedule_render(0)

    def _on_h_scroll(self, *args):
        self.canvas.xview(*args)
        self.schedule_render(0)

    def _async_calc_ink_coverage(self, layer_dict):
        try:
            ic = 1.0 - (float(np.mean(layer_dict["np_arr"])) / 255.0)
            layer_dict["ink_coverage"] = ic
            if "lbl_widget" in layer_dict and layer_dict["lbl_widget"].winfo_exists():
                tag = "M" if layer_dict.get("is_mirror_label", False) else "N"
                ruling = layer_dict.get("screen_ruling", "N/A")
                angle = layer_dict.get("screen_angle", "N/A")
                gra = layer_dict.get("gradation", "N/A")
                
                new_text = f"{layer_dict['name'][:14]}  [{tag}]  [{ruling}∠{angle}, {gra}]  [{ic * 100:.2f}%]"
                self.root.after(0, lambda: layer_dict["lbl_widget"].config(text=new_text))
        except Exception: pass

    def _process_ink_coverage_queue(self, layers_to_process):
        for layer in layers_to_process:
            self._async_calc_ink_coverage(layer)

    def add_folder(self):
        folder_path = filedialog.askdirectory(title="Choose Image Folder")
        if not folder_path: return

        # 1. Bersihkan memori dan data layer lama
        self.cleanup_resources()

        # 2. Reset tampilan UI panel kanan secara instan sebelum loading dimulai
        for widget in self.layer_frame.winfo_children():
            widget.destroy()
        
        self.size_frame.pack_forget()  # Sembunyikan informasi ukuran sampai file baru siap
        self.lbl_legend_m.pack_forget()
        self.lbl_legend_n.pack_forget()
        
        self.img_width = 0
        self.img_height = 0
        self.size_var.set("Height x Width = - mm")
        self.canvas.delete("all")

        extensions = ["*.tif", "*.tiff", "*.png", "*.jpg", "*.jpeg", "*.bmp"]
        image_files = []
        for ext in extensions:
            image_files.extend(glob.glob(os.path.join(folder_path, ext)))

        if not image_files: return

        # Set status sibuk dan jalankan proses di background thread agar progress bar aktif berputar
        self.set_status("Checking X & Y resolutions and loading files...", is_busy=True)
        threading.Thread(target=self._load_folder_worker, args=(image_files,), daemon=True).start()

    def _load_folder_worker(self, image_files):
        image_files.sort(key=lambda x: os.path.basename(x).lower())
        
        # Bersihkan resource di main thread/safe context
        # Unused karena sudah ada di add_folder
        # self.root.after(0, self.cleanup_resources)

        file_info_list = []
        failed_files = []
        standard_dpi = 300.0

        for path in image_files:
            try:
                w, h = 0, 0
                dpi_x, dpi_y = 300.0, 300.0
                ori = 1
                is_tif = path.lower().endswith(('.tif', '.tiff'))
                success = False

                if is_tif and HAS_TIFFFILE:
                    try:
                        with tifffile.TiffFile(path) as tif:
                            page = tif.pages[0]
                            h, w = page.shape[0], page.shape[1]
                            
                            res_x, res_y = 300.0, 300.0
                            if hasattr(page, 'resolution') and page.resolution:
                                res_x = float(page.resolution[0])
                                res_y = float(page.resolution[1]) if len(page.resolution) > 1 else res_x
                                    
                            unit = page.resolutionunit if hasattr(page, 'resolutionunit') and page.resolutionunit else 2
                            dpi_x = res_x * 2.54 if unit == 3 else res_x
                            dpi_y = res_y * 2.54 if unit == 3 else res_y

                            if 274 in page.tags:
                                val = page.tags[274].value
                                ori = int(val[0]) if hasattr(val, '__getitem__') and not isinstance(val, (str, bytes)) else int(val)
                        success = True
                    except Exception:
                        pass 

                if not success:
                    try:
                        with Image.open(path) as img:
                            w, h = img.size
                            if "dpi" in img.info:
                                dpi_val = img.info["dpi"]
                                if isinstance(dpi_val, tuple) and len(dpi_val) >= 2:
                                    dpi_x, dpi_y = float(dpi_val[0]), float(dpi_val[1])
                                elif isinstance(dpi_val, tuple) and len(dpi_val) >= 1:
                                    dpi_x = dpi_y = float(dpi_val[0])
                    except Exception as e_pil:
                        failed_files.append(f"• {os.path.basename(path)} - Gagal baca metadata: {str(e_pil)}")
                        continue

                if dpi_x > 600.0:
                    dpi_x = 600.0
                if dpi_y > 600.0:
                    dpi_y = 600.0

                file_info_list.append({"path": path, "width": w, "height": h, "dpi_x": dpi_x, "dpi_y": dpi_y, "orientation": ori})
                if dpi_x <= 600 and standard_dpi == 300.0:
                    standard_dpi = dpi_x
            except Exception as e_pass1:
                failed_files.append(f"• {os.path.basename(path)} - Error sistem tahap 1: {str(e_pass1)}")

        if not file_info_list:
            def show_err():
                self.set_status("Failed reading image file.")
                if failed_files:
                    messagebox.showerror("Error", "Failed reading all image files:\n\n" + "\n".join(failed_files))
            self.root.after(0, show_err)
            return

        ref_info = file_info_list[0]
        for info in file_info_list:
            if info["dpi_x"] <= 600:
                ref_info = info
                break

        self.image_dpi = ref_info["dpi_x"]
        new_layers = []

        for idx_info, info in enumerate(file_info_list):
            path = info["path"]
            ori_val = info["orientation"]
            target_dpi_x = info["dpi_x"]
            target_dpi_y = info["dpi_y"]
            
            base_name_no_ext = os.path.splitext(path)[0]
            meta_candidates = [base_name_no_ext, f"{base_name_no_ext}.txt", f"{base_name_no_ext}.meta"]
            
            extracted_rgb = None
            is_mirror_label = False
            layer_ruling = "N/A"
            layer_angle = "N/A"
            gra = "N/A"

            for meta_file in meta_candidates:
                if os.path.exists(meta_file):
                    m_status, screen_ruling, screen_angle, gradation = self.check_metadata_info(meta_file)
                    if m_status: is_mirror_label = True
                    if screen_ruling != "N/A": layer_ruling = screen_ruling
                    if screen_angle != "N/A": layer_angle = screen_angle
                    if gradation != "N/A": gra = gradation
                    if not extracted_rgb: extracted_rgb = self.extract_color_from_meta(meta_file)

            rgb_color = extracted_rgb if extracted_rgb else ImageColor.getrgb(self.default_colors[len(new_layers) % len(self.default_colors)])
            
            np_arr = None
            img_data = None
            is_tif = path.lower().endswith(('.tif', '.tiff'))
            error_msg = "Format tidak dikenali atau gambar kosong"

            try:
                if is_tif and HAS_PYVIPS:
                    try:
                        # 1. KEMBALIKAN access='sequential' agar baca file dari SSD/HDD super kilat (streaming)
                        vips_img = pyvips.Image.new_from_file(path, access='sequential')
                        
                        scale_x = 1.0
                        scale_y = 1.0

                        if target_dpi_x > 600.0: scale_x = 600.0 / target_dpi_x
                        if target_dpi_y > 600.0: scale_y = 600.0 / target_dpi_y
                            
                        MAX_PIXELS = 400_000_000
                        current_pixels = (vips_img.width * scale_x) * (vips_img.height * scale_y)
                        
                        if current_pixels > MAX_PIXELS:
                            ratio = math.sqrt(MAX_PIXELS / current_pixels)
                            scale_x *= ratio
                            scale_y *= ratio
                            
                        # 2. Pyvips HANYA bertugas mengecilkan gambar (masih sangat aman secara sequential)
                        if scale_x < 1.0 or scale_y < 1.0:
                            vips_img = vips_img.resize(scale_x, vscale=scale_y, kernel='linear')
                            
                        if vips_img.bands > 1: vips_img = vips_img.colourspace('b-w')
                        if vips_img.format != 'uchar': vips_img = vips_img.cast('uchar')
                            
                        # 3. PAKSA EKSEKUSI SEKARANG sebelum ada perintah rotasi
                        mem = vips_img.write_to_memory()
                        np_arr_temp = np.ndarray(buffer=mem, dtype=np.uint8, shape=(vips_img.height, vips_img.width))
                        np_arr = np_arr_temp.copy()

                        del vips_img
                        del mem
                        del np_arr_temp
                        gc.collect()

                        # Koreksi polaritas TIF 1-bit secara in-place
                        if np_arr.max() <= 1:
                            np_arr ^= 1        
                            np_arr *= 255      

                        # 4. ROTASI DIALIHKAN KE OPENCV: Eksekusi instan karena array (np_arr) sudah berukuran kecil
                        if ori_val == 2: np_arr = cv2.flip(np_arr, 1)
                        elif ori_val == 3: np_arr = cv2.rotate(np_arr, cv2.ROTATE_180)
                        elif ori_val == 4: np_arr = cv2.flip(cv2.rotate(np_arr, cv2.ROTATE_180), 1)
                        elif ori_val == 5: np_arr = cv2.flip(cv2.rotate(np_arr, cv2.ROTATE_90_CLOCKWISE), 1)
                        elif ori_val == 6: np_arr = cv2.rotate(np_arr, cv2.ROTATE_90_CLOCKWISE)
                        elif ori_val == 7: np_arr = cv2.flip(cv2.rotate(np_arr, cv2.ROTATE_90_COUNTERCLOCKWISE), 1)
                        elif ori_val == 8: np_arr = cv2.rotate(np_arr, cv2.ROTATE_90_COUNTERCLOCKWISE)
                        
                    except Exception as e_vips:
                        print(f"\n[DEBUG] PyVips Error: {str(e_vips)}")
                        error_msg = f"Pyvips internal failure: {str(e_vips)}"
                        np_arr = None

                if np_arr is None:
                    if is_tif and HAS_TIFFFILE:
                        try: img_data = tifffile.memmap(path)
                        except Exception:
                            try: img_data = tifffile.imread(path)
                            except Exception: pass 

                    if img_data is None:
                        try:
                            with Image.open(path) as pil_img:
                                s_x, s_y = 1.0, 1.0
                                if target_dpi_x > 600.0: s_x = 600.0 / target_dpi_x
                                if target_dpi_y > 600.0: s_y = 600.0 / target_dpi_y
                                    
                                MAX_PIXELS = 400_000_000
                                curr_px = (pil_img.width * s_x) * (pil_img.height * s_y)
                                
                                if curr_px > MAX_PIXELS:
                                    r = math.sqrt(MAX_PIXELS / curr_px)
                                    s_x *= r
                                    s_y *= r
                                    
                                if s_x < 1.0 or s_y < 1.0:
                                    new_w = max(1, int(pil_img.width * s_x))
                                    new_h = max(1, int(pil_img.height * s_y))
                                    pil_img = pil_img.resize((new_w, new_h), Image.Resampling.NEAREST)
                                
                                # Konversi mode hanya dieksekusi SETELAH gambar menjadi kecil
                                if pil_img.mode != 'L': 
                                    pil_img = pil_img.convert('L')
                                
                                img_data = np.array(pil_img)
                        except Exception as e_pil:
                            error_msg = f"Insufficient RAM (PIL fallback failed): {str(e_pil)}"

                if np_arr is None and img_data is not None:
                    if len(img_data.shape) == 3:
                        img_data = cv2.cvtColor(img_data, cv2.COLOR_RGBA2GRAY if img_data.shape[2] == 4 else cv2.COLOR_RGB2GRAY)
                    if img_data.dtype == bool or img_data.max() <= 1: 
                        if img_data.dtype == bool:
                            img_data = img_data.astype(np.uint8)
                        img_data *= 255  # Operasi in-place
                    elif img_data.dtype != np.uint8: 
                        img_data = cv2.normalize(img_data, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)

                    oriented_img = self.apply_tiff_orientation(img_data, ori_val)
                    
                    s_x, s_y = 1.0, 1.0
                    if target_dpi_x > 600.0: s_x = 600.0 / target_dpi_x
                    if target_dpi_y > 600.0: s_y = 600.0 / target_dpi_y
                        
                    MAX_PIXELS = 400_000_000
                    curr_px = (oriented_img.shape[1] * s_x) * (oriented_img.shape[0] * s_y)
                    if curr_px > MAX_PIXELS:
                        r = math.sqrt(MAX_PIXELS / curr_px)
                        s_x *= r
                        s_y *= r

                    # --- MULAI DIBUNGKUS PENANGANAN ERROR ---
                    try:
                        if s_x < 1.0 or s_y < 1.0:
                            new_w = max(1, int(oriented_img.shape[1] * s_x))
                            new_h = max(1, int(oriented_img.shape[0] * s_y))
                            np_arr = cv2.resize(oriented_img, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
                        else:
                            np_arr = np.array(oriented_img, copy=True)
                    except cv2.error as e_cv:
                        print(f"[WARNING] OpenCV Out of Memory: {e_cv}")
                        gc.collect()
                        error_msg = f"OpenCV insufficient memory: {str(e_cv)}"
                        np_arr = None
                    # --- SELESAI DIBUNGKUS ---

                    del img_data
                    del oriented_img
                    gc.collect()

                if np_arr is not None:
                    h_ori, w_ori = np_arr.shape[:2]

                    if idx_info == 0:
                        self.img_width = w_ori
                        self.img_height = h_ori

                    if w_ori != self.img_width or h_ori != self.img_height:
                        np_arr = cv2.resize(np_arr, (self.img_width, self.img_height), interpolation=cv2.INTER_NEAREST)

            except Exception as e_proc:
                error_msg = f"Array system failure: {str(e_proc)}"

            if np_arr is None:
                failed_files.append(f"• {os.path.basename(path)}\n   ↳ Detail: {error_msg}")
                continue

            # Tambahkan baris ini untuk memaksa pembersihan memori per file
            gc.collect()

            color_arr = np.array(rgb_color, dtype=np.float32)
            new_layers.append({
                "path": path, "name": os.path.basename(path),
                "color": rgb_color, "original_color": rgb_color,
                "color_arr": color_arr, "inv_color": (1.0 - (color_arr / 255.0)).reshape(1, 1, 3),
                "visible": True, "is_mirror_label": is_mirror_label,
                "screen_ruling": layer_ruling, "screen_angle": layer_angle, "gradation": gra,
                "np_arr": np_arr, "dot_value": "-"
            })

            # Tambahan pembersihan RAM per file agar tidak menumpuk dengan Firefox
            gc.collect()

        # Selesaikan update UI di main thread
        def finalize_loading():
            if failed_files:
                msg = "Some files encountered issues while loading:\n\n" + "\n\n".join(failed_files)
                messagebox.showwarning("File Failure Warning", msg)

            self.layers = new_layers
            if not self.layers:
                self.set_status("No layers successfully loaded.")
                return

            threading.Thread(target=self._process_ink_coverage_queue, args=(self.layers.copy(),), daemon=True).start()

            self.size_frame.pack(fill=tk.X, padx=10, pady=2, ipady=3, before=self.layer_container)
            self.lbl_legend_m.pack(fill=tk.X, padx=10, pady=(4, 0))
            self.lbl_legend_n.pack(fill=tk.X, padx=10, pady=(0, 8))

            self.update_layer_list_ui()
            self.update_size_info()
            self.zoom_to_fit()
            self.set_status(f"Ready. {len(self.layers)} layers loaded.")

        self.root.after(0, finalize_loading)

    def toggle_layer_visibility(self, idx):
        if self.solo_layer_idx is not None:
            for layer in self.layers:
                layer["color"] = layer["original_color"]
                layer["color_arr"] = np.array(layer["original_color"], dtype=np.float32)
                layer["inv_color"] = (1.0 - (layer["color_arr"] / 255.0)).reshape(1, 1, 3)
            self.solo_layer_idx, self.layers_backup = None, []

        self.layers[idx]["visible"] = not self.layers[idx]["visible"]
        self.update_layer_list_ui()
        self.schedule_render(0)
        
    def toggle_solo_black_and_white(self, idx):
        if self.solo_layer_idx == idx:
            for i, layer in enumerate(self.layers):
                layer["visible"] = self.layers_backup[i]["visible"] if self.layers_backup else True
                layer["color"] = layer["original_color"]
                layer["color_arr"] = np.array(layer["original_color"], dtype=np.float32)
                layer["inv_color"] = (1.0 - (layer["color_arr"] / 255.0)).reshape(1, 1, 3)
            self.solo_layer_idx, self.layers_backup = None, []
        else:
            if self.solo_layer_idx is None:
                self.layers_backup = [{"visible": l["visible"]} for l in self.layers]
            for i, layer in enumerate(self.layers):
                layer["visible"] = (i == idx)
                if i == idx:
                    layer["color"] = (0, 0, 0)
                    layer["color_arr"] = np.array((0, 0, 0), dtype=np.float32)
                    layer["inv_color"] = np.ones((1, 1, 3), dtype=np.float32)
            self.solo_layer_idx = idx
        self.update_layer_list_ui()
        self.schedule_render(0)

    def change_layer_color(self, idx):
        color_result = colorchooser.askcolor(title="Pilih Warna")
        if color_result and color_result[0] is not None:
            if self.solo_layer_idx is not None: self.toggle_solo_black_and_white(self.solo_layer_idx)
            new_color = tuple(int(c) for c in color_result[0])
            self.layers[idx]["color"] = self.layers[idx]["original_color"] = new_color
            color_arr = np.array(new_color, dtype=np.float32)
            self.layers[idx]["color_arr"] = color_arr
            self.layers[idx]["inv_color"] = (1.0 - (color_arr / 255.0)).reshape(1, 1, 3)
            self.update_layer_list_ui()
            self.schedule_render(0)

    def remove_layer(self, idx):
        if self.solo_layer_idx is not None: self.toggle_solo_black_and_white(self.solo_layer_idx)
        self.layers[idx]["np_arr"] = None
        self.layers.pop(idx)
        self.update_layer_list_ui()
        self.schedule_render(0)

    def zoom_in(self):
        if self.layers: self.zoom_scale = min(10.0, self.zoom_scale * 1.25); self.schedule_render(0)

    def zoom_out(self):
        if self.layers: self.zoom_scale = max(0.05, self.zoom_scale / 1.25); self.schedule_render(0)

    def reset_zoom(self):
        if self.layers: self.zoom_scale = 1.0; self.schedule_render(0)

    def zoom_to_fit(self):
        if not self.layers or self.img_width == 0 or self.img_height == 0: return
        self.root.update_idletasks()
        canvas_w, canvas_h = max(800, self.canvas.winfo_width()), max(600, self.canvas.winfo_height())
        eff_w, eff_h = self.get_effective_dimensions()
        self.zoom_scale = max(0.05, min(10.0, min(canvas_w / float(eff_w), canvas_h / float(eff_h))))
        self.schedule_render(0)

    def _on_zoom_text_change(self, event=None):
        if not self.layers: return
        try:
            self.zoom_scale = max(0.05, min(10.0, float(self.txt_zoom.get().replace("%", "").strip()) / 100.0))
            self.schedule_render(0)
        except ValueError:
            self.txt_zoom.delete(0, tk.END); self.txt_zoom.insert(0, f"{int(self.zoom_scale * 100)}%")


if __name__ == "__main__":
    root = tk.Tk()
    app = AndreyImageViewerApp(root)
    root.mainloop()