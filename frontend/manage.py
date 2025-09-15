#!/usr/bin/env python
import os
import sys
from pathlib import Path

def main():
    # 让 Django 运行时能 import 到项目根目录（以便 from app.rag import answer）
    this_dir = Path(__file__).resolve().parent
    project_root = this_dir.parent  # 仓库根目录
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "djfrontend.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)

if __name__ == "__main__":
    main()
