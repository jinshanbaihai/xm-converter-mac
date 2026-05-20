# -*- coding: utf-8 -*-
"""
喜马拉雅 XM 文件批量解密 + 转 MP3 工具 (Mac GUI 版)

核心解密逻辑来自上游开源项目:
    https://github.com/sld272/Ximalaya-XM-Decrypt
本程序在其基础上增加了拖拽 GUI、批量处理、自动转 mp3 等功能。
"""

import base64
import io
import os
import sys
import glob
import shutil
import subprocess
import threading
import pathlib
import traceback

import mutagen
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from mutagen.easyid3 import ID3

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# 拖拽支持 (tkinterdnd2)
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

# wasm 运行时
import wasmtime


# ============================================================
# 以下 XMInfo / get_xm_info / xm_decrypt / find_ext / replace_invalid_chars
# 全部来自原作者 sld272/Ximalaya-XM-Decrypt 的 main.py，
# 仅把 wasmer 调用替换为 wasmtime 调用（语义一对一对应）。
# ============================================================

class XMInfo:
    def __init__(self):
        self.title = ""
        self.artist = ""
        self.album = ""
        self.tracknumber = 0
        self.size = 0
        self.header_size = 0
        self.ISRC = ""
        self.encodedby = ""
        self.encoding_technology = ""

    def iv(self):
        if self.ISRC != "":
            return bytes.fromhex(self.ISRC)
        return bytes.fromhex(self.encodedby)


def get_xm_info(data: bytes):
    id3 = ID3(io.BytesIO(data), v2_version=3)
    v = XMInfo()
    v.title = str(id3["TIT2"])
    v.album = str(id3["TALB"])
    v.artist = str(id3["TPE1"])
    v.tracknumber = int(str(id3["TRCK"]))
    v.ISRC = "" if id3.get("TSRC") is None else str(id3["TSRC"])
    v.encodedby = "" if id3.get("TENC") is None else str(id3["TENC"])
    v.size = int(str(id3["TSIZ"]))
    v.header_size = id3.size
    v.encoding_technology = str(id3["TSSE"])
    return v


def get_printable_count(x: bytes):
    i = 0
    for i, c in enumerate(x):
        if c < 0x20 or c > 0x7e:
            return i
    return i


def get_printable_bytes(x: bytes):
    return x[:get_printable_count(x)]


