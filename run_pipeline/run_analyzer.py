#!/usr/bin/env python3
"""
分析器运行脚本

根据 JSON 配置文件运行指定分析器，并将结果导出到 CSV 文件。

使用方式：
    # 使用默认配置文件运行
    python examples/run_analyzer.py data/sesora.db
    
    # 指定配置文件
    python examples/run_analyzer.py data/sesora.db --config run_cases.json
    
    # 指定输出 CSV 文件
    python examples/run_analyzer.py data/sesora.db --output results.csv
    
    # 显示详细输出
    python examples/run_analyzer.py data/sesora.db --verbose
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sesora.store.sqlite_store import SQLiteDataStore
from sesora.engine import AssessmentEngine
from sesora.core.analyzer import ScoreState


def load_run_cases(config_path: Path) -> list[str]:
    """从 JSON 文件加载要运行的分析器列表"""
    if not config_path.exists():
        print(f"错误: 配置文件不存在: {config_path}")
        sys.exit(1)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        cases = json.load(f)
    
    if not isinstance(cases, list):
        print(f"错误: 配置文件格式不正确，应为字符串数组")
        sys.exit(1)
    
    return cases


def print_data_status(store: SQLiteDataStore, engine: AssessmentEngine, keys: list[str] = None, show_all_items: bool = True):
    """打印数据状态报告
    
    Args:
        store: 数据存储
        engine: 评估引擎
        keys: 分析器 key 列表
        show_all_items: 是否显示数据库中所有 DataItem（使用 --key 时为 False）
    """
    print("\n数据就绪状态:")
    print("-" * 70)
    
    # 列出数据库中的所有数据（仅在 show_all_items=True 时显示）
    available_items = store.list_dataitems()
    if show_all_items:
        print(f"\n数据库中的 DataItem ({len(available_items)} 个):")
        for item in sorted(available_items):
            records = store.get(item)
            print(f"  ✓ {item} ({len(records)} 条记录)")
    else:
        print(f"\n数据库中共有 {len(available_items)} 个 DataItem")
    
    # 检查分析器所需数据
    print(f"\n分析器数据需求检查:")
    requirements = engine.get_data_requirements(keys)
    
    print(f"\n  必需数据 (required):")
    for name in sorted(requirements["required"]):
        available = store.available(name)
        status = "✓" if available else "✗"
        print(f"    {status} {name}")
    
    print(f"\n  可选数据 (optional):")
    for name in sorted(requirements["optional"]):
        available = store.available(name)
        status = "✓" if available else "○"
        print(f"    {status} {name}")
    
    # 汇总
    required_count = len(requirements["required"])
    required_available = sum(1 for n in requirements["required"] if store.available(n))
    optional_count = len(requirements["optional"])
    optional_available = sum(1 for n in requirements["optional"] if store.available(n))
    
    print(f"\n  汇总:")
    print(f"    必需数据: {required_available}/{required_count} 可用")
    print(f"    可选数据: {optional_available}/{optional_count} 可用")


def run_analyzers(engine: AssessmentEngine, store: SQLiteDataStore,
                  keys: list[str], verbose: bool = False) -> list[dict]:
    """运行分析器并返回结果列表"""
    print("\n执行分析器:")
    print("-" * 70)
    
    # 获取分析器元数据
    metadata = {a.key(): a for a in engine.registry.get_all()}
    
    # 验证 keys 是否存在
    valid_keys = []
    for key in keys:
        if key in metadata:
            valid_keys.append(key)
        else:
            print(f"  警告: 分析器 '{key}' 不存在，已跳过")
    
    if not valid_keys:
        print("  没有有效的分析器可运行")
        return []
    
    # 运行分析器
    results = engine.registry.run_by_keys(store, valid_keys)
    
    # 构建结果列表
    result_list = []
    total_score = 0
    total_max = 0
    
    for result in results:
        analyzer = metadata.get(result.key)
        
        state_str = result.state.value if hasattr(result.state, 'value') else str(result.state)
        
        row = {
            "key": result.key,
            "dimension": analyzer.dimension() if analyzer else "",
            "category": analyzer.category() if analyzer else "",
            "state": state_str,
            "score": result.score,
            "max_score": result.max_score,
            "percentage": round(result.score / result.max_score * 100, 1) if result.max_score > 0 else 0,
            "reason": result.reason,
            "evidence_count": len(result.evidence) if result.evidence else 0,
            "evidence": "; ".join(result.evidence[:5]) if result.evidence else "",
        }
        result_list.append(row)
        
        # 统计
        if result.state == ScoreState.SCORED:
            total_score += result.score
            total_max += result.max_score
            status = f"✓ {result.score}/{result.max_score} ({row['percentage']}%)"
        elif result.state == ScoreState.NOT_SCORED:
            total_max += result.max_score
            status = f"○ 0/{result.max_score}"
        else:
            status = "- 未评估"
        
        print(f"  {result.key}: {status}")
        if verbose:
            print(f"    原因: {result.reason}")
    
    # 汇总
    print("\n" + "=" * 70)
    print("评估汇总")
    print("=" * 70)
    pct = total_score / total_max * 100 if total_max > 0 else 0
    print(f"  总得分: {total_score}/{total_max} ({pct:.1f}%)")
    print(f"  评估项: {len(results)} 项")
    
    return result_list


def save_to_csv(results: list[dict], output_path: Path) -> None:
    """将结果保存到 CSV 文件"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if not results:
        print("\n没有结果可保存")
        return
    
    fieldnames = [
        "key", "dimension", "category", "state", 
        "score", "max_score", "percentage", 
        "reason", "evidence_count", "evidence"
    ]
    
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    
    print(f"\n✓ 结果已保存到: {output_path}")


