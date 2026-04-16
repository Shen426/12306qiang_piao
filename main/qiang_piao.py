import time
from datetime import datetime
from playwright.sync_api import sync_playwright

# ===== 配置区 =====
TARGET_TIME = "08:15:00"   # 开票时间（改成你的）
REFRESH_INTERVAL = 1       # 刷新间隔（秒）


# ===== 等待到指定时间 =====
def wait_until_target():
    print("⏳ 等待开票时间...")
    while True:
        now = datetime.now().strftime("%H:%M:%S")
        if now >= TARGET_TIME:
            print("🚀 到点了，开始抢票！")
            break
        time.sleep(0.5)


# ===== 主程序 =====
def run():
    with sync_playwright() as p:
        # ✅ 正确初始化浏览器（你刚才缺这个）
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # 打开12306
        page.goto("https://www.12306.cn/index/")

        print("👉 请手动扫码登录")
        input("✅ 登录完成后按回车继续...")

        # 👉 建议你手动选好：出发地、目的地、日期，然后停在查询页

        # 等待开票时间
        wait_until_target()

        # ===== 抢票循环 =====
        while True:
            try:
                print("🔄 正在刷新查询...")

                # 点击查询按钮
                page.click("#search_one")
                page.wait_for_timeout(800)

                # 查找“预订”
                if page.query_selector("text=预订"):
                    print("🎉 抢到票了！！！")

                    page.click("text=预订")

                    print("👉 已进入下单页面，请尽快确认支付！")
                    break

                else:
                    print("❌ 暂无票")

                time.sleep(REFRESH_INTERVAL)

            except Exception as e:
                print("⚠️ 出错:", e)
                time.sleep(1)

        input("按回车关闭浏览器...")
        browser.close()


# ===== 启动 =====
if __name__ == "__main__":
    run()
