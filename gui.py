"""archive_categorizer/gui.py - tkinter 图形界面（支持多源文件夹、分页、暴力破解）"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
from collections import Counter
from core import (read_passwords, categorize_archives, get_missing_tool_message,
                  find_archives, estimate_bruteforce)


PAGE_SIZE = 20


class ArchiveCategorizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("压缩包密码分类工具")
        self.root.geometry("850x720")
        self.root.minsize(750, 620)

        self.source_dirs = []
        self.dest_dir = tk.StringVar()
        self.password_file = tk.StringVar()
        self.move_mode = tk.BooleanVar(value=False)
        self.bruteforce_enabled = tk.BooleanVar(value=False)
        self.bruteforce_length = tk.IntVar(value=3)

        # Pagination state
        self.all_results = []
        self.current_page = 0
        self.total_pages = 0

        self.create_widgets()
        self._update_bf_estimate()

    def create_widgets(self):
        header = ttk.Frame(self.root, padding=10)
        header.pack(fill=tk.X)
        ttk.Label(header, text="压缩包密码分类工具",
                  font=("Microsoft YaHei UI", 18, "bold")).pack()
        ttk.Label(header, text="扫描文件夹中的压缩包，用密码尝试解压，按密码分类存放",
                  font=("Microsoft YaHei UI", 10), foreground="gray").pack(pady=(2, 0))

        main_frame = ttk.Frame(self.root, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- 源文件夹 ---
        src_frame = ttk.LabelFrame(main_frame, text="源文件夹（可添加多个）", padding=10)
        src_frame.pack(fill=tk.X, pady=(0, 8))
        listbox_frame = ttk.Frame(src_frame)
        listbox_frame.pack(fill=tk.X, pady=(0, 5))
        self.src_listbox = tk.Listbox(listbox_frame, height=3, font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=self.src_listbox.yview)
        self.src_listbox.configure(yscrollcommand=scrollbar.set)
        self.src_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        src_btn_row = ttk.Frame(src_frame)
        src_btn_row.pack(fill=tk.X)
        ttk.Button(src_btn_row, text="添加源文件夹", command=self.add_source).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(src_btn_row, text="删除选中", command=self.remove_source).pack(side=tk.LEFT)

        # --- 目标文件夹 ---
        dest_frame = ttk.LabelFrame(main_frame, text="目标文件夹（分类结果）", padding=8)
        dest_frame.pack(fill=tk.X, pady=(0, 8))
        dest_row = ttk.Frame(dest_frame)
        dest_row.pack(fill=tk.X)
        self.dest_entry = ttk.Entry(dest_row, textvariable=self.dest_dir,
                                    state="readonly", font=("Consolas", 10))
        self.dest_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(dest_row, text="浏览...", command=self.browse_dest).pack(side=tk.RIGHT)

        # --- 密码文件 ---
        pwd_frame = ttk.LabelFrame(main_frame, text="密码文件", padding=8)
        pwd_frame.pack(fill=tk.X, pady=(0, 8))
        pwd_row = ttk.Frame(pwd_frame)
        pwd_row.pack(fill=tk.X)
        self.pwd_entry = ttk.Entry(pwd_row, textvariable=self.password_file,
                                   state="readonly", font=("Consolas", 10))
        self.pwd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        pwd_btn_frame = ttk.Frame(pwd_row)
        pwd_btn_frame.pack(side=tk.RIGHT)
        ttk.Button(pwd_btn_frame, text="浏览...", command=self.browse_password).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(pwd_btn_frame, text="创建示例", command=self.create_sample_password).pack(side=tk.LEFT)

        # --- 操作按钮 + 模式 ---
        btn_frame = ttk.LabelFrame(main_frame, text="操作设置", padding=8)
        btn_frame.pack(fill=tk.X, pady=(0, 8))

        # Row 1: action buttons
        action_row = ttk.Frame(btn_frame)
        action_row.pack(fill=tk.X, pady=(0, 6))
        self.start_btn = ttk.Button(action_row, text="开始分类", command=self.start_categorize,
                                    style="Accent.TButton")
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(action_row, text="清空结果", command=self.clear_results).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Checkbutton(action_row, text="移动文件（删除源文件）",
                        variable=self.move_mode).pack(side=tk.LEFT, padx=(0, 15))

        # Row 2: brute-force controls
        bf_row = ttk.Frame(btn_frame)
        bf_row.pack(fill=tk.X)
        self.bf_check = ttk.Checkbutton(bf_row, text="暴力破解（尝试所有字符组合）",
                                        variable=self.bruteforce_enabled,
                                        command=self._update_bf_estimate)
        self.bf_check.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(bf_row, text="最大位数:").pack(side=tk.LEFT, padx=(0, 4))
        self.bf_spinbox = ttk.Spinbox(bf_row, from_=1, to=4, textvariable=self.bruteforce_length,
                                      width=4, command=self._update_bf_estimate)
        self.bf_spinbox.pack(side=tk.LEFT, padx=(0, 10))
        # Bind to changes
        self.bf_spinbox.bind("<KeyRelease>", lambda e: self._update_bf_estimate())

        self.bf_estimate_label = ttk.Label(bf_row, text="", foreground="gray")
        self.bf_estimate_label.pack(side=tk.LEFT)

        # --- 进度条 ---
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 5))
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress_bar.pack(fill=tk.X, expand=True, side=tk.LEFT, padx=(0, 8))
        self.progress_label = ttk.Label(progress_frame, text="就绪", width=30, anchor=tk.W)
        self.progress_label.pack(side=tk.RIGHT, padx=(0, 4))
        self.open_btn = ttk.Button(progress_frame, text="打开目标文件夹", command=self.open_dest,
                                   state=tk.DISABLED)
        self.open_btn.pack(side=tk.RIGHT)

        # --- 结果表格 ---
        result_frame = ttk.LabelFrame(main_frame, text="处理结果", padding=5)
        result_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("file", "source", "password", "status")
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings", height=14)
        self.tree.heading("file", text="压缩包")
        self.tree.heading("source", text="来源")
        self.tree.heading("password", text="匹配密码")
        self.tree.heading("status", text="状态")
        self.tree.column("file", width=300, anchor=tk.W)
        self.tree.column("source", width=100, anchor=tk.W)
        self.tree.column("password", width=180, anchor=tk.W)
        self.tree.column("status", width=100, anchor=tk.CENTER)

        scrollbar_t = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar_t.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_t.pack(side=tk.RIGHT, fill=tk.Y)

        # --- 分页控件 ---
        page_frame = ttk.Frame(main_frame)
        page_frame.pack(fill=tk.X, pady=(3, 0))
        self.page_prev_btn = ttk.Button(page_frame, text="◀ 上一页", command=self._prev_page, state=tk.DISABLED)
        self.page_prev_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.page_next_btn = ttk.Button(page_frame, text="下一页 ▶", command=self._next_page, state=tk.DISABLED)
        self.page_next_btn.pack(side=tk.LEFT)
        self.page_label = ttk.Label(page_frame, text="", foreground="gray")
        self.page_label.pack(side=tk.LEFT, padx=(15, 0))

        # --- 底部状态栏 ---
        self.status_bar = ttk.Label(self.root, text="就绪", relief=tk.SUNKEN,
                                    anchor=tk.W, padding=(10, 2))
        self.status_bar.pack(fill=tk.X)

    # ---------- 暴力破解预估 ----------
    def _update_bf_estimate(self, event=None):
        if self.bruteforce_enabled.get():
            max_len = self.bruteforce_length.get()
            total, time_str, level = estimate_bruteforce(max_len)
            if level == 2:
                color = "red"
            elif level == 1:
                color = "orange"
            else:
                color = "gray"
            text = "约 %d 种组合，%s" % (total, time_str)
            self.bf_estimate_label.config(text=text, foreground=color)
        else:
            self.bf_estimate_label.config(text="")

    # ---------- 源文件夹管理 ----------
    def add_source(self):
        dirpath = filedialog.askdirectory(title="选择包含压缩包的文件夹")
        if dirpath and dirpath not in self.source_dirs:
            self.source_dirs.append(dirpath)
            self._refresh_source_list()

    def remove_source(self):
        sel = self.src_listbox.curselection()
        if sel:
            idx = sel[0]
            if 0 <= idx < len(self.source_dirs):
                del self.source_dirs[idx]
                self._refresh_source_list()

    def _refresh_source_list(self):
        self.src_listbox.delete(0, tk.END)
        for d in self.source_dirs:
            self.src_listbox.insert(tk.END, d)

    # ---------- 目标/密码 ----------
    def browse_dest(self):
        dirpath = filedialog.askdirectory(title="选择存放分类结果的文件夹")
        if dirpath:
            self.dest_dir.set(dirpath)

    def browse_password(self):
        filepath = filedialog.askopenfilename(
            title="选择密码文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if filepath:
            self.password_file.set(filepath)

    def create_sample_password(self):
        filepath = filedialog.asksaveasfilename(
            title="保存示例密码文件", defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile="passwords.txt")
        if not filepath:
            return
        sample = """# 密码文件示例 - 每行一个密码