def _wasm_path():
    """xm_encryptor.wasm 与本脚本同目录"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "xm_encryptor.wasm")


def xm_decrypt(raw_data):
    """解密函数（实现来自上游项目 sld272/Ximalaya-XM-Decrypt）"""
    # ---- 加载 wasm ----
    engine = wasmtime.Engine()
    store = wasmtime.Store(engine)
    module = wasmtime.Module.from_file(engine, _wasm_path())
    linker = wasmtime.Linker(engine)
    instance = linker.instantiate(store, module)
    exports = instance.exports(store)

    fn_a = exports["a"]
    fn_c = exports["c"]
    fn_g = exports["g"]
    memory = exports["i"]  # 与原作者命名一致

    # ---- 读取 ID3 信息 ----
    xm_info = get_xm_info(raw_data)
    encrypted_data = raw_data[xm_info.header_size:xm_info.header_size + xm_info.size]

    # ---- Stage 1 ----
    xm_key = b"ximalayaximalayaximalayaximalaya"
    cipher = AES.new(xm_key, AES.MODE_CBC, xm_info.iv())
    de_data = cipher.decrypt(pad(encrypted_data, 16))

    # ---- Stage 2 ----
    de_data = get_printable_bytes(de_data)
    track_id = str(xm_info.tracknumber).encode()

    stack_pointer = fn_a(store, -16)
    de_data_offset = fn_c(store, len(de_data))
    track_id_offset = fn_c(store, len(track_id))

    # 写入 de_data
    mem_buf = memory.data_ptr(store)
    mem_size = memory.data_len(store)
    for i, b in enumerate(de_data):
        mem_buf[de_data_offset + i] = b
    for i, b in enumerate(track_id):
        mem_buf[track_id_offset + i] = b

    fn_g(store, stack_pointer, de_data_offset, len(de_data),
         track_id_offset, len(track_id))

    # 读 int32 结果指针
    import ctypes
    int32_ptr = ctypes.cast(
        ctypes.addressof(mem_buf.contents) + stack_pointer,
        ctypes.POINTER(ctypes.c_int32),
    )
    result_pointer = int32_ptr[0]
    result_length = int32_ptr[1]

    result_data = bytes(mem_buf[result_pointer:result_pointer + result_length]).decode()

    # ---- Stage 3 ----
    decrypted_data = base64.b64decode(xm_info.encoding_technology + result_data)
    final_data = decrypted_data + raw_data[xm_info.header_size + xm_info.size:]
    return xm_info, final_data


def find_ext(data):
    """
    通过文件头字节识别解密后的音频格式。
    不依赖 libmagic（避免用户需要额外 brew install libmagic）。
    """
    if len(data) >= 12:
        # ISO BMFF 容器（m4a / mp4 / aac）
        if data[4:8] == b"ftyp":
            return "m4a"
        # MP3：带 ID3 头 或 MPEG 同步字节
        if data[:3] == b"ID3" or data[:2] == b"\xff\xfb" or data[:2] == b"\xff\xf3" or data[:2] == b"\xff\xfa":
            return "mp3"
        # FLAC
        if data[:4] == b"fLaC":
            return "flac"
        # WAV
        if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            return "wav"
        # OGG（兜底支持）
        if data[:4] == b"OggS":
            return "ogg"

    # 认不出来就按 m4a 处理（喜马拉雅 95% 以上是 m4a，
    # 即使猜错，ffmpeg 也能从文件本身识别真实编码）
    print(f"  ⚠ 文件头未识别（前 16 字节: {data[:16].hex()}），按 m4a 处理")
    return "m4a"


def replace_invalid_chars(name):
    invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for char in invalid_chars:
        if char in name:
            name = name.replace(char, " ")
    return name


# ============================================================
# 以下是相对原作者增加的部分: 输出统一为 mp3
# ============================================================

def find_ffmpeg():
    """
    查找 ffmpeg 可执行文件，按优先级：
      1. 项目目录下 bin/ffmpeg（内嵌版，用户也可手动放进去）
      2. 系统 PATH
      3. Homebrew 常见安装路径
    """
    # 1. 项目内嵌
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.join(base, "bin", "ffmpeg")
    if os.path.exists(bundled) and os.access(bundled, os.X_OK):
        return bundled

    # 2. PATH
    p = shutil.which("ffmpeg")
    if p:
        return p

    # 3. Homebrew 常见路径
    for cand in (
        "/opt/homebrew/bin/ffmpeg",        # Apple Silicon
        "/usr/local/bin/ffmpeg",           # Intel
        "/opt/homebrew/opt/ffmpeg/bin/ffmpeg",
    ):
        if os.path.exists(cand):
            return cand
    return None


def decrypt_and_convert(from_file, output_path, log_fn, ffmpeg_bin):
    """解密一个 xm 文件并转换为 mp3"""
    log_fn(f"▶ 正在解密 {os.path.basename(from_file)}")
    data = pathlib.Path(from_file).read_bytes()
    info, audio_data = xm_decrypt(data)
    ext = find_ext(audio_data[:0xff])

    # 输出目录: <output_path>/<album>/
    album_dir = os.path.join(output_path, replace_invalid_chars(info.album))
    os.makedirs(album_dir, exist_ok=True)
    title_safe = replace_invalid_chars(info.title)
    intermediate = os.path.join(album_dir, f"{title_safe}.{ext}")

    # 写解密后的中间文件，并写入 ID3 标签
    buffer = io.BytesIO(audio_data)
    try:
        tags = mutagen.File(buffer, easy=True)
        if tags is not None:
            tags["title"] = info.title
            tags["album"] = info.album
            tags["artist"] = info.artist
            tags.save(buffer)
    except Exception as e:
        log_fn(f"  ⚠ 写标签失败: {e}（不影响音频）")

    with open(intermediate, "wb") as f:
        buffer.seek(0)
        f.write(buffer.read())

    # 若已经是 mp3，直接完工
    if ext == "mp3":
        log_fn(f"  ✓ 已是 mp3，输出: {intermediate}")
        return intermediate

    # 否则用 ffmpeg 转 mp3
    mp3_path = os.path.join(album_dir, f"{title_safe}.mp3")
    log_fn(f"  → ffmpeg 转换 {ext} → mp3")
    cmd = [
        ffmpeg_bin, "-y", "-i", intermediate,
        "-codec:a", "libmp3lame", "-qscale:a", "2",
        "-id3v2_version", "3",
        mp3_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        log_fn(f"  ✗ ffmpeg 失败: {proc.stderr[-300:]}")
        log_fn(f"    中间文件保留在: {intermediate}")
        return None

    # 转换成功，删掉中间文件
    try:
        os.remove(intermediate)
    except OSError:
        pass
    log_fn(f"  ✓ 完成: {mp3_path}")
    return mp3_path


# ============================================================
# GUI 部分
# ============================================================

class App:
    def __init__(self, root):
        self.root = root
        root.title("喜马拉雅 XM → MP3 转换器")
        root.geometry("720x520")

        # 顶部说明
        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="拖拽 .xm 文件或文件夹到下方区域，或点按钮选择",
                  font=("Helvetica", 13)).pack(anchor="w")

        # 输出目录选择
        out_frame = ttk.Frame(root, padding=(10, 0))
        out_frame.pack(fill="x")
        ttk.Label(out_frame, text="输出目录:").pack(side="left")
        self.output_var = tk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "Desktop", "XM_Output")
        )
        ttk.Entry(out_frame, textvariable=self.output_var).pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Button(out_frame, text="选择…", command=self.choose_output).pack(side="left")

        # 拖拽区
        self.drop_zone = tk.Label(
            root,
            text="\n\n把 .xm 文件或文件夹拖到这里\n\n（也可以多选）\n\n",
            relief="ridge", bd=2, bg="#f0f0f0", fg="#555",
            font=("Helvetica", 14),
        )
        self.drop_zone.pack(fill="both", expand=False, padx=10, pady=10, ipady=20)

        if DND_AVAILABLE:
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind("<<Drop>>", self.on_drop)
        else:
            self.drop_zone.config(
                text="\n\n⚠ 未安装 tkinterdnd2，拖拽不可用\n请点下面按钮手动选择文件\n\n"
            )

        # 按钮区
        btn_frame = ttk.Frame(root, padding=(10, 0))
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="选择文件…", command=self.choose_files).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="选择文件夹…", command=self.choose_folder).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="清空日志", command=self.clear_log).pack(side="right", padx=4)

        # 日志
        self.log = scrolledtext.ScrolledText(root, height=14, font=("Menlo", 11))
        self.log.pack(fill="both", expand=True, padx=10, pady=10)

        # 启动检查
        self.check_env()

    # ---------- 工具方法 ----------
    def log_line(self, s):
        self.log.insert("end", s + "\n")
        self.log.see("end")
        self.root.update_idletasks()

    def clear_log(self):
        self.log.delete("1.0", "end")

    def choose_output(self):
        d = filedialog.askdirectory(initialdir=self.output_var.get())
        if d:
            self.output_var.set(d)

    def choose_files(self):
        files = filedialog.askopenfilenames(
            title="选择 .xm 文件",
            filetypes=[("XM files", "*.xm"), ("All files", "*.*")],
        )
        if files:
            self.process_paths(list(files))

    def choose_folder(self):
        d = filedialog.askdirectory(title="选择包含 .xm 的文件夹")
        if d:
            self.process_paths([d])

    def on_drop(self, event):
        # tkinterdnd2 返回的字符串可能是 {path with space} a b 这种格式
        paths = self.root.tk.splitlist(event.data)
        self.process_paths(list(paths))

    def check_env(self):
        if not DND_AVAILABLE:
            self.log_line("⚠ tkinterdnd2 未安装，拖拽功能不可用（其他功能正常）。")
        wp = _wasm_path()
        if not os.path.exists(wp):
            self.log_line(f"✗ 找不到 xm_encryptor.wasm，应位于: {wp}")
        else:
            self.log_line(f"✓ wasm 文件就绪: {wp}")
        ff = find_ffmpeg()
        if not ff:
            self.log_line("✗ 没找到 ffmpeg。请先安装：brew install ffmpeg")
        else:
            self.log_line(f"✓ ffmpeg 就绪: {ff}")

    def process_paths(self, paths):
        """展开拖入路径，收集所有 .xm 文件，丢到后台线程跑"""
        xm_files = []
        for p in paths:
            p = p.strip()
            if not p:
                continue
            if os.path.isdir(p):
                xm_files.extend(sorted(glob.glob(os.path.join(p, "**", "*.xm"), recursive=True)))
            elif os.path.isfile(p) and p.lower().endswith(".xm"):
                xm_files.append(p)
            else:
                self.log_line(f"忽略（非 .xm）: {p}")

        if not xm_files:
            messagebox.showinfo("提示", "没有找到 .xm 文件")
            return

        ff = find_ffmpeg()
        if not ff:
            messagebox.showerror("缺少 ffmpeg", "请先在终端运行：\n\nbrew install ffmpeg")
            return

        output = self.output_var.get()
        os.makedirs(output, exist_ok=True)

        self.log_line(f"\n=== 开始处理 {len(xm_files)} 个文件 ===")
        threading.Thread(
            target=self._run_batch,
            args=(xm_files, output, ff),
            daemon=True,
        ).start()

    def _run_batch(self, files, output, ff):
        ok, fail = 0, 0
        for f in files:
            try:
                r = decrypt_and_convert(f, output, self.log_line, ff)
                if r:
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                fail += 1
                self.log_line(f"  ✗ 出错: {e}")
                self.log_line(traceback.format_exc())
        self.log_line(f"\n=== 完成: 成功 {ok}，失败 {fail} ===\n")


def main():
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
