from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
env_path = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=env_path, override=True)

import collect_data
import run_analyzer

def main():
    collect_data.main()
    run_analyzer.main()


if __name__ == "__main__":
    main()