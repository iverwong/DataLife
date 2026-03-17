#!/usr/bin/env python3
"""
SubagentStop Hook - 子代理完成评估脚本

当worker子代理完成工作时，此脚本会被调用进行评估。
评估方式：读取子代理的转录文件，分析其完成的任务，并根据代码变更进行评估。

用法：
    此脚本由Claude Code的SubagentStop hook自动调用，无需手动运行。

输入：
    JSON格式的hook事件数据，包含：
    - agent_type: 子代理类型（如 "worker"）
    - agent_transcript_path: 转录文件路径
    - last_assistant_message: 子代理的最后消息

输出：
    评估结果到stdout，错误信息到stderr
    退出码：
    - 0: 评估通过
    - 1: 警告（可以继续）
    - 2: 评估失败，阻止子代理停止
"""

import json
import sys
import os
from pathlib import Path


def load_transcript(transcript_path: str) -> dict | None:
    """加载子代理转录文件"""
    if not transcript_path or not os.path.exists(transcript_path):
        return None

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] 无法加载转录文件: {e}", file=sys.stderr)
        return None


def extract_task_info(transcript: dict) -> dict:
    """从转录中提取任务信息"""
    messages = transcript.get("messages", [])

    # 找到用户的原始任务委托
    task_info = {
        "task_description": "",
        "files_mentioned": [],
        "actions_taken": [],
    }

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "user":
            # 提取任务描述（取最后的用户消息）
            if isinstance(content, str):
                task_info["task_description"] = content
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        task_info["task_description"] = item.get("text", "")

        elif role == "assistant":
            # 提取assistant执行的操作
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        tool_name = item.get("name", "")
                        if tool_name:
                            task_info["actions_taken"].append(tool_name)

    return task_info


def evaluate_completion(task_info: dict, transcript: dict) -> tuple[bool, str]:
    """
    评估子代理完成情况

    返回: (success: bool, message: str)
    """
    task_desc = task_info.get("task_description", "")
    actions = task_info.get("actions_taken", [])

    if not task_desc:
        return True, "无法提取任务描述，跳过评估"

    # 检查是否包含关键操作
    key_actions = {"Read", "Edit", "Write", "Glob", "Grep"}
    has_key_action = any(action in actions for action in key_actions)

    if not has_key_action:
        return True, f"任务可能未执行实际操作: {task_desc[:100]}..."

    # 检查是否提到了错误或问题
    messages = transcript.get("messages", [])
    has_errors = False

    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str) and "error" in content.lower():
            has_errors = True
            break
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and "error" in str(item).lower():
                    has_errors = True
                    break

    if has_errors:
        return False, "子代理执行过程中可能遇到错误"

    # 评估通过
    return True, f"任务完成评估通过: {task_desc[:100]}..."


def main():
    # 从stdin读取hook事件数据
    input_data = sys.stdin.read()

    if not input_data:
        print("[INFO] 无输入数据，跳过评估", file=sys.stderr)
        sys.exit(0)

    try:
        event_data = json.loads(input_data)
    except json.JSONDecodeError as e:
        print(f"[WARN] JSON解析失败: {e}", file=sys.stderr)
        sys.exit(0)

    # 提取关键信息
    agent_type = event_data.get("agent_type", "")
    transcript_path = event_data.get("agent_transcript_path", "")
    last_message = event_data.get("last_assistant_message", "")

    print(f"[INFO] SubagentStop hook triggered for agent type: {agent_type}", file=sys.stderr)

    # 只对worker类型的子代理进行评估
    if agent_type != "worker":
        print(f"[INFO] 非worker agent ({agent_type})，跳过评估", file=sys.stderr)
        sys.exit(0)

    # 加载转录文件
    transcript = load_transcript(transcript_path)

    if not transcript:
        print("[WARN] 无法加载转录文件，跳过评估", file=sys.stderr)
        sys.exit(0)

    # 提取任务信息
    task_info = extract_task_info(transcript)
    print(f"[INFO] 任务描述: {task_info.get('task_description', '')[:100]}...", file=sys.stderr)
    print(f"[INFO] 执行的操作: {task_info.get('actions_taken', [])}", file=sys.stderr)

    # 评估完成情况
    success, message = evaluate_completion(task_info, transcript)

    print(f"[EVALUATION] {message}", file=sys.stderr)

    if success:
        sys.exit(0)
    else:
        # 退出码2表示阻止子代理停止
        print(f"[ERROR] {message}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