def save_summary_csv(results: list[dict], output_path: Path) -> None:
    """保存汇总结果到 CSV（按维度汇总）"""
    if not results:
        return
    
    # 按维度汇总
    by_dimension = {}
    for r in results:
        dim = r["dimension"] or "Unknown"
        if dim not in by_dimension:
            by_dimension[dim] = {"score": 0, "max_score": 0, "count": 0}
        if r["state"] in ("SCORED", "NOT_SCORED"):
            by_dimension[dim]["score"] += r["score"]
            by_dimension[dim]["max_score"] += r["max_score"]
            by_dimension[dim]["count"] += 1
    
    summary_path = output_path.with_name(output_path.stem + "_summary.csv")
    
    with open(summary_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["维度", "得分", "满分", "百分比", "评估项数"])
        
        total_score = 0
        total_max = 0
        total_count = 0
        
        for dim in sorted(by_dimension.keys()):
            data = by_dimension[dim]
            pct = data["score"] / data["max_score"] * 100 if data["max_score"] > 0 else 0
            writer.writerow([dim, data["score"], data["max_score"], f"{pct:.1f}%", data["count"]])
            total_score += data["score"]
            total_max += data["max_score"]
            total_count += data["count"]
        
        # 总计行
        total_pct = total_score / total_max * 100 if total_max > 0 else 0
        writer.writerow(["总计", total_score, total_max, f"{total_pct:.1f}%", total_count])
    
    print(f"✓ 汇总已保存到: {summary_path}")


def main():
    parser = argparse.ArgumentParser(
        description="根据 JSON 配置运行分析器并导出 CSV 结果",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 运行单个分析器
  python run_analyzer.py --key cicd_pipeline_exists
  
  # 运行多个指定分析器
  python run_analyzer.py --key cicd_pipeline_exists cicd_auto_triggered
  
  # 运行所有分析器
  python run_analyzer.py --all
  
  # 使用配置文件运行
  python run_analyzer.py --config run_cases.json
  
  # 仅检查数据就绪状态
  python run_analyzer.py --check-only --all
"""
    )
    
    parser.add_argument("--db_path", help="SQLite 数据库文件路径", default="data/sesora.db")
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="分析器配置 JSON 文件"
    )
    parser.add_argument(
        "--key", "-k",
        nargs="+",
        type=str,
        default=None,
        help="要运行的分析器 key（可指定多个）"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出 CSV 文件路径 (默认: results_YYYYMMDD_HHMMSS.csv)"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="运行所有分析器"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="列出所有可用的分析器 key"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细输出"
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="不生成汇总 CSV"
    )
    parser.add_argument(
        "--check-only", "-C",
        action="store_true",
        help="仅检查数据就绪状态，不运行分析器"
    )
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("SESORA 分析器运行工具")
    print("=" * 70)
    
    # 检查数据库
    db_path = Path(args.db_path)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    
    if not db_path.exists():
        print(f"\n错误: 数据库文件不存在: {db_path}")
        return 1
    
    print(f"\n数据库: {db_path}")
    
    # 列出所有分析器模式
    if args.list:
        with SQLiteDataStore(db_path) as store:
            engine = AssessmentEngine(store=store)
            all_analyzers = engine.registry.get_all()
            
            # 按维度分组
            by_dimension = {}
            for a in all_analyzers:
                dim = a.dimension()
                if dim not in by_dimension:
                    by_dimension[dim] = []
                by_dimension[dim].append(a)
            
            print(f"\n可用分析器 ({len(all_analyzers)} 个):")
            print("-" * 70)
            for dim in sorted(by_dimension.keys()):
                print(f"\n[{dim}]")
                for a in sorted(by_dimension[dim], key=lambda x: x.key()):
                    print(f"  {a.key()}")
        return 0
    
    # 加载配置 - 优先级: --key > --all > --config > 默认全部
    if args.key:
        keys = args.key
        print(f"模式: 运行指定分析器 ({len(keys)} 个)")
        for key in keys:
            print(f"  - {key}")
    elif args.all:
        keys = None
        print("模式: 运行所有分析器")
    elif args.config:
        config_path = Path(args.config)
        if not config_path.is_absolute():
            config_path = PROJECT_ROOT / config_path
        
        keys = load_run_cases(config_path)
        print(f"配置文件: {config_path}")
        print(f"待运行分析器: {len(keys)} 个")
        if args.verbose:
            for key in keys:
                print(f"  - {key}")
    else:
        # 默认运行全部
        keys = None
        print("模式: 运行所有分析器 (未指定配置)")
    
    # 输出路径
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = PROJECT_ROOT / output_path
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = PROJECT_ROOT /"results"/ timestamp / f"results_{timestamp}.csv"
    
    print(f"输出文件: {output_path}")
    
    # 运行分析器
    with SQLiteDataStore(db_path) as store:
        engine = AssessmentEngine(store=store)
        
        # 使用 --key 时不显示完整的 DataItem 列表
        show_all_items = not bool(args.key)
        
        if keys is None:
            # 运行所有
            all_analyzers = engine.registry.get_all()
            keys = [a.key() for a in all_analyzers]
        
        # 显示数据状态
        print_data_status(store, engine, keys, show_all_items=show_all_items)
        
        # 仅检查模式
        if args.check_only:
            print("\n数据检查完成!")
            return 0
        
        results = run_analyzers(engine, store, keys, args.verbose)
    
    # 保存结果
    if results:
        save_to_csv(results, output_path)
        if not args.no_summary:
            save_summary_csv(results, output_path)
    
    print("\n运行完成!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
