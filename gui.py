"""archive_categorizer/gui.py - tkinter 图形界面（支持多源文件夹、分页、暴力破解）"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import re
from collections import Counter
from pathlib import Path
from core import (read_passwords, categorize_archives, get_missing_tool_message,
                  find_archives, estimate_bruteforce, generate_bruteforce_passwords,
                  test_password, get_multi_volume_parts, is_archive_file)


PAGE_SIZE = 20


class ArchiveCategorizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("压缩包密码分类工具")
        self.root.geometry("880x750")
        self.root.minsize(780, 650)

        self.source_dirs = []
        self.dest_dir = tk.StringVar()
        self.password_file = tk.StringVar()
        self.move_mode = tk.BooleanVar(value=False)

        # Pagination state
        self.all_results = []
        self.current_page = 0
        self.total_pages = 0
        self.dest_path_cached = ""

        # Brute-force state
        self.bf_archives = []       # list of (abspath, relpath) for unmatched archives
        self.bf_current_folder = ""

        self.create_widgets()

    def create_widgets(self):
        header = ttk.Frame(self.root, padding=10)
        header.pack(fill=tk.X)
        ttk.Label(header, text="压缩包密码分类工具",
                  font=("Microsoft YaHei UI", 18, "bold")).pack()
        ttk.Label(header, text="扫描文件夹中的压缩包，用密码尝试解压，按密码分类存放",
                  font=("Microsoft YaHei UI", 10), foreground="gray").pack(pady=(2, 0))

        main_frame = ttk.Frame(self.root, padding=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- 源文件夹 ---
        src_frame = ttk.LabelFrame(main_frame, text="源文件夹（可添加多个）", padding=8)
        src_frame.pack(fill=tk.X, pady=(0, 6))
        lf = ttk.Frame(src_frame)
        lf.pack(fill=tk.X, pady=(0, 4))
        self.src_listbox = tk.Listbox(lf, height=2, font=("Consolas", 10))
        sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.src_listbox.yview)
        self.src_listbox.configure(yscrollcommand=sb.set)
        self.src_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        sr = ttk.Frame(src_frame)
        sr.pack(fill=tk.X)
        ttk.Button(sr, text="添加源文件夹", command=self.add_source).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(sr, text="删除选中", command=self.remove_source).pack(side=tk.LEFT)

        # --- 目标文件夹 + 密码文件 row ---
        opt_frame = ttk.Frame(main_frame)
        opt_frame.pack(fill=tk.X, pady=(0, 6))
        # Dest
        dest_f = ttk.LabelFrame(opt_frame, text="目标文件夹（分类结果）", padding=6)
        dest_f.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        dr = ttk.Frame(dest_f)
        dr.pack(fill=tk.X)
        self.dest_entry = ttk.Entry(dr, textvariable=self.dest_dir, state="readonly", font=("Consolas", 10))
        self.dest_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(dr, text="浏览", command=self.browse_dest).pack(side=tk.RIGHT)
        # Password
        pwd_f = ttk.LabelFrame(opt_frame, text="密码文件", padding=6)
        pwd_f.pack(side=tk.LEFT, fill=tk.X, expand=True)
        pr = ttk.Frame(pwd_f)
        pr.pack(fill=tk.X)
        self.pwd_entry = ttk.Entry(pr, textvariable=self.password_file, state="readonly", font=("Consolas", 10))
        self.pwd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(pr, text="浏览", command=self.browse_password).pack(side=tk.RIGHT, padx=(0, 4))
        ttk.Button(pr, text="创建示例", command=self.create_sample_password).pack(side=tk.RIGHT)

        # --- 操作按钮 ---
        act_frame = ttk.Frame(main_frame)
        act_frame.pack(fill=tk.X, pady=(0, 6))
        self.start_btn = ttk.Button(act_frame, text="开始分类", command=self.start_categorize,
                                    style="Accent.TButton")
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(act_frame, text="清空结果", command=self.clear_results).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Checkbutton(act_frame, text="移动文件（删除源文件）",
                        variable=self.move_mode).pack(side=tk.LEFT, padx=(0, 15))

        # --- 进度条 ---
        prog_frame = ttk.Frame(main_frame)
        prog_frame.pack(fill=tk.X, pady=(0, 4))
        self.progress_bar = ttk.Progressbar(prog_frame, mode="determinate")
        self.progress_bar.pack(fill=tk.X, expand=True, side=tk.LEFT, padx=(0, 6))
        self.progress_label = ttk.Label(prog_frame, text="就绪", width=25, anchor=tk.W)
        self.progress_label.pack(side=tk.RIGHT, padx=(0, 4))
        self.open_btn = ttk.Button(prog_frame, text="打开目标文件夹", command=self.open_dest, state=tk.DISABLED)
        self.open_btn.pack(side=tk.RIGHT)

        # --- Notebook ---
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: 分类结果
        self._build_results_tab()
        # Tab 2: 暴力破解
        self._build_bruteforce_tab()

        # --- 底部状态栏 ---
        self.status_bar = ttk.Label(self.root, text="就绪", relief=tk.SUNKEN, anchor=tk.W, padding=(10, 2))
        self.status_bar.pack(fill=tk.X)

    # ========== Tab 1: 分类结果 ==========
    def _build_results_tab(self):
        tab = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(tab, text="分类结果")

        columns = ("file", "source", "password", "status")
        self.tree = ttk.Treeview(tab, columns=columns, show="headings", height=14)
        self.tree.heading("file", text="压缩包")
        self.tree.heading("source", text="来源")
        self.tree.heading("password", text="匹配密码")
        self.tree.heading("status", text="状态")
        self.tree.column("file", width=320, anchor=tk.W)
        self.tree.column("source", width=100, anchor=tk.W)
        self.tree.column("password", width=180, anchor=tk.W)
        self.tree.column("status", width=120, anchor=tk.CENTER)
        sb_t = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb_t.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_t.pack(side=tk.RIGHT, fill=tk.Y)

        # Pagination
        pg = ttk.Frame(tab)
        pg.pack(fill=tk.X, pady=(3, 0))
        self.page_prev_btn = ttk.Button(pg, text="◀ 上一页", command=self._prev_page, state=tk.DISABLED)
        self.page_prev_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.page_next_btn = ttk.Button(pg, text="下一页 ▶", command=self._next_page, state=tk.DISABLED)
        self.page_next_btn.pack(side=tk.LEFT)
        self.page_label = ttk.Label(pg, text="", foreground="gray")
        self.page_label.pack(side=tk.LEFT, padx=(15, 0))

    # ========== Tab 2: 暴力破解 ==========
    def _build_bruteforce_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="暴力破解")

        # Top controls
        ctrl = ttk.Frame(tab)
        ctrl.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(ctrl, text="扫描未匹配文件", command=self._bf_scan_unmatched).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(ctrl, text="最大位数:").pack(side=tk.LEFT, padx=(0, 4))
        self.bf_length_var = tk.IntVar(value=3)
        ttk.Spinbox(ctrl, from_=1, to=4, textvariable=self.bf_length_var, width=4).pack(side=tk.LEFT, padx=(0, 10))
        self.bf_est_label = ttk.Label(ctrl, text="", foreground="gray")
        self.bf_est_label.pack(side=tk.LEFT, padx=(0, 10))
        self.bf_start_btn = ttk.Button(ctrl, text="开始暴力破解", command=self._bf_start,
                                       state=tk.DISABLED, style="Accent.TButton")
        self.bf_start_btn.pack(side=tk.LEFT)

        # Unmatched archive list
        list_f = ttk.LabelFrame(tab, text="待破解的压缩包", padding=5)
        list_f.pack(fill=tk.X, pady=(0, 6))
        lf_row = ttk.Frame(list_f)
        lf_row.pack(fill=tk.X)
        self.bf_listbox = tk.Listbox(lf_row, height=5, font=("Consolas", 10))
        sb_bf = ttk.Scrollbar(lf_row, orient=tk.VERTICAL, command=self.bf_listbox.yview)
        self.bf_listbox.configure(yscrollcommand=sb_bf.set)
        self.bf_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sb_bf.pack(side=tk.RIGHT, fill=tk.Y)

        # BF progress
        bf_prog = ttk.Frame(tab)
        bf_prog.pack(fill=tk.X, pady=(0, 4))
        self.bf_progress_bar = ttk.Progressbar(bf_prog, mode="determinate")
        self.bf_progress_bar.pack(fill=tk.X, expand=True, side=tk.LEFT, padx=(0, 6))
        self.bf_progress_label = ttk.Label(bf_prog, text="", width=30, anchor=tk.W)
        self.bf_progress_label.pack(side=tk.RIGHT)

        # BF results table
        res_f = ttk.LabelFrame(tab, text="暴力破解结果", padding=5)
        res_f.pack(fill=tk.BOTH, expand=True)
        cols = ("file", "password", "status")
        self.bf_tree = ttk.Treeview(res_f, columns=cols, show="headings", height=8)
        self.bf_tree.heading("file", text="压缩包")
        self.bf_tree.heading("password", text="破解密码")
        self.bf_tree.heading("status", text="状态")
        self.bf_tree.column("file", width=350, anchor=tk.W)
        self.bf_tree.column("password", width=200, anchor=tk.W)
        self.bf_tree.column("status", width=120, anchor=tk.CENTER)
        sb_bfr = ttk.Scrollbar(res_f, orient=tk.VERTICAL, command=self.bf_tree.yview)
        self.bf_tree.configure(yscrollcommand=sb_bfr.set)
        self.bf_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_bfr.pack(side=tk.RIGHT, fill=tk.Y)

        self.bf_listbox.bind("<<ListboxSelect>>", self._bf_update_estimate)

    def _bf_update_estimate(self, event=None):
        max_len = self.bf_length_var.get()
        total, time_str, level = estimate_bruteforce(max_len)
        color = "red" if level >= 2 else ("orange" if level == 1 else "gray")
        self.bf_est_label.config(text="共 %d 种组合，%s" % (total, time_str), foreground=color)

    # ========== 暴力破解：扫描未匹配 ==========
    def _bf_scan_unmatched(self):
        dest = self.dest_dir.get()
        if not dest:
            messagebox.showerror("错误", "请先选择目标文件夹并完成一次分类")
            return
        unsolved_dir = os.path.join(dest, "未匹配密码")
        if not os.path.isdir(unsolved_dir):
            messagebox.showinfo('提示', '目标文件夹中没有[未匹配密码]目录，请先运行一次分类')
            return

        self.bf_archives = []
        self.bf_listbox.delete(0, tk.END)
        self.bf_current_folder = unsolved_dir

        # Scan for archive files in "未匹配密码" folder
        for root, dirs, files in os.walk(unsolved_dir):
            for f in files:
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, unsolved_dir)
                ext = os.path.splitext(f)[1].lower()
                # Only include actual archive files
                if is_archive_file(Path(fp)) or f.lower().endswith(".001"):
                    self.bf_archives.append((fp, rel))
                    self.bf_listbox.insert(tk.END, rel)

        if self.bf_archives:
            self.bf_start_btn.config(state=tk.NORMAL)
            self.status_bar.config(text="找到 %d 个未匹配压缩包" % len(self.bf_archives))
        else:
            self.bf_start_btn.config(state=tk.DISABLED)
            self.status_bar.config(text="未匹配密码目录为空，没有需要暴力破解的文件")
        self._bf_update_estimate()

    # ========== 暴力破解：开始 ==========
    def _bf_start(self):
        if not self.bf_archives:
            messagebox.showerror("错误", "没有待破解的压缩包，请先扫描")
            return

        bf_length = self.bf_length_var.get()
        total, time_str, level = estimate_bruteforce(bf_length)

        if level >= 1:
            msg = ("暴力破解将尝试约 %d 种字符组合，预计耗时 %s。\n\n"
                   "对 %d 个未匹配文件每个都要尝试所有组合，总时间为此 × %d。\n是否继续？" %
                   (total, time_str, len(self.bf_archives), len(self.bf_archives)))
            if level == 2:
                msg = ("⚠ 暴力破解将尝试约 %d 种字符组合，预计耗时 %s。\n"
                       "这可能需要数天，建议减小位数。\n是否继续？" % (total, time_str))
                if not messagebox.askyesno("暴力破解提示", msg):
                    return
            else:
                if not messagebox.askyesno("暴力破解提示", msg):
                    return

        self.bf_start_btn.config(state=tk.DISABLED)
        self.bf_tree.delete(*self.bf_tree.get_children())

        thread = threading.Thread(target=self._bf_run, args=(bf_length,), daemon=True)
        thread.start()

    def _bf_run(self, bf_length):
        import shutil
        dest = self.dest_dir.get()
        count = len(self.bf_archives)
        bf_hits = []
        bf_index = 0
        discovered_passwords = []

        try:
            for abs_path, rel_path in self.bf_archives:
                bf_pwd = None
                tried = 0
                bf_index += 1

                # Try already-discovered passwords first
                for dp in discovered_passwords:
                    tried += 1
                    if test_password(abs_path, dp):
                        bf_pwd = dp
                        msg = "[%d/%d] %s - 复用密码: %s" % (bf_index, count, rel_path, dp)
                        self.root.after(0, self._bf_update_progress, bf_index, count, msg)
                        break

                # Brute-force if not matched
                if not bf_pwd:
                    for pwd in generate_bruteforce_passwords(bf_length):
                        tried += 1
                        if tried % 50 == 0 or tried <= 5:
                            msg = "[%d/%d] %s - 尝试: %s (已试%d个)" % (bf_index, count, rel_path, pwd, tried)
                            self.root.after(0, self._bf_update_progress, bf_index, count, msg)
                        if test_password(abs_path, pwd):
                            bf_pwd = pwd
                            discovered_passwords.append(pwd)
                            break

                if bf_pwd:
                    pwd_dir = os.path.join(dest, "密码：" + bf_pwd)
                    os.makedirs(pwd_dir, exist_ok=True)
                    parts = get_multi_volume_parts(Path(abs_path))
                    for part in parts:
                        p = Path(pwd_dir) / part.relative_to(Path(self.bf_current_folder).parent if
                                    self.bf_current_folder else Path(abs_path).parent)
                        p.parent.mkdir(parents=True, exist_ok=True)
                        if part.exists():
                            shutil.move(str(part), str(p))

                    is_reused = tried <= len(discovered_passwords) if discovered_passwords else False
                    last_new = discovered_passwords[-1] if discovered_passwords else None
                    status = "破解成功！密码：" + bf_pwd
                    if is_reused and bf_pwd != last_new:
                        status = "复用成功！密码：" + bf_pwd
                    bf_hits.append((rel_path, bf_pwd, "成功"))
                else:
                    bf_hits.append((rel_path, None, "未破解"))
                    status = "未破解"

                self.root.after(0, self._bf_insert_result, rel_path, bf_pwd or "-", status)

            self.root.after(0, self._bf_complete, bf_hits, discovered_passwords)
        except Exception as e:
            self.root.after(0, self._bf_error, str(e))

    def _bf_update_progress(self, current, total, message):
        self.bf_progress_bar["maximum"] = total
        self.bf_progress_bar["value"] = current
        self.bf_progress_label.config(text="%d/%d" % (current, total))
        self.status_bar.config(text=message)
        self.root.update_idletasks()

    def _bf_insert_result(self, rel_path, pwd, status):
        tags = ("success",) if "成功" in status else ("fail",)
        self.bf_tree.insert("", tk.END, values=(rel_path, pwd, status), tags=tags)
        self.bf_tree.tag_configure("success", foreground="#2e7d32")
        self.bf_tree.tag_configure("fail", foreground="#c62828")

    def _bf_complete(self, hits):
        self.bf_start_btn.config(state=tk.NORMAL)
        self.bf_progress_label.config(text="完成")
        success = sum(1 for _, _, s in hits if s == "成功")
        failed = sum(1 for _, _, s in hits if s == "未破解")
        self.status_bar.config(text="暴力破解完成！成功 %d，未破解 %d" % (success, failed))
        messagebox.showinfo("暴力破解完成", "暴力破解完成！\n成功破解: %d\n未破解: %d" % (success, failed))
        # If any succeeded, suggest re-scanning results
        if success > 0:
            self.notebook.select(0)  # Switch to results tab
            messagebox.showinfo("提示", "部分文件已破解，请重新运行分类以更新结果表格")

    def _bf_scan_and_retry(self, new_passwords):
        import shutil
        dest = self.dest_dir.get()
        if not dest:
            return
        unsolved_dir = os.path.join(dest, "未匹配密码")
        if not os.path.isdir(unsolved_dir):
            return

        matched_any = False
        for root, dirs, files in os.walk(unsolved_dir):
            for f in files:
                fp = os.path.join(root, f)
                for pwd in new_passwords:
                    if test_password(fp, pwd):
                        pwd_dir = os.path.join(dest, "密码：" + pwd)
                        os.makedirs(pwd_dir, exist_ok=True)
                        parts = get_multi_volume_parts(Path(fp))
                        for part in parts:
                            p = Path(pwd_dir) / part.relative_to(Path(unsolved_dir))
                            p.parent.mkdir(parents=True, exist_ok=True)
                            if part.exists():
                                shutil.move(str(part), str(p))
                        matched_any = True
                        break

        if matched_any:
            messagebox.showinfo("完成", "新密码已尝试用于其他未匹配文件！\n请返回分类结果标签页，重新运行分类。")
            self.notebook.select(0)
            self._bf_scan_unmatched()
        else:
            messagebox.showinfo("提示", "新密码未匹配到其他文件。")

    def _bf_error(self, error_msg):
        self.bf_start_btn.config(state=tk.NORMAL)
        self.bf_progress_label.config(text="出错")
        self.status_bar.config(text="错误：" + error_msg)
        messagebox.showerror("暴力破解出错", error_msg)

    # ========== 源文件夹管理 ==========
    def add_source(self):
        d = filedialog.askdirectory(title="选择包含压缩包的文件夹")
        if d and d not in self.source_dirs:
            self.source_dirs.append(d)
            self._refresh_source_list()

    def remove_source(self):
        sel = self.src_listbox.curselection()
        if sel and 0 <= sel[0] < len(self.source_dirs):
            del self.source_dirs[sel[0]]
            self._refresh_source_list()

    def _refresh_source_list(self):
        self.src_listbox.delete(0, tk.END)
        for d in self.source_dirs:
            self.src_listbox.insert(tk.END, d)

    def browse_dest(self):
        d = filedialog.askdirectory(title="选择存放分类结果的文件夹")
        if d:
            self.dest_dir.set(d)

    def browse_password(self):
        fp = filedialog.askopenfilename(title="选择密码文件", filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if fp:
            self.password_file.set(fp)

    def create_sample_password(self):
        fp = filedialog.asksaveasfilename(title="保存示例密码文件", defaultextension=".txt",
                                          filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
                                          initialfile="passwords.txt")
        if not fp:
            return
        try:
            with open(fp, "w", encoding="utf-8") as f:
                f.write("# 密码文件示例 - 每行一个密码\n123456\npassword\nadmin\n")
            self.password_file.set(fp)
            messagebox.showinfo("成功", "示例密码文件已创建：\n" + fp)
        except Exception as e:
            messagebox.showerror("错误", "创建文件失败：" + str(e))

    # ========== 分页 ==========
    def _render_page(self):
        self.tree.delete(*self.tree.get_children())
        if not self.all_results:
            return
        start = self.current_page * PAGE_SIZE
        end = start + PAGE_SIZE
        self.tree.tag_configure("success", foreground="#2e7d32")
        self.tree.tag_configure("fail", foreground="#c62828")
        for fname, src_name, pwd, status in self.all_results[start:end]:
            tags = ("success",) if "成功" in status else ("fail",)
            self.tree.insert("", tk.END, values=(fname, src_name, pwd or "-", status), tags=tags)
        self._update_page_buttons()

    def _update_page_buttons(self):
        total = len(self.all_results)
        self.total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_prev_btn.config(state=tk.NORMAL if self.current_page > 0 else tk.DISABLED)
        self.page_next_btn.config(state=tk.NORMAL if self.current_page < self.total_pages - 1 else tk.DISABLED)
        shown = min(PAGE_SIZE, total - self.current_page * PAGE_SIZE)
        self.page_label.config(text="第 %d/%d 页（显示 %d 条，共 %d 条）" %
                                (self.current_page + 1, self.total_pages, shown, total))

    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._render_page()

    def _next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._render_page()

    # ========== 结果 ==========
    def clear_results(self):
        self.all_results = []
        self.current_page = 0
        self._render_page()
        self.progress_bar["value"] = 0
        self.progress_label.config(text="就绪")
        self.status_bar.config(text="已清空")
        self.open_btn.config(state=tk.DISABLED)

    # ========== 开始分类（文件密码，不含暴力破解）==========
    def start_categorize(self):
        if not self.source_dirs:
            messagebox.showerror("错误", "请添加至少一个源文件夹")
            return
        if not self.dest_dir.get():
            messagebox.showerror("错误", "请选择目标文件夹")
            return
        if not self.password_file.get():
            messagebox.showerror("错误", "请选择密码文件")
            return
        if not os.path.exists(self.password_file.get()):
            messagebox.showerror("错误", "密码文件不存在")
            return

        try:
            passwords = read_passwords(self.password_file.get())
        except Exception as e:
            messagebox.showerror("错误", "读取密码文件失败：" + str(e))
            return
        if not passwords:
            messagebox.showerror("错误", "密码文件为空或没有有效密码")
            return

        for sd in self.source_dirs:
            af, _ = find_archives(sd)
            w = get_missing_tool_message(af)
            if w:
                if not messagebox.askyesno("工具提示",
                    "%s\n\n是否继续？（仅 ZIP 格式可正常处理）" % w):
                    return

        self.start_btn.config(state=tk.DISABLED)
        self.clear_results()

        thread = threading.Thread(
            target=self._run_categorize,
            args=(list(self.source_dirs), self.dest_dir.get(), passwords, self.move_mode.get()),
            daemon=True
        )
        thread.start()

    def _run_categorize(self, source_dirs, dest_dir, passwords, move_files):
        all_stats = {"total": 0, "success": 0, "failed": 0, "results": [], "warnings": []}
        overall_total = 0
        for sd in source_dirs:
            af, _ = find_archives(sd)
            overall_total += len(af)

        processed = 0
        try:
            for sd in source_dirs:
                def mk_progress(base):
                    def cb(cur, tot, msg):
                        self.root.after(0, self._update_progress,
                                        base + cur, overall_total,
                                        "[%s] %s" % (os.path.basename(sd), msg))
                    return cb

                stats = categorize_archives(sd, dest_dir, passwords,
                                            progress_callback=mk_progress(processed),
                                            move_files=move_files)
                for fname, pwd, status in stats["results"]:
                    all_stats["results"].append((fname, os.path.basename(sd), pwd, status))
                all_stats["total"] += stats["total"]
                all_stats["success"] += stats["success"]
                all_stats["failed"] += stats["failed"]
                all_stats["warnings"].extend(stats.get("warnings", []))
                processed += stats["total"]

            self.root.after(0, self._on_complete, all_stats)
        except Exception as e:
            self.root.after(0, self._on_error, str(e))

    def _update_progress(self, current, total, message):
        if total > 0:
            self.progress_bar["maximum"] = total
            self.progress_bar["value"] = min(current + 1, total)
        self.progress_label.config(text="%d/%d" % (min(current + 1, total), total))
        self.status_bar.config(text=message)
        self.root.update_idletasks()

    def _on_complete(self, stats):
        self.start_btn.config(state=tk.NORMAL)
        self.all_results = stats["results"]
        self.current_page = 0
        self._render_page()
        self.progress_label.config(text="完成")
        self.open_btn.config(state=tk.NORMAL)

        pwd_counter = Counter()
        for _, _, p, _ in stats["results"]:
            pwd_counter[p or "未匹配"] += 1
        parts = ["%s: %d" % (p, c) for p, c in pwd_counter.most_common(10)]
        self.status_bar.config(text="完成！共%d个，成功%d，失败%d  |  %s" %
                                (stats["total"], stats["success"], stats["failed"], " | ".join(parts)))

        for w in stats.get("warnings", []):
            messagebox.showwarning("提示", w)
        messagebox.showinfo("完成", "处理完成！\n\n总压缩包数: %d\n成功匹配: %d\n未匹配: %d\n\n结果已保存至：%s" %
                            (stats["total"], stats["success"], stats["failed"], self.dest_dir.get()))

        # Auto-switch to brute-force tab if there are unmatched files
        if stats["failed"] > 0:
            self.notebook.select(1)
            self._bf_scan_unmatched()

    def _on_error(self, error_msg):
        self.start_btn.config(state=tk.NORMAL)
        self.progress_label.config(text="出错")
        self.status_bar.config(text="错误：" + error_msg)
        messagebox.showerror("处理出错", error_msg)

    def open_dest(self):
        d = self.dest_dir.get()
        if d and os.path.isdir(d):
            os.startfile(d)
        elif d:
            messagebox.showerror("错误", "目标文件夹不存在：" + d)


def main():
    root = tk.Tk()
    style = ttk.Style()
    try:
        style.theme_use("vista")
    except tk.TclError:
        pass
    try:
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"))
    except:
        pass
    app = ArchiveCategorizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
