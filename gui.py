"""
archive_categorizer/gui.py - tkinter 图形界面
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
from pathlib import Path

from core import read_passwords, categorize_archives, get_missing_tool_message, find_archives


class ArchiveCategorizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("压缩包密码分类工具")
        self.root.geometry("800x650")
        self.root.minsize(700, 550)

        self.source_dir = tk.StringVar()
        self.dest_dir = tk.StringVar()
        self.password_file = tk.StringVar()
        self.move_mode = tk.BooleanVar(value=False)

        self.create_widgets()

    def create_widgets(self):
        # --- 顶部标题 ---
        header = ttk.Frame(self.root, padding=10)
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text="压缩包密码分类工具",
            font=("Microsoft YaHei UI", 18, "bold"),
        ).pack()
        ttk.Label(
            header,
            text="扫描文件夹中的压缩包，用密码文件中的密码依次尝试解压，按密码分类存放",
            font=("Microsoft YaHei UI", 10),
            foreground="gray",
        ).pack(pady=(2, 0))

        # --- 主设置区域 ---
        main_frame = ttk.Frame(self.root, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 源文件夹
        src_frame = ttk.LabelFrame(main_frame, text="源文件夹（包含压缩包）", padding=10)
        src_frame.pack(fill=tk.X, pady=(0, 10))
        src_row = ttk.Frame(src_frame)
        src_row.pack(fill=tk.X)
        self.src_entry = ttk.Entry(src_row, textvariable=self.source_dir, state="readonly", font=("Consolas", 10))
        self.src_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(src_row, text="浏览...", command=self.browse_source).pack(side=tk.RIGHT)

        # 目标文件夹
        dest_frame = ttk.LabelFrame(main_frame, text="目标文件夹（分类结果）", padding=10)
        dest_frame.pack(fill=tk.X, pady=(0, 10))
        dest_row = ttk.Frame(dest_frame)
        dest_row.pack(fill=tk.X)
        self.dest_entry = ttk.Entry(dest_row, textvariable=self.dest_dir, state="readonly", font=("Consolas", 10))
        self.dest_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(dest_row, text="浏览...", command=self.browse_dest).pack(side=tk.RIGHT)

        # 密码文件
        pwd_frame = ttk.LabelFrame(main_frame, text="密码文件（txt，每行一个密码，#开头的行为注释）", padding=10)
        pwd_frame.pack(fill=tk.X, pady=(0, 15))
        pwd_row = ttk.Frame(pwd_frame)
        pwd_row.pack(fill=tk.X)
        self.pwd_entry = ttk.Entry(pwd_row, textvariable=self.password_file, state="readonly", font=("Consolas", 10))
        self.pwd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        pwd_btn_frame = ttk.Frame(pwd_row)
        pwd_btn_frame.pack(side=tk.RIGHT)
        ttk.Button(pwd_btn_frame, text="浏览...", command=self.browse_password).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(pwd_btn_frame, text="创建示例密码文件", command=self.create_sample_password).pack(side=tk.LEFT)

        # --- 操作按钮 ---
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        self.start_btn = ttk.Button(
            btn_frame, text="开始分类", command=self.start_categorize,
            style="Accent.TButton"
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_frame, text="清空结果", command=self.clear_results).pack(side=tk.LEFT)
        ttk.Checkbutton(
            btn_frame, text="移动文件（复制后删除源文件，释放空间）",
            variable=self.move_mode
        ).pack(side=tk.LEFT, padx=(10, 0))

        # --- 进度条 ---
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 5))
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress_bar.pack(fill=tk.X, expand=True, side=tk.LEFT, padx=(0, 8))
        self.progress_label = ttk.Label(progress_frame, text="就绪", width=30, anchor=tk.W)
        self.progress_label.pack(side=tk.RIGHT, padx=(0, 4))
        self.open_btn = ttk.Button(
            progress_frame, text="打开目标文件夹", command=self.open_dest,
            state=tk.DISABLED
        )
        self.open_btn.pack(side=tk.RIGHT)

        # --- 结果表格 ---
        result_frame = ttk.LabelFrame(main_frame, text="处理结果", padding=5)
        result_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("file", "password", "status")
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings", height=12)
        self.tree.heading("file", text="压缩包")
        self.tree.heading("password", text="匹配密码")
        self.tree.heading("status", text="状态")
        self.tree.column("file", width=380, anchor=tk.W)
        self.tree.column("password", width=200, anchor=tk.W)
        self.tree.column("status", width=120, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # --- 底部状态栏 ---
        self.status_bar = ttk.Label(
            self.root, text="就绪", relief=tk.SUNKEN, anchor=tk.W, padding=(10, 2)
        )
        self.status_bar.pack(fill=tk.X)

    def browse_source(self):
        dirpath = filedialog.askdirectory(title="选择包含压缩包的文件夹")
        if dirpath:
            self.source_dir.set(dirpath)

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
        """在当前目录创建一个示例密码文件"""
        filepath = filedialog.asksaveasfilename(
            title="保存示例密码文件",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile="passwords.txt",
        )
        if not filepath:
            return
        sample_content = """# 密码文件示例 - 每行一个密码，空行和#开头的行会被忽略
