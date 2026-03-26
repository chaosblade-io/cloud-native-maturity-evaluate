#!/usr/bin/env python3
"""
单个采集器执行脚本

用于被 Web API 通过 subprocess 调用，避免 signal 只能在主线程的问题

用法: python run_one_collector.py <collector_name>
输出: JSON 格式的采集结果
"""
import json
import sys
import time
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 尝试加载 dotenv，如果失败则忽略（环境变量可能已从父进程继承）
try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / ".env"
    load_dotenv(dotenv_path=env_path, override=True)
except ImportError:
    pass  # 环境变量已从父进程继承

from run_pipeline.collect_data import (
    validate_config,
    create_context,
    collect_codeup,
    collect_fc,
    collect_ack,
    collect_sls,
    collect_rds,
    collect_cms,
    collect_ros,
    collect_oss,
    collect_arms,
    collect_acr,
    collect_alb,
    collect_ecs,
    collect_eventbridge,
    collect_grafana,
    collect_gtm,
    collect_tair,
)

# 采集器映射
COLLECTOR_FUNCS = {
    "codeup": collect_codeup,
    "fc": collect_fc,
    "ack": collect_ack,
    "sls": collect_sls,
    "rds": collect_rds,
    "cms": collect_cms,
    "ros": collect_ros,
    "oss": collect_oss,
    "arms": collect_arms,
    "acr": collect_acr,
    "alb": collect_alb,
    "ecs": collect_ecs,
    "eventbridge": collect_eventbridge,
    "grafana": collect_grafana,
    "gtm": collect_gtm,
    "tair": collect_tair,
}


def run_collector(collector_name: str) -> dict:
    """
    运行单个采集器
    
    Args:
        collector_name: 采集器名称
        
    Returns:
        采集结果字典
    """
    import io
    import contextlib
    
    if collector_name not in COLLECTOR_FUNCS:
        return {
            "success": False,
            "message": f"未知的采集器: {collector_name}",
            "elapsed_seconds": 0,
        }
    
    start_time = time.time()
    
    try:
        # 验证配置并创建上下文
        config = validate_config()
        context = create_context(config)
        
        # 数据库路径
        db_dir = PROJECT_ROOT / "data"
        db_dir.mkdir(exist_ok=True)
        db_path = db_dir / "sesora.db"
        
        # 执行采集，捕获所有输出到 stderr
        func = COLLECTOR_FUNCS[collector_name]
        
        # 重定向 stdout 到 stderr，让采集日志不干扰 JSON 输出
        old_stdout = sys.stdout
        sys.stdout = sys.stderr
        
        try:
            success = func(context, db_path)
        finally:
            sys.stdout = old_stdout
        
        elapsed = time.time() - start_time
        
        return {
            "success": success,
            "message": "采集成功" if success else "采集失败或无数据",
            "elapsed_seconds": round(elapsed, 2),
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "success": False,
            "message": f"采集异常: {str(e)}",
            "elapsed_seconds": round(elapsed, 2),
        }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"success": False, "message": "缺少采集器名称参数", "elapsed_seconds": 0}))
        sys.exit(1)
    
    collector_name = sys.argv[1]
    result = run_collector(collector_name)
    
    # 输出 JSON 结果
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
