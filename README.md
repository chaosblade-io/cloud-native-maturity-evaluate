**使用方法：**
```
1. 先采集数据到数据库
python run_pipeline/collect_data.py

2. 查看采集到的数据状态
python run_pipeline/run_analyzer.py --check-only --all

4. 运行分析器测试
python run_pipeline/run_analyzer.py --db_path data/sesora.db --config run_cases.json
```