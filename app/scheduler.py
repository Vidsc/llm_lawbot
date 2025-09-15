# app/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import time

from scripts import check_updates  # 复用你的更新脚本

def start_scheduler():
    scheduler = BackgroundScheduler()

    # 每周执行一次
    scheduler.add_job(
        check_updates.main,
        trigger=IntervalTrigger(weeks=1),
        id="weekly_update",
        replace_existing=True,
    )

    scheduler.start()
    print("[scheduler] started: weekly update job registered")

    try:
        # 阻塞主线程，不让程序退出
        while True:
            time.sleep(10)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

if __name__ == "__main__":
    start_scheduler()
