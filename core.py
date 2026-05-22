"""
archive_categorizer/core.py - 核心逻辑：按密码分类压缩包（不解压，只测试密码）
支持分卷压缩包（.part1.rar, .7z.001 等）
"""
import os
import re
import itertools
import zipfile
import shutil
import subprocess
import math
from pathlib import Path


# 支持的压缩包扩展名
ARCHIVE_EXTENSIONS = {
    ".zip", ".jar", ".war", ".ear",
    ".7z", ".rar", ".tar", ".gz",
    ".tgz", ".bz2", ".xz", ".zst",
}

# 分卷命名模式
# 模式1: .part1.rar, .part2.rar ...
RE_PART_RAR = re.compile(r"\.part(\d+)\.(rar|7z|zip)$", re.IGNORECASE)
# 模式2: .7z.001, .7z.002 ...
RE_NUM_EXT = re.compile(r"\.(\d{3})$")

# 可打印 ASCII 字符集（95 个字符：空格到 ~）
CHARSET_PRINTABLE = "".join(chr(i) for i in range(32, 127))


def read_passwords(password_file):
    """从txt文件读取密码列表，每行一个密码，跳过空行和注释行(#)，自动处理BOM"""
    passwords = []
    with open(password_file, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                passwords.append(line)
    return passwords


def is_archive_file(filepath):
    """判断是否为支持的压缩包文件（不含非首分卷）"""
    lower_name = filepath.name.lower()
    if lower_name.endswith(".tar.gz"):
        return True
    if filepath.suffix.lower() in ARCHIVE_EXTENSIONS:
        # 排除 .part2.rar, .part3.rar 等非首分卷
        m = RE_PART_RAR.search(lower_name)
        if m and int(m.group(1)) > 1:
            return False
        return True
    return False


def is_split_archive(filepath):
    """判断是否为分卷压缩包的首卷"""
    lower_name = filepath.name.lower()
    # .part1.rar 样式
    if RE_PART_RAR.search(lower_name):
        return True
    # .7z.001 样式 — 后缀本身不在 ARCHIVE_EXTENSIONS 中，需单独检测
    m = RE_NUM_EXT.search(lower_name)
    if m:
        base = filepath.with_suffix("")  # 去掉 .001
        base_ext = base.suffix.lower()
        base_name = base.name.lower()
        # 标准格式: xxx.7z.001
        if base_ext in ARCHIVE_EXTENSIONS and m.group(1) == "001":
            return True
        # 非标准格式: xxx_7z.001 (base_name 以 7z, rar, zip 等结尾)
        if m.group(1) == "001":
            for ext in ARCHIVE_EXTENSIONS:
                if base_name.endswith(ext) or base_name.endswith(ext[1:]):
                    return True
    return False


def get_multi_volume_parts(first_vol_path):
    """获取分卷压缩包的所有分卷文件（传入首卷路径，返回所有分卷的列表）"""
    first_vol = Path(first_vol_path)
    lower_name = first_vol.name.lower()
    parts = [first_vol]

    # 模式1: .part1.rar → .part2.rar, .part3.rar ...
    m = RE_PART_RAR.search(lower_name)
    if m:
        stem = RE_PART_RAR.sub("", first_vol.name)
        ext = m.group(2)
        part_num = 2
        while True:
            next_part = first_vol.with_name(stem + ".part%d.%s" % (part_num, ext))
            if next_part.exists():
                parts.append(next_part)
                part_num += 1
            else:
                break
        return parts

    # 模式2: .7z.001 → .7z.002, .7z.003 ...
    m2 = RE_NUM_EXT.search(lower_name)
    if m2:
        # 去掉 .001 得到基础文件名
        base_no_ext = lower_name[:-4]  # 去掉末尾 .001
        parent = first_vol.parent
        num = 2
        while True:
            next_name = base_no_ext + ".%03d" % num
            next_part = parent / next_name
            if next_part.exists():
                parts.append(next_part)
                num += 1
            else:
                break
        return parts

    return parts  # 非分卷，只返回自身


def find_archives(source_dir):
    """
    递归扫描源文件夹下所有压缩包文件（分卷只返回首卷）
    返回 (archive_files, all_parts_map)
    - archive_files: 需要测试密码的文件列表（每个分卷集只列一次）
    - all_parts_map: {首卷路径: [所有分卷路径]}
    """
    source_path = Path(source_dir)
    archive_files = []
    all_parts_map = {}

    # 第一步：收集所有 .7z.001 样式的首卷（它们后缀不在 ARCHIVE_EXTENSIONS 中）
    for f in source_path.rglob("*"):
        if f.is_file() and is_split_archive(f):
            parts = get_multi_volume_parts(f)
            archive_files.append(f)
            all_parts_map[f] = parts

    # 第二步：收集标准扩展名的压缩包，排除分卷中的非首卷和非分卷部分的重复
    seen_parents = set()  # 对于 .part1.rar 样式，track base name
    for f in source_path.rglob("*"):
        if f.is_file() and is_archive_file(f):
            # 检查是否已被 .7z.001 样式覆盖
            if f in all_parts_map:
                continue
            # 检查是否为某个 .part1 分卷集的一部分
            m = RE_PART_RAR.search(f.name.lower())
            if m and int(m.group(1)) == 1:
                if f not in archive_files:
                    parts = get_multi_volume_parts(f)
                    archive_files.append(f)
                    all_parts_map[f] = parts
                continue
            # 普通压缩包
            if f not in archive_files:
                archive_files.append(f)
                all_parts_map[f] = [f]

    return archive_files, all_parts_map


def _find_7z_path():
    """查找 7z 可执行文件路径"""
    candidate_paths = [
        r"D:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            return p
    try:
        result = subprocess.run(
            ["where", "7z"], capture_output=True, timeout=5,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0:
            path = result.stdout.strip().splitlines()[0]
            if path:
                return path
    except Exception:
        pass
    return None


def test_zip_password(archive_path, password):
    """
    测试ZIP密码是否正确（不解压到磁盘，只读内存验证）。
    先判断压缩包是否有密码：无密码返回False（不匹配任何密码）。
    """
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            has_password = False
            for member in zf.infolist():
                if not member.is_dir():
                    try:
                        zf.read(member.filename)
                        has_password = False
                        break
                    except RuntimeError as e:
                        if "password" in str(e).lower():
                            has_password = True
                            break
                        continue
                    except Exception:
                        continue

            if not has_password:
                return False

            pwd_bytes = password.encode("utf-8")
            for member in zf.infolist():
                if not member.is_dir():
                    try:
                        zf.read(member.filename, pwd=pwd_bytes)
                        return True
                    except (RuntimeError, zipfile.BadZipFile):
                        continue
                    except Exception:
                        continue
            return False
    except Exception:
        return False


def test_7z_password_py7zr(archive_path, password):
    """使用 py7zr 测试7z密码（不解压到磁盘），py7zr未安装返回 None"""
    try:
        import py7zr
        with py7zr.SevenZipFile(archive_path, mode="r", password=password) as sz:
            _ = sz.list()
            return True
    except ImportError:
        return None
    except Exception:
        return False


def test_archive_password_7z_cli(archive_path, password):
    """使用7z命令行测试密码（t 命令只测试不解压），7z不可用时返回 None"""
    sz_path = _find_7z_path()
    if not sz_path:
        return None
    cmd = [sz_path, "t", archive_path, f"-p{password}", "-y"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=120,
            encoding="utf-8", errors="replace"
        )
        return result.returncode == 0
    except Exception:
        return False


def test_password(archive_path, password):
    """测试压缩包的密码是否正确（只验证不解压）"""
    ext = Path(archive_path).suffix.lower()
    lower_name = Path(archive_path).name.lower()

    if not password:
        return False

    if ext == ".zip" or ext in {".jar", ".war", ".ear"}:
        return test_zip_password(archive_path, password)
    elif ext == ".7z":
        result = test_7z_password_py7zr(archive_path, password)
        if result is not None:
            return result
        cli_result = test_archive_password_7z_cli(archive_path, password)
        if cli_result is not None:
            return cli_result
        return False
    elif ext == ".rar":
        cli_result = test_archive_password_7z_cli(archive_path, password)
        if cli_result is not None:
            return cli_result
        return False
    # 对于 .7z.001 样式的分卷，用7z CLI测试
    elif RE_NUM_EXT.search(lower_name):
        cli_result = test_archive_password_7z_cli(archive_path, password)
        if cli_result is not None:
            return cli_result
        return False
    elif lower_name.endswith(".tar.gz") or ext in {".tar", ".gz", ".tgz", ".bz2", ".xz"}:
        return False
    else:
        cli_result = test_archive_password_7z_cli(archive_path, password)
        if cli_result is not None:
            return cli_result
        return False


def get_missing_tool_message(archive_files):
    """检查是否有7z/rar文件但缺少对应工具，返回提示信息"""
    has_7z = any(str(f).lower().endswith(".7z") or str(f).lower().endswith(".7z.001") for f in archive_files)
    has_rar = any(str(f).lower().endswith(".rar") for f in archive_files)

    if has_7z or has_rar:
        sz_path = _find_7z_path()
        try:
            import py7zr  # noqa: F401
            has_py7zr = True
        except ImportError:
            has_py7zr = False

        msgs = []
        if has_7z and not sz_path and not has_py7zr:
            msgs.append("检测到 .7z 文件，但未安装 7-Zip 或 py7zr，7z 格式无法测试密码。")
        if has_rar and not sz_path:
            msgs.append("检测到 .rar 文件，但未安装 7-Zip，RAR 格式无法测试密码。")
        if msgs:
            msgs.append("建议：安装 7-Zip (https://7-zip.org/) 并加入 PATH，或执行: pip install py7zr")
            return "\n".join(msgs)
    return None


def generate_bruteforce_passwords(max_length, charset=CHARSET_PRINTABLE):
    """生成器：从1到max_length所有字符组合，逐个 yield"""
    for length in range(1, max_length + 1):
        for combo in itertools.product(charset, repeat=length):
            yield "".join(combo)


def estimate_bruteforce(max_length, charset=CHARSET_PRINTABLE):
    """返回 (total_combinations, readable_time_str, warning_level)
    warning_level: 0=安全, 1=警告(>30min), 2=危险(>24h)"""
    total = 0
    for length in range(1, max_length + 1):
        total += len(charset) ** length

    # 假设每密码测试 0.3 秒
    seconds = total * 0.3
    if seconds < 60:
        time_str = "约 %d 秒" % seconds
    elif seconds < 3600:
        time_str = "约 %d 分钟" % (seconds / 60)
    elif seconds < 86400:
        time_str = "约 %.1f 小时" % (seconds / 3600)
    else:
        time_str = "约 %.1f 天" % (seconds / 86400)

    if seconds > 86400:
        warning_level = 2
    elif seconds > 1800:
        warning_level = 1
    else:
        warning_level = 0

    return total, time_str, warning_level


def categorize_archives(source_dir, dest_dir, passwords, progress_callback=None, move_files=False, bruteforce_max_length=0):
    """
    主处理函数：
    - 扫描 source_dir 下所有压缩包（含分卷）
    - 对每个压缩包（分卷只测首卷），依次尝试每个密码
    - 匹配成功则复制/移动到 dest_dir/密码：xxx/ 下
    - 不匹配任何密码则放到 dest_dir/未匹配密码/ 下
    - 只验证密码，不解压文件
    - move_files=True 时移动文件（默认移动）
    """
    source_path = Path(source_dir)
    dest_path = Path(dest_dir)
    dest_path.mkdir(parents=True, exist_ok=True)

    archive_files, all_parts_map = find_archives(source_dir)

    stats = {
        "total": len(archive_files),
        "success": 0,
        "failed": 0,
        "results": [],
        "warnings": [],
    }

    warning = get_missing_tool_message(archive_files)
    if warning:
        stats["warnings"].append(warning)

    for idx, archive_file in enumerate(archive_files):
        parts = all_parts_map.get(archive_file, [archive_file])
        # 用首卷文件名作为显示名
        rel_path = archive_file.relative_to(source_path)
        archive_name = str(rel_path)

        if progress_callback:
            progress_callback(idx, len(archive_files), "处理: " + archive_name)

        matched = False
        used_password = None

        for password in passwords:
            if test_password(str(archive_file), password):
                matched = True
                used_password = password
                break

        if matched and used_password:
            password_dir_name = "密码：" + used_password
            password_dir = dest_path / password_dir_name
            password_dir.mkdir(parents=True, exist_ok=True)

            # 复制/移动所有分卷
            for part in parts:
                part_rel = part.relative_to(source_path)
                dest_subpath = password_dir / part_rel
                dest_subpath.parent.mkdir(parents=True, exist_ok=True)
                dest_subpath = _resolve_path_conflict(dest_subpath)
                _copy_or_move(str(part), str(dest_subpath), move_files)

            stats["success"] += 1
            stats["results"].append((archive_name, used_password, "成功"))
            stats.setdefault("bruteforce_hits", []).append(None)
        else:
            # 未匹配 - 如果启用了暴力破解，加入待破解列表
            if bruteforce_max_length > 0:
                stats.setdefault("unmatched", []).append((archive_file, parts, archive_name, rel_path))
            else:
                unsolved_dir = dest_path / "未匹配密码"
                for part in parts:
                    part_rel = part.relative_to(source_path)
                    unsolved_subpath = unsolved_dir / part_rel
                    unsolved_subpath.parent.mkdir(parents=True, exist_ok=True)
                    unsolved_subpath = _resolve_path_conflict(unsolved_subpath)
                    _copy_or_move(str(part), str(unsolved_subpath), move_files)

                stats["failed"] += 1
                stats["results"].append((archive_name, None, "未找到匹配密码"))
                stats.setdefault("bruteforce_hits", []).append(None)

    # --- 阶段2: 暴力破解 ---
    unmatched = stats.get("unmatched", [])
    if unmatched and bruteforce_max_length > 0:
        total_unmatched = len(unmatched)
        for uidx, (archive_file, parts, archive_name, rel_path) in enumerate(unmatched):
            bf_matched = False
            bf_password = None
            bf_count = 0

            for bf_pwd in generate_bruteforce_passwords(bruteforce_max_length):
                bf_count += 1
                if progress_callback:
                    if bf_count % 100 == 0 or bf_count <= 5:
                        msg = "[暴力破解 %d/%d] %s - 正在尝试: %s (已试%d个)" % (
                            uidx + 1, total_unmatched, archive_name, bf_pwd, bf_count)
                        progress_callback(uidx, total_unmatched, msg)

                if test_password(str(archive_file), bf_pwd):
                    bf_matched = True
                    bf_password = bf_pwd
                    break

            if bf_matched and bf_password:
                password_dir_name = "密码：" + bf_password
                password_dir = dest_path / password_dir_name
                password_dir.mkdir(parents=True, exist_ok=True)

                for part in parts:
                    part_rel = part.relative_to(source_path)
                    dest_subpath = password_dir / part_rel
                    dest_subpath.parent.mkdir(parents=True, exist_ok=True)
                    dest_subpath = _resolve_path_conflict(dest_subpath)
                    _copy_or_move(str(part), str(dest_subpath), move_files)

                stats["success"] += 1
                # Fix failed count since we moved from unmatched to matched
                stats["failed"] = max(0, stats["failed"] - 1)
                stats["results"].append((archive_name, bf_password, "成功（暴力破解）"))
                stats.setdefault("bruteforce_hits", []).append(bf_password)
            else:
                # Still unmatched after brute-force
                unsolved_dir = dest_path / "未匹配密码"
                for part in parts:
                    part_rel = part.relative_to(source_path)
                    unsolved_subpath = unsolved_dir / part_rel
                    unsolved_subpath.parent.mkdir(parents=True, exist_ok=True)
                    unsolved_subpath = _resolve_path_conflict(unsolved_subpath)
                    _copy_or_move(str(part), str(unsolved_subpath), move_files)

                stats["failed"] += 1
                stats["results"].append((archive_name, None, "未找到匹配密码"))
                stats.setdefault("bruteforce_hits", []).append(None)

        # Add brute-force info to warnings
        stats["warnings"].append(
            "暴力破解完成：尝试了 %d 个未匹配文件，最多 %d 位字符所有组合" %
            (len(unmatched), bruteforce_max_length))

    return stats


def _copy_or_move(src, dst, move_files):
    """复制或移动文件"""
    if move_files:
        shutil.move(src, dst)
    else:
        shutil.copy2(src, dst)


def _resolve_path_conflict(path):
    """如果文件已存在，自动添加序号避免覆盖"""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        new_path = path.with_name(stem + "_" + str(counter) + suffix)
        if not new_path.exists():
            return new_path
        counter += 1