123456
password
admin
"""
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(sample)
            self.password_file.set(filepath)
            messagebox.showinfo("成功", "示例密码文件已创建\n%s\n\n请用记事本编辑，填入您的密码。" % filepath)
        except Exception as e:
            messagebox.showerror("错误", "创建文件失败：%s" % e)

    # ---------- 分页 ----------
    def _render_page(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        if not self.all_results:
            return
        start = self.current_page * PAGE_SIZE
        end = start + PAGE_SIZE
        for fname, src_name, pwd, status in self.all_results[start:end]:
            tags = ("success",) if "成功" in status else ("fail",)
            self.tree.insert("", tk.END, values=(fname, src_name, pwd or "-", status), tags=tags)
        self.tree.tag_configure("success", foreground="#2e7d32")
        self.tree.tag_configure("fail", foreground="#c62828")
        self._update_page_buttons()

    def _update_page_buttons(self):
        self.total_pages = max(1, (len(self.all_results) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_prev_btn.config(state=tk.NORMAL if self.current_page > 0 else tk.DISABLED)
        self.page_next_btn.config(state=tk.NORMAL if self.current_page < self.total_pages - 1 else tk.DISABLED)
        shown = min(PAGE_SIZE, len(self.all_results) - self.current_page * PAGE_SIZE)
        self.page_label.config(
            text="第 %d/%d 页（显示 %d 条，共 %d 条）" %
                 (self.current_page + 1, self.total_pages, shown, len(self.all_results)))

    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._render_page()

    def _next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._render_page()

    # ---------- 结果 ----------
    def clear_results(self):
        self.all_results = []
        self.current_page = 0
        self.total_pages = 0
        self._render_page()
        self.progress_bar["value"] = 0
        self.progress_label.config(text="就绪")
        self.status_bar.config(text="已清空")
        self.open_btn.config(state=tk.DISABLED)

    # ---------- 开始分类 ----------
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
            messagebox.showerror("错误", "读取密码文件失败：%s" % e)
            return
        if not passwords:
            messagebox.showerror("错误", "密码文件为空或没有有效密码")
            return

        # Bruteforce validation
        bf_length = 0
        if self.bruteforce_enabled.get():
            bf_length = self.bruteforce_length.get()
            total, time_str, level = estimate_bruteforce(bf_length)
            if level >= 1:
                msg = ("暴力破解将尝试约 %d 种字符组合，预计耗时 %s。\n\n"
                       "这可能需要很长时间，是否继续？\n"
                       "（建议：先用密码文件试完，对少量未匹配文件启用）" % (total, time_str))
                if level == 2:
                    msg = ("⚠ 暴力破解将尝试约 %d 种字符组合，预计耗时 %s。\n\n"
                           "这个组合数过大，不建议继续。\n"
                           "建议减小最大位数或缩小字符范围。" % (total, time_str))
                    messagebox.showwarning("暴力破解提示", msg)
                    return
                if not messagebox.askyesno("暴力破解提示", msg):
                    return

        # Tool warnings
        all_warnings = []
        for sd in self.source_dirs:
            af, _ = find_archives(sd)
            w = get_missing_tool_message(af)
            if w:
                all_warnings.append("[%s] %s" % (os.path.basename(sd), w))
        if all_warnings:
            msg = "\n".join(all_warnings) + "\n\n是否继续？（仅 ZIP 格式可正常处理）"
            if not messagebox.askyesno("工具提示", msg):
                return

        self.start_btn.config(state=tk.DISABLED)
        self.clear_results()

        thread = threading.Thread(
            target=self._run_categorize,
            args=(list(self.source_dirs), self.dest_dir.get(), passwords,
                  self.move_mode.get(), bf_length),
            daemon=True
        )
        thread.start()

    def _run_categorize(self, source_dirs, dest_dir, passwords, move_files, bf_length):
        all_stats = {"total": 0, "success": 0, "failed": 0, "results": [], "warnings": []}
        overall_total = 0
        for sd in source_dirs:
            af, _ = find_archives(sd)
            overall_total += len(af)

        processed = 0
        try:
            for sd in source_dirs:
                def make_progress(base_processed):
                    def cb(current, total, message):
                        real_current = base_processed + current
                        folder_name = os.path.basename(sd)
                        self.root.after(0, self._update_progress,
                                        real_current, overall_total,
                                        "[%s] %s" % (folder_name, message))
                    return cb

                stats = categorize_archives(
                    sd, dest_dir, passwords,
                    progress_callback=make_progress(processed),
                    move_files=move_files,
                    bruteforce_max_length=bf_length
                )
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

        pwd_counter = Counter()
        for _, _, pwd, _ in stats["results"]:
            pwd_counter[pwd or "未匹配"] += 1
        summary_parts = ["%s: %d" % (pwd, c) for pwd, c in pwd_counter.most_common(10)]
        summary_text = " | ".join(summary_parts)
        total_text = "完成！共%d个，成功%d，失败%d" % (stats["total"], stats["success"], stats["failed"])
        self.status_bar.config(text="%s  |  %s" % (total_text, summary_text))

        self.open_btn.config(state=tk.NORMAL)

        for warning in stats.get("warnings", []):
            messagebox.showwarning("提示", warning)

        messagebox.showinfo("完成",
            "处理完成！\n\n总压缩包数: %d\n成功匹配: %d\n未匹配: %d\n\n结果已保存至：%s" %
            (stats["total"], stats["success"], stats["failed"], self.dest_dir.get()))

    def _on_error(self, error_msg):
        self.start_btn.config(state=tk.NORMAL)
        self.progress_label.config(text="出错")
        self.status_bar.config(text="错误：%s" % error_msg)
        messagebox.showerror("处理出错", error_msg)

    def open_dest(self):
        dest = self.dest_dir.get()
        if dest and os.path.isdir(dest):
            os.startfile(dest)
        elif dest:
            messagebox.showerror("错误", "目标文件夹不存在：%s" % dest)


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
