#!/usr/bin/env python3
"""Zero-dependency consistency checker for .project/ managed repositories."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.parse import unquote


VALID_TASK_STATUSES = {
    "unknown",
    "planned",
    "ready",
    "in_progress",
    "blocked",
    "in_review",
    "done",
    "cancelled",
}

VALID_VERIFICATION_STATUSES = {
    "not_run",
    "passed",
    "partial",
    "failed",
    "stale",
    "unavailable",
}

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\r\n]+)\)")
INLINE_CODE_RE = re.compile(r"`[^`\r\n]*`")
TREE_LINE_RE = re.compile(r"^((?:│   |    |\|   )*)(├── |└── )(.+)$")
BARE_ROOT_RE = re.compile(r"^([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*/)$")
NEXT_ID_RE_TEMPLATE = r"^{prefix}-(\d+)(?:\b|$)"


def configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def strip_quotes(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
        return val[1:-1]
    return val


def parse_inline_list(raw: str) -> list[str]:
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return []
    return [strip_quotes(item) for item in inner.split(",") if strip_quotes(item)]


def parse_scalar(raw: str) -> Any:
    val = raw.strip()
    if val == "" or val.lower() == "null" or val == "~":
        return None
    if val.startswith("[") and val.endswith("]"):
        return parse_inline_list(val)
    return strip_quotes(val)


def parse_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return None, text

    data: dict[str, Any] = {}
    current_parent: str | None = None
    for raw_line in lines[1:end_idx]:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if indent == 0:
            current_parent = None
            if ":" not in stripped:
                continue
            key, rest = stripped.split(":", 1)
            key = key.strip()
            rest = rest.strip()
            if rest == "":
                data[key] = {}
                current_parent = key
            else:
                data[key] = parse_scalar(rest)
        elif indent > 0 and current_parent is not None:
            parent_val = data.get(current_parent)
            if isinstance(parent_val, dict):
                if stripped.startswith("- "):
                    # Convert empty dict block to list if YAML list items are used
                    data[current_parent] = [strip_quotes(stripped[2:])]
                    continue
                if ":" in stripped:
                    sub_key, sub_rest = stripped.split(":", 1)
                    parent_val[sub_key.strip()] = parse_scalar(sub_rest)
            elif isinstance(parent_val, list) and stripped.startswith("- "):
                parent_val.append(strip_quotes(stripped[2:]))

    body = "\n".join(lines[end_idx + 1 :])
    return data, body


def collect_task_ids_in_dir(base_dir: Path) -> set[str]:
    ids: set[str] = set()
    if not base_dir.is_dir():
        return ids
    for entry in base_dir.iterdir():
        if not entry.is_dir():
            continue
        ids.add(entry.name)
        task_file = entry / "TASK.md"
        if task_file.is_file():
            fm, _ = parse_frontmatter(task_file.read_text(encoding="utf-8-sig", errors="replace"))
            if isinstance(fm, dict) and isinstance(fm.get("id"), str) and fm["id"].strip():
                ids.add(fm["id"].strip())
    return ids


def find_next_id(project_dir: Path, prefix: str) -> str:
    normalized = prefix.strip().rstrip("-")
    pattern = re.compile(rf"^{re.escape(normalized)}-(\d+)(?:\D|$)", re.IGNORECASE)
    candidates: set[str] = set()
    candidates |= collect_task_ids_in_dir(project_dir / "tasks")
    archive_dir = project_dir / "archive"
    if archive_dir.is_dir():
        for sub in archive_dir.rglob("TASK.md"):
            candidates.add(sub.parent.name)
            fm, _ = parse_frontmatter(sub.read_text(encoding="utf-8-sig", errors="replace"))
            if isinstance(fm, dict) and isinstance(fm.get("id"), str):
                candidates.add(fm["id"].strip())

    max_num = 0
    width = 3
    for item in candidates:
        m = pattern.match(item)
        if m:
            num_str = m.group(1)
            width = max(width, len(num_str))
            max_num = max(max_num, int(num_str))
    return f"{normalized}-{max_num + 1:0{width}d}"


def check_tasks(
    project_dir: Path,
    archive_threshold: int,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    tasks_dir = project_dir / "tasks"
    archive_ids: set[str] = set()
    archive_dir = project_dir / "archive"
    if archive_dir.is_dir():
        for sub in archive_dir.rglob("TASK.md"):
            archive_ids.add(sub.parent.name)
            fm, _ = parse_frontmatter(sub.read_text(encoding="utf-8-sig", errors="replace"))
            if isinstance(fm, dict) and isinstance(fm.get("id"), str):
                archive_ids.add(fm["id"].strip())

    status_counts: Counter[str] = Counter()
    verification_counts: Counter[str] = Counter()
    active_tasks: list[dict[str, str]] = []
    done_non_passed: list[dict[str, str]] = []
    seen_ids: dict[str, str] = {}
    dependencies: dict[str, list[str]] = {}
    task_dirs: list[Path] = []

    if tasks_dir.is_dir():
        task_dirs = sorted([p for p in tasks_dir.iterdir() if p.is_dir()], key=lambda p: p.name)

    valid_tasks = 0
    for tdir in task_dirs:
        rel_dir = f".project/tasks/{tdir.name}"
        task_file = tdir / "TASK.md"
        if not task_file.is_file():
            errors.append(
                {
                    "code": "missing_task_file",
                    "path": rel_dir,
                    "message": f"任务目录 {tdir.name} 缺少 TASK.md",
                }
            )
            continue

        fm, _ = parse_frontmatter(task_file.read_text(encoding="utf-8-sig", errors="replace"))
        if fm is None:
            errors.append(
                {
                    "code": "missing_frontmatter",
                    "path": f"{rel_dir}/TASK.md",
                    "message": f"{tdir.name}/TASK.md 缺少 YAML frontmatter",
                }
            )
            continue

        valid_tasks += 1
        task_id = fm.get("id")
        title = fm.get("title")
        status = fm.get("status")

        if not isinstance(task_id, str) or not task_id.strip():
            errors.append(
                {
                    "code": "missing_task_id",
                    "path": f"{rel_dir}/TASK.md",
                    "message": f"{tdir.name}/TASK.md 缺少 id 字段",
                }
            )
            task_id = tdir.name
        else:
            task_id = task_id.strip()
            if task_id != tdir.name:
                errors.append(
                    {
                        "code": "task_id_mismatch",
                        "path": f"{rel_dir}/TASK.md",
                        "message": f"目录名 {tdir.name} 与 YAML id '{task_id}' 不一致",
                    }
                )
            if task_id in seen_ids:
                errors.append(
                    {
                        "code": "duplicate_task_id",
                        "path": f"{rel_dir}/TASK.md",
                        "message": f"任务 id '{task_id}' 重复（首次出现在 {seen_ids[task_id]}）",
                    }
                )
            else:
                seen_ids[task_id] = rel_dir

        if not isinstance(title, str) or not title.strip():
            errors.append(
                {
                    "code": "missing_task_title",
                    "path": f"{rel_dir}/TASK.md",
                    "message": f"{tdir.name}/TASK.md 缺少 title 字段",
                }
            )

        if not isinstance(status, str) or status not in VALID_TASK_STATUSES:
            errors.append(
                {
                    "code": "invalid_task_status",
                    "path": f"{rel_dir}/TASK.md",
                    "message": f"{tdir.name}/TASK.md 的 status '{status}' 无效",
                }
            )
            status_val = "unknown"
        else:
            status_val = status

        status_counts[status_val] += 1

        verif = fm.get("verification")
        verif_status = "not_run"
        if isinstance(verif, dict):
            vs = verif.get("status")
            if vs is not None:
                if not isinstance(vs, str) or vs not in VALID_VERIFICATION_STATUSES:
                    errors.append(
                        {
                            "code": "invalid_verification_status",
                            "path": f"{rel_dir}/TASK.md",
                            "message": f"{tdir.name}/TASK.md 的 verification.status '{vs}' 无效",
                        }
                    )
                else:
                    verif_status = vs
        verification_counts[verif_status] += 1

        if status_val == "done" and verif_status != "passed":
            done_non_passed.append({"id": task_id, "verification": verif_status, "path": f"{rel_dir}/TASK.md"})
        if status_val not in {"done", "cancelled"}:
            active_tasks.append({"id": task_id, "status": status_val, "path": f"{rel_dir}/TASK.md"})

        deps = fm.get("depends_on")
        if isinstance(deps, list):
            dependencies[tdir.name] = [str(d).strip() for d in deps if str(d).strip()]
        else:
            dependencies[tdir.name] = []

    known_ids = set(seen_ids.keys()) | {d.name for d in task_dirs} | archive_ids
    for tname, deps in dependencies.items():
        for dep in deps:
            if dep == tname:
                errors.append(
                    {
                        "code": "self_dependency",
                        "path": f".project/tasks/{tname}/TASK.md",
                        "message": f"任务 {tname} 存在自依赖",
                    }
                )
            elif dep not in known_ids:
                errors.append(
                    {
                        "code": "missing_dependency",
                        "path": f".project/tasks/{tname}/TASK.md",
                        "message": f"任务 {tname} 依赖不存在的任务 '{dep}'",
                    }
                )

    # Cycle detection (DFS)
    color: dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=done

    def dfs(node: str, stack: list[str]) -> None:
        color[node] = 1
        for nxt in dependencies.get(node, []):
            if nxt not in dependencies:
                continue
            if color.get(nxt, 0) == 1:
                cycle = " -> ".join(stack[stack.index(nxt) :] + [nxt])
                errors.append(
                    {
                        "code": "dependency_cycle",
                        "path": f".project/tasks/{node}/TASK.md",
                        "message": f"任务依赖存在环：{cycle}",
                    }
                )
            elif color.get(nxt, 0) == 0:
                dfs(nxt, stack + [nxt])
        color[node] = 2

    for tname in dependencies:
        if color.get(tname, 0) == 0:
            dfs(tname, [tname])

    finished_count = status_counts["done"] + status_counts["cancelled"]
    if finished_count >= archive_threshold:
        warnings.append(
            {
                "code": "archive_threshold_reached",
                "path": ".project/tasks",
                "message": (
                    f"已完结任务共 {finished_count} 项（达到阈值 {archive_threshold}），"
                    "可提示用户是否按功能或阶段整理归档至 .project/archive/"
                ),
            }
        )

    return {
        "task_dir_count": len(task_dirs),
        "valid_task_count": valid_tasks,
        "status_counts": dict(status_counts),
        "verification_counts": dict(verification_counts),
        "done_non_passed": done_non_passed,
        "active_tasks": active_tasks,
    }


def check_links(
    root: Path,
    project_dir: Path,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> int:
    checked = 0
    for md_file in sorted(project_dir.rglob("*.md")):
        rel_md = md_file.relative_to(root).as_posix()
        is_record = "/records/" in rel_md or rel_md.startswith(".project/archive/")
        lines = md_file.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        in_fence = False
        for line_no, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            cleaned_line = INLINE_CODE_RE.sub("", line)
            for match in LINK_RE.finditer(cleaned_line):
                raw_target = match.group(1).strip()
                if not raw_target:
                    continue
                # Handle optional link title: path "title"
                target = raw_target.split()[0].strip("<>")
                if (
                    target.startswith("#")
                    or "://" in target
                    or target.startswith("mailto:")
                    or "{" in target
                    or "}" in target
                ):
                    continue
                path_part = target.split("#", 1)[0]
                if not path_part:
                    continue
                path_part = unquote(path_part)
                resolved = (md_file.parent / path_part).resolve()
                checked += 1
                if not resolved.exists():
                    issue = {
                        "code": "broken_link",
                        "path": f"{rel_md}:{line_no}",
                        "message": f"断链 '{target}'（解析为 {resolved}）",
                    }
                    if is_record:
                        warnings.append(issue)
                    else:
                        errors.append(issue)
    return checked


def parse_map_paths(map_file: Path, root: Path, errors: list[dict[str, str]]) -> set[str]:
    text = map_file.read_text(encoding="utf-8-sig", errors="replace")
    rel_map = map_file.relative_to(root).as_posix()

    # Module index maps (like agent/MAP.md) use schematic blocks pointing to sub-maps.
    lines = text.splitlines()
    has_submap_links = any("MAP.md)" in ln for ln in lines)

    mapped_paths: set[str] = set()
    in_text_block = False
    stack: list[tuple[int, str]] = []

    for line_no, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if stripped.startswith("```text"):
            in_text_block = True
            stack = []
            continue
        if in_text_block and stripped.startswith("```"):
            in_text_block = False
            stack = []
            continue
        if not in_text_block or not stripped:
            continue

        # Skip schematic trees inside parent index MAPs that use Chinese enumeration commas
        if has_submap_links and "、" in raw_line:
            continue

        bare_m = BARE_ROOT_RE.match(stripped)
        if bare_m and not stack:
            root_name = bare_m.group(1).rstrip("/")
            if root_name and root_name != ".":
                stack = [(-1, root_name)]
                target = root / root_name
                if not target.exists():
                    errors.append(
                        {
                            "code": "map_missing_path",
                            "path": f"{rel_map}:{line_no}",
                            "message": f"地图路径不存在：{root_name}",
                        }
                    )
                else:
                    mapped_paths.add(root_name)
            continue

        m = TREE_LINE_RE.match(raw_line)
        if not m:
            continue
        prefix_ws, _connector, rest = m.groups()
        node_part = rest.split("  #", 1)[0].split(" #", 1)[0].strip()
        if not node_part or node_part in {"...", "…"}:
            continue
        if "、" in node_part:
            continue

        level = len(prefix_ws) // 4
        is_dir = node_part.endswith("/")
        name = node_part.rstrip("/")
        if not name or name == ".":
            continue

        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, name))

        rel_target = "/".join(item[1] for item in stack)
        target_path = root / rel_target
        if not target_path.exists():
            errors.append(
                {
                    "code": "map_missing_path",
                    "path": f"{rel_map}:{line_no}",
                    "message": f"地图声明路径不存在：{rel_target}",
                }
            )
        else:
            if not is_dir and target_path.is_file():
                mapped_paths.add(rel_target)
            elif is_dir:
                mapped_paths.add(rel_target)

    return mapped_paths


def check_maps_and_git(
    root: Path,
    project_dir: Path,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    modules_dir = project_dir / "modules"
    all_mapped: set[str] = set()
    map_files = sorted(modules_dir.rglob("MAP.md")) if modules_dir.is_dir() else []

    for mf in map_files:
        all_mapped |= parse_map_paths(mf, root, errors)

    unmapped_changed: list[str] = []
    if (root / ".git").exists():
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "-c", "core.quotepath=false", "status", "--porcelain=v1", "-uall"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    if len(line) < 4:
                        continue
                    code = line[:2]
                    rel_path = line[3:].strip()
                    if " -> " in rel_path:
                        rel_path = rel_path.split(" -> ", 1)[1].strip()
                    rel_path = rel_path.strip('"').replace("\\", "/")
                    if (
                        rel_path.startswith(".project/")
                        or rel_path.startswith("output/")
                        or "/__pycache__/" in rel_path
                        or rel_path.endswith(".pyc")
                    ):
                        continue
                    # Warn on added/untracked files not present in any MAP.md
                    if ("?" in code or "A" in code) and (root / rel_path).is_file():
                        if rel_path not in all_mapped:
                            unmapped_changed.append(rel_path)
                            warnings.append(
                                {
                                    "code": "unmapped_changed_file",
                                    "path": rel_path,
                                    "message": f"工作区新增/未跟踪文件尚未登记到任何 MAP.md：{rel_path}",
                                }
                            )
        except OSError:
            pass

    return {
        "map_file_count": len(map_files),
        "mapped_path_count": len(all_mapped),
        "unmapped_changed_files": unmapped_changed,
    }


def render_text_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"=== .project 校验报告 ({report['root']}) ===")
    tasks = report["tasks"]
    lines.append(
        f"任务汇总: 目录 {tasks['task_dir_count']} 个, 有效 {tasks['valid_task_count']} 个"
    )
    if tasks["status_counts"]:
        status_str = ", ".join(f"{k}={v}" for k, v in sorted(tasks["status_counts"].items()))
        lines.append(f"  status 分布: {status_str}")
    if tasks["verification_counts"]:
        verif_str = ", ".join(f"{k}={v}" for k, v in sorted(tasks["verification_counts"].items()))
        lines.append(f"  verification 分布: {verif_str}")
    if tasks["done_non_passed"]:
        items = ", ".join(f"{x['id']}({x['verification']})" for x in tasks["done_non_passed"])
        lines.append(f"  done 但非 passed: {items}")
    if tasks["active_tasks"]:
        items = ", ".join(f"{x['id']}({x['status']})" for x in tasks["active_tasks"])
        lines.append(f"  活跃任务: {items}")

    lines.append(
        f"链接与地图: 校验相对链接 {report['links_checked']} 个; "
        f"MAP 文件 {report['maps']['map_file_count']} 份, 登记路径 {report['maps']['mapped_path_count']} 条"
    )

    lines.append(f"\n错误 ({len(report['errors'])}):")
    if not report["errors"]:
        lines.append("  无")
    else:
        for err in report["errors"]:
            lines.append(f"  [ERROR] [{err['code']}] {err['path']}: {err['message']}")

    lines.append(f"\n提醒 ({len(report['warnings'])}):")
    if not report["warnings"]:
        lines.append("  无")
    else:
        for warn in report["warnings"]:
            lines.append(f"  [WARN]  [{warn['code']}] {warn['path']}: {warn['message']}")

    return "\n".join(lines)


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="Validate .project/ structure, tasks, links, and MAPs.")
    parser.add_argument("--root", default=".", help="Target repository root containing .project/")
    parser.add_argument("--next-id", metavar="PREFIX", help="Output the next available task ID for PREFIX and exit")
    parser.add_argument(
        "--archive-threshold",
        type=int,
        default=25,
        help="Warn when finished (done + cancelled) tasks reach this count (default: 25)",
    )
    parser.add_argument("--json", action="store_true", help="Print structured JSON output")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if any warnings are present")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    project_dir = root / ".project"
    if not project_dir.is_dir():
        print(f"[ERROR] 未找到 .project 目录: {project_dir}", file=sys.stderr)
        return 2

    if args.next_id:
        print(find_next_id(project_dir, args.next_id))
        return 0

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    task_summary = check_tasks(project_dir, args.archive_threshold, errors, warnings)
    links_checked = check_links(root, project_dir, errors, warnings)
    map_summary = check_maps_and_git(root, project_dir, errors, warnings)

    report = {
        "root": str(root),
        "tasks": task_summary,
        "links_checked": links_checked,
        "maps": map_summary,
        "errors": errors,
        "warnings": warnings,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text_report(report))

    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