123456
password
admin
12345678
888888
# 以下为常见弱密码
111111
000000
passw0rd
abc123
"""
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(sample_content)
            self.password_file.set(filepath)
            messagebox.showinfo("成功", f"示例密码文件已创建：\n{filepath}\n\n请用记事本编辑该文件，填入您的密码。")
        except Exception as e:
            messagebox.showerror("错误", f"创建文件失败：{e}")

    def clear_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.progress_bar["value"] = 0
        self.progress_label.config(text="就绪")
        self.status_bar.config(text="已清空")

    def start_categorize(self):
        # Validation
        if not self.source_dir.get():
            messagebox.showerror("错误", "请选择源文件夹")
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

        # Read passwords
        try:
            passwords = read_passwords(self.password_file.get())
        except Exception as e:
            messagebox.showerror("错误", f"读取密码文件失败：{e}")
            return

        if not passwords:
            messagebox.showerror("错误", "密码文件为空或没有有效密码")
            return

        # Check for tool warnings
        archive_files, _ = find_archives(self.source_dir.get())
        warning = get_missing_tool_message(archive_files)
        if warning:
            if not messagebox.askyesno("工具提示", f"{warning}\n\n是否继续？（仅 ZIP 格式可正常处理）"):
                return

        # Disable button and start thread
        self.start_btn.config(state=tk.DISABLED)
        self.clear_results()

        thread = threading.Thread(
            target=self._run_categorize,
            args=(self.source_dir.get(), self.dest_dir.get(), passwords, self.move_mode.get()),
            daemon=True
        )
        thread.start()

    def _run_categorize(self, source_dir, dest_dir, passwords, move_files=False):
        def progress_callback(current, total, message):
            self.root.after(0, self._update_progress, current, total, message)

        try:
            stats = categorize_archives(
                source_dir, dest_dir, passwords,
                progress_callback=progress_callback,
                move_files=move_files
            )
            self.root.after(0, self._on_complete, stats)
        except Exception as e:
            self.root.after(0, self._on_error, str(e))

    def _update_progress(self, current, total, message):
        if total > 0:
            self.progress_bar["maximum"] = total
            self.progress_bar["value"] = current + 1
        self.progress_label.config(text=f"{current+1}/{total}")
        self.status_bar.config(text=message)
        self.root.update_idletasks()

    def _on_complete(self, stats):
        self.start_btn.config(state=tk.NORMAL)

        # Populate tree
        for fname, pwd, status in stats["results"]:
            tags = ()
            if status == "成功":
                tags = ("success",)
            else:
                tags = ("fail",)
            self.tree.insert("", tk.END, values=(fname, pwd or "-", status), tags=tags)

        # Style tags
        self.tree.tag_configure("success", foreground="#2e7d32")
        self.tree.tag_configure("fail", foreground="#c62828")

        self.progress_label.config(text="完成")
        
        # Build password summary
        from collections import Counter
        pwd_counter = Counter()
        for fname, pwd, status in stats["results"]:
            pwd_counter[pwd or "未匹配"] += 1
        summary_parts = []
        for pwd, count in pwd_counter.most_common(10):
            summary_parts.append(f"{pwd}: {count}")
        summary_text = " | ".join(summary_parts)
        total_text = f"完成！共{stats['total']}个，成功{stats['success']}，失败{stats['failed']}"
        self.status_bar.config(text=f"{total_text}  |  {summary_text}")
        
        # Enable open destination button
        self.open_btn.config(state=tk.NORMAL)

        # Show warnings if any
        for warning in stats.get("warnings", []):
            messagebox.showwarning("提示", warning)

        messagebox.showinfo(
            "完成",
            f"处理完成！\n\n"
            f"总压缩包数: {stats['total']}\n"
            f"成功匹配: {stats['success']}\n"
            f"未匹配: {stats['failed']}\n\n"
            f"结果已保存至：{self.dest_dir.get()}"
        )

    def _on_error(self, error_msg):
        self.start_btn.config(state=tk.NORMAL)
        self.progress_label.config(text="出错")
        self.status_bar.config(text=f"错误：{error_msg}")
        messagebox.showerror("处理出错", error_msg)


    def open_dest(self):
        """打开目标文件夹"""
        dest = self.dest_dir.get()
        if dest and os.path.isdir(dest):
            os.startfile(dest)
        elif dest:
            messagebox.showerror("错误", f"目标文件夹不存在：{dest}")


def main():
    root = tk.Tk()

    # Style
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
